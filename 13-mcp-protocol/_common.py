"""13-mcp-protocol 共享辅助: 复用 L1 _common + MCP 教学用 banner.

复用 L1: banner + get_llm (via importlib.util 按路径加载, 跟 09/10/11/12 一致).
  - 不用 sys.path hack, 避免 import _common 时拿到自己 (circular)
  - 用唯一 module name '_l1_common' 隔离

新增:
  - step(): 跟 09/10/11/12 同风格, 输出 "--- Step N: title ---"
  - output_dir(): 每个 demo 写报告到这里 (gitignored)
  - run_async(): 同步上下文跑 coroutine (跟 12 同, 教学便利)
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

# Windows GBK: LLM 返回 emoji/中文 → 默认 cp936 崩. 提前 reconfigure.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================
# 复用 L1 _common — 不要重复 provider 切换代码
# ============================================================
_ROOT = Path(__file__).resolve().parent.parent
_L1_COMMON_PATH = _ROOT / "01-langchain-basics" / "_common.py"

_spec = importlib.util.spec_from_file_location("_l1_common", _L1_COMMON_PATH)
_l1_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_l1_common)

# 暴露 L1 的两个公开符号
banner = _l1_common.banner
get_llm = _l1_common.get_llm


# ============================================================
# 进度显示 — 跟 09/10/11/12 同风格
# ============================================================
def step(n: int, title: str) -> None:
    """打印步骤: --- Step N: title ---."""
    print(f"\n--- Step {n}: {title} ---")


# ============================================================
# output/ 目录 — demo 写报告到这里 (gitignored)
# ============================================================
_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def output_dir() -> Path:
    """返回 output/ 目录, 不存在则创建."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


# ============================================================
# 异步 helper — 同步上下文跑 coroutine
# ============================================================
def run_async(coro):
    """从同步函数跑 coroutine (教学 demo 简化).

    跟 12-async-pipeline 同 — Jupyter 兼容 wrapper.
    生产代码用 `asyncio.run(coro)` 即可.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("已有 event loop 在运行, 请用 'await coro'")
    except RuntimeError as e:
        if "no current event loop" in str(e).lower():
            pass
        elif "已有 event loop" in str(e):
            raise
        else:
            raise
    return asyncio.run(coro)


__all__ = ["banner", "get_llm", "step", "output_dir", "run_async"]