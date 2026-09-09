"""
01_asyncio_gather.py
====================
学完你能回答:
1. asyncio.gather 怎么并发多个协程?
2. 一个失败会传染其他吗?
3. gather 接收的是协程还是 await 后的值?
4. TaskGroup (3.11+) 比 gather 强在哪?
5. 项目里 gather 用在什么场景?
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


async def work(i: int, delay: float = 0.1, fail: bool = False) -> str:
    await asyncio.sleep(delay)
    if fail:
        raise ValueError(f"task {i} 故意失败")
    return f"task-{i}"


async def demo_basic_gather() -> None:
    banner("1. 基本 gather 并发")

    t0 = time.perf_counter()
    results = await asyncio.gather(
        work(1, 0.1),
        work(2, 0.1),
        work(3, 0.1),
    )
    elapsed = time.perf_counter() - t0
    print(f"  results = {results}")
    print(f"  耗时 {elapsed*1000:.1f}ms (并发应该 ~100ms, 而不是 300ms)")


async def demo_return_exceptions() -> None:
    banner("2. return_exceptions=True 让失败不传染")

    # 默认: 一个失败 -> 全部失败 (CancelledError)
    try:
        await asyncio.gather(work(1), work(2, fail=True), work(3))
    except ValueError as e:
        print(f"  默认行为: {type(e).__name__}: {e}")

    # return_exceptions=True: 失败变结果里的 Exception 实例
    results = await asyncio.gather(
        work(1),
        work(2, fail=True),
        work(3),
        return_exceptions=True,
    )
    for i, r in enumerate(results, 1):
        if isinstance(r, Exception):
            print(f"  task-{i} -> 异常: {type(r).__name__}: {r}")
        else:
            print(f"  task-{i} -> 结果: {r}")


async def demo_unpack_with_gather() -> None:
    banner("3. 解包生成器批量并发 (项目 02_tools.py:423 模式)")

    # 项目惯用法: 拿到 tool_calls 列表后, 批量并发跑
    tool_calls = [{"name": f"task_{i}", "args": {}} for i in range(5)]

    async def one(tc):
        await asyncio.sleep(0.05)
        return f"ran {tc['name']}"

    t0 = time.perf_counter()
    results = await asyncio.gather(*(one(tc) for tc in tool_calls))
    elapsed = time.perf_counter() - t0
    print(f"  results = {results}")
    print(f"  耗时 {elapsed*1000:.1f}ms (5 个并发应该 ~50ms)")


async def demo_task_group() -> None:
    banner("4. TaskGroup (Python 3.11+) — 更现代的写法")

    if sys.version_info < (3, 11):
        print("  Python < 3.11, 跳过")
        return

    async def task(name, fail=False):
        await asyncio.sleep(0.05)
        if fail:
            raise RuntimeError(f"{name} failed")
        return name

    try:
        async with asyncio.TaskGroup() as tg:
            t1 = tg.create_task(task("a"))
            t2 = tg.create_task(task("b", fail=True))
            t3 = tg.create_task(task("c"))
        print(f"  全部成功: {t1.result()}, {t2.result()}, {t3.result()}")
    except* RuntimeError as eg:                      # ExceptionGroup 语法 (3.11+)
        print(f"  TaskGroup 失败, 收到 {len(eg.exceptions)} 个异常")
        for e in eg.exceptions:
            print(f"    {type(e).__name__}: {e}")


async def main() -> None:
    await demo_basic_gather()
    await demo_return_exceptions()
    await demo_unpack_with_gather()
    await demo_task_group()


if __name__ == "__main__":
    setup()
    asyncio.run(main())
    print("\n[L2-01] 全部 demo 跑完。")
