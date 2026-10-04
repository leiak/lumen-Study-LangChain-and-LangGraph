"""dep_graph.py — 共享 dep graph 工具: 提取 import + topo sort + cycle detection.

教学 codegen 真实工程概念:
  - 文件间 import 关系 → directed graph
  - 拓扑排序 → 生成顺序 (依赖先生成)
  - cycle 检测 → 必须报错, 不沉默 (循环 import 运行时挂死)
  - forward declaration → 循环依赖的兜底 (TYPE_CHECKING)

💡 设计要点:
  - extract_imports regex-only (够用, AST 复杂)
  - 拓扑排序用 Kahn's algorithm (BFS, 易理解)
  - cycle detection 用 Tarjan-like DFS (返回所有环)
  - 不假设 LLM 输出完美, 加 defensive guard
"""
from __future__ import annotations

import re
from collections import defaultdict


# ============================================================
# Import extraction
# ============================================================
# from X import Y, Z
_FROM_IMPORT = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+", re.MULTILINE)
# import X  /  import X.Y  /  import X as Y
_IMPORT = re.compile(r"^\s*import\s+([\w.]+)(?:\s+as\s+\w+)?\s*$", re.MULTILINE)


def extract_imports(code: str) -> set[str]:
    """从 code 提取所有顶层 import 的 root module 名.

    覆盖两种语法: `from X import Y` 和 `import X`.
    嵌套模块只取 root: `from foo.bar import baz` → `"foo"`.

    Returns:
        set of root module names (e.g. {"utils", "main", "os"})

    Note:
        简单 regex 解析, 不处理:
        - 注释里的 import (e.g. ``# from x import y``)
        - docstring 里的 import (e.g. 三引号字符串内)
        - 多行 ``try: import x except: ...`` 结构
        教学用够, 生产应走 AST (e.g. ``ast.parse`` + walk Import/ImportFrom).
    """
    imports: set[str] = set()
    for m in _FROM_IMPORT.finditer(code):
        root = m.group(1).split(".")[0]
        imports.add(root)
    for m in _IMPORT.finditer(code):
        root = m.group(1).split(".")[0]
        imports.add(root)
    return imports


# ============================================================
# Path → module name heuristic
# ============================================================
def _path_to_module(path: str) -> str:
    """从 file path 推 module 名.

    启发式: `foo/bar/utils.py` → `utils`, `utils.py` → `utils`.

    ⚠️ 不完美:
      - 不支持 nested packages (`pkg/sub/utils.py` 应是 `pkg.sub.utils`)
      - 不看 `__init__.py` 判断包结构
    教学够用, 生产应解析实际 import 系统 (e.g. `astroid` / `importlib`).
    """
    # 规范化路径分隔符
    normalized = path.replace("\\", "/")
    # 取文件名 (去 .py 后缀)
    name = normalized.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        name = name[:-3]
    return name


# ============================================================
# Dep graph
# ============================================================
def build_dep_graph(files: list) -> dict[str, set[str]]:
    """从 file list 构建 dep graph.

    Args:
        files: list of FileSpec (or any object with .path and .content attributes).
               FileSpec 没 content → 视为无 import (空字符串).

    Returns:
        dict mapping file_path (str) → set of file_paths it depends on.
        只包含 files 之间相互依赖的边 —
        `import os` 不会让 `'os'` 出现在 graph 里 (stdlib 被忽略).
        """
    graph: dict[str, set[str]] = {str(f.path): set() for f in files}

    # path → module 映射
    path_to_module = {str(f.path): _path_to_module(str(f.path)) for f in files}

    for f in files:
        path = str(f.path)
        content = getattr(f, "content", "") or ""
        imports = extract_imports(content)
        for imp in imports:
            # 找哪个 file 的 module 名匹配 (排除自身)
            for other_path, other_module in path_to_module.items():
                if other_path != path and other_module == imp:
                    graph[path].add(other_path)
    return graph


# ============================================================
# Cycle error
# ============================================================
class CycleError(Exception):
    """依赖图有循环依赖."""

    def __init__(self, cycles: list[list[str]]):
        self.cycles = cycles
        super().__init__(f"Detected {len(cycles)} cycle(s) in dep graph: {cycles}")


