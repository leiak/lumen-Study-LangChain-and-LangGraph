"""
00_class_inheritance.py
=======================
学完你能回答:
1. Python 类怎么继承?
2. super().__init__() 必须显式调吗?
3. 多继承 MRO 怎么算?
4. isinstance() 和 type() 区别?
5. LangChain 的 BaseTool 子类化怎么写?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_inheritance() -> None:
    banner("1. 基本继承 + super()")

    class Animal:
        def __init__(self, name: str):
            self.name = name

        def speak(self) -> str:
            return f"{self.name} 发出声音"

    class Dog(Animal):
        def __init__(self, name: str, breed: str):
            super().__init__(name)            # 必须显式 super
            self.breed = breed

        def speak(self) -> str:                # 重写
            return f"{self.name} (品种 {self.breed}) 说 Woof!"

    d = Dog("旺财", "柴犬")
    print(d.speak())
    print(f"isinstance(d, Animal) = {isinstance(d, Animal)}")
    print(f"isinstance(d, Dog)    = {isinstance(d, Dog)}")


def demo_mro_multiple_inheritance() -> None:
    banner("2. 多继承 MRO (C3 线性化)")

    class A:
        def who(self) -> str:
            return "A"

    class B(A):
        def who(self) -> str:
            return "B"

    class C(A):
        def who(self) -> str:
            return "C"

    class D(B, C):                              # B 优先于 C
        pass

    d = D()
    print(f"D().who() = {d.who()}")              # B (B 在 C 前面)
    print(f"D.__mro__ = {[c.__name__ for c in D.__mro__]}")


def demo_langchain_basetool_pattern() -> None:
    banner("3. LangChain BaseTool 子类化 (项目 02_tools.py 模式)")

    # 用最简化的 BaseTool 替身演示继承
    class BaseTool:
        """LangChain 1.x 的 BaseTool 简化替身, 真实类比这复杂"""
        name: str = ""
        description: str = ""

        def invoke(self, args: dict) -> str:
            return self._run(**args)

    class CalculatorTool(BaseTool):
        name = "calculator"
        description = "算术计算 (项目 02_tools.py:108 模式)"

        def _run(self, expression: str) -> str:
            try:
                return f"{expression} = {eval(expression)}"  # 演示用, 生产别用 eval
            except Exception as e:
                return f"计算失败: {e}"

    calc = CalculatorTool()
    print(calc.invoke({"expression": "2 + 3 * 4"}))
    print(calc.invoke({"expression": "1 / 0"}))


def demo_classmethod_staticmethod() -> None:
    banner("4. classmethod / staticmethod")

    class Config:
        DEFAULT_TIMEOUT = 30

        def __init__(self, timeout: float):
            self.timeout = timeout

        @classmethod
        def from_env(cls) -> "Config":
            """类方法: 用 cls 调用, 可以被子类继承"""
            import os
            return cls(float(os.getenv("TIMEOUT", cls.DEFAULT_TIMEOUT)))

        @staticmethod
        def is_valid(timeout: float) -> bool:
            """静态方法: 不需要 self/cls"""
            return 0 < timeout < 600

    c1 = Config(60)
    c2 = Config.from_env()
    print(f"c1.timeout = {c1.timeout}")
    print(f"c2.timeout = {c2.timeout}")
    print(f"Config.is_valid(60) = {Config.is_valid(60)}")
    print(f"Config.is_valid(999) = {Config.is_valid(999)}")


if __name__ == "__main__":
    setup()
    demo_basic_inheritance()
    demo_mro_multiple_inheritance()
    demo_langchain_basetool_pattern()
    demo_classmethod_staticmethod()
    print("\n[L1-00] 全部 demo 跑完。")
