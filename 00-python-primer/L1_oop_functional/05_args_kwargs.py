"""
05_args_kwargs.py
==================
学完你能回答:
1. *args 和 **kwargs 区别?
2. 调用时 * 和 ** 是什么?
3. 装饰器 wrapper 为啥必须 *args, **kwargs?
4. 项目里 asyncio.gather(*coros) 为什么用 *?
5. 关键字-only 参数怎么写 (PEP 3102)?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_collect_args_kwargs() -> None:
    banner("1. 收集 *args 和 **kwargs")

    def demo(a, b, *args, default=10, **kwargs):
        print(f"  a={a}, b={b}")
        print(f"  args={args}")
        print(f"  default={default}")
        print(f"  kwargs={kwargs}")

    demo(1, 2, 3, 4, 5, default=99, x=100, y=200)


def demo_unpack() -> None:
    banner("2. 调用时解包 * 和 **")

    def f(a, b, c):
        print(f"  f(a={a}, b={b}, c={c})")

    # 解包 list/tuple 给位置参数
    f(*[1, 2, 3])
    f(*(1, 2, 3))

    # 解包 dict 给关键字参数 (key 必须和参数名一致)
    f(**{"a": 10, "b": 20, "c": 30})

    # 混合
    f(1, *[2, 3])                              # a=1, b=2, c=3
    f(1, **{"b": 2, "c": 3})                   # a=1, b=2, c=3


def demo_decorator_passthrough() -> None:
    banner("3. 装饰器 wrapper 透传 (项目惯例)")

    from functools import wraps
    import time

    def timed(func):
        @wraps(func)
        def wrapper(*args, **kwargs):          # 必须 *args, **kwargs
            t0 = time.perf_counter()
            result = func(*args, **kwargs)      # 透传
            elapsed = time.perf_counter() - t0
            print(f"  [{func.__name__}] 耗时 {elapsed*1000:.2f}ms, 返回 {result!r}")
            return result
        return wrapper

    @timed
    def search(query: str, top_k: int = 3) -> list[str]:
        return [f"doc{i}-{query}" for i in range(top_k)]

    search("OPC")
    search("MiniMax", top_k=5)


def demo_keyword_only() -> None:
    banner("4. 关键字-only 参数 (PEP 3102)")

    # *, 之后的参数必须用关键字传
    def connect(host, port, *, timeout=10, retries=3):
        print(f"  host={host}, port={port}, timeout={timeout}, retries={retries}")

    connect("localhost", 8080)
    connect("localhost", 8080, timeout=30, retries=5)
    try:
        connect("localhost", 8080, 30)          # 错误: timeout 必须关键字
    except TypeError as e:
        print(f"  TypeError: {e}")


def demo_asyncio_gather_unpack() -> None:
    banner("5. asyncio.gather(*coros) 模式 (项目 02_tools.py:423)")

    import asyncio

    async def one(i: int) -> str:
        await asyncio.sleep(0.05)
        return f"task-{i}"

    async def run():
        coros = [one(i) for i in range(5)]
        results = await asyncio.gather(*coros)   # * 解包, gather 接变长 coroutine
        return results

    results = asyncio.run(run())
    print(f"  并发结果: {results}")


if __name__ == "__main__":
    setup()
    demo_collect_args_kwargs()
    demo_unpack()
    demo_decorator_passthrough()
    demo_keyword_only()
    demo_asyncio_gather_unpack()
    print("\n[L1-05] 全部 demo 跑完。")