# ============================================================
# Topological sort (Kahn's algorithm)
# ============================================================
def topological_sort(graph: dict[str, set[str]]) -> list[str]:
    """Kahn's algorithm: 返回生成顺序 (依赖先生成).

    graph[n] = set of nodes that n depends on (出边, n → dep).
    in-degree(n) = len(graph[n]) = n 依赖多少个 graph 里的 node.
    起点: in-degree 0 = 不依赖任何 node → 先处理.
    处理 n 后, 让所有 m where n ∈ graph[m] 的 m 的 in-degree 减 1.

    Note:
        名字 sort 保证同 in-degree 节点的处理顺序 deterministic —
        同样输入总得到同样顺序 (易测试 / 易 diff).

    Raises:
        CycleError: graph 含循环依赖.
    """
    # in-degree(n) = len(graph[n])
    in_degree: dict[str, int] = {node: len(graph.get(node, set())) for node in graph}

    # reverse index: dep → set of nodes that depend on dep
    # 用于: 处理完 n 后, 让所有把 n 列入 graph[X] 的 X 减 in-degree
    reverse: dict[str, set[str]] = defaultdict(set)
    for node, deps in graph.items():
        for dep in deps:
            reverse[dep].add(node)

    # 起点: in-degree 0 → 先处理
    queue = sorted([n for n, d in in_degree.items() if d == 0])
    result: list[str] = []

    while queue:
        # 用 pop(0) 保持 FIFO; queue 已 sorted, 同 in-degree 节点按名字处理
        node = queue.pop(0)
        result.append(node)
        # node 处理完后, 让所有"依赖 node"的节点的 in-degree 减 1
        for dependent in reverse.get(node, set()):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
                queue.sort()

    if len(result) != len(graph):
        # 剩余节点说明有环
        remaining = [n for n in graph if n not in set(result)]
        cycles = detect_cycles({n: graph[n] for n in remaining})
        raise CycleError(cycles)

    return result


# ============================================================
# Cycle detection (Tarjan-like DFS)
# ============================================================
def detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """DFS 找所有 cycle.

    Returns:
        list of cycles. 每个 cycle 是 file path 列表,
        起点重复一次 (e.g. ['a.py', 'b.py', 'a.py'] 表示 a → b → a).
    """
    cycles: list[list[str]] = []
    # 用 index-based 去重: cycle normalize 到最小节点开头
    seen_cycles: set[tuple[str, ...]] = set()

    def dfs(node: str, path: list[str], visiting: set[str]) -> None:
        if node in visiting:
            # 找到环: 从 node 在 path 里的位置截取
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            # 规范化: 最小节点开头, 用于 dedup
            normalized = _normalize_cycle(cycle)
            if normalized not in seen_cycles:
                seen_cycles.add(normalized)
                cycles.append(cycle)
            return
        if node not in graph:
            return  # 已知节点外, 跳过

        visiting.add(node)
        path.append(node)
        for dep in graph[node]:
            dfs(dep, path, visiting)
        path.pop()
        visiting.discard(node)

    for node in graph:
        dfs(node, [], set())

    return cycles


def _normalize_cycle(cycle: list[str]) -> tuple[str, ...]:
    """规范化 cycle 用于 dedup: 找最小节点开头, rotate.

    e.g. ['a.py', 'b.py', 'a.py'] → ('a.py', 'b.py', 'a.py')
    e.g. ['b.py', 'a.py', 'b.py'] → rotate → ('a.py', 'b.py', 'a.py')
    """
    # cycle 形如 [a, b, c, a], 去掉末尾重复
    core = cycle[:-1]
    if not core:
        return tuple(cycle)
    min_idx = core.index(min(core))
    rotated = core[min_idx:] + core[:min_idx]
    return tuple(rotated + [rotated[0]])


# ============================================================
# Forward declaration helper
# ============================================================
def add_forward_decls(content: str, dep_module: str, symbols: list[str]) -> str:
    """在文件顶部加 TYPE_CHECKING forward decl.

    用于循环依赖场景:
      - type checker 知道符号存在 (annotation 用)
      - 运行时不在 (避免 cycle 时 ImportError)

    Args:
        content: 原始文件内容
        dep_module: 依赖的 module 名
        symbols: 要 forward-declare 的符号列表

    Returns:
        加了 forward decl 的新 content.

    Example:
        >>> add_forward_decls("def foo():\n    pass\n", "other_mod", ["Bar"])
        "from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from other_mod import Bar

        def foo():
            pass
"
    """
    if not symbols:
        return content
    # 检测已有 TYPE_CHECKING import — 避免重复 `from typing import TYPE_CHECKING`
    has_type_checking = bool(
        re.search(r"^\s*from\s+typing\s+import\s+.*TYPE_CHECKING", content, re.MULTILINE)
        or re.search(r"^\s*import\s+typing\b", content, re.MULTILINE)
    )
    if has_type_checking:
        fwd = (
            f"if TYPE_CHECKING:\n"
            f"    from {dep_module} import {', '.join(symbols)}\n"
            f"\n"
        )
    else:
        fwd = (
            f"from typing import TYPE_CHECKING\n"
            f"if TYPE_CHECKING:\n"
            f"    from {dep_module} import {', '.join(symbols)}\n"
            f"\n"
        )
    return fwd + content


__all__ = [
    "extract_imports",
    "build_dep_graph",
    "topological_sort",
    "detect_cycles",
    "add_forward_decls",
    "CycleError",
]