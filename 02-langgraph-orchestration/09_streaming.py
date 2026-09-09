"""09_streaming.py — Streaming: 流式输出.

学完这个模块你能回答:
1.  stream vs astream 区别?
2.  stream_mode 有哪些? (values / updates / messages / events / custom)
3.  怎么给前端输出 token 级流?
4.  怎么用 stream_mode="custom" 让节点主动推进度?
5.  怎么同时订阅多个 stream_mode (传 list)?
6.  async stream 怎么写?

跑法:
    python 09_streaming.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Annotated

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from _common import banner, get_llm

# ============================================================
# 共享 Agent
# ============================================================


@tool
def get_weather(city: str) -> str:
    """查天气."""
    return f"{city} 晴 25°C"


def build_agent():
    llm = get_llm()
    return create_agent(
        model=llm, tools=[get_weather],
        checkpointer=InMemorySaver(),
        system_prompt="你是一个简短助手, 回答不超过 50 字。",
    )


# ============================================================
# 1. stream_mode="values" — 每步返回完整 state
# ============================================================
banner('1. stream_mode="values" — 完整 state')


def demo_values_mode() -> None:
    agent = build_agent()
    print(">>> 流式输出 (values mode — 每次是完整 state):")
    for chunk in agent.stream(
        {"messages": [HumanMessage("上海天气?")]},
        config={"configurable": {"thread_id": "stream-1"}},
        stream_mode="values",
    ):
        msgs = chunk.get("messages", [])
        if msgs:
            last = msgs[-1]
            print(f"  [{type(last).__name__}] {(last.content or '')[:60]}")

    # 💡 values 模式适用:
    #   - 调试: 看每步后整个 state 长啥样
    #   - 同步刷新: 整页替换 UI


# ============================================================
# 2. stream_mode="updates" — 每步返回 state delta
# ============================================================
banner('2. stream_mode="updates" — 增量')


def demo_updates_mode() -> None:
    agent = build_agent()
    print(">>> 流式输出 (updates mode — 每步只有 delta):")
    for chunk in agent.stream(
        {"messages": [HumanMessage("北京天气?")]},
        config={"configurable": {"thread_id": "stream-2"}},
        stream_mode="updates",
    ):
        # chunk = {node_name: state_delta}
        for node, delta in chunk.items():
            if "messages" in delta:
                for m in delta["messages"]:
                    print(f"  [node={node}] {type(m).__name__}: {(m.content or '')[:60]}")

    # 💡 updates 模式适用:
    #   - 前端只关心"新增了什么" (chat 场景最常用)
    #   - patch 风格的状态更新


# ============================================================
# 3. stream_mode="messages" — LLM token 级流
# ============================================================
banner('3. stream_mode="messages" — token 级流 (LLM)')


def demo_messages_mode() -> None:
    agent = build_agent()
    print(">>> token 级流 (像 ChatGPT 那样一个字一个字蹦):")
    print(">>> ", end="", flush=True)
    for token, metadata in agent.stream(
        {"messages": [HumanMessage("介绍 LangGraph")]},
        config={"configurable": {"thread_id": "stream-3"}},
        stream_mode="messages",
    ):
        if hasattr(token, "content") and token.content:
            # metadata 里能拿到 langgraph_node / langgraph_path
            print(token.content, end="", flush=True)
    print()


# ============================================================
# 4. stream_mode="events" — 详细事件流
# ============================================================
banner('4. stream_mode="events" — 详细事件')


def demo_events_mode() -> None:
    agent = build_agent()
    print(">>> events mode (前 6 个事件, 含 on_chain_start / on_llm_stream 等):")
    for i, event in enumerate(agent.stream(
        {"messages": [HumanMessage("广州?")]},
        config={"configurable": {"thread_id": "stream-4"}},
        stream_mode="events",
    )):
        kind = list(event.keys())[0]
        print(f"  [{i}] {kind}: {str(event[kind])[:80]}")
        if i >= 5:
            break

    # 💡 events 适用: 调试 / 监控 / 上报 LangSmith


# ============================================================
# 5. stream_mode="custom" — 节点内主动推进度
# ============================================================
banner('5. stream_mode="custom" — 节点主动推进度')


def demo_custom_writer() -> None:
    class State(TypedDict):
        messages: Annotated[list, add_messages]

    def slow_node(state: State):
        # get_stream_writer() 拿到当前流的 writer, 直接写 dict 出去
        writer = get_stream_writer()
        for i in range(5):
            writer({"progress": f"step {i+1}/5"})
            time.sleep(0.05)
        return {"messages": [HumanMessage(content="done")]}

    graph = StateGraph(State)
    graph.add_node("slow", slow_node)
    graph.add_edge(START, "slow")
    graph.add_edge("slow", END)
    app = graph.compile()

    print(">>> 节点内主动推 progress:")
    for chunk in app.stream({"messages": []}, stream_mode="custom"):
        print(f"  [custom] {chunk}")

    # 💡 实战: 长任务里推 "正在查 A 接口... 查 B 接口... 正在生成报告..."
    #   类似 SSE (server-sent events) 的前端体验


# ============================================================
# 6. 同时订阅多个 stream_mode (传 list)
# ============================================================
banner('6. 同时订阅多个 stream_mode (传 list)')


def demo_multi_modes() -> None:
    agent = build_agent()
    print(">>> 同时开 'updates' + 'messages' 两种流:")
    print("    (chunk 类型是 (mode, chunk) tuple)")

    updates_count = 0
    for mode, chunk in agent.stream(
        {"messages": [HumanMessage("杭州天气?")]},
        config={"configurable": {"thread_id": "stream-multi"}},
        stream_mode=["updates", "messages"],
    ):
        if mode == "updates":
            updates_count += 1
            for node, delta in chunk.items():
                if "messages" in delta:
                    print(f"  [updates / {node}] {len(delta['messages'])} new msg(s)")
        elif mode == "messages":
            # token 流: 打印到一行
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)
    print(f"\n  (updates 事件共 {updates_count} 次)")

    # 💡 实战: 前端 SSE 同时拿 "步骤进度 (updates)" 和 "token 流 (messages)"
    #   用 stream_mode=list 一次订阅, 比开两次 stream 高效


# ============================================================
# 7. 异步流 (astream)
# ============================================================
banner("7. 异步流 (astream)")


async def demo_async_stream() -> None:
    agent = build_agent()
    print(">>> async stream (FastAPI / WebSocket 集成场景):")
    async for chunk in agent.astream(
        {"messages": [HumanMessage("深圳?")]},
        config={"configurable": {"thread_id": "stream-async"}},
        stream_mode="updates",
    ):
        for node, delta in chunk.items():
            if "messages" in delta:
                print(f"  [async / node={node}] {type(delta['messages'][0]).__name__}")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    for name, fn in [
        ("demo_values_mode", demo_values_mode),
        ("demo_updates_mode", demo_updates_mode),
        ("demo_messages_mode", demo_messages_mode),
        ("demo_events_mode", demo_events_mode),
        ("demo_custom_writer", demo_custom_writer),
        ("demo_multi_modes", demo_multi_modes),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    try:
        asyncio.run(demo_async_stream())
    except Exception as e:
        print(f"[demo_async_stream] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 09_streaming.py 全部 demo 跑完。")