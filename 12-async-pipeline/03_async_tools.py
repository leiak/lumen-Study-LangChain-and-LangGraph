"""03_async_tools.py — Demo 3: Async 工具 (async @tool + 异步 IO).

学完这个 demo 你能回答:
1.  async def + @tool 跟 sync def + @tool 区别? (多了 .ainvoke 方法)
2.  异步工具内调 httpx.AsyncClient / asyncpg mock 怎么写?
3.  一个工具并发调多个 IO (gather) 实战?
4.  sync 工具内调 async 工具会怎样? (返回 coroutine, 不 await = 错)
5.  async tool 在 sync agent 里能跑吗? (能, 但失去异步优势)
6.  asyncio.Semaphore 在工具内做并发限流?

跑法:
    python 03_async_tools.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from _common import banner, get_llm, run_async, step
from async_pipeline import AsyncRateLimiter, gather_safe, measure_latency

# ============================================================
# Demo
# ============================================================
banner("Demo 3: Async Tools (ainvoke / async def / gather)")


# =========================================================
# Step 1: async @tool vs sync @tool
# =========================================================
async def demo_async_tool_basic() -> None:
    step(1, "async @tool — 比 sync 多了 .ainvoke")

    @tool
    async def fetch_url(url: str) -> str:
        """异步获取 URL 内容 (mock).

        Args:
            url: 目标 URL

        Returns:
            URL 内容 (mock)
        """
        await asyncio.sleep(0.1)  # 模拟网络 IO
        return f"<html>{url} 内容</html>"

    # async @tool 自动有 .invoke 和 .ainvoke
    print(f"  工具名: {fetch_url.name}")
    print(f"  有 invoke: {hasattr(fetch_url, 'invoke')}")
    print(f"  有 ainvoke: {hasattr(fetch_url, 'ainvoke')}")

    # .ainvoke — 真异步 (event loop 不阻塞)
    async with measure_latency() as t:
        r = await fetch_url.ainvoke({"url": "https://a.com"})
    print(f"  ainvoke: {r} (耗时 {t.elapsed_ms:.0f}ms)")

    # .invoke — 同步 (event loop 阻塞)
    async with measure_latency() as t:
        r = fetch_url.invoke({"url": "https://b.com"})
    print(f"  invoke:  {r} (耗时 {t.elapsed_ms:.0f}ms)")

    # 💡 ainvoke 是真异步 — 多个并发时不阻塞 event loop
    #    invoke 在 event loop 里跑会阻塞 — 别在 async 上下文用


# =========================================================
# Step 2: async HTTP — httpx.AsyncClient mock
# =========================================================
async def demo_async_http() -> None:
    step(2, "async HTTP — httpx.AsyncClient (实战 API 调用)")

    import httpx

    @tool
    async def fetch_json(url: str) -> dict:
        """异步 HTTP GET, 返回 JSON.

        实战:
            - 用 httpx.AsyncClient (vs requests — 异步友好)
            - aiohttp 也可以, 但 httpx 接口更现代
            - 实战记得 timeout=10 / HTTPStatusError 处理
        """
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return {"status": resp.status_code, "body": resp.json()}
            except httpx.HTTPError as e:
                return {"status": -1, "error": str(e)[:100]}

    # 测试一个真实 endpoint (httpbin.org 提供 JSON echo)
    # 用 httpbin / jsonplaceholder 都行 — 教学 demo
    print(">>> 调用 https://httpbin.org/json (mock 响应):")
    try:
        result = await fetch_json.ainvoke({"url": "https://httpbin.org/json"})
        print(f"  状态: {result.get('status', '?')}")
        print(f"  键: {list(result.get('body', {}).keys()) if isinstance(result.get('body'), dict) else 'n/a'}")
    except Exception as e:
        print(f"  [跳过] 网络不可达: {type(e).__name__}")

    # 💡 httpx.AsyncClient 实战要点:
        # - timeout=5.0 — 防止 hang
        # - async with — 自动 close 连接池
        # - raise_for_status() — 4xx/5xx 抛错
        # - production 加 retry (httpx 1.x 自带 transport=httpx.AsyncHTTPTransport(retries=3))


# =========================================================
# Step 3: 工具内并发 — gather N 个 IO
# =========================================================
async def demo_tool_concurrent_fetch() -> None:
    step(3, "工具内并发 — 一个 tool 内部 gather 多个 URL")

    import httpx

    @tool
    async def fetch_many(urls: list[str]) -> dict:
        """并发获取多个 URL, 汇总结果.

        Args:
            urls: URL 列表

        Returns:
            {url: {status, body_length} or {error}} map
        """
        async with httpx.AsyncClient(timeout=5.0) as client:
            async def one(url: str) -> tuple[str, dict]:
                try:
                    resp = await client.get(url)
                    return (url, {"status": resp.status_code, "len": len(resp.text)})
                except Exception as e:
                    return (url, {"error": str(e)[:50]})

            # 关键 — 工具内部自己并发
            results = await asyncio.gather(*(one(u) for u in urls))
            return dict(results)

    print(">>> 工具内并发 fetch 3 URL:")
    try:
        urls = [
            "https://httpbin.org/get",
            "https://httpbin.org/uuid",
            "https://httpbin.org/json",
        ]
        async with measure_latency() as t:
            r = await fetch_many.ainvoke({"urls": urls})
        print(f"  耗时 {t.elapsed_ms:.0f}ms (并发 ~ 1 个 RTT)")
        for url, info in r.items():
            print(f"    {url}: {info}")
    except Exception as e:
        print(f"  [跳过] 网络: {type(e).__name__}")

    # 💡 实战场景:
    #    - "research" 工具: 搜 3 个 source API 并发, 1 次 RTT 出全部
    #    - "data enrichment": 查 user 在 DB / cache / external API 并发
    #    - 节省: 串行 3 RTT → 并发 1 RTT


# =========================================================
# Step 4: 限流 inside tool — Semaphore
# =========================================================
async def demo_tool_rate_limit() -> None:
    step(4, "工具内 Semaphore — 防并发打爆")

    import httpx

    @tool
    async def fetch_with_limit(urls: list[str], max_concurrent: int = 2) -> dict:
        """并发 fetch URL, 上限 max_concurrent 个.

        实战:
            - 外部 API 有 rate limit (e.g. 10 req/s)
            - 用 Semaphore 控制并发, 不会超限
            - 实战可以配合 rate limiter (Redis)
        """
        sem = asyncio.Semaphore(max_concurrent)

        async with httpx.AsyncClient(timeout=5.0) as client:
            async def one(url: str) -> tuple[str, dict]:
                async with sem:  # acquire / release 自动
                    try:
                        resp = await client.get(url)
                        return (url, {"status": resp.status_code, "len": len(resp.text)})
                    except Exception as e:
                        return (url, {"error": str(e)[:50]})

            results = await asyncio.gather(*(one(u) for u in urls))
            return dict(results)

    print(">>> 5 个 URL, 上限 2 并发:")
    try:
        urls = [f"https://httpbin.org/get?n={i}" for i in range(5)]
        async with measure_latency() as t:
            r = await fetch_with_limit.ainvoke({"urls": urls, "max_concurrent": 2})
        print(f"  耗时 {t.elapsed_ms:.0f}ms (限流 → 多 1 RTT)")
        success = sum(1 for v in r.values() if "status" in v)
        print(f"  成功 {success}/{len(urls)}")
    except Exception as e:
        print(f"  [跳过] 网络: {type(e).__name__}")

    # 💡 Semaphore vs rate limiter:
    #    - Semaphore: 并发上限 (同时间), 适合 IO bound
    #    - Rate limiter: 时间窗口次数 (e.g. 10/s), 适合 API 限速
    #    - 实战: Semaphore 限并发 + 时间窗口 check = 双重防护


# =========================================================
# Step 5: AsyncRateLimiter 装饰器模式
# =========================================================
async def demo_async_rate_limiter_decorator() -> None:
    step(5, "AsyncRateLimiter — 装饰器模式 (全局并发上限)")

    limiter = AsyncRateLimiter(max_concurrent=3)

    @limiter
    async def work(i: int) -> str:
        await asyncio.sleep(0.05)
        return f"work {i} done"

    print(f">>> 装饰器模式, max_concurrent={limiter.max_concurrent}")
    print(">>> 并发跑 10 个 task:")

    t0 = asyncio.get_event_loop().time()
    results = await gather_safe(*(work(i) for i in range(10)))
    elapsed = asyncio.get_event_loop().time() - t0

    success = sum(1 for r in results if not isinstance(r, BaseException))
    print(f"  耗时 {elapsed:.2f}s, 成功 {success}/10")
    print(f"  (10 task 限 3 并发 = 4 批 × 0.05s ≈ 0.2s)")

    # 💡 AsyncRateLimiter 装饰器实战:
    #    - 全局并发上限 (e.g. 整个 process 最多 3 个 LLM 调用)
    #    - 防止误用导致打爆 provider rate limit
    #    - 实战可加 metric (拒绝率 / 等待时长)


# =========================================================
# Step 6: mix sync + async — 实战陷阱
# =========================================================
async def demo_mix_sync_async() -> None:
    step(6, "sync @tool 在 async 上下文里 — 陷阱")

    @tool
    def sync_tool(x: int) -> str:
        """同步工具 — 会阻塞 event loop."""
        import time as _t
        _t.sleep(0.05)  # 同步 sleep 阻塞 event loop
        return f"sync {x}"

    @tool
    async def async_tool(x: int) -> str:
        """异步工具 — 不阻塞."""
        await asyncio.sleep(0.05)
        return f"async {x}"

    print(">>> sync 串行 5 次 (阻塞 event loop):")
    t0 = asyncio.get_event_loop().time()
    sync_results = []
    for i in range(5):
        sync_results.append(sync_tool.invoke({"x": i}))
    sync_elapsed = asyncio.get_event_loop().time() - t0
    print(f"  耗时 {sync_elapsed:.2f}s, results: {sync_results}")

    print("\n>>> async 并发 5 次 (不阻塞):")
    t0 = asyncio.get_event_loop().time()
    async_results = await gather_safe(*(async_tool.ainvoke({"x": i}) for i in range(5)))
    async_elapsed = asyncio.get_event_loop().time() - t0
    print(f"  耗时 {async_elapsed:.2f}s, results: {async_results}")

    speedup = sync_elapsed / max(async_elapsed, 0.001)
    print(f"\n  加速比: {speedup:.2f}x (async 优势在并发)")

    # 💡 实战陷阱:
    #    - sync @tool 在 async 上下文里会阻塞 event loop
    #    - 大量 sync 工具调用 + 并发需求 → 改 async 版本
    #    - LLM 客户端是 sync 的: 包 asyncio.to_thread(sync_llm.invoke, prompt)
    #      这样调用方是异步, 不阻塞 event loop


# =========================================================
# entry point
# =========================================================
if __name__ == "__main__":
    # 全部 demo 不需要 LLM (纯工具行为) — 都可以跑
    demos = [
        demo_async_tool_basic,
        demo_async_http,
        demo_tool_concurrent_fetch,
        demo_tool_rate_limit,
        demo_async_rate_limiter_decorator,
        demo_mix_sync_async,
    ]

    for fn in demos:
        try:
            run_async(fn())
        except Exception as e:
            print(f"[{fn.__name__}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 03_async_tools.py 全部 demo 跑完。")
    print("[i]   网络 demo (Step 2/3/4) 取决于 httpbin.org 可达性, 失败属正常.")