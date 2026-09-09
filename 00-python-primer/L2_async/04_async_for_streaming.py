"""
04_async_for_streaming.py
=========================
学完你能回答:
1. async for 和 for 区别?
2. 异步生成器怎么写?
3. 普通 for 遍历异步生成器会怎样?
4. async with 怎么用?
5. 项目里 LLM 流式输出怎么消费?
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


async def mock_llm_stream() -> AsyncIterator[str]:
    """模拟 LLM 流式输出: 每次吐一个 token"""
    tokens = ["你好", ",", " 我", " 是", " MiniMax", "-", "M3", "."]
    for t in tokens:
        await asyncio.sleep(0.05)                       # 模拟网络延迟
        yield t


async def demo_basic_async_for() -> None:
    banner("1. async for 基础")

    print("  [流式] ", end="")
    async for token in mock_llm_stream():
        print(token, end="", flush=True)
    print("\n  完成")


async def demo_async_generator_func() -> None:
    banner("2. 自己写异步生成器函数")

    async def countdown(n: int) -> AsyncIterator[str]:
        for i in range(n, 0, -1):
            await asyncio.sleep(0.1)
            yield f"  T-{i}..."

    async for msg in countdown(3):
        print(msg)
    print("  Lift off!")


async def demo_async_generator_expression() -> None:
    banner("3. 异步生成器表达式 (PEP 530)")

    async def source():
        for x in [1, 2, 3, 4, 5]:
            await asyncio.sleep(0.05)
            yield x

    # 异步生成器表达式 (3.6+ 用, 3.10+ 简化)
    if sys.version_info >= (3, 10):
        doubled = [x async for x in source() if x % 2 == 0]
        doubled = [x * 2 for x in doubled]
        print(f"  偶数 × 2: {doubled}")
    else:
        doubled = [x async for x in source() if x % 2 == 0]
        print(f"  偶数 (旧版): {doubled}")


async def demo_async_with() -> None:
    banner("4. async with (异步上下文管理器)")

    # 用 aiohttp 风格的异步连接
    class AsyncConn:
        async def __aenter__(self):
            print("  [async] 连接建立")
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            print("  [async] 连接关闭")
            return False

        async def fetch(self, url: str) -> str:
            await asyncio.sleep(0.05)
            return f"<{url}>"

    async with AsyncConn() as conn:
        html = await conn.fetch("https://api.example.com")
        print(f"  收到: {html}")


async def demo_langchain_astream_pattern() -> None:
    banner("5. LangChain astream 模式 (09_streaming.py:221)")

    # 模拟 agent.astream 返回的异步流
    class FakeEvent:
        def __init__(self, kind, payload):
            self.kind = kind
            self.payload = payload

    async def fake_astream(state):
        """模拟 LangChain 的 astream(state, stream_mode='updates')"""
        # 第一次 yield: 用户消息确认
        await asyncio.sleep(0.05)
        yield FakeEvent("values", {"messages": ["USER: 深圳?"]})
        # 第二次 yield: 模型调工具
        await asyncio.sleep(0.05)
        yield FakeEvent("updates", {"agent": {"messages": ["calling: get_weather('深圳')"]}})
        # 第三次 yield: 工具结果
        await asyncio.sleep(0.05)
        yield FakeEvent("updates", {"tools": {"messages": ["weather: 28°C 晴"]}})
        # 第四次 yield: 最终回答
        await asyncio.sleep(0.05)
        yield FakeEvent("updates", {"agent": {"messages": ["回答: 深圳 28°C 晴"]}})

    # 项目里就是这么消费的
    async for event in fake_astream({}):
        if event.kind == "updates":
            for node, data in event.payload.items():
                print(f"  [{node}] {data}")
        elif event.kind == "values":
            print(f"  [state] {event.payload}")


async def main() -> None:
    await demo_basic_async_for()
    await demo_async_generator_func()
    await demo_async_generator_expression()
    await demo_async_with()
    await demo_langchain_astream_pattern()


if __name__ == "__main__":
    setup()
    asyncio.run(main())
    print("\n[L2-04] 全部 demo 跑完。")
