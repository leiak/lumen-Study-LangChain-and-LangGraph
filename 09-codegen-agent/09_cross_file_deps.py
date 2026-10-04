"""09_cross_file_deps.py — Demo 9: 跨文件依赖 + 拓扑排序 + cycle detection.

教学 codegen 真实工程问题:
- LLM 生成多文件时, import 顺序很重要 (utils 必须在 main 前)
- 拓扑排序保证依赖先生成
- 循环依赖必须检测 (循环 import 运行时挂死, NameError)
- forward decl (TYPE_CHECKING) 是循环依赖的兜底

学完这个 demo 你能回答:
1.  为什么多文件 codegen 需要 dep graph? (LLM 生成顺序可能错)
2.  怎么从 source code 提取 import 关系? (regex + AST)
3.  Kahn's algorithm 怎么算 topo order? (BFS + in-degree)
4.  怎么检测循环依赖? (DFS + 路径记录)
5.  forward declaration 怎么解决循环? (TYPE_CHECKING type-only import)
6.  codegen pipeline 怎么集成 dep order? (build graph + topo sort + write 顺序)

跑法:
    python 09_cross_file_deps.py

💡 设计要点:
  - dep_graph.py 抽出来, 纯算法 + no LLM (易测试)
  - 6 个 demo steps: 3 个无 LLM (算法演示) + 3 个有 LLM (集成)
  - CycleError raise 不 silent (跟 spec validation 风格一致: 不放过)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows GBK 编码保护 — LLM 返回的 emoji 可能崩 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _common import banner, get_llm, output_dir, step
from codegen_pipeline import (
    file_to_code,
    plan_to_code_with_deps,
)
from dep_graph import (
    CycleError,
    add_forward_decls,
    build_dep_graph,
    detect_cycles,
    extract_imports,
    topological_sort,
)
from plan_schema import FileSpec, spec_to_plan


# ============================================================
# Test fixtures (no LLM needed for steps 1-3)
# ============================================================
# Linear chain: utils.py → main.py → app.py
# utils 不依赖别人
FILE_UTILS = FileSpec(
    path="utils.py",
    purpose="helper functions",
    functions=[],
    content='def helper():\n    return 42\n',
)
# main 依赖 utils
FILE_MAIN = FileSpec(
    path="main.py",
    purpose="uses utils.helper",
    functions=[],
    content='from utils import helper\n\nresult = helper()\n',
)
# app 依赖 main
FILE_APP = FileSpec(
    path="app.py",
    purpose="uses main.result",
    functions=[],
    content='from main import result\n\nprint(result)\n',
)

# Cycle fixture: a ↔ b
FILE_A = FileSpec(
    path="a.py",
    purpose="depends on b",
    functions=[],
    content='from b import x\n\ndef use_b():\n    return x\n',
)
FILE_B = FileSpec(
    path="b.py",
    purpose="depends on a",
    functions=[],
    content='from a import y\n\ndef use_a():\n    return y\n',
)


# ============================================================
# Demo helpers
# ============================================================
def print_graph(graph: dict[str, set[str]], indent: str = "    ") -> None:
    """打印 dep graph (短路径, 易读)."""
    for k, v in graph.items():
        deps = ", ".join(Path(d).name for d in v) or "(无)"
        print(f"{indent}{Path(k).name:20} → {deps}")


# ============================================================
# Main demo
# ============================================================
def main() -> None:
    banner("Demo 9: Cross-file Dependencies + Topo Sort + Cycle Detection")

    # ----------------------------------------------------------------
    step(1, "算法演示 (no LLM): 3-file linear chain → topo order")
    # ----------------------------------------------------------------
    print("  文件:")
    print(f"    - {FILE_UTILS.path}: helper functions")
    print(f"    - {FILE_MAIN.path}: from utils import helper")
    print(f"    - {FILE_APP.path}: from main import result")

    graph = build_dep_graph([FILE_UTILS, FILE_MAIN, FILE_APP])
    print("\n  dep graph (who depends on who):")
    print_graph(graph)

    try:
        order = topological_sort(graph)
        names = " → ".join(Path(p).name for p in order)
        print(f"\n  ✓ 拓扑排序结果: {names}")
        # utils 必须先生成 (没人依赖它 → in-degree 0 → 起点)
        # app 最后生成 (in-degree 2 → 等 utils + main)
        assert order == ["utils.py", "main.py", "app.py"], f"顺序错: {order}"
        print(f"  ✓ 顺序正确: utils → main → app")
    except CycleError as e:
        print(f"  ⛔ unexpected cycle: {e}")

    # ----------------------------------------------------------------
    step(2, "算法演示 (no LLM): 循环依赖 (a ↔ b) → CycleError")
    # ----------------------------------------------------------------
    print("  文件:")
    print(f"    - {FILE_A.path}: from b import x")
    print(f"    - {FILE_B.path}: from a import y")

    graph_cycle = build_dep_graph([FILE_A, FILE_B])
    print("\n  dep graph:")
    print_graph(graph_cycle)

    print("\n  调 topological_sort()...")
    try:
        order = topological_sort(graph_cycle)
        print(f"  ⛔ FAIL: 拓扑排序应该抛 CycleError, 但返回 {order}")
        assert False, "should have raised"
    except CycleError as e:
        print(f"  ✓ CycleError 抛出 (含 {len(e.cycles)} 个 cycle):")
        for cycle in e.cycles:
            names = " → ".join(Path(p).name for p in cycle)
            print(f"     cycle: {names}")

    # ----------------------------------------------------------------
    step(3, "算法演示 (no LLM): DFS detect_cycles 返回所有环")
    # ----------------------------------------------------------------
    print("  调 detect_cycles() 直接找所有环 (绕过 topo sort):")
    cycles = detect_cycles(graph_cycle)
    print(f"  found {len(cycles)} cycle(s):")
    for c in cycles:
        names = " → ".join(Path(p).name for p in c)
        print(f"    {names}")

    # ----------------------------------------------------------------
    step(4, "LLM 集成: 生成 3-file spec (models + repository + app)")
    # ----------------------------------------------------------------
    print("  spec 摘要: models.User → repository.UserRepository → app uses repo")
    spec = """\
