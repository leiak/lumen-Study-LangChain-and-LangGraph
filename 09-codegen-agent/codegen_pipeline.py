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
from plan_schema import FileSpec, FunctionSpec, Plan


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


__all__ = [
    "plan_to_code",
    "file_to_code",
    "code_to_test",
    "fix_code",
    "fix_code_incremental",
    "extract_search_replace_blocks",
    "apply_search_replace",
]
