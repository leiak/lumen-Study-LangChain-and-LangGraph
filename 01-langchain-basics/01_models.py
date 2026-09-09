"""01_models.py — LangChain 1.x Models 入门.

学完这个模块你能回答:
1. 怎么用 init_chat_model 接入任何 provider (MiniMax / OpenAI / Anthropic / Ollama)?
2. 怎么让模型流式输出?
3. 怎么用 Pydantic 让模型吐结构化 JSON?
4. 怎么用 bind_tools 把工具提前绑定给模型?

跑法:
    python 01_models.py
"""
from __future__ import annotations

import os
import re

from langchain_core.output_parsers import BaseOutputParser, PydanticOutputParser
from pydantic import BaseModel, Field

from _common import banner, get_llm


# 兼容各种 CoT 标签:DeepSeek-R1 / Kimi / MiniMax M3 / Qwen3 等都会用其中一种
_THINK_RE = re.compile(
    r"<think>.*?</think>"
    r"|<thinking>.*?</thinking>"
    r"|<reflection>.*?</reflection>",
    flags=re.DOTALL,
)


class StripThinkParser(BaseOutputParser):
    """在解析前先剥掉 <think>...</think> / ... 块。

    推理模型 (R1 / Kimi / MiniMax-M3) 经常把思考过程当普通 content 吐出,
    导致 with_structured_output 的严格 JSON 解析失败。
    """

    inner: BaseOutputParser = Field(...)  # type: ignore[assignment]

    model_config = {"arbitrary_types_allowed": True}

    def parse(self, text: str, **kwargs):
        cleaned = _THINK_RE.sub("", text).strip()
        if not cleaned:
            raise ValueError(f"模型返回为空(被 think 块占满)。原文: {text[:200]}")
        return self.inner.parse(cleaned, **kwargs)


StripThinkParser.model_rebuild()

# ============================================================
# 1. 最基础的调用
# ============================================================
banner("1. init_chat_model + invoke")


def demo_basic_invoke() -> None:
    llm = get_llm()
    print("Provider:", llm.__class__.__name__)

    resp = llm.invoke("用一句话介绍 LangChain 1.x。")
    print("回复ALL:", resp)

    print("回复:", resp.content[:200])
    print("元数据:", resp.response_metadata.get("model_name", "n/a"))


# ============================================================
# 2. 流式输出
# ============================================================
banner("2. stream — token 级流式")


def demo_stream() -> None:
    llm = get_llm()
    print(">>> 流式打字机:")
    for chunk in llm.stream("写一首关于 AI Agent 的七言绝句。"):
        # print("chunk_position",chunk.chunk_position)
        # print("init_tool_calls",chunk.init_tool_calls)
        # print(chunk.content, end="", flush=True)
        print(chunk, end="", flush=True)
    print()


# ============================================================
# 3. 结构化输出 (Pydantic schema)
# ============================================================
banner("3. structured output (Pydantic BaseModel)")


class MovieReview(BaseModel):
    """电影评论的结构化输出."""

    title: str = Field(description="电影名")
    rating: float = Field(description="1-5 星评分")
    pros: list[str] = Field(description="优点,3 条以内")
    cons: list[str] = Field(description="缺点,3 条以内")


def demo_structured_output() -> None:
    # 推理模型 (MiniMax-M3 / R1 / Kimi) 经常不能稳定吐 JSON,所以:
    # 主路: tool_calling — 绕过 CoT,大多数 OpenAI 兼容 provider 都支持
    # 备路: 剥 CoT 后让 Pydantic 解析 (兼容 OpenAI 协议 + Anthropic)
    llm = get_llm()
    prompt = (
        "请评价科幻电影《流浪地球》,必须给出 title / rating(1-5) / "
        "至少 2 条 pros 和 cons。只返回 JSON,不要任何解释。"
    )

    review: MovieReview | None = None

    # 主路: tool_calling
    # LangChain 的 type stub 把 with_structured_output 返回声明成 dict | BaseModel
    # (因为支持 dict / Pydantic / TypedDict 多种 schema),runtime 实际一定是 MovieReview。
    # 用 # type: ignore[assignment] 告诉 type checker: 我比你懂,这里就是 MovieReview。
    try:
        review = llm.with_structured_output(  # type: ignore[assignment]
            MovieReview, method="function_calling"
        ).invoke(prompt)

    except Exception as e:
        print(f"[tool_calling] 失败: {type(e).__name__}: {str(e)[:120]}")

    # 备路: llm | StripThinkParser | PydanticOutputParser
    if review is None:
        print("[fallback] 切换到 strip-think + PydanticOutputParser")
        # llm | parser 就是"管道":把 llm 的输出塞给 parser 当输入。视觉上像 Unix 的 |,但底层是 Runnable 类重载了 __or__ 运算符。 
        # prompt (str)
        #     │
        #     ▼
        # [ llm ]                                  → AIMessage(content="<think>...think</think>\n{json...}")
        #     │ extract .content
        #     ▼
        # [ StripThinkParser ]                     → 用正则剥掉 <think>...</think> → "{json...}"
        #     │
        #     ▼
        # [ PydanticOutputParser(pydantic_object=MovieReview) ]
        #                                             → json.loads() → MovieReview.model_validate() → MovieReview 实例 
        chain = llm | StripThinkParser(
            inner=PydanticOutputParser(pydantic_object=MovieReview)
        )
        review = chain.invoke(prompt)

    assert isinstance(review, MovieReview), f"expected MovieReview, got {type(review)}"
    print(f"片名: {review.title}")
    print(f"评分: {review.rating}/5")
    print(f"优点: {review.pros}")
    print(f"缺点: {review.cons}")


# ============================================================
# 4. bind_tools — 提前把工具绑给模型
# ============================================================
banner("4. bind_tools — 让模型直接调用工具")


def get_weather(city: str) -> str:
    """查某城市天气 (mock)."""
    return f"{city} 晴,25°C"


def demo_bind_tools() -> None:
    llm = get_llm()
    llm_with_tools = llm.bind_tools([get_weather])

    resp = llm_with_tools.invoke("北京今天天气怎么样?")
    print("text:", resp.content or "(空,模型决定调用工具)")
    print("tool_calls:", resp.tool_calls)
    # 真实场景:这里要把 tool_calls 路由回工具执行,见 02_tools.py


# ============================================================
# 5. 多轮对话 (手动管理消息列表)
# ============================================================
banner("5. 多轮对话 — 手动管理 messages")


def demo_multi_turn() -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm()

    messages = [
        SystemMessage(content="你是一个简短的助手,每句不超过 20 字。"),
        HumanMessage(content="我叫王明。"),
    ]
    resp1 = llm.invoke(messages)
    messages.append(resp1)
    print("助手 1:", resp1.content)

    messages.append(HumanMessage(content="我叫什么?"))
    resp2 = llm.invoke(messages)
    print("助手 2:", resp2.content)


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    # 检查是否有 API key
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    # demo_basic_invoke()
    # demo_stream()
    # demo_structured_output()
    # demo_bind_tools()
    demo_multi_turn()

    print("\n[OK] 01_models.py 全部 demo 跑完。")
