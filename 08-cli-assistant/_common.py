"""_common.py — 复用 01-langchain-basics/_common.py 的 LLM 工厂 + banner.

CLI 模块独立目录,但需要复用项目其它模块已经写好的:
  - get_llm(): 4-provider 自动检测 (Anthropic/DeepSeek/MiniMax/OpenAI)
  - banner():  分节标题打印

实现要点:
  1. sys.path 临时加项目根,这样 from _common import get_llm 能找到 01-langchain-basics
  2. 不复制 _common.py 内容,直接 import (避免双份维护)
  3. CLI 内部所有 demo / REPL 都从这里 import

跑法:
    python 08-cli-assistant/main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根 (parent of 08-cli-assistant/), 这样能 import 兄弟模块的 _common
_ROOT = Path(__file__).resolve().parent.parent
_SELF = str(Path(__file__).resolve().parent)

# 关键: 先把当前目录(含本 _common.py)从 sys.path 摘掉,
# 同时把部分初始化的 '_common' 从 sys.modules 弹出,
# 否则下面 `from _common` 会再次找到本文件 → circular import。
sys.path[:] = [p for p in sys.path if p not in ("", _SELF)]
sys.modules.pop("_common", None)

if str(_ROOT / "01-langchain-basics") not in sys.path:
    sys.path.insert(0, str(_ROOT / "01-langchain-basics"))

# 从 L1 _common 复用 (不要复制粘贴,改一处全部生效)
from _common import banner, get_llm  # noqa: E402  (sys.path 改了才能 import)

__all__ = ["banner", "get_llm"]
