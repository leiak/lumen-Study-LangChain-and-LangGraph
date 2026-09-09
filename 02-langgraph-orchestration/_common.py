"""Layer 2 共享 helper."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / ".env.example", override=False)


_PLACEHOLDER_VALUES = {
    "your_minimax_api_key_here",
    "your_api_key_here",
    "sk-...",
    "",
}


def _is_real_key(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in _PLACEHOLDER_VALUES


def get_llm(temperature: float = 0.0, **kwargs) -> BaseChatModel:
    # 1. Anthropic
    if _is_real_key(os.getenv("ANTHROPIC_API_KEY")):
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        return init_chat_model(
            model=f"anthropic:{model}",
            temperature=temperature,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            **kwargs,
        )
    # 2. MiniMax
    if _is_real_key(os.getenv("MINIMAX_API_KEY")):
        model = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
        base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
        return init_chat_model(
            model=f"openai:{model}",
            temperature=temperature,
            api_key=os.getenv("MINIMAX_API_KEY"),
            base_url=base_url,
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
        "  - ANTHROPIC_API_KEY=sk-ant-...\n"
        "  - MINIMAX_API_KEY=...\n"
        "  - OPENAI_API_KEY=sk-..."
    )


def banner(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}\n  {title}\n{bar}")
