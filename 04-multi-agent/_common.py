"""Layer 4 共享 helper."""
from __future__ import annotations

import os
import warnings
from pathlib import Path

# ============================================================
# 静音 langgraph 1.x 加载时的 known warning
# ============================================================
# 调用链: import langchain_community.vectorstores.FAISS (或其它 langchain_community)
#       → ... → langgraph.checkpoint.base (line 18)
#       → jsonplus.py: LC_REVIVER = Reviver()
#       → langchain_core/load/load.py: Reviver.__init__ 检测 allowed_objects=None
#       → 触发 LangChainPendingDeprecationWarning
#
# 这条警告不影响运行 (Reviver 内部自动 fallback 到 'core'),
# 但每次 demo 跑都看到一句 noise 比较烦。
# 等 langgraph 显式传 allowed_objects 之后再删除。
from langchain_core._api.deprecation import LangChainPendingDeprecationWarning  # noqa: E402

warnings.filterwarnings(
    "ignore",
    message=r".*allowed_objects.*",
    category=LangChainPendingDeprecationWarning,
)

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / ".env.example", override=False)


_PLACEHOLDER_VALUES = {
    "your_minimax_api_key_here",
    "your_deepseek_api_key_here",
    "your_api_key_here",
    "sk-...",
    "",
}


def _is_real_key(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in _PLACEHOLDER_VALUES


def _make_anthropic_llm(temperature: float, **kwargs) -> BaseChatModel:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("ANTHROPIC_API_KEY 未设置或为占位符")
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    return init_chat_model(
        model=f"anthropic:{model}", temperature=temperature, api_key=api_key, **kwargs,
    )


def _make_deepseek_llm(temperature: float, **kwargs) -> BaseChatModel:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("DEEPSEEK_API_KEY 未设置或为占位符")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    return init_chat_model(
        model=f"openai:{model}", temperature=temperature, api_key=api_key,
        base_url=base_url, **kwargs,
    )


def _make_minimax_llm(temperature: float, **kwargs) -> BaseChatModel:
    api_key = os.getenv("MINIMAX_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("MINIMAX_API_KEY 未设置或为占位符")
    model = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
    base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
    return init_chat_model(
        model=f"openai:{model}", temperature=temperature, api_key=api_key,
        base_url=base_url, **kwargs,
    )


def _make_openai_llm(temperature: float, **kwargs) -> BaseChatModel:
    api_key = os.getenv("OPENAI_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("OPENAI_API_KEY 未设置或为占位符")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return init_chat_model(
        model=f"openai:{model}", temperature=temperature, api_key=api_key, **kwargs,
    )


_PROVIDERS = {
    "anthropic": _make_anthropic_llm,
    "deepseek": _make_deepseek_llm,
    "minimax": _make_minimax_llm,
    "openai": _make_openai_llm,
}


def get_llm(temperature: float = 0.0, **kwargs) -> BaseChatModel:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider:
        factory = _PROVIDERS.get(provider)
        if factory is None:
            raise RuntimeError(f"LLM_PROVIDER={provider!r} 不在 {sorted(_PROVIDERS)} 里。")
        try:
            return factory(temperature, **kwargs)
        except ValueError as e:
            raise RuntimeError(f"LLM_PROVIDER={provider} 但 {e}") from e
    for factory in (
        _make_anthropic_llm, _make_deepseek_llm, _make_minimax_llm, _make_openai_llm,
    ):
        try:
            return factory(temperature, **kwargs)
        except ValueError:
            continue
    raise RuntimeError(
        "未找到有效的 LLM API key。\n"
        "请在 .env 设置 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY\n"
        "或者用 LLM_PROVIDER=deepseek 之类强制指定(优先级最高)。"
    )


def banner(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}\n  {title}\n{bar}")
