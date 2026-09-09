"""
02_asyncio_run.py
=================
学完你能回答:
1. asyncio.run 干什么?
2. 一个 .py 文件能调两次 asyncio.run 吗?
3. asyncio.run 嵌套会怎样?
4. Jupyter 里为啥不用 asyncio.run?
5. 项目里同步入口怎么跑并发 demo?
"""
from __future__ import annotations

import asyncio
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup

# 这个 demo 故意制造 "未 await 的协程" 来演示嵌套错误, 抑制警告
warnings.filterwarnings("ignore", message="coroutine .* was never awaited")


async def fetch(i: int) -> str:
    await asyncio.sleep(0.05)
    return f"fetched {i}"


async def async_main() -> None:
    """顶层协程, 不能 await"""
    print("  [main] 异步入口开始")
    results = await asyncio.gather(fetch(1), fetch(2), fetch(3))
    print(f"  [main] 结果: {results}")


def demo_basic_run() -> None:
    banner("1. 同步入口跑异步")

    print("  这是同步函数, 但内部跑异步")
    t0 = time.perf_counter()
    asyncio.run(async_main())                         # 创建 + 关闭 loop
    print(f"  耗时: {(time.perf_counter()-t0)*1000:.1f}ms")


def demo_nested_run_fails() -> None:
    banner("2. 嵌套 asyncio.run 会失败")

    async def inner():
        return "inner result"

    async def outer():
        # 错误: 不能在 async 里调 asyncio.run
        # 先 await 触发, 再 run — 都会失败
        return asyncio.run(inner())

    try:
        asyncio.run(outer())
    except RuntimeError as e:
        print(f"  RuntimeError: {e}")
        print("  解决: 内部协程直接 await, 不要 asyncio.run")
        # 清理: outer 抛出前 inner 协程未 await, 显式 close 避免警告
        try:
            inner().close()
        except Exception:
            pass


def demo_reuse_after_close() -> None:
    banner("3. asyncio.run 后 loop 已关闭")

    async def get_loop_id() -> int:
        return id(asyncio.get_running_loop())

    first = asyncio.run(get_loop_id())
    second = asyncio.run(get_loop_id())
    print(f"  第一次 loop id: {first}")
    print(f"  第二次 loop id: {second}")
    print(f"  两次 ID 不同 → asyncio.run 每次创建新 loop, 自动清理")


def demo_with_sync_initial_check() -> None:
    banner("4. 项目级模式: 同步前置检查 + 异步主体")

    # 模拟项目 _run_parallel 模式 (02_tools.py:425)
    def _run_parallel():
        # 1) 同步前置检查 (比如确认 API key)
        if not hasattr(asyncio, "run"):
            raise RuntimeError("需要 Python 3.7+")

        # 2) 跑异步主体
        async def main():
            results = await asyncio.gather(fetch(1), fetch(2))
            return results

        return asyncio.run(main())

    results = _run_parallel()
    print(f"  同步入口跑并发结果: {results}")


if __name__ == "__main__":
    setup()
    demo_basic_run()
    demo_nested_run_fails()
    demo_reuse_after_close()
    demo_with_sync_initial_check()
    print("\n[L2-02] 全部 demo 跑完。")
