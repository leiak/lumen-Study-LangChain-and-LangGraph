"""
01_decorator_basics.py
======================
学完你能回答:
1. 装饰器本质是什么?
2. 怎么写带参数的装饰器 (装饰器工厂)?
3. @property 干什么用?
4. functools.wraps 为什么重要?
5. 多个装饰器叠加顺序?
"""
from __future__ import annotations

import sys
import time
from functools import wraps
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_simple_decorator() -> None:
    banner("1. 简单装饰器 + functools.wraps")

    def log_call(func):
        @wraps(func)                              # 保留原函数 __name__/__doc__
        def wrapper(*args, **kwargs):
            print(f"  [LOG] 进入 {func.__name__}({args}, {kwargs})")
            result = func(*args, **kwargs)
            print(f"  [LOG] 离开 {func.__name__}, 返回 {result!r}")
            return result
        return wrapper

    @log_call
    def add(a: int, b: int) -> int:
        """两数相加"""
        return a + b

    print(f"add.__name__ = {add.__name__}")        # 'add' (因为 wraps)
    print(f"add(2, 3) = {add(2, 3)}")


def demo_decorator_factory() -> None:
    banner("2. 装饰器工厂 (带参数)")

    def retry(max_attempts: int = 3, delay: float = 0.1):
        """retry 是一个返回装饰器的函数"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                for attempt in range(1, max_attempts + 1):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        if attempt == max_attempts:
                            print(f"  [重试] 第 {attempt} 次失败, 放弃: {e}")
                            raise
                        print(f"  [重试] 第 {attempt} 次失败, 重试: {e}")
                        time.sleep(delay)
            return wrapper
        return decorator

    @retry(max_attempts=3, delay=0.01)
    def flaky_call(n: int) -> int:
        if n < 3:
            raise ValueError(f"n={n} 太小")
        return n * 10

    print(flaky_call(5))


def demo_property() -> None:
    banner("3. @property 把方法变只读属性")

    class Temperature:
        def __init__(self, celsius: float):
            self._celsius = celsius

        @property
        def celsius(self) -> float:
            return self._celsius

        @property
        def fahrenheit(self) -> float:
            """派生属性, 调用像属性但其实是方法"""
            return self._celsius * 9 / 5 + 32

        # @celsius.setter 可加可写属性
        @celsius.setter
        def celsius(self, value: float) -> None:
            if value < -273.15:
                raise ValueError("低于绝对零度")
            self._celsius = value

    t = Temperature(100)
    print(f"t.celsius     = {t.celsius}")           # 像属性一样访问
    print(f"t.fahrenheit = {t.fahrenheit}")
    t.celsius = 0
    print(f"修改后: t.fahrenheit = {t.fahrenheit}")


def demo_class_decorator() -> None:
    banner("4. 类装饰器 (简化版 @tool)")

    def tool(name: str, description: str = ""):
        """模拟 LangChain 的 @tool 装饰器"""
        def decorator(func):
            func.tool_name = name                # 挂属性
            func.tool_description = description
            return func
        return decorator

    @tool(name="search", description="搜索关键词")
    def search(query: str) -> str:
        return f"searched: {query}"

    @tool(name="calc")
    def calc(expr: str) -> str:
        return f"calc({expr})"

    for fn in [search, calc]:
        print(f"  工具名={fn.tool_name}, 描述={fn.tool_description}")


if __name__ == "__main__":
    setup()
    demo_simple_decorator()
    demo_decorator_factory()
    demo_property()
    demo_class_decorator()
    print("\n[L1-01] 全部 demo 跑完。")
