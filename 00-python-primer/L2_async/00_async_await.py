"""
00_async_await.py
==================
学完你能回答:
1. async def 和 def 区别?
2. 直接调 async def 会执行吗?
3. await 后面能接什么?
4. asyncio.sleep(0) 和 time.sleep(0) 区别?
5. async 函数里能调同步函数吗?
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


async def fetch(url: str, delay: float = 0.1) -> str:
    """模拟 IO 协程"""
    await asyncio.sleep(delay)                       # 不阻塞事件循环
    return f"<html>{url}</html>"


async def demo_basic_async() -> None:
    banner("1. async def + await 基础")

    # 直接调 fetch() 返回 coroutine 对象, 不执行
    coro = fetch("https://a.com")
    print(f"  type(coro) = {type(coro).__name__}")     # coroutine

    # await 触发执行
    html = await fetch("https://a.com")
    print(f"  await 结果: {html}")


async def demo_sleep_vs_time_sleep() -> None:
    banner("2. asyncio.sleep vs time.sleep (并发关键)")

    # 用 asyncio.sleep: 让出控制权, 协程可切换
    t0 = time.perf_counter()
    await asyncio.gather(fetch("a"), fetch("b"), fetch("c"))
    async_time = time.perf_counter() - t0

    # 用 time.sleep: 阻塞整个事件循环
    def blocking_fetch(url):
        time.sleep(0.1)
        return f"<html>{url}</html>"

    t0 = time.perf_counter()
    blocking_fetch("a"); blocking_fetch("b"); blocking_fetch("c")
    sync_time = time.perf_counter() - t0

    print(f"  asyncio.sleep 总耗时: {async_time*1000:.1f}ms")
    print(f"  time.sleep 总耗时:   {sync_time*1000:.1f}ms")
    print(f"  性能差: {sync_time / async_time:.1f}x")


async def demo_sync_inside_async() -> None:
    banner("3. async 里调同步函数 (会阻塞)")

    def slow_sync():
        time.sleep(0.2)                              # 阻塞整个事件循环
        return "done"

    t0 = time.perf_counter()
    a = await fetch("a")
    s = slow_sync()                                   # 阻塞
    b = await fetch("b")
    print(f"  串行 + 同步阻塞: {(time.perf_counter()-t0)*1000:.1f}ms")
    # 应该是 ~0.3s (fetch a + slow_sync + fetch b)

    print("  提示: 同步阻塞 IO 放在 async 里会拖垮并发,")
    print("        用 asyncio.to_thread 桥接 (见 L2-03)")


async def main() -> None:
    await demo_basic_async()
    await demo_sleep_vs_time_sleep()
    await demo_sync_inside_async()


if __name__ == "__main__":
    setup()
    asyncio.run(main())
    print("\n[L2-00] 全部 demo 跑完。")
