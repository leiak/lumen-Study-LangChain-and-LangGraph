"""05_websocket.py — Demo 5: WebSocket 双向流 (对话 / 中途可打断).

学完这个 demo 你能回答:
1.  WebSocket vs SSE 区别? (WS 双向, SSE 单向 — 实战选哪个)
2.  FastAPI WebSocket endpoint 怎么构造?
4.  中途用户打断怎么实现? (cancel task + partial response)
5.  多轮对话 thread_id 怎么管? (per-connection or per-user)
6.  客户端断连时 agent.aiterate 会怎样? (GeneratorExit)
7.  websockets 库怎么测?

跑法:
    python 05_websocket.py        # 跑 (websockets 客户端自测, 不起 server)
    uvicorn 05_websocket:app      # 真起 server (另开 terminal 测)
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

from _common import banner, get_llm, run_async, step

# ============================================================
# Demo
# ============================================================
banner("Demo 5: WebSocket Bidirectional Streaming")


# =========================================================
# Step 1: WebSocket vs SSE 对比
# =========================================================
async def demo_ws_vs_sse() -> None:
    step(1, "WebSocket vs SSE — 实战选择")

    print("""
  ┌────────────────┬─────────────────────┬──────────────────────┐
  │ 维度            │ SSE                  │ WebSocket            │
  ├────────────────┼─────────────────────┼──────────────────────┤
  │ 方向            │ 单向 (server→client) │ 双向                 │
  │ 协议            │ HTTP                 │ 升级到 WS 协议       │
  │ 浏览器原生      │ ✅ EventSource       │ ✅ WebSocket         │
  │ 鉴权            │ Cookie / Header     │ Cookie / Token / Query│
  │ 多轮对话        │ 需客户端重连         │ 持久连接             │
  │ 中途打断        │ 关连接即可           │ send cancel          │
  │ 代理穿透        │ 简单 (HTTP)         │ 复杂 (Upgrade)        │
  │ 服务器推送      │ ✅                  │ ✅                   │
  └────────────────┴─────────────────────┴──────────────────────┘

  实战选择:
    - 简单 chat 流: SSE (OpenAI / Claude API 都用 SSE)
    - 多轮实时: WebSocket (可中途打断, 双向消息)
    - 协同编辑 / 游戏: WebSocket (必须双向)

  本 demo 演示 WebSocket — 教学价值更高 (SSE Demo 4 已讲)
""")


# =========================================================
# Step 2: FastAPI WebSocket endpoint 基础
# =========================================================
async def demo_websocket_basics() -> None:
    step(2, "FastAPI WebSocket endpoint — 骨架")

    print("""
# 基本骨架:
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_text()
            await ws.send_text(f"echo: {msg}")
    except WebSocketDisconnect:
        # 客户端断开 — 走 cleanup
        pass

