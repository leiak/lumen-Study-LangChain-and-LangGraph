"""
08_dunder_methods.py
====================
学完你能回答:
1. __str__ 和 __repr__ 区别?
2. __init__ 是构造方法吗?
3. __call__ 让对象能像函数被调?
4. __eq__ 重写后为什么 __hash__ 也要?
5. 哪些 dunder 是 dataclass 自动生成的?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_str_and_repr() -> None:
    banner("1. __str__ vs __repr__")

    class Point:
        def __init__(self, x, y):
            self.x = x
            self.y = y

        def __repr__(self):
            return f"Point(x={self.x!r}, y={self.y!r})"

        def __str__(self):
            return f"({self.x}, {self.y})"

    p = Point(1, 2)
    print(f"print(p)   -> {p}")               # 调 __str__
    print(f"f-string   -> {p!r}")              # 调 __repr__ (带 !r)
    print(f"直接 {p!r} = {p!r}")                # REPL 风格

    print(f"\n无 __str__ 时, print 退回到 __repr__")
    class OnlyRepr:
        def __repr__(self):
            return "OnlyRepr()"

    print(f"print(OnlyRepr()) = {OnlyRepr()}")


def demo_call_dunder() -> None:
    banner("2. __call__: 对象能像函数被调")

    class Counter:
        def __init__(self):
            self.count = 0

        def __call__(self) -> int:
            self.count += 1
            return self.count

    c = Counter()
    print(f"c() = {c()}, c() = {c()}, c() = {c()}")
    print(f"对象是 callable: {callable(c)}")


def demo_eq_and_hash() -> None:
    banner("3. __eq__ + __hash__ (放 dict 必看)")

    class User:
        def __init__(self, name):
            self.name = name

        def __eq__(self, other):
            return isinstance(other, User) and self.name == other.name

        def __hash__(self):
            return hash(self.name)

    u1 = User("alice")
    u2 = User("alice")
    u3 = User("bob")

    print(f"u1 == u2 = {u1 == u2}")           # True (重写 __eq__)
    print(f"u1 == u3 = {u1 == u3}")           # False

    # 重写 __eq__ 必须同时重写 __hash__, 否则不能放 set/dict
    s = {u1, u2, u3}
    print(f"set 长度 = {len(s)}")              # 2 (u1 和 u2 视为同一个)


def demo_dataclass_dunders() -> None:
    banner("4. @dataclass 自动生成哪些 dunder")

    from dataclasses import dataclass

    @dataclass
    class Box:
        w: int
        h: int

    b = Box(3, 4)
    print(f"b       = {b}")                   # 自动 __repr__
    print(f"b == Box(3, 4) = {b == Box(3, 4)}")  # 自动 __eq__
    print(f"自动方法: {[m for m in dir(Box) if m.startswith('__') and not m.startswith('___')]}")


if __name__ == "__main__":
    setup()
    demo_str_and_repr()
    demo_call_dunder()
    demo_eq_and_hash()
    demo_dataclass_dunders()
    print("\n[L1-08] 全部 demo 跑完。")
