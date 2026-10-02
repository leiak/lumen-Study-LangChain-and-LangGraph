"""共享辅助: LLM 工厂 + 终端美化 + 环境变量加载.

每个 L1 模块都会从这里 import get_llm(),不需要重复写 provider 切换代码。
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
import sys

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
    "your_minimax_api_key_here",
    "your_deepseek_api_key_here",
}


def _is_real_key(value: str | None) -> bool:
    """判断是不是真实 API key (过滤 .env.example 里的占位符)."""
    return bool(value) and value.strip().lower() not in _PLACEHOLDER_VALUES


# ============================================================
# 每个 provider 一个工厂函数 — 失败时抛 ValueError,不要 raise 出去
# ============================================================
def _make_anthropic_llm(temperature: float, **kwargs) -> BaseChatModel:
    """Anthropic Claude."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("ANTHROPIC_API_KEY 未设置或为占位符")
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    return init_chat_model(
        model=f"anthropic:{model}",
        temperature=temperature,
        api_key=api_key,
        **kwargs,
    )


def _make_deepseek_llm(temperature: float, **kwargs) -> BaseChatModel:
    """DeepSeek (OpenAI 兼容协议,base_url 官方固定)."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("DEEPSEEK_API_KEY 未设置或为占位符")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    return init_chat_model(
        model=f"openai:{model}",
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )


def _make_minimax_llm(temperature: float, **kwargs) -> BaseChatModel:
    """MiniMax M3 (OpenAI 兼容)."""
    api_key = os.getenv("MINIMAX_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("MINIMAX_API_KEY 未设置或为占位符")
    model = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
    base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
    return init_chat_model(
        model=f"openai:{model}",
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        default_headers={"Accept-Encoding": "gzip, deflate"},
        **kwargs,
    )


def _make_openai_llm(temperature: float, **kwargs) -> BaseChatModel:
    """OpenAI 官方."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not _is_real_key(api_key):
        raise ValueError("OPENAI_API_KEY 未设置或为占位符")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return init_chat_model(
        model=f"openai:{model}",
        temperature=temperature,
        api_key=api_key,
        **kwargs,
    )


# name -> factory 的注册表 (LLM_PROVIDER 用这个查)
_PROVIDERS = {
    "anthropic": _make_anthropic_llm,
    "deepseek": _make_deepseek_llm,
    "minimax": _make_minimax_llm,
    "openai": _make_openai_llm,
}


def get_llm(temperature: float = 0.0, **kwargs) -> BaseChatModel:
    """统一的 LLM 工厂.

    优先级(谁先匹配就用谁):
      A. LLM_PROVIDER 显式指定 (最高优先级,无视 shell env)
         取值: anthropic / deepseek / minimax / openai
         用途: shell 里 ANTHROPIC_API_KEY 被 Claude Code 全局设置污染时,
               在 .env 写 `LLM_PROVIDER=deepseek` 强制走 DeepSeek。
      B. ANTHROPIC_API_KEY 存在 -> Claude (anthropic)
      C. DEEPSEEK_API_KEY 存在  -> DeepSeek (openai 兼容)
      D. MINIMAX_API_KEY 存在   -> MiniMax M3 (openai 兼容)
      E. OPENAI_API_KEY 存在    -> OpenAI
      F. 都没有                 -> 抛错

    想用其它 provider (Ollama / DashScope / 硅基流动),加一个 _make_xxx_llm +
    在 _PROVIDERS 注册表里加一行即可。
    """
    # A. LLM_PROVIDER 强制选择
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider:
        factory = _PROVIDERS.get(provider)
        if factory is None:
            raise RuntimeError(
                f"LLM_PROVIDER={provider!r} 不在已知列表 {sorted(_PROVIDERS)} 里。"
            )
        try:
            return factory(temperature, **kwargs)
        except ValueError as e:
            raise RuntimeError(
                f"LLM_PROVIDER={provider} 但 {e}。\n"
                "请在 .env 里设置对应 provider 的 API key。\n"
                "或者把 LLM_PROVIDER 注释掉,改用自动检测模式。"
            ) from e

    # B/C/D/E. 自动检测: 谁先填了真实 key 就用谁
    for factory in (
        _make_anthropic_llm,
        _make_deepseek_llm,
        _make_minimax_llm,
        _make_openai_llm,
    ):
        try:
            return factory(temperature, **kwargs)
        except ValueError:
            continue

    raise RuntimeError(
        "未找到有效的 LLM API key。\n"
        "请在项目根目录的 .env 文件中设置以下之一:\n"
        "  - ANTHROPIC_API_KEY=sk-ant-...   (Claude)\n"
        "  - DEEPSEEK_API_KEY=sk-...        (DeepSeek)\n"
        "  - MINIMAX_API_KEY=...            (MiniMax M3)\n"
        "  - OPENAI_API_KEY=sk-...          (OpenAI)\n"
        "\n"
        "或者用 LLM_PROVIDER=deepseek 之类强制指定(优先级最高)。\n"
        "复制 .env.example 为 .env 后填入真实 key。"
    )


def banner(title: str) -> None:
    """打印分节标题."""
    bar = "=" * 60
    print(f"\n{bar}\n  {title}\n{bar}")

def setup() -> None:
    """Windows 终端 UTF-8 修复。
    原因: Windows cmd 默认 GBK, print emoji / 中文 content 可能 UnicodeEncodeError。
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")