生成一个 3 文件 Python 项目 (用户管理):
- `models.py`: 定义 `User` dataclass (name: str, email: str), 加 `__repr__` 和 `__eq__`
- `repository.py`: 定义 `UserRepository` 类, 用内存 list 存 user, 含 `add(user)` / `get_by_email(email) -> User | None`
- `app.py`: 演示用 — 创建 repo, 加 3 个 user (alice/bob/carol), 然后 query alice 的 email

要求:
- 完整类型注解
- 完整 Google 风格 docstring
- imports 关系: repository 用 models, app 用 repository (无循环)
"""

    llm = get_llm(temperature=0.0)
    plan = spec_to_plan(llm, spec)
    print(f"\n  plan summary: {plan.summary}")
    print(f"  plan files: {[f.path for f in plan.files]}")

    # 先生成 content (plan 顺序), 再构建 graph
    file_codes: dict[str, str] = {}
    print("\n  生成各 file content (按 plan 顺序)...")
    for fs in plan.files:
        code = file_to_code(llm, fs)
        file_codes[fs.path] = code
        print(f"    {fs.path}: {len(code)} 字符")

    # 用真实 content 构建 graph
    enriched = [
        FileSpec(path=fs.path, purpose=fs.purpose, functions=fs.functions, content=file_codes[fs.path])
        for fs in plan.files
    ]
    graph_real = build_dep_graph(enriched)
    print("\n  graph (用真实 content 构建):")
    print_graph(graph_real)

    # 展示 import 提取
    print("\n  提取 import 验证 (正则抓 from X import):")
    for fs in plan.files:
        imps = extract_imports(file_codes[fs.path])
        print(f"    {fs.path:20} imports: {sorted(imps) or '(none)'}")

    try:
        order = topological_sort(graph_real)
        names = " → ".join(Path(p).name for p in order)
        print(f"\n  ✓ 拓扑顺序: {names}")
    except CycleError as e:
        print(f"  ⚠️ 意外 cycle: {e}")

    # ----------------------------------------------------------------
    step(5, "LLM 集成: cyclic spec → 检测 + forward decl 演示")
    # ----------------------------------------------------------------
    print("  spec 摘要: 2 个互相调用的 class (用 TYPE_CHECKING forward decl)")
    cyclic_spec = """\
