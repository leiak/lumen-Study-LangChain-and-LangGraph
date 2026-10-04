"""09-codegen-agent 共享辅助: 复用 L1 _common + 加 codegen 专用 helpers.

复用 L1: banner + get_llm (via importlib.util 按路径加载, 跟 08-cli-assistant 一致).
  - 不用 sys.path hack, 避免 import _common 时拿到自己 (circular)
  - 用唯一 module name '_l1_common' 隔离
新增: spec_loader (从 markdown/text 读 spec) + output_writer (写到 output/).
"""
from __future__ import annotations

import importlib.util
import re
import textwrap
from pathlib import Path

# ============================================================
# 复用 L1 _common — 不要重复 provider 切换代码
# ============================================================
# 按路径加载 L1 的 _common (绕开 sys.modules['_common'] 命名冲突)
_ROOT = Path(__file__).resolve().parent.parent
_L1_COMMON_PATH = _ROOT / "01-langchain-basics" / "_common.py"

_spec = importlib.util.spec_from_file_location("_l1_common", _L1_COMMON_PATH)
_l1_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_l1_common)

# 暴露 L1 的两个公开符号
banner = _l1_common.banner
get_llm = _l1_common.get_llm


# ============================================================
# output/ 目录 — 所有 demo 写出的代码放这里 (gitignored)
# ============================================================
_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def output_dir() -> Path:
    """返回 output/ 目录, 不存在则创建."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def write_code_file(filename: str, content: str) -> Path:
    """写一个代码文件到 output/. 返回写入路径."""
    out = output_dir() / filename
    out.write_text(content, encoding="utf-8")
    return out


# ============================================================
# Spec loader — 读 markdown / text spec
# ============================================================
def load_spec(source: str | Path) -> str:
    """从文件路径或字符串加载 spec.

    Args:
        source: 文件路径 (str/Path) 或 raw spec 字符串 (含换行)

    Returns:
        spec 字符串 (strip 过)
    """
    p = Path(source)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return str(source).strip()


def preview_spec(text: str, max_chars: int = 300) -> str:
    """截断 spec 用于打印 (避免长 spec 刷屏)."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"...\n[共 {len(text)} 字符, 截断]"


# ============================================================
# Code block 提取 (从 LLM 输出里抓 ```python ... ``` 块)
# ============================================================
_PY_BLOCK_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_python_blocks(text: str) -> list[str]:
    """从 LLM 输出提取所有 ```python ... ``` 块.

    Returns:
        list of code strings. 没找到 → [text] (整段当 code)
    """
    blocks = _PY_BLOCK_RE.findall(text)
    if not blocks:
        return [text.strip()]
    return [b.strip() for b in blocks]


# ============================================================
# 进度显示
# ============================================================
def step(n, title: str) -> None:  # noqa: ANN001 — n 可以是 int 或 str
    """打印步骤: >>> [1] title."""
    print(f"\n>>> [{n}] {title}")


# ============================================================
# Example spec — 5 个 demo 共用
# ============================================================
EXAMPLE_SPEC = textwrap.dedent("""\
    # FizzBuzz 函数

    写一个 Python 函数 `fizzbuzz(n: int) -> str`, 输入 1 到 n 的整数:

    - 能被 3 整除 → 返回 "Fizz"
    - 能被 5 整除 → 返回 "Buzz"
    - 能被 15 整除 → 返回 "FizzBuzz"
    - 否则 → 返回数字本身 (str)

    要求:
    - 用类型注解
    - 边界: n=0 返回 "0", 负数返回 "" (空字符串)
    - 加 docstring (Google 风格)

    测试: 写 pytest 测试覆盖 4 种情况 + 边界.
""")


def get_example_spec() -> str:
    """返回共用 FizzBuzz spec (5 个 demo 默认用它)."""
    return EXAMPLE_SPEC


__all__ = [
    "banner", "get_llm",
    "output_dir", "write_code_file",
    "load_spec", "preview_spec", "extract_python_blocks", "step",
    "get_example_spec",
]
