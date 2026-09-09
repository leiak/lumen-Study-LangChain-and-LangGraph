"""
04_future_annotations.py
========================
学完你能回答:
1. from __future__ import annotations 干什么?
2. 没这行, 类方法返回自己的类型怎么写?
3. __annotations__ 拿到的是字符串还是真类型?
4. 循环导入类型怎么办?
5. PEP 563 vs PEP 649 区别?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_self_reference() -> None:
    banner("1. 前向引用: 类方法返回自己")

    class Node:
        def __init__(self, name: str):
            self.name = name
            self.children: list[Node] = []              # 直接写 Node

        def add_child(self, child: Node) -> Node:        # 返回自己
            self.children.append(child)
            return self

    # 没 future: 要写 'Node', 或者 Node 定义后再加方法
    n = Node("root").add_child(Node("a")).add_child(Node("b"))
    print(f"  root = {n.name}, children = {[c.name for c in n.children]}")


def demo_lazy_eval() -> None:
    banner("2. 注解是字符串, 延迟解析")

    def f(x: list[dict[str, int]]) -> dict[str, list[int]]:
        return {"data": [1, 2, 3]}

    # __annotations__ 拿到的全是字符串
    print(f"  f.__annotations__ = {f.__annotations__}")
    print(f"  类型: {type(f.__annotations__['x']).__name__}")

    # 想拿到真类型用 get_type_hints
    import typing
    resolved = typing.get_type_hints(f)
    print(f"  get_type_hints(f)['x'] = {resolved['x']}")


def demo_circular_import_safety() -> None:
    banner("3. 避免循环 import (项目常见)")

    # 场景: a.py 想用 B 类型, 但 B 在 b.py 里, b.py 又 import a.py
    # 没有 future: import 时求值注解 -> NameError (因为 B 还没定义)
    # 有 future: 注解是字符串, 真要用时再解析

    # 模拟: 这里直接定义两个互相引用的 dataclass
    from dataclasses import dataclass

    @dataclass
    class Author:
        name: str
        books: list[Book] = None                          # 前向引用 OK 因为 future

    @dataclass
    class Book:
        title: str
        author: Author = None

    # 现在互相引用也不会 NameError
    a = Author("Alice")
    b = Book("OPC 实战", a)
    a.books = [b]

    print(f"  author = {a.name}")
    print(f"  book = {b.title}")
    print(f"  书数 = {len(a.books)}")


def demo_perf_benefit() -> None:
    banner("4. 性能: 启动时不必 import 整个 typing")

    # 没 future: 定义 f 时, list[int] / dict[str, list] 立刻求值
    #            -> import typing.List, typing.Dict
    # 有 future: 字符串, 跳过

    # 实测: 通过 __annotations__ 访问能看到区别
    import time

    def with_future(x: list[dict[str, tuple[int, ...]]]) -> None:
        pass

    # __annotations__ 访问
    t0 = time.perf_counter()
    for _ in range(1000):
        _ = with_future.__annotations__
    elapsed = time.perf_counter() - t0
    print(f"  1000 次访问 __annotations__: {elapsed*1000:.2f}ms (字符串, 快)")


def demo_when_required() -> None:
    banner("5. 必须用的场景")

    print("  场景 1: 类内引用自己")
    print("    class Node:")
    print("        def copy(self) -> Node: ...")
    print()
    print("  场景 2: dataclass 字段是同模块后面的类型")
    print("    @dataclass")
    print("    class A:")
    print("        b: B = None  # B 在下面定义")
    print()
    print("  场景 3: 项目所有 .py 顶部都有这一行, 风格一致")
    print()
    print("  项目所有 23 个文件的 import 顺序都是:")
    print("    from __future__ import annotations    # 第一行")
    print("    import sys / pathlib / typing ...    # 标准库")
    print("    from _common import ...              # 项目内部")
    print("    from langchain_xxx import ...        # 第三方")


if __name__ == "__main__":
    setup()
    demo_self_reference()
    demo_lazy_eval()
    demo_circular_import_safety()
    demo_perf_benefit()
    demo_when_required()
    print("\n[L3-04] 全部 demo 跑完。")
