"""codegen_pipeline.py — 共享 pipeline: plan → code → tests → fix.

被 02/03/04/05/07 demo 共用. 抽出来避免重复.

💡 设计要点:
  - 一次生成一个文件 (避免 LLM 单次输出过大)
  - 用 ```python ... ``` 块提取, 容错强 (LLM 经常吐 markdown 解释)
  - 每个 prompt 强约束 "只输出代码块, 不要解释", 减少噪音
  - 增量 diff 模式 (fix_code_incremental): 用 SEARCH/REPLACE 块 + difflib 模糊匹配
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from _common import extract_python_blocks, step, write_code_file
from _common import output_dir as default_output_dir
from plan_schema import FileSpec, FunctionSpec, Plan
from dep_graph import (
    CycleError,
    build_dep_graph,
    topological_sort,
)
from safety import Severity, format_findings, has_block_findings, scan_code


# ============================================================
# Prompts
# ============================================================
_FILE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是 Python 实现者. 根据 file spec 生成完整 Python 代码.

要求:
- 用 ```python ... ``` 块包裹代码
- 不要解释, 只输出代码块
- 函数签名必须跟 spec 一致
- docstring 写全 (Google 风格)
- 不要 import 用不到的模块"""),
    ("human", "File: {path}\nPurpose: {purpose}\n\n{functions_text}\n\n输出 Python 代码 (```python 块)."),
])


_TEST_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是 pytest 专家. 根据 Python 代码生成完整 pytest 测试文件.

要求:
- 文件名: test_<filename_without_py>.py
- 用 ```python ... ``` 块包裹
- 每个函数至少 3 个测试 (正常 + 边界 + 异常)
- 用 assert, 不需要 unittest
- import 同目录模块 (from <filename_without_py> import ... )"""),
    ("human", "代码文件: {filename}\n\n```python\n{code}\n```\n\n生成 pytest 测试 (```python 块)."),
])


_FIX_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是 Python 调试专家. 根据 pytest 失败信息修改代码.

要求:
- 用 ```python ... ``` 块包裹完整修正后的代码
- 不要解释
- 修复失败的 assert, 保留其它正确行为
- 不要破坏已通过的测试"""),
    ("human", "原代码:\n```python\n{code}\n```\n\n测试失败:\n{error}\n\n输出修正后的代码."),
])


_FIX_INCREMENTAL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是 Python 调试专家. 根据 pytest 失败信息, **只输出需要修改的部分**, 不要重写整个文件.

格式 A (优先, Aider 风格): 用 SEARCH/REPLACE 块
<<<<<<< SEARCH
原代码 (含足够上下文让 diff 匹配, 一般 2-5 行)
=======
新代码
>>>>>>> REPLACE

格式 B (fallback, 行号风格):
Line 42: return x + 1   →   return x + 2

