"""
03_asyncio_to_thread.py
========================
学完你能回答:
1. asyncio.to_thread 解决什么问题?
2. 同步阻塞 IO 在 async 里怎么不阻塞事件循环?
3. 线程池默认多大?
4. CPU 密集用 to_thread 还是 ProcessPoolExecutor?
5. 项目里 LangChain 同步工具怎么桥到 async?
"""
from __future__ import annotations

import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def blocking_io(name: str, delay: float) -> str:
    """模拟同步阻塞 IO (如 requests.get, 文件读取)"""
    time.sleep(delay)
    return f"{name} done"


async def demo_basic_to_thread() -> None:
    banner("1. 基本 to_thread")

    t0 = time.perf_counter()
    result = await asyncio.to_thread(blocking_io, "fetch-A", 0.2)
    elapsed = time.perf_counter() - t0

    print(f"  结果: {result}")
    print(f"  耗时: {elapsed*1000:.1f}ms")
    print(f"  事件循环在 to_thread 期间没阻塞 (其他协程能跑)")


async def demo_concurrent_to_thread() -> None:
    banner("2. 并发多个 to_thread")

    # 三个阻塞 IO 并发跑, 总耗时应该 ~0.2s, 不是 0.6s
    t0 = time.perf_counter()
    results = await asyncio.gather(
        asyncio.to_thread(blocking_io, "A", 0.2),
        asyncio.to_thread(blocking_io, "B", 0.2),
        asyncio.to_thread(blocking_io, "C", 0.2),
    )
    elapsed = time.perf_counter() - t0
    print(f"  results = {results}")
    print(f"  总耗时: {elapsed*1000:.1f}ms (并发应该 ~200ms)")


async def demo_blocking_without_to_thread() -> None:
    banner("3. 对比: 直接调同步会阻塞整个 loop")

    async def quick_task():
        await asyncio.sleep(0.05)
        return "quick"

    t0 = time.perf_counter()
    # ❌ 反面教材: 在 async 里直接调 time.sleep 会阻塞
    blocking_io("block", 0.2)                          # 阻塞整个 loop
    quick = await quick_task()                          # 只能等上面阻塞完
    elapsed = time.perf_counter() - t0
    print(f"  反例耗时: {elapsed*1000:.1f}ms (阻塞了 quick_task)")


async def demo_langchain_tool_pattern() -> None:
    banner("4. LangChain 同步工具桥接 (02_tools.py:420 模式)")

    # 模拟 LangChain 工具: invoke 是同步的
    class FakeTool:
        name = "search"

        def invoke(self, args: dict) -> str:
            time.sleep(0.1)                              # 模拟同步阻塞
            return f"search({args}) = result"

    tool = FakeTool()

    # ❌ 反面: 直接 await tool.invoke() — 错, invoke 不是协程
    try:
        await tool.invoke({"q": "OPC"})                 # TypeError
    except TypeError as e:
        print(f"  ❌ await sync invoke -> {e}")

    # ✅ 正确: to_thread
    result = await asyncio.to_thread(tool.invoke, {"q": "OPC"})
    print(f"  ✅ to_thread invoke -> {result}")

    # ✅ 批量并发
    results = await asyncio.gather(
        asyncio.to_thread(tool.invoke, {"q": "OPC"}),
        asyncio.to_thread(tool.invoke, {"q": "MiniMax"}),
        asyncio.to_thread(tool.invoke, {"q": "LangChain"}),
    )
    print(f"  ✅ 并发 3 个 tool 调用: {results}")


if __name__ == "__main__":
    setup()
    asyncio.run(demo_basic_to_thread())
    asyncio.run(demo_concurrent_to_thread())
    asyncio.run(demo_blocking_without_to_thread())
    asyncio.run(demo_langchain_tool_pattern())
    print("\n[L2-03] 全部 demo 跑完。")
