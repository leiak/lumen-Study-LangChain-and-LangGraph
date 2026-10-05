"""async_pipeline.py — 12 共享 async helpers.

实战 async 模式 (4 类):
  - gather_safe: asyncio.gather + return_exceptions (永远加这个)
  - stream_to_sse: astream_events 转 SSE 格式 (生产 FastAPI 用)
  - AsyncRateLimiter: asyncio.Semaphore 并发限流 (async middleware 用)
  - background_task: fire-and-forget 后台任务 (logging / metrics 上报)

💡 设计要点:
  - 不依赖 LangChain (可独立单元测试)
  - 类型注解清晰 (tuple / dict 显式)
  - log 走 print (生产可换 logging)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

T = TypeVar("T")

# 默认 logger — demo 用 print 模拟, 生产可换 logging
_log = logging.getLogger("async_pipeline")


# ============================================================
# 1. gather_safe — 永远加 return_exceptions
# ============================================================
async def gather_safe(
    *coros: Awaitable[T],
    return_exceptions: bool = True,
) -> list[T | BaseException]:
    """asyncio.gather 包装 — 默认 return_exceptions=True.

    为什么永远要 return_exceptions:
      - 默认 gather 一个抛, 其它全 cancelled
      - LLM API 多个并发跑时, 一个 401 不应该拖垮其它
      - 实战几乎所有 gather 都该 True

    Args:
        *coros: 任意 awaitable
        return_exceptions: True 永不 raise, 失败 task 返回 Exception 对象

    Returns:
        list of T or BaseException (按入参顺序对齐)

    实战:
        results = await gather_safe(agent1.ainvoke(...), agent2.ainvoke(...))
        for r in results:
            if isinstance(r, Exception):
                log(r)
            else:
                use(r["messages"][-1])
    """
    return await asyncio.gather(*coros, return_exceptions=return_exceptions)


# ============================================================
# 2. stream_to_sse — astream_events 转 SSE 格式
# ============================================================
async def stream_to_sse(
    events: AsyncIterator[dict[str, Any]],
    *,
    event_field: str = "event",
    data_keys: tuple = ("data",),
) -> AsyncIterator[str]:
    """把 LangGraph astream_events 转 SSE 格式.

    SSE 格式 (HTTP text/event-stream):
        event: <name>
        data: <json>
        \\n

    客户端用 EventSource (browser) / sse-starlette / curl 接收.

    Args:
        events: astream_events 异步迭代器
        event_field: event 字段名 (默认 v1 是 'event', v2 同名)
        data_keys: 转 JSON 的字段名 tuple (默认取 'data' 字段)

    Yields:
        SSE 格式字符串, 每个事件含 event + data + 终止 \\n\\n

    实战:
        @app.get("/chat")
        async def chat(message: str):
            return StreamingResponse(
                stream_to_sse(agent.astream_events(...)),
                media_type="text/event-stream",
            )
    """
    async for ev in events:
        ev_name = ev.get(event_field, "message")
        # 把指定字段拼成 data
        data = {k: ev[k] for k in data_keys if k in ev}
        if not data:
            # 拿不到 fields 时 fallback — 整 event 简化
            data = {"event": ev_name}

        # SSE 协议: event/data 各占一行, 双换行结尾
        yield f"event: {ev_name}\n"
        yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n"
        yield "\n"


# ============================================================
# 3. AsyncRateLimiter — Semaphore 并发限流
# ============================================================
class AsyncRateLimiter:
    """基于 Semaphore 的并发限流器 (async middleware 用).

    区别于 11-tool-fabric 的 rate_limit_middleware:
      - 11 用时间戳 dict (同步)
      - 这个用 Semaphore (并发上限), 适合 async pipeline
      - 实战: Semaphore 防 "并发打爆下游" (DB / API)

    Args:
        max_concurrent: 同时最多跑 N 个 task, 多的等 → 阻塞

    实战:
        limiter = AsyncRateLimiter(max_concurrent=5)

        @limiter.limit
        async def call_llm(prompt):
            return await llm.ainvoke(prompt)

        # 100 个 prompt 同时进 — 一次最多 5 个并发, 其余排队
    """

    def __init__(self, max_concurrent: int = 5) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max = max_concurrent

    @property
    def max_concurrent(self) -> int:
        return self._max

    async def acquire(self) -> None:
        await self._sem.acquire()

    def release(self) -> None:
        self._sem.release()

    def __call__(self, fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """装饰器形式: @limiter 后函数自动走限流.

        实战:
                limiter = AsyncRateLimiter(3)

                @limiter
                async def call_api(x):
                    return await httpx.AsyncClient().get(...)
        """
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            await self._sem.acquire()
            try:
                return await fn(*args, **kwargs)
            finally:
                self._sem.release()

        return wrapper


# ============================================================
# 4. background_task — fire-and-forget 后台任务
# ============================================================
def background_task(
    coro: Awaitable[T],
    *,
    name: str | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> asyncio.Task:
    """起一个 fire-and-forget 后台 task (生产日志/metrics 上报用).

    Args:
        coro: 要后台跑的 awaitable
        name: task 名字 (debug 用)
        on_error: 失败 callback (默认 print)

    Returns:
        asyncio.Task — **不 await**, 调用方继续执行

    实战场景:
            - 上报 latency 到 metrics (不应该阻塞主流程)
            - 写 audit log (失败也不影响业务)
            - 异步发 webhook 通知 (失败重试在后台)

    陷阱:
        - 必须 asyncio.create_task, 不是 asyncio.run
        - 主程序退出前最好 gather 所有 background task 避免丢
        - 失败默认 swallowed — 别让后台任务把进程拖崩
    """
    async def _wrap() -> None:
        try:
            await coro
        except BaseException as e:
            _log.warning("[BG %s] failed: %s: %s", name or "?", type(e).__name__, e)
            if on_error:
                try:
                    on_error(e)
                except Exception:
                    pass

    return asyncio.create_task(_wrap(), name=name)


# ============================================================
# 5. measure_latency — async 上下文管理器
# ============================================================
class measure_latency:
    """async 上下文管理器 — 测 block 耗时.

    实战:
        async with measure_latency() as t:
            result = await llm.ainvoke(prompt)
        print(f"耗时 {t.elapsed_ms:.1f}ms")
    """

    def __init__(self) -> None:
        self.elapsed_ms: float = 0.0
        self._t0: float = 0.0

    async def __aenter__(self) -> "measure_latency":
        self._t0 = time.perf_counter()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self._t0) * 1000


__all__ = [
    "gather_safe",
    "stream_to_sse",
    "AsyncRateLimiter",
    "background_task",
    "measure_latency",
]