"""共享辅助: LLM 工厂 + 终端美化 + 环境变量加载.

每个 L1 模块都会从这里 import get_llm(),不需要重复写 provider 切换代码。
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

# ============================================================
# 静音 langgraph 1.x 加载时的 known warning
# ============================================================
# 调用链: import langchain_community.vectorstores.FAISS
#       → ... → langgraph.checkpoint.base (line 18)
#       → jsonplus.py: LC_REVIVER = Reviver()
#       → langchain_core/load/load.py: Reviver.__init__ 检测 allowed_objects=None
#       → 触发 LangChainPendingDeprecationWarning
#
# 这条警告不影响运行 (Reviver 内部自动 fallback 到 'core'),
# 但每次 demo 跑都看到一句 noise 比较烦。
# 等 langgraph 显式传 allowed_objects 之后再删除这行。
from langchain_core._api.deprecation import LangChainPendingDeprecationWarning  # noqa: E402  (先 import 才能在 filterwarnings 里用)

warnings.filterwarnings(
    "ignore",
    message=r".*allowed_objects.*",
    category=LangChainPendingDeprecationWarning,
)

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

# 加载根目录 .env (兼容 git bash / Windows)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / ".env.example", override=False)  # 兜底:即使没 .env 也能 import


_PLACEHOLDER_VALUES = {
    "sk-",
    "",
}


def _is_real_key(value: str | None) -> bool:
    """判断是不是真实 API key (过滤 .env.example 里的占位符)."""
    return bool(value) and value.strip().lower() not in _PLACEHOLDER_VALUES


def get_llm(temperature: float = 0.0, **kwargs) -> BaseChatModel:
    """统一的 LLM 工厂.

    优先级:
      1. ANTHROPIC_API_KEY 存在 -> 用 Claude (anthropic)
      2. MINIMAX_API_KEY 存在   -> 用 MiniMax (openai 兼容)
      3. OPENAI_API_KEY 存在    -> 用 OpenAI
      4. 都没有                 -> 抛错

    想用其它 provider (Ollama / DeepSeek / DashScope),改这里就行。
    """
    # 1. Anthropic Claude
    if _is_real_key(os.getenv("ANTHROPIC_API_KEY")):
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        return init_chat_model(
            model=f"anthropic:{model}",
            temperature=temperature,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            **kwargs,
        )

    # 2. MiniMax M3 (OpenAI 兼容)
    if _is_real_key(os.getenv("MINIMAX_API_KEY")):
        model = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
        base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
        return init_chat_model(
            model=f"openai:{model}",
            temperature=temperature,
            api_key=os.getenv("MINIMAX_API_KEY"),
            base_url=base_url,
            default_headers={"Accept-Encoding": "gzip, deflate"},
            **kwargs,
        )

    # 3. OpenAI
    if _is_real_key(os.getenv("OPENAI_API_KEY")):
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return init_chat_model(
            model=f"openai:{model}",
            temperature=temperature,
            api_key=os.getenv("OPENAI_API_KEY"),
            **kwargs,
        )

    raise RuntimeError(
        "未找到有效的 LLM API key。\n"
        "请在项目根目录的 .env 文件中设置以下之一:\n"
        "  - ANTHROPIC_API_KEY=sk-ant-...   (Claude)\n"
        "  - MINIMAX_API_KEY=...            (MiniMax M3)\n"
        "  - OPENAI_API_KEY=sk-...          (OpenAI)\n"
        "\n"
        "复制 .env.example 为 .env 后填入真实 key。"
    )


def banner(title: str) -> None:
    """打印分节标题."""
    bar = "=" * 60
    print(f"\n{bar}\n  {title}\n{bar}")