# 启动:
#   uvicorn 05_websocket:app --port 8000
#
# 客户端 (浏览器):
#   const ws = new WebSocket('ws://localhost:8000/ws');
#   ws.onmessage = (e) => console.log(e.data);
#   ws.send('hello');
""")


# =========================================================
# Step 3: agent 流式回复 — WS
# =========================================================
async def demo_agent_ws() -> None:
    step(3, "agent aastream → WebSocket — 多轮对话")

    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from langchain_core.messages import HumanMessage

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    app = FastAPI()

    @app.websocket("/ws/chat")
    async def chat_ws(ws: WebSocket):
        await ws.accept()
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        try:
            while True:
                # 1. 收客户端 query
                user_msg = await ws.receive_text()
                print(f"  [WS] 收到: {user_msg[:60]}")

                # 2. agent 流式回复, 每个 token 推回客户端
                async for ev in agent.astream_events(
                    {"messages": [HumanMessage(user_msg)]},
                    config=config,
                    version="v2",
                ):
                    if ev.get("event") == "on_chat_model_stream":
                        chunk = ev.get("data", {}).get("chunk")
                        if chunk:
                            content = getattr(chunk, "content", "")
                            # M3 吐 <think>...</think> 过滤
                            if content and "<think>" not in content:
                                continue
                            if content:
                                await ws.send_json({
                                    "type": "token",
                                    "data": content,
                                })

                # 3. 标结束
                await ws.send_json({"type": "done"})

        except WebSocketDisconnect:
            print(f"  [WS] 客户端断开 (thread={thread_id[:8]})")
            # cleanup: 不需要主动关 checkpointer (InMemorySaver 自动)
        except Exception as e:
            print(f"  [WS] 异常: {type(e).__name__}: {e}")

    print("  ✓ FastAPI app 已构造 (含 /ws/chat WebSocket endpoint)")

    # 💡 实战要点:
    #    - 每个连接一个 thread_id (持久化对话)
    #    - agent.aastream_events + on_chat_model_stream → token 流
    #    - 客户端断线: framework 关 generator, 会触发 GeneratorExit
    #    - 长连接需 keepalive (ping/pong 或 idle timeout)


# =========================================================
# Step 4: 测试 — websockets 客户端
# =========================================================
async def demo_test_websocket() -> None:
    step(4, "测试 WebSocket — 客户端发 query 收流")

    # 真起 server + 客户端连 → 太重, 教学 demo 不真起
    # 改用: 直接 agent.aiterate 模拟 WebSocket 行为
    print(">>> 模拟 WS 行为: client 发 query → server 流式推 token\n")

    from langchain_core.messages import HumanMessage

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    # 模拟: 客户端发 2 个 message
    conversation = ["你好", "今天北京天气怎么样?"]

    try:
        config = {"configurable": {"thread_id": "demo-ws-1"}}

        for i, user_msg in enumerate(conversation, 1):
            print(f"  [client #{i}] 发送: {user_msg}")

            tokens: list[str] = []
            async for ev in agent.astream_events(
                {"messages": [HumanMessage(user_msg)]},
                config=config,
                version="v2",
            ):
                if ev.get("event") == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", "")
                        if content:
                            tokens.append(content)

            full = "".join(tokens)
            print(f"  [server] 推送 {len(tokens)} token: {full[:80]}")
            print(f"  [server] send done\n")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 测试 WebSocket 客户端 (另开 terminal):
    #    import websockets, asyncio
    #    async def client():
    #        async with websockets.connect("ws://localhost:8000/ws/chat") as ws:
    #            await ws.send("hi")
    #            while True:
    #                msg = await ws.recv()
    #                print(msg)
    #    asyncio.run(client())


# =========================================================
# Step 5: 中途打断 — cancel task
# =========================================================
async def demo_cancel() -> None:
    step(5, "中途打断 — asyncio.Task cancel")

    from langchain_core.messages import HumanMessage

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    async def slow_query(query: str):
        """模拟一个长任务."""
        async for ev in agent.astream_events(
            {"messages": [HumanMessage(query)]},
            version="v2",
        ):
            if ev.get("event") == "on_chat_model_stream":
                chunk = ev.get("data", {}).get("chunk")
                if chunk:
                    yield getattr(chunk, "content", "")

    print(">>> 启动 task → 200ms 后 cancel:")

    task = asyncio.create_task(slow_query("详细介绍 RAG 的全 5 个步骤").__aiter__())
    collected: list[str] = []

    async def collector():
        async for chunk in task:
            collected.append(chunk)

    try:
        # 让 task 跑一会, 然后 cancel
        consumer = asyncio.create_task(collector())
        await asyncio.sleep(0.2)  # 给 200ms 收集
        consumer.cancel()  # 中途打断
        try:
            await consumer
        except asyncio.CancelledError:
            pass

        print(f"  收集到 {len(collected)} token, 然后打断")
        print(f"  片段: {''.join(collected)[:80]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {e}")

    # 清理 task
    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass

    # 💡 实战打断:
    #    - 用户点 "停止" → server cancel 当前 task
    #    - asyncio.Task.cancel() 触发 CancelledError, generator 退出
    #    - 部分 token 已发出, 客户端拼接仍有效
    #    - 生产: 加 "stop_reason: user_canceled" 元数据, 客户端显示


# =========================================================
# entry point
# =========================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    run_async(demo_ws_vs_sse())
    run_async(demo_websocket_basics())
    run_async(demo_agent_ws())

    if has_key:
        run_async(demo_test_websocket())
        run_async(demo_cancel())
        print("\n[OK] 05_websocket.py 全部 demo 跑完。")
    else:
        print("\n[OK] 05_websocket.py — Step 4/5 跳过 (需 API key)。")
        print("[i]   真起 server: uvicorn 05_websocket:app --port 8000")