要求:
- 最小改动, 只动失败的行
- 保留其它正确行为
- 1-3 个 SEARCH/REPLACE 块足够
- search 块要包含足够上下文, 避免歧义匹配
- 输出只包含 SEARCH/REPLACE 块, 其它解释一律不要"""),
    ("human", "原代码:\n```python\n{code}\n```\n\n测试失败:\n{error}\n\n输出 SEARCH/REPLACE 块."),
])


# ============================================================
# Helpers
# ============================================================
def _format_functions(functions: list[FunctionSpec]) -> str:
    """把 FunctionSpec list 格式化成 prompt 输入."""
    lines = []
    for f in functions:
        lines.append(f"- `{f.signature}`")
        lines.append(f"  Docstring: {f.docstring}")
        if f.test_cases:
            lines.append(f"  Tests: {', '.join(f.test_cases)}")
    return "\n".join(lines)


def _invoke_text(llm, prompt_input: dict, prompt: ChatPromptTemplate) -> str:
    """invoke LLM, 返回 text (兼容 AIMessage / str)."""
    response = llm.invoke(prompt.format(**prompt_input))
    if hasattr(response, "content"):
        return response.content
    return str(response)


# ============================================================
# Pipeline 步骤
# ============================================================
def file_to_code(llm, file_spec: FileSpec) -> str:
    """单 file spec → Python code string."""
    text = _invoke_text(
        llm,
        {
            "path": file_spec.path,
            "purpose": file_spec.purpose,
            "functions_text": _format_functions(file_spec.functions),
        },
        _FILE_PROMPT,
    )
    blocks = extract_python_blocks(text)
    return blocks[0]  # 第一个 python 块就是答案


def code_to_test(llm, code_file: Path) -> str:
    """code 文件 → pytest test code string."""
    code = code_file.read_text(encoding="utf-8")
    text = _invoke_text(
        llm,
        {"filename": code_file.name, "code": code},
        _TEST_PROMPT,
    )
    blocks = extract_python_blocks(text)
    return blocks[0]


def fix_code(llm, code: str, error: str) -> str:
    """code + 错误 → 修正后 code string."""
    text = _invoke_text(
        llm,
        {"code": code, "error": error},
        _FIX_PROMPT,
    )
    blocks = extract_python_blocks(text)
    return blocks[0]


def fix_code_incremental(llm, code: str, error: str) -> str:
    """增量 diff fix: LLM 输出 SEARCH/REPLACE 块 → difflib 模糊匹配 apply.

    比 fix_code 省 token: 1000 行文件 1-line bug, full regen ~1500 字符,
    incremental ~200 字符 (7.5x 便宜).

    Returns:
        修正后的完整 code string. 解析失败 → 返回原 code (defensive).
    """
    text = _invoke_text(
        llm,
        {"code": code, "error": error},
        _FIX_INCREMENTAL_PROMPT,
    )
    patches = extract_search_replace_blocks(text)
    if not patches:
        # 解析失败 → 保留原 code (defensive, 不破坏)
        return code
    result = code
    for search, replace in patches:
        result = apply_search_replace(result, search, replace)
    return result


def extract_search_replace_blocks(text: str) -> list[tuple[str, str]]:
    """从 LLM 输出提取 SEARCH/REPLACE 块 (Aider 风格).

    匹配: <<<<<<< SEARCH\\n...\\n=======\\n...\\n>>>>>>> REPLACE

    Returns:
        list of (search_text, replace_text) tuples. 没找到 → []
    """
    pattern = re.compile(
        r"<<<<<<< SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>> REPLACE",
        re.DOTALL,
    )
    return [(m.group(1), m.group(2)) for m in pattern.finditer(text)]


def apply_search_replace(code: str, search: str, replace: str) -> str:
    """把 search 块替换成 replace 块.

    1. 优先 exact match (`search` 直接出现在 code 里)
    2. fallback: difflib.SequenceMatcher 找最相似的连续 N 行, threshold 0.6

    Returns:
        替换后的 code. 模糊匹配 < 0.6 → 拒绝替换, 返回原 code (defensive)
    """
    if not search:
        return code

    # 路径 1: exact match
    if search in code:
        return code.replace(search, replace, 1)

    # 路径 2: difflib 模糊匹配
    lines = code.split("\n")
    search_lines = search.split("\n")
    n = len(search_lines)

    if n > len(lines):
        return code  # search 比 code 还长, 不可能匹配

    best_ratio, best_idx = 0.0, -1
    for i in range(len(lines) - n + 1):
        candidate = "\n".join(lines[i:i + n])
        ratio = SequenceMatcher(None, candidate, search).ratio()
        if ratio > best_ratio:
            best_ratio, best_idx = ratio, i

    if best_ratio < 0.6:
        # 太不相似, 拒绝替换 (defensive, 不强行改)
        return code

    # 替换最相似的那段
    lines[best_idx:best_idx + n] = replace.split("\n")
    return "\n".join(lines)


def plan_to_code(llm, plan: Plan) -> list[Path]:
    """Plan → 写 output/, 返回文件路径列表."""
    written: list[Path] = []
    for i, file_spec in enumerate(plan.files, 1):
        step(i, f"生成 {file_spec.path}")
        code = file_to_code(llm, file_spec)
        path = write_code_file(file_spec.path, code)
        print(f"  写入 {path} ({len(code)} 字符)")
        # 打印前 8 行预览
        preview = "\n".join(code.split("\n")[:8])
        print(f"  预览:\n{preview}\n  ...")
        written.append(path)
    return written


def safe_plan_to_code(llm, plan: Plan, output_dir: Path | None = None) -> list[Path]:
    """Plan → 写盘, 但写盘前 safety 扫描. BLOCK → 跳过该文件.

    在 `plan_to_code` 基础上加 safety gate:
      - Layer 1+2 扫描代码 (regex + AST)
      - BLOCK 级别 finding → 拒绝写盘, 打印原因, skip
      - WARN 级别 → 写但打印警告
      - INFO → 静默

    Args:
        llm: LLM 实例
        plan: Plan Pydantic 对象
        output_dir: 输出目录 (默认 = `output_dir()` 当前模块默认目录)

    Returns:
        成功写入的文件路径列表 (BLOCK 文件被剔除).

    💡 设计要点:
      - BLOCK 跳过而不是 fail: 一个文件危险不影响其它文件
      - 不在 safe_plan_to_code 里 raise: 让调用方决定怎么处理
        (demo 里 print + count, 生产可以 log + alert)
      - WARN 不阻断: 给 false-positive 兜底, 写但留下审计痕迹
    """
    # output_dir 在函数入口解析一次 (R13 fix #6), 避免每次调用重新 invoke default_output_dir()
    if output_dir is None:
        output_dir = default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    blocked_count = 0
    warn_count = 0

    for i, file_spec in enumerate(plan.files, 1):
        step(i, f"生成 {file_spec.path} (with safety gate)")
        code = file_to_code(llm, file_spec)

        # === Safety scan ===
        findings = scan_code(code, file_spec.path)

        if has_block_findings(findings):
            blocked_count += 1
            print(f"  ⛔ BLOCKED by safety scan ({len([f for f in findings if f.severity == Severity.BLOCK])} BLOCK findings)")
            print(format_findings(findings))
            continue  # skip 写盘

        # WARN findings: log but proceed
        warns = [f for f in findings if f.severity == Severity.WARN]
        if warns:
            warn_count += 1
            print(f"  ⚠️  {len(warns)} warnings (will write anyway):")
            for f in warns:
                loc = f"line {f.line_no}" if f.line_no else "全文"
                print(f"    - {f.pattern} @ {loc}: {f.snippet!r}")

        # 写盘
        path = output_dir / file_spec.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        print(f"  ✓ 写入 {path} ({len(code)} 字符)")
        written.append(path)

    # 总结
    total = len(plan.files)
    print(f"\n  safe_plan_to_code 总结: 写入 {len(written)}/{total} (BLOCK 跳过 {blocked_count}, WARN {warn_count})")
    return written


def plan_to_code_with_deps(
    llm,
    plan: Plan,
    output_dir: Path | None = None,
) -> list[Path]:
    """Dep-aware 写盘: 先 build graph, topo sort, 然后按依赖顺序生成.

    区别于 `plan_to_code` (按 plan 列表顺序) —
    这里用 topological sort 保证:
        - utils.py 在 main.py 之前生成
        - 不会出现"先有 consumer, 后 provider"的死锁

    集成 safety gate (跟 safe_plan_to_code 一致):
        - 每个文件生成后跑 scan_code
        - BLOCK finding → 跳过该文件 (不写盘)
        - WARN finding → 写但打印警告

    ⚠️ 设计决策: graph 何时构建?
      - 方案 A: 用 LLM 之前 plan 里的 files (无 content), graph 全空
      - 方案 B: 生成 content 后构建 graph, 但生成顺序不确定 → chicken-egg
      - 我们采用方案 C: 按 plan.files 顺序生成 code, **同时**构建 graph;
        topo sort 用于 "写盘" 顺序, 而不是 LLM 调用顺序.
        这样:
          - LLM 调用按 plan 顺序 (确定性, 易调试)
          - 写盘按 dep 顺序 (utils 一定在 main 前)
          - graph 反映真实 content (非空时)

    Args:
        llm: LLM 实例
        plan: Plan Pydantic 对象
        output_dir: 输出目录 (默认 = `output_dir()` 当前模块默认目录)

    Returns:
        成功写入的文件路径列表 (按 topo sort 顺序).

    Raises:
        CycleError: 依赖图含循环依赖 (不沉默, 跟 spec validation 风格一致).
                    调用方可以:
                    - 直接让 caller 看到错误 (fail fast)
                    - 走 add_forward_decls 重试 (LLM 加 TYPE_CHECKING)
    """
    if output_dir is None:
        output_dir = default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 先生成所有 file content (按 plan 顺序, 确定性, 易调试)
    #    然后用真实 content 构建 graph
    print("\n  [phase 1] 生成所有 file content (按 plan 顺序)...")
    file_codes: dict[str, str] = {}
    for i, file_spec in enumerate(plan.files, 1):
        step(i, f"生成 {file_spec.path}")
        code = file_to_code(llm, file_spec)
        file_codes[file_spec.path] = code
        print(f"  ({len(code)} 字符)")
        # 打印前 8 行预览 (跟 plan_to_code 一致)
        preview = "\n".join(code.split("\n")[:8])
        print(f"  预览:\n{preview}\n  ...")

    # 2. 构建 dep graph (用真实 content) + topo sort
    print("\n  [phase 2] 构建 dep graph + 拓扑排序...")
    enriched_files = [
        FileSpec(path=f.path, purpose=f.purpose, functions=f.functions, content=file_codes[f.path])
        for f in plan.files
    ]
    graph = build_dep_graph(enriched_files)
    print(f"  graph ({len(graph)} nodes):")
    for k, v in graph.items():
        deps = ", ".join(Path(d).name for d in v) or "(无)"
        print(f"    {Path(k).name:20} → {deps}")

    try:
        order = topological_sort(graph)
    except CycleError as e:
        print(f"\n  ⛔ 检测到 {len(e.cycles)} 个循环依赖:")
        for cycle in e.cycles:
            print(f"     {' → '.join(Path(p).name for p in cycle)}")
        print(f"  💡 解决: 加 TYPE_CHECKING forward decl 或重构依赖方向")
        raise

    names = " → ".join(Path(p).name for p in order)
    print(f"  ✓ 拓扑顺序: {names}")

    # 3. 按 topo 顺序写盘 + safety scan
    print("\n  [phase 3] 按 dep 顺序写盘 (with safety gate)...")
    written = []
    blocked_count = 0
    warn_count = 0
    for path_str in order:
        file_spec = next(f for f in plan.files if f.path == path_str)
        code = file_codes[path_str]
        print(f"\n  --- {file_spec.path} ---")

        findings = scan_code(code, file_spec.path)
        if has_block_findings(findings):
            blocked_count += 1
            print(f"  ⛔ BLOCKED by safety scan")
            print(format_findings(findings))
            continue

        warns = [f for f in findings if f.severity == Severity.WARN]
        if warns:
            warn_count += 1
            print(f"  ⚠️  {len(warns)} warnings (writing anyway):")
            for f in warns:
                loc = f"line {f.line_no}" if f.line_no else "全文"
                print(f"    - {f.pattern} @ {loc}: {f.snippet!r}")

        path = output_dir / file_spec.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        print(f"  ✓ 写入 {path} ({len(code)} 字符)")
        written.append(path)

    # 4. 总结
    total = len(plan.files)
    print(f"\n  plan_to_code_with_deps 总结: 写入 {len(written)}/{total} (BLOCK {blocked_count}, WARN {warn_count})")
    return written


__all__ = [
    "plan_to_code",
    "safe_plan_to_code",
    "plan_to_code_with_deps",
    "file_to_code",
    "code_to_test",
    "fix_code",
    "fix_code_incremental",
    "extract_search_replace_blocks",
    "apply_search_replace",
]
