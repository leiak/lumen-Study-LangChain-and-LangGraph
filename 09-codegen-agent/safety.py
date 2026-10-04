"""safety.py — 共享 safety scanner: 静态分析 LLM 生成的代码.

两层扫描:
  Layer 1: regex 字符串匹配 (快, 覆盖大多数)
  Layer 2: AST 节点扫描 (准, 处理赋值 / 调用 / 属性)

Severity: BLOCK (拒绝写盘) / WARN (写但警告) / INFO (no-op)

💡 设计要点:
  - 不做运行时沙箱 (太复杂). 静态分析足够 catch 90% 危险
  - regex 优先: 快 + 易读; AST fallback: 处理 regex 漏掉的复杂结构
  - 每条规则有 docstring 说明为什么危险 (教育性)
  - 默认 BLOCK 保守, 不放过. WARN 给 false-positive 兜底
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Severity(Enum):
    BLOCK = "BLOCK"  # 拒绝写盘
    WARN = "WARN"    # 写但警告
    INFO = "INFO"    # no-op (just info)


@dataclass
class Finding:
    """单个 safety finding."""

    severity: Severity
    pattern: str         # 命中的 pattern / rule name
    line_no: int | None  # 行号 (None = regex 全文匹配)
    snippet: str         # 命中片段
    reason: str          # 为什么危险


# ============================================================
# Layer 1: Regex 规则
# ============================================================
# 每条规则: (compiled_pattern, severity, name, reason)
_REGEX_RULES: list[tuple[re.Pattern, Severity, str, str]] = [
    # --- BLOCK: 直接执行任意代码 ---
    (
        re.compile(r"\beval\s*\("),
        Severity.BLOCK,
        "eval_call",
        "eval() 执行任意 Python 表达式, 不可信输入可注入",
    ),
    (
        re.compile(r"\bexec\s*\("),
        Severity.BLOCK,
        "exec_call",
        "exec() 执行任意 Python 代码, 等价于代码注入",
    ),
    (
        re.compile(r"\bcompile\s*\("),
        Severity.BLOCK,
        "compile_call",
        "compile() 配合 exec/eval 形成注入链",
    ),
    # --- BLOCK: shell 注入 ---
    (
        re.compile(r"os\.system\s*\("),
        Severity.BLOCK,
        "os_system",
        "os.system() 走 shell, 命令注入风险高",
    ),
    (
        re.compile(r"shell\s*=\s*True"),
        Severity.BLOCK,
        "shell_true",
        "subprocess shell=True 命令注入",
    ),
    # --- BLOCK: 反序列化 ---
    (
        re.compile(r"pickle\.loads?\s*\("),
        Severity.BLOCK,
        "pickle_load",
        "pickle.loads 反序列化不可信数据, 可执行任意代码",
    ),
    (
        re.compile(r"marshal\.loads?\s*\("),
        Severity.BLOCK,
        "marshal_load",
        "marshal.loads 同 pickle, 反序列化风险",
    ),
    # --- BLOCK: 动态 import 绕过审查 ---
    (
        re.compile(r"__import__\s*\("),
        Severity.BLOCK,
        "dynamic_import",
        "__import__() 动态加载模块, 绕过静态审查",
    ),
    (
        re.compile(r"importlib\.import_module\s*\("),
        Severity.BLOCK,
        "importlib_dynamic",
        "importlib.import_module 同样动态加载",
    ),
    # --- WARN: 可能的硬编码 secret (启发式 — 不完美) ---
    (
        re.compile(
            r"(?i)(password|passwd|pwd|secret|api_?key|token)\s*=\s*['\"][^'\"]{4,}['\"]"
        ),
        Severity.WARN,
        "hardcoded_secret",
        "硬编码 secret/credential, 应该走环境变量或 vault",
    ),
    # --- WARN: 文件写入 path 可控 ---
    # 单行 `open("x").write(...)` 用 regex 抓. 多行 `f = open(); f.write()`
    # 用 AST layer 抓 (R13 fix). 两者 pattern 名都是 `open_write`, dedup 友好.
    (
        re.compile(r"open\s*\(\s*[^)]*\)\s*\.write\s*\("),
        Severity.WARN,
        "open_write",
        "open().write() 可被 path 注入, 应该用 with open() + path validate",
    ),
    # --- INFO: 不安全 hash (教育性) ---
    (
        re.compile(r"\bhashlib\.md5\b|\bhashlib\.sha1\b"),
        Severity.INFO,
        "weak_hash",
        "MD5/SHA1 已不安全, 密码场景用 bcrypt/argon2",
    ),
]


def scan_regex(code: str, source: str = "<input>") -> list[Finding]:
    """Layer 1: regex 全文件扫描.

    Args:
        code: 源代码字符串
        source: 来源标识 (e.g. 文件路径, 仅用于 finding 元数据)

    Returns:
        Finding 列表. 一行多个命中 → 多个 findings.
    """
    findings: list[Finding] = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        for pattern, severity, name, reason in _REGEX_RULES:
            if pattern.search(line):
                findings.append(
                    Finding(
                        severity=severity,
                        pattern=name,
                        line_no=i,
                        snippet=line.strip()[:80],
                        reason=reason,
                    )
                )
    return findings


# ============================================================
# Layer 2: AST 扫描
# ============================================================
_AST_FORBIDDEN_FUNCS = {"eval", "exec", "compile"}
_AST_DANGEROUS_ATTRS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "call"),  # 仅当 shell=True 时 block, AST layer 兜底
    ("pickle", "loads"),
    ("pickle", "load"),
    ("marshal", "loads"),
    ("marshal", "load"),
}


def _ast_attr_pattern_name(full: tuple[str, str]) -> str:
    """把 (module, attr) 映射成跟 regex 同名的 pattern 标识 (R13 fix).

    例:
      (os, system)        → 'os_system'      (regex: os_system)
      (pickle, loads)     → 'pickle_load'    (regex: pickle_load)
      (pickle, load)      → 'pickle_load'    (同上, dedup)
      (marshal, loads)    → 'marshal_load'
      (os, popen)         → 'os_popen'       (AST-only)
      (subprocess, call)  → 'subprocess_call' (AST-only)

    目的: 让 dedup 在 (severity, pattern, line_no) 维度能跨 regex + AST 合并.
    之前 AST pattern 用 `ast_eval` / `ast_os_system` 等前缀, 跟 regex 不一致,
    跨层 dedup 从不触发 (R13 review #2).
    """
    mod, attr = full
    # load/loads 都映射到 {mod}_load, 跟 regex 的 pickle_load / marshal_load 对齐
    if attr in ("loads", "load"):
        return f"{mod}_load"
    return f"{mod}_{attr}"


def _scan_ast_node(
    node: ast.AST,
    source: str,
    open_vars: set[str] | None = None,
) -> list[Finding]:
    """递归 AST walk, 收集 forbidden Call 节点.

    处理三类危险 call (R13 fix 加了 #3):
      1. Call(func=Name(id in _AST_FORBIDDEN_FUNCS))
         → eval / exec / compile
      2. Call(func=Attribute(value=Name, attr) 且 (name, attr) in _AST_DANGEROUS_ATTRS)
         → os.system / pickle.loads / ...
      3. Call(func=Attribute(attr='write', value=Name)) 且 Name ∈ open_vars
         → multiline open().write() pattern (R13 fix)

    Args:
        node: 当前 AST 节点
        source: 来源标识
        open_vars: 已经赋值为 open() 调用的变量名集合 (mutable, 跨递归共享).
                   新看到 `f = open(...)` 就把 'f' 加进来; 看到 `f.write()` 就
                   触发 open_write finding.

    Returns:
        当前节点 (含子树) 的 findings 列表.

    💡 简化: open_vars 集合跨整个 module 共享, 不区分函数作用域. 局限:
      如果 `f` 被 rebind 到非-open() 值 (e.g. `f = [1,2]`), AST 仍把 `f` 视为
      open_var. 这是 simple static analysis 的 known limitation — demo 接受
      少量 false positive, 换简洁性.
    """
    if open_vars is None:
        open_vars = set()

    findings: list[Finding] = []

    # 0. Track open() assignments (NEW R13 — multiline open_write fix)
    if isinstance(node, ast.Assign):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            if node.value.func.id == "open":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        open_vars.add(target.id)

    if isinstance(node, ast.Call):
        func = node.func
        # 1. Bare eval/exec/compile
        if isinstance(func, ast.Name) and func.id in _AST_FORBIDDEN_FUNCS:
            # 命名跟 regex 一致: eval_call / exec_call / compile_call
            # 这样 dedup 在 (severity, pattern, line_no) 维度能合并
            name = f"{func.id}_call"
            findings.append(
                Finding(
                    severity=Severity.BLOCK,
                    pattern=name,
                    line_no=node.lineno,
                    snippet=f"call to {func.id}()",
                    reason=f"AST 检测到 {func.id}() 调用, 等价 regex 检测",
                )
            )
        # 2. Attribute call: os.system / pickle.loads / ...
        if isinstance(func, ast.Attribute):
            value = func.value
            if isinstance(value, ast.Name):
                full = (value.id, func.attr)
                if full in _AST_DANGEROUS_ATTRS:
                    findings.append(
                        Finding(
                            severity=Severity.BLOCK,
                            pattern=_ast_attr_pattern_name(full),
                            line_no=node.lineno,
                            snippet=f"call to {full[0]}.{full[1]}()",
                            reason=f"AST 检测到 {full[0]}.{full[1]}()",
                        )
                    )

                # 3. multiline open().write() — 跟踪 open() 赋值的变量 (NEW R13)
                if func.attr == "write" and value.id in open_vars:
                    findings.append(
                        Finding(
                            severity=Severity.WARN,
                            pattern="open_write",
                            line_no=node.lineno,
                            snippet=f".write() on {value.id} (bound to open())",
                            reason="open().write() 可被 path 注入, 应该用 with open() + path validate",
                        )
                    )

    # 递归 walk 子节点
    for child in ast.iter_child_nodes(node):
        findings.extend(_scan_ast_node(child, source, open_vars))

    return findings


def scan_ast(code: str, source: str = "<input>") -> list[Finding]:
    """Layer 2: AST 扫描. 解析失败 → 返回空 (regex 已 catch 表面错误).

    Args:
        code: 源代码字符串
        source: 来源标识

    Returns:
        Finding 列表. SyntaxError → [] (静默, 不抛).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return _scan_ast_node(tree, source)


# ============================================================
# Combined scan
# ============================================================
def scan_code(code: str, source: str = "<input>") -> list[Finding]:
    """两层扫描合并, 去重 (同 severity+pattern+line 只保留 1 个).

    Args:
        code: 源代码字符串
        source: 来源标识

    Returns:
        去重后的 Finding 列表.
    """
    findings = scan_regex(code, source) + scan_ast(code, source)
    # 去重: (severity, pattern, line_no) 三元组去重
    seen: set[tuple[Severity, str, int | None]] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = (f.severity, f.pattern, f.line_no)
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def has_block_findings(findings: list[Finding]) -> bool:
    """是否有 BLOCK 级别 finding."""
    return any(f.severity == Severity.BLOCK for f in findings)


def format_findings(findings: list[Finding]) -> str:
    """格式化 findings 为可读字符串.

    Args:
        findings: Finding 列表

    Returns:
        多行可读文本. 空 findings → "(无 safety finding)"
    """
    if not findings:
        return "(无 safety finding)"
    lines: list[str] = []
    for f in findings:
        loc = f"line {f.line_no}" if f.line_no else "全文"
        lines.append(f"  [{f.severity.value}] {f.pattern} @ {loc}: {f.snippet!r}")
        lines.append(f"      → {f.reason}")
    return "\n".join(lines)


# ============================================================
# Convenience: scan_file / scan_directory
# ============================================================
def scan_file(path: Path) -> list[Finding]:
    """扫描一个文件."""
    code = path.read_text(encoding="utf-8")
    return scan_code(code, str(path))


def scan_directory(directory: Path) -> dict[Path, list[Finding]]:
    """扫描目录下所有 .py 文件, 按路径排序.

    Args:
        directory: 要扫描的目录路径

    Returns:
        {file_path: [Finding, ...]} 字典. 无 .py 文件 → {}.
    """
    out: dict[Path, list[Finding]] = {}
    for p in sorted(directory.glob("**/*.py")):
        out[p] = scan_file(p)
    return out


__all__ = [
    "Severity",
    "Finding",
    "scan_regex",
    "scan_ast",
    "scan_code",
    "scan_file",
    "scan_directory",
    "has_block_findings",
    "format_findings",
]
