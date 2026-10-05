"""06_production_async.py — Demo 6: Async Middleware + Production 模式.

学完这个 demo 你能回答:
1.  @wrap_tool_call async 版本怎么写? (handler 是 awaitable)
2.  async middleware vs sync middleware 区别? (异步日志 / 异步限流 / 异步 metrics)
3.  background_task fire-and-forget 怎么用? (metrics 上报 / audit log)
4.  并发限流 (Semaphore) 怎么嵌 middleware? (防打爆下游 API)
5.  async with measure_latency() 怎么用? (上报 P50/P95)
6.  生产 LLM 服务怎么做? (async 全链路 + 后台 metrics)

跑法:
    python 06_production_async.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from _common import banner, get_llm, run_async, step
from async_pipeline import (
    AsyncRateLimiter,
    background_task,
    gather_safe,
    measure_latency,
)

# ============================================================
# Demo
# ============================================================
banner("Demo 6: Async Middleware + Production 模式")


# =========================================================
# Step 1: async @wrap_tool_call — 异步日志
# =========================================================
async def demo_async_tool_middleware() -> None:
    step(1, "async @wrap_tool_call — 异步日志 (上报 metrics)")

    from langchain.agents import create_agent
    from langchain.agents.middleware import wrap_tool_call

    @tool
    async def fetch(url: str) -> str:
        """模拟 fetch."""
        await asyncio.sleep(0.05)
        return f"content from {url}"

    # async @wrap_tool_call — handler 返回 awaitable
    @wrap_tool_call
    async def async_log_mw(request, handler):
        tool_name = request.tool_call["name"]
        t0 = time.perf_counter()
        # handler 是 awaitable — 必须 await
        result = await handler(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # 后台上报 metrics — 不阻塞主流程
        async def report():
            await asyncio.sleep(0.01)  # 模拟 IO
            print(f"  [METRIC] {tool_name} latency={elapsed_ms:.1f}ms")

        background_task(report(), name=f"metric-{tool_name}")

        return result

    agent = create_agent(
        model=get_llm(),
        tools=[fetch],
        middleware=[async_log_mw],
    )

    print(">>> invoke 触发 fetch + 异步日志:")
    try:
        r = await agent.ainvoke({"messages": [HumanMessage("帮我 fetch https://example.com")]})
        last = r["messages"][-1]
        print(f"  最终回复: {getattr(last, 'content', '')[:80]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 给 background_task 一点时间
    await asyncio.sleep(0.1)

    # 💡 async vs sync middleware:
    #    sync: handler() 同步调用 → 阻塞 event loop
    #    async: await handler() → 不阻塞, 可做 IO (写 DB / 发 metric)
    #    12 async 优势: middleware 内部能 gather / Semaphore / IO


# =========================================================
# Step 2: async @wrap_model_call — 改 message
# =========================================================
async def demo_async_model_middleware() -> None:
    step(2, "async @wrap_model_call — 注入 system prompt")

    from langchain.agents import create_agent
    from langchain.agents.middleware import wrap_model_call
    from langchain_core.messages import SystemMessage

    # 异步拦截 model call — 注入 system message
    @wrap_model_call
    async def inject_system_mw(request, handler):
        # request.state["messages"] — 当前 messages
        msgs = request.state.get("messages", [])
        # 在最前面插 system message
        new_msgs = [SystemMessage(content="你只用 emoji 回答, 不超过 3 个")] + list(msgs)
        # 替换 state (LangGraph 用 dataclass replace 模式)
        request.state["messages"] = new_msgs

        # 调真 model
        return await handler(request)

    agent = create_agent(
        model=get_llm(),
        tools=[],
        middleware=[inject_system_mw],
    )

    print(">>> middleware 注入 'emoji 回答' system prompt:")
    try:
        r = await agent.ainvoke({"messages": [HumanMessage("你好, 介绍一下 RAG")]})
        last = r["messages"][-1]
        content = getattr(last, "content", "")
        print(f"  最终回复: {content[:100]}")
        # 期望: emoji 回答
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 async wrap_model_call 实战:
    #    - 动态 system prompt (按 user 时间 / 偏好)
    #    - 加 guardrails (敏感词拦截)
    #    - 异步加载 prompt template (不阻塞)


# =========================================================
# Step 3: background_task fire-and-forget — 生产审计
# =========================================================
async def demo_background_task() -> None:
    step(3, "background_task — fire-and-forget 审计日志")

    # 模拟 audit log 队列
    audit_log: list[str] = []

    async def write_audit(msg: str) -> None:
        # 模拟 IO — 写 DB
        await asyncio.sleep(0.02)
        audit_log.append(f"{time.time():.2f} - {msg}")

    # 业务流程 — 不能被 audit 阻塞
    async def business_logic(item: str) -> str:
        # 业务跑得很快
        await asyncio.sleep(0.01)

        # 后台写 audit — 不 await
        background_task(write_audit(f"processed {item}"), name=f"audit-{item}")

        return f"done: {item}"

    print(">>> 跑 3 个业务 task + 后台 audit:")
    t0 = time.perf_counter()
    results = await gather_safe(*(business_logic(f"item-{i}") for i in range(3)))
    elapsed = time.perf_counter() - t0

    print(f"  业务耗时: {elapsed*1000:.0f}ms (audit 在后台)")
    print(f"  业务结果: {results}")

    # 等 audit 跑完
    await asyncio.sleep(0.2)
    print(f"  audit log ({len(audit_log)} 条):")
    for entry in audit_log:
        print(f"    {entry}")

    # 💡 background_task 实战:
    #    - audit log 不阻塞主流程
    #    - metrics 上报 (Prometheus pushgateway)
    #    - webhook 通知 (失败重试在后台)
    #    - 陷阱: 主进程退出前应 gather 所有 background task, 否则丢


# =========================================================
# Step 4: Semaphore 限流 in middleware
# =========================================================
async def demo_semaphore_in_middleware() -> None:
    step(4, "Semaphore in middleware — 防打爆下游 API")

    from langchain.agents import create_agent
    from langchain.agents.middleware import wrap_tool_call

    sem = asyncio.Semaphore(2)  # 最多 2 并发

    @tool
    async def slow_api(x: int) -> str:
        """模拟慢 API."""
        await asyncio.sleep(0.1)
        return f"slow result {x}"

    @wrap_tool_call
    async def rate_limit_mw(request, handler):
        # 拿不到 semaphore → 等 (不报错)
        async with sem:
            return await handler(request)

    agent = create_agent(
        model=get_llm(),
        tools=[slow_api],
        middleware=[rate_limit_mw],
    )

    print(">>> 5 个 tool call 并发, 上限 2:")
    # 直接并发调 — 模拟前端 5 个并发动作
    t0 = time.perf_counter()

    async def one_call(i: int) -> str:
        r = await agent.ainvoke({"messages": [HumanMessage(f"调用 slow_api x={i}")]})
        return getattr(r["messages"][-1], "content", "")[:30]

    results = await gather_safe(*(one_call(i) for i in range(5)))
    elapsed = time.perf_counter() - t0

    success = sum(1 for r in results if not isinstance(r, BaseException))
    print(f"  耗时 {elapsed:.2f}s, 成功 {success}/5")
    print(f"  (5 个并发, 限 2 → 3 批 ≈ 0.3s; 不限 ≈ 0.1s 并发全部)")

    # 💡 Semaphore in middleware 实战:
    #    - 全局并发上限 (e.g. 整个 process 5 个 LLM 调用)
    #    - 防 provider rate limit (Anthropic tier 1: 5 concurrent)
    #    - 跟 rate_limit_middleware (11 同步) 区别: 异步不阻塞 event loop


# =========================================================
# Step 5: measure_latency + metrics
# =========================================================
async def demo_metrics_pipeline() -> None:
    step(5, "measure_latency — 完整 metrics 管线")

    # 模拟 metrics 存储
    metrics = {
        "llm_calls": 0,
        "total_ms": 0.0,
        "latencies": [],
    }

    from langchain.agents import create_agent
    from langchain.agents.middleware import wrap_model_call

    agent = create_agent(
        model=get_llm(),
        tools=[],
        middleware=[
            # 测 model call 耗时
            # 实战: 用 @wrap_model_call 装饰器
        ],
    )

    queries = ["hi", "what is RAG?", "explain BM25 briefly"]

    print(">>> 跑 3 query + 测每次 latency:")

    for i, q in enumerate(queries, 1):
        async with measure_latency() as t:
            try:
                await agent.ainvoke({"messages": [HumanMessage(q)]})
            except Exception as e:
                print(f"  [{i}] 失败: {type(e).__name__}")
                continue

        metrics["llm_calls"] += 1
        metrics["total_ms"] += t.elapsed_ms
        metrics["latencies"].append(t.elapsed_ms)
        print(f"  [{i}] '{q[:30]}' 耗时 {t.elapsed_ms:.0f}ms")

    if metrics["latencies"]:
        sorted_lat = sorted(metrics["latencies"])
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if len(sorted_lat) >= 5 else sorted_lat[-1]
        print(f"\n  P50: {p50:.0f}ms")
        print(f"  P95: {p95:.0f}ms")
        print(f"  avg: {metrics['total_ms'] / metrics['llm_calls']:.0f}ms")

    # 💡 measure_latency 实战:
    #    - 包每次 ainvoke → 上报 histogram
    #    - 上报 prometheus: histogram.observe(elapsed_ms)
    #    - 告警: P95 > 5s 触发
    #    - 实战换 streaming percentile estimator (t-digest / HDR) — 见 10-rag-deep-dive


# =========================================================
# Step 6: 全链路 async — end-to-end 总结
# =========================================================
async def demo_full_pipeline() -> None:
    step(6, "End-to-end 总结 — 全链路 async pipeline")

    print("""
  生产 LLM 服务架构 (12 async 全链路):

  Client (浏览器)
     │  WebSocket
     ▼
  FastAPI app + uvicorn
     │  async endpoint
     ▼
  agent.aastream_events(v="v2")
     │  on_chat_model_stream events
     ▼
  async middleware chain (12):
     - async_log_mw (background_task 上报 metrics)
     - async_semaphore_mw (全局 ≤5 并发)
     - async_inject_mw (动态 system prompt)
     ▼
  async tools (06 demo):
     - httpx async fetch (并发 N URL)
     - asyncpg async DB
     - gather 内并发
     ▼
  Provider (OpenAI / Anthropic / MCP)
     │  HTTP / SSE
     ▼
  metrics (Prometheus / OpenTelemetry)
     │
     ▼
  Grafana / Datadog (告警 + 看板)
""")

    # 简单演示完整链路 + 测耗时
    print(">>> 实测全链路 latency (1 query):")

    from langchain.agents import create_agent

    agent = create_agent(model=get_llm(), tools=[])

    async with measure_latency() as t:
        try:
            await agent.ainvoke({"messages": [HumanMessage("用 1 句话介绍 MCP 协议")]})
            print(f"  端到端耗时: {t.elapsed_ms:.0f}ms")
        except Exception as e:
            print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")


# =========================================================
# entry point
# =========================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    # Step 3 不需要 LLM, 其它需要
    run_async(demo_background_task())

    if not has_key:
        print("\n[!] 没 API key — 其它 demo 跳过")
        print("\n[OK] 06_production_async.py — 仅 Step 3 跑通。")
        sys.exit(0)

    demos = [
        demo_async_tool_middleware,
        demo_async_model_middleware,
        demo_semaphore_in_middleware,
        demo_metrics_pipeline,
        demo_full_pipeline,
    ]

    for fn in demos:
        try:
            run_async(fn())
        except Exception as e:
            print(f"[{fn.__name__}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 06_production_async.py 全部 demo 跑完。")
    print("[i]   12 async 全链路 = production LLM 服务基础架构.")