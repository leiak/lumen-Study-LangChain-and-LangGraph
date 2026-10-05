"""01_astream_modes.py — Demo 1: LangGraph 异步流式 5 种模式.

学完这个 demo 你能回答:
1.  astream_events v1 vs v2 区别? (v2 必须 version="v2",event 字段更清晰)
2.  astream 4 种 mode (updates/values/messages/custom) 怎么选?
3.  哪种模式给前端 token 级流式用? (messages + on_chat_model_stream)
4.  哪种模式给监控/debug 用? (updates + on_chain_start/end)
5.  哪种模式给批量数据采集? (values 全 state)
6.  ainvoke vs aastream 一致性? (config 复用 + 同一 thread)

跑法:
    python 01_astream_modes.py
"""
from __future__ import annotations

import os
import time

from langchain_core.messages import HumanMessage

from _common import banner, get_llm, step
from async_pipeline import gather_safe

# ============================================================
# Demo
# ============================================================
banner("Demo 1: Async Streaming Modes (5 种)")


# =========================================================
# Step 1: astream_events v2 — 5 类事件
# =========================================================
async def demo_astream_events_v2() -> None:
    step(1, "astream_events v2 — 5 类事件 (chain / tool / chat_model / retriever / parser)")

    from langchain.agents import create_agent

    from async_pipeline import stream_to_sse  # noqa: F401  (示例引用)

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[],  # 简单 — 不带 tool
    )

    event_types: list[str] = []
    t0 = time.perf_counter()

    # version="v2" — LangChain 1.x 推荐的现代 API
    async for ev in agent.astream_events(
        {"messages": [HumanMessage("用一句话介绍 RAG")]},
        version="v2",
    ):
        ev_type = ev.get("event", "?")
        event_types.append(ev_type)

    elapsed = time.perf_counter() - t0
    print(f"  收到 {len(event_types)} 个事件, 耗时 {elapsed:.2f}s")
    # 统计事件类型
    from collections import Counter
    counter = Counter(event_types)
    print(f"  事件类型分布:")
    for ev_name, count in sorted(counter.items()):
        print(f"    {ev_name}: {count}")

    # 💡 5 类核心事件 (v2):
    #    - on_chain_start / end — 整个 chain 边界
    #    - on_chat_model_start / stream / end — LLM 边界 (stream 触发每个 token)
    #    - on_tool_start / end — 工具调用边界
    #    - on_retriever_start / end — 检索工具
    #    - on_parser_start / end — 输出解析
    # 实战: SSE 用 ev["event"] 做事件名, ev["data"] 转 JSON


# =========================================================
# Step 2: astream mode="updates" — 节点级 state delta
# =========================================================
async def demo_astream_updates() -> None:
    step(2, 'astream mode="updates" — 节点级 state delta')

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    print(">>> 流式看 state 节点更新:")
    async for chunk in agent.astream(
        {"messages": [HumanMessage("什么是 vector store?")]},
        stream_mode="updates",
    ):
        # chunk = {node_name: state_delta}
        for node_name, delta in chunk.items():
            msgs = delta.get("messages", [])
            if msgs:
                last = msgs[-1]
                content = getattr(last, "content", "") or getattr(last, "type", "?")
                print(f"  [{node_name}] msg type={last.type} content[:80]='{str(content)[:80]}'")

    # 💡 mode="updates" — 监控/debug 场景
    #    知道每一步走了哪个 node, 增量改了什么
    #    vs mode="values" 看完整 state (下面 Step 4)


# =========================================================
# Step 3: astream mode="messages" — token 级流
# =========================================================
async def demo_astream_messages() -> None:
    step(3, 'astream mode="messages" — token 级流 (LLM 输出每个 token)')

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    print(">>> 流式拿 token:")
    token_count = 0
    async for msg_chunk, meta in agent.astream(
        {"messages": [HumanMessage("LangGraph 1.x 的核心改进是什么?")]},
        stream_mode="messages",
    ):
        token_count += 1
        # msg_chunk 是 AIMessageChunk (langchain_core.messages)
        # meta 含 graph 节点信息
        node = meta.get("langgraph_node", "?")
        content = getattr(msg_chunk, "content", "")
        # 每个 chunk 通常很短 (1 token), 攒一行打印一次
        if token_count <= 3 or token_count % 10 == 0:
            print(f"  [{node}] token#{token_count}: '{content[:40]}'")

    print(f"  总 token chunk 数: {token_count}")

    # 💡 mode="messages" — 前端打字机效果
    #    vs v2 的 on_chat_model_stream 事件 — 等价, 但 messages 接口更直接
    #    实战: 前端 SSE 用 messages 流 → 实时显示


