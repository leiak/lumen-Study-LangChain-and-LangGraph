"""
07_time_sleep.py
=================
学完你能回答:
1. time.sleep 在 async 函数里能用吗?
2. time.time() 和 time.perf_counter() 区别?
3. 测耗时用哪个?
4. 为什么 time.sleep 不精确?
5. 项目里 time.sleep 用在哪?
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_sleep() -> None:
    banner("1. 基本 time.sleep")

    t0 = time.perf_counter()
    time.sleep(0.1)
    elapsed = time.perf_counter() - t0
    print(f"  sleep(0.1) 实际耗时: {elapsed*1000:.2f}ms")


def demo_perf_counter_vs_time() -> None:
    banner("2. perf_counter vs time.time (测耗时用哪个)")

    # perf_counter: 单调递增, 不受系统时间影响
    t0_pc = time.perf_counter()
    time.sleep(0.1)
    pc_elapsed = time.perf_counter() - t0_pc

    # time.time: 受系统时间影响
    t0_t = time.time()
    time.sleep(0.1)
    t_elapsed = time.time() - t0_t

    print(f"  perf_counter 耗时: {pc_elapsed*1000:.2f}ms")
    print(f"  time.time    耗时: {t_elapsed*1000:.2f}ms")
    print()
    print("  推荐: 测耗时永远用 perf_counter")


def demo_sleep_blocks_async() -> None:
    banner("3. async 里 time.sleep 会阻塞事件循环")

    import asyncio

    async def good_sleep():
        await asyncio.sleep(0.1)
        return "done (用 asyncio.sleep)"

    async def bad_sleep():
        time.sleep(0.1)                              # 阻塞整个事件循环
        return "done (阻塞!)"

    async def main():
        t0 = time.perf_counter()
        result = await good_sleep()
        good_elapsed = time.perf_counter() - t0
        print(f"  {result}: {good_elapsed*1000:.2f}ms (不阻塞)")

        t0 = time.perf_counter()
        result = await bad_sleep()
        bad_elapsed = time.perf_counter() - t0
        print(f"  {result}: {bad_elapsed*1000:.2f}ms (阻塞了 loop)")

    asyncio.run(main())


def demo_project_slow_tool() -> None:
    banner("4. 项目 slow_lookup 模式 (04_middleware.py:64)")

    # 模拟工具: 故意慢, 测试 timeout middleware
    def slow_lookup(query: str) -> str:
        import time
        time.sleep(2)                                 # 模拟慢 IO
        return f"results for {query}"

    # 测一下
    t0 = time.perf_counter()
    result = slow_lookup("MiniMax")
    elapsed = time.perf_counter() - t0
    print(f"  slow_lookup 耗时: {elapsed*1000:.2f}ms")
    print(f"  结果: {result}")
    print("  → 这种工具会触发 timeout middleware")


def demo_strftime() -> None:
    banner("5. 时间格式化 (time.strftime)")

    now_ts = time.time()
    formatted = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts))
    print(f"  localtime:    {formatted}")

    utc_formatted = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now_ts))
    print(f"  gmtime (UTC): {utc_formatted}")

    # 推荐: 用 datetime 替代 time.strftime
    from datetime import datetime
    print(f"  datetime.now().strftime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    setup()
    demo_basic_sleep()
    demo_perf_counter_vs_time()
    demo_sleep_blocks_async()
    demo_project_slow_tool()
    demo_strftime()
    print("\n[L4-07] 全部 demo 跑完。")
