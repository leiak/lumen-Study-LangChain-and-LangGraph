"""_common.py — 复用 01-langchain-basics/_common.py 的 LLM 工厂 + banner.

CLI 模块独立目录,但需要复用项目其它模块已经写好的:
  - get_llm(): 4-provider 自动检测 (Anthropic/DeepSeek/MiniMax/OpenAI)
  - banner():  分节标题打印

实现要点:
  1. 不复制 L1 的 _common.py (避免双份维护)
  2. 用 importlib.util.spec_from_file_location 直接按路径加载, 不污染 sys.path
     (避免破坏 08-cli-assistant/ 内部兄弟模块的互相 import)
  3. CLI 内部所有 demo / REPL 都从这里 import

跑法:
    python 08-cli-assistant/main.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

# 项目根 (parent of 08-cli-assistant/), L1 的 _common.py 在兄弟目录
_ROOT = Path(__file__).resolve().parent.parent
_L1_COMMON_PATH = _ROOT / "01-langchain-basics" / "_common.py"

# 按路径加载 L1 的 _common (绕开 sys.path, 避免模块名冲突 + 保持兄弟 import 通)
_spec = importlib.util.spec_from_file_location("_l1_common", _L1_COMMON_PATH)
_l1_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_l1_common)

# 暴露 L1 的两个公开符号
banner = _l1_common.banner
get_llm = _l1_common.get_llm

__all__ = ["banner", "get_llm"]