生成 2 个 Python 文件, 演示 TYPE_CHECKING forward declaration:
- `models_a.py`: 定义 `class ServiceA`, 方法 `call_b()` 实例化 `ServiceB` 并调用其方法
- `models_b.py`: 定义 `class ServiceB`, 方法 `call_a()` 实例化 `ServiceA` 并调用其方法

要求:
- 两个类互相调用 (运行时, 不是仅 type annotation)
- 用 `from __future__ import annotations` + `TYPE_CHECKING` forward decl 解决 type-only 依赖
- 类型注解要互相引用对方的类
"""

    plan_c = spec_to_plan(llm, cyclic_spec)
    print(f"\n  plan files: {[f.path for f in plan_c.files]}")

    file_codes_c: dict[str, str] = {}
    for fs in plan_c.files:
        code = file_to_code(llm, fs)
        file_codes_c[fs.path] = code

    enriched_c = [
        FileSpec(path=fs.path, purpose=fs.purpose, functions=fs.functions, content=file_codes_c[fs.path])
        for fs in plan_c.files
    ]
    graph_c = build_dep_graph(enriched_c)
    print("\n  graph (含 content):")
    print_graph(graph_c)

    cycles = detect_cycles(graph_c)
    if cycles:
        print(f"\n  ⛔ 检测到 {len(cycles)} 个 cycle:")
        for c in cycles:
            names = " → ".join(Path(p).name for p in c)
            print(f"    {names}")
        print(f"  💡 解决: TYPE_CHECKING forward decl 或重构依赖方向")
    else:
        print(f"\n  ✓ 无 cycle — LLM 用了 TYPE_CHECKING 或 lazy import 规避了")

    # 演示 add_forward_decls 工具
    print("\n  add_forward_decls 工具演示:")
    sample_code = "class ServiceB:\n    def make_a(self) -> 'ServiceA':\n        ...\n"
    fwd_code = add_forward_decls(sample_code, "models_a", ["ServiceA"])
    print(f"  原始 code:\n{sample_code}")
    print(f"  + forward decl 后:\n{fwd_code}")

    # ----------------------------------------------------------------
    step(6, "端到端: plan_to_code_with_deps on linear spec")
    # ----------------------------------------------------------------
    print("  复用 step 4 的 3-file plan, 走 dep-aware pipeline:")
    out = output_dir() / "demo9"
    out.mkdir(parents=True, exist_ok=True)
    print(f"  output_dir: {out}")

    try:
        written = plan_to_code_with_deps(llm, plan, output_dir=out)
        print(f"\n  ✓ 写入 {len(written)} 个文件 (按 dep order):")
        for p in written:
            size = p.stat().st_size
            print(f"    {p.name:20} {size} bytes")

        # 验证 import 真的能工作 — 模拟 utils 写盘后 main 加载
        print(f"\n  import 验证 (topo 顺序加载 3 文件):")
        if written:
            sys.path.insert(0, str(out))
            try:
                # 按写入顺序 (即 topo 顺序) 加载
                for p in written:
                    mod_name = p.stem
                    __import__(mod_name)
                    print(f"    ✓ import {mod_name} OK")
            except Exception as e:
                print(f"    ⚠️ import 失败 (LLM 生成的代码语法问题, 非 dep 顺序): {e}")
            finally:
                # 清理 sys.modules cache
                for p in written:
                    sys.modules.pop(p.stem, None)
                sys.path.remove(str(out))
    except CycleError as e:
        print(f"  ⛔ CycleError: {e}")

    # ----------------------------------------------------------------
    step(7, "dep-aware codegen trade-offs 总结")
    # ----------------------------------------------------------------
    print("  ✅ 拓扑排序保证生成顺序正确:")
    print("    - 避免 'utils 没生成就 import' 的 ImportError")
    print("    - 大型多文件项目必备 (10+ 文件时 LLM 经常搞错顺序)")
    print("  ⚠️  局限:")
    print("    - module name heuristic 不完美 (nested packages / __init__.py)")
    print("    - regex import 解析不处理 conditional / dynamic import")
    print("    - forward decl 只解决 type-time, runtime 循环仍会挂死")
    print("  🛡️ 生产建议:")
    print("    - 静态分析 dep graph + 真实 import test (e.g. pytest import collection)")
    print("    - 循环检测要 raise 不 silent (跟 spec validation 风格一致)")
    print("    - TYPE_CHECKING 用得起就用 (零运行时成本)")


if __name__ == "__main__":
    main()