# =========================================================
# Step 4: astream mode="values" — 全 state 每次重发
# =========================================================
async def demo_astream_values() -> None:
    step(4, 'astream mode="values" — 每次 emit 完整 messages 列表')

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    snapshot_count = 0
    async for state in agent.astream(
        {"messages": [HumanMessage("什么是 embedding?")]},
        stream_mode="values",
    ):
        snapshot_count += 1
        msgs = state.get("messages", [])
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", "") or ""
            print(f"  snapshot #{snapshot_count}: msgs={len(msgs)} last.content[:60]='{content[:60]}'")

    print(f"  总 snapshot 数: {snapshot_count}")

    # 💡 mode="values" — 批量数据采集
    #    每次 emit 完整 state, 适合 "导出所有中间结果"
    #    vs updates 只 emit delta (节点级增量)


# =========================================================
# Step 5: astream mode="custom" — 自定义事件
# =========================================================
async def demo_astream_custom() -> None:
    step(5, 'astream mode="custom" — 自定义事件 (业务 progress / log)')

    from langgraph.graph import END, START, MessagesState, StateGraph

    from async_pipeline import gather_safe  # noqa: F401

    # 简单 graph: 2 个节点, 每个 emit 自定义事件
    async def step_a(state: MessagesState) -> dict:
        # get_stream_writer — LangGraph 提供的 emit custom event 接口
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        writer({"phase": "A", "progress": 0.5, "msg": "processing..."})
        return {"messages": []}

    async def step_b(state: MessagesState) -> dict:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        writer({"phase": "B", "progress": 1.0, "msg": "done"})
        return {"messages": []}

    g = StateGraph(MessagesState)
    g.add_node("step_a", step_a)
    g.add_node("step_b", step_b)
    g.add_edge(START, "step_a")
    g.add_edge("step_a", "step_b")
    g.add_edge("step_b", END)
    graph = g.compile()

    print(">>> 监听 custom 事件:")
    custom_events: list[dict] = []
    async for ev in graph.astream(
        {"messages": [HumanMessage("test")]},
        stream_mode="custom",
    ):
        # ev 是 writer() 里传的 dict
        custom_events.append(ev)
        print(f"  收到 custom: {ev}")

    print(f"  总 custom 事件: {len(custom_events)}")

    # 💡 mode="custom" — 业务 progress / 长任务进度条
    #    例: 数据迁移任务, 每个 chunk 完成 emit {progress: 0.3}
    #    前端拿 progress 显示进度条
    #    实战: writer() 在任何节点里调, 不需要 return message


# =========================================================
# Step 6: 对比表 (5 种模式)
# =========================================================
async def demo_mode_comparison() -> None:
    step(6, "5 种模式选择指南")

    print("""
  ┌────────────────┬─────────────────────────────────────────────┐
  │ 模式            │ 用法                                         │
  ├────────────────┼─────────────────────────────────────────────┤
  │ updates         │ 监控 / debug — 每节点增量 state delta         │
  │ values          │ 批量采集 — 每节点完整 state snapshot          │
  │ messages        │ 前端 token 流 — LLM 每次输出 token            │
  │ custom          │ 业务 progress — 主动 writer() 弹事件          │
  │ events (v2)     │ 5 类事件 + token 流 — 监控 + 前端合一        │
  └────────────────┴─────────────────────────────────────────────┘

  实战选择:
    - 前端 token 流:   astream_events v2 (on_chat_model_stream)
    - 后端监控:        astream_events v2 (on_chain_start/end)
    - 进度条:          astream mode="custom" + writer()
    - 数据导出:        astream mode="values"
    - 简单 debug:      astream mode="updates"
""")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    if not has_key:
        print("[!] 没 API key — Step 5 custom event 不需要, 其它 demo 跑不了")
        # Step 5 custom event 也不需要 LLM (纯 graph 测试)
        print(">>> 跑 Step 5 (custom event, 不需要 LLM)")

        from _common import run_async
        run_async(demo_astream_custom())
        print("\n[OK] 01_astream_modes.py — 仅 demo 5 跑通。")
        import sys
        sys.exit(0)

    # 顺序跑 — 每次 invoke 是独立 thread
    demos = [
        demo_astream_events_v2,
        demo_astream_updates,
        demo_astream_messages,
        demo_astream_values,
        demo_astream_custom,
        demo_mode_comparison,
    ]

    from _common import run_async

    # 5 个需要 LLM 的 demo 并发跑 — 节省总时间
    # 实战: gather_safe 让一个失败不影响其它
    from async_pipeline import gather_safe
    llm_needed = demos[:5]
    results = run_async(gather_safe(*(d() for d in llm_needed)))

    for fn, r in zip(llm_needed, results):
        if isinstance(r, Exception):
            print(f"  [{fn.__name__}] 失败: {type(r).__name__}: {str(r)[:100]}")
        else:
            print(f"  [{fn.__name__}] OK")

    # Step 6 是 print, 直接调
    demo_mode_comparison()

    print("\n[OK] 01_astream_modes.py 全部 demo 跑完。")
    print("[i]   5 个 LLM demo 用 gather_safe 并发跑, 失败隔离.")