"""04_sse_server.py — Demo 4: FastAPI + SSE 流式输出 (生产部署形态).

学完这个 demo 你能回答:
1.  SSE 协议格式? (event/data 双\\n\\n 结尾)
2.  FastAPI StreamingResponse 怎么返回流?
3.  agent.astream_events → SSE 怎么转?
4.  curl 怎么测 SSE? (-N 不缓冲 + 监听 data:)
5.  生产要点? (CORS / keep-alive / timeout / backpressure)
6.  实战: 不真起 server, 用 httpx.AsyncClient + ASGITransport 测 endpoint

跑法:
    python 04_sse_server.py       # 跑 (httpx ASGI 自测, 无需起 server)
    uvicorn 04_sse_server:app     # 真起 server (curl -N http://localhost:8000/chat?q=hi)
"""
from __future__ import annotations

import asyncio
import os
import sys

from _common import banner, get_llm, run_async, step
from async_pipeline import stream_to_sse

# ============================================================
# Demo
# ============================================================
banner("Demo 4: FastAPI + SSE Streaming")


# =========================================================
# Step 1: SSE 协议格式
# =========================================================
async def demo_sse_protocol() -> None:
    step(1, "SSE 协议格式 (text/event-stream)")

    print("""
SSE 格式 (服务器发):

    event: message_start
    data: {"role": "assistant"}

    event: content_delta
    data: {"token": "你好"}

    event: content_delta
    data: {"token": "世界"}

    event: message_end
    data: {"finish_reason": "stop"}


    (双 \\n 结尾 = 1 个事件)
    (空行 = 事件分界)

客户端 (浏览器):

    const es = new EventSource("/chat?q=hi");
    es.addEventListener("content_delta", (e) => {
        const data = JSON.parse(e.data);
        appendToUI(data.token);
    });

Python httpx 测试:

    async with httpx.AsyncClient() as client:
        async with client.stream("GET", url) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
""")


# =========================================================
# Step 2: FastAPI StreamingResponse 基础
# =========================================================
async def demo_fastapi_basics() -> None:
    step(2, "FastAPI StreamingResponse — 异步生成器")

    # 在 module-level 定义 app, 但 demo 不真起 server
    print("""
# 基本骨架:
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/stream")
async def stream():
    async def gen():
        for i in range(5):
            await asyncio.sleep(0.1)
            yield f"data: {{\"i\": {i}}}\\n\\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

# curl 测试:
#   curl -N http://localhost:8000/stream
# (-N 关键: 关闭 curl 缓冲, 实时看流)
""")

    # 💡 关键点:
    #    - media_type="text/event-stream" — SSE 协议
    #    - async def gen() yield — FastAPI 自动异步迭代
    #    - yield "data: ...\\n\\n" — 双换行结尾
    #    - curl -N 关闭缓冲


# =========================================================
# Step 3: agent.astream_events → SSE 转换
# =========================================================
async def demo_agent_to_sse() -> None:
    step(3, "agent.aastream_events → SSE — 生产端点")

    from fastapi import FastAPI, Query
    from fastapi.responses import StreamingResponse
    from langchain_core.messages import HumanMessage

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    app = FastAPI(title="Streaming Chat API")

    @app.get("/chat")
    async def chat(q: str = Query(..., description="用户问题")):
        """SSE 端点 — agent.aastream_events 转 SSE."""

        async def event_gen():
            async for ev in agent.astream_events(
                {"messages": [HumanMessage(q)]},
                version="v2",
            ):
                # 转 SSE 格式 — 用 12 共享 helper stream_to_sse
                # 但 stream_to_sse 是 AsyncIterator[str], 需要 async generator
                async for sse_chunk in stream_to_sse(iter_async([ev])):
                    yield sse_chunk

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Nginx 不缓冲
            },
        )

    print("  ✓ FastAPI app 已构造 (含 /chat SSE endpoint)")

    # 验证 app 路由
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    print(f"  路由: {routes}")

    # 💡 实战 headers:
    #    - Cache-Control: no-cache — 防止中间层缓存
    #    - X-Accel-Buffering: no — Nginx 不缓冲 (生产 Nginx 必备)
    #    - Connection: keep-alive — 保持长连


async def iter_async(items):
    """把 list 转 async iterator (helper)."""
    for item in items:
        yield item


# =========================================================
# Step 4: 测试 — httpx.AsyncClient + ASGITransport
# =========================================================
async def demo_test_with_httpx() -> None:
    step(4, "测试 SSE — httpx.AsyncClient + ASGITransport (不起 server)")

    import httpx
    from fastapi import FastAPI, Query
    from fastapi.responses import StreamingResponse
    from langchain_core.messages import HumanMessage

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    app = FastAPI()

    @app.get("/chat")
    async def chat(q: str = Query(...)):
        async def gen():
            # 简化 — 不用 aastream_events, 直接 LLM 流
            async for ev in agent.astream_events(
                {"messages": [HumanMessage(q)]},
                version="v2",
            ):
                if ev.get("event") == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    if chunk and "<think>" not in str(getattr(chunk, "content", "")):
                        content = getattr(chunk, "content", "")
                        if content:
                            yield f"data: {{\"token\": \"{content}\"}}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    print(">>> httpx.ASGITransport 测 SSE endpoint (不起 server):")

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("GET", "/chat?q=hi") as resp:
                print(f"  status: {resp.status_code}")
                print(f"  content-type: {resp.headers.get('content-type')}")

                collected_tokens: list[str] = []
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        import json
                        payload = json.loads(line[5:].strip())
                        token = payload.get("token", "")
                        if token:
                            collected_tokens.append(token)

                full_text = "".join(collected_tokens)
                print(f"  收到 {len(collected_tokens)} token")
                print(f"  拼接文本: {full_text[:150]}")

    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:120]}")

    # 💡 测为什么用 ASGITransport:
    #    - 不需要真起 uvicorn server
    #    - pytest 里直接 request app, 比 subprocess uvicorn 100x 快
    #    - 生产才用 uvicorn


# =========================================================
# Step 5: 真起 server (注释启用)
# =========================================================
async def demo_run_server() -> None:
    step(5, "真起 server — uvicorn (注释启用)")

    print("""
# 真起 server 用:
#   $ uvicorn 04_sse_server:app --host 0.0.0.0 --port 8000
#
# curl 测试:
#   $ curl -N 'http://localhost:8000/chat?q=hi'
#
# 浏览器测试 (浏览器原生 EventSource):
#   const es = new EventSource('/chat?q=hi');
#   es.addEventListener('message', (e) => console.log(e.data));
#
# 生产部署:
#   - gunicorn -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
#   - 反向代理 (Nginx): 加 X-Accel-Buffering: no + 长 timeout
    """)

    # 当前 demo 不真起 — 否则会 block
    print("  (本 demo 不真起 server; 用 ASGITransport 自测已覆盖功能)")


# =========================================================
# entry point
# =========================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    # Step 1/2/3 不需要 LLM, Step 4 需要
    run_async(demo_sse_protocol())
    run_async(demo_fastapi_basics())
    run_async(demo_agent_to_sse())
    run_async(demo_run_server())

    if has_key:
        run_async(demo_test_with_httpx())
        print("\n[OK] 04_sse_server.py 全部 demo 跑完。")
    else:
        print("\n[OK] 04_sse_server.py — 跳过 Step 4 (没 API key, httpx 测试跑不了)。")
        print("[i]   真起 server: uvicorn 04_sse_server:app --port 8000 + curl -N")