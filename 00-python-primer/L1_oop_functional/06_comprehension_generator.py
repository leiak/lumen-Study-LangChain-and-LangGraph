"""
06_comprehension_generator.py
=============================
学完你能回答:
1. list / dict / set 推导式区别?
2. 生成器表达式为什么省内存?
3. 推导式能嵌套几层?
4. sum(1 for x in ...) 是什么意思?
5. 生成器能迭代几次?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_list_comprehension() -> None:
    banner("1. 列表推导式")

    # 基本
    squares = [x * x for x in range(5)]
    print(f"squares = {squares}")

    # 带条件
    evens = [x for x in range(10) if x % 2 == 0]
    print(f"evens = {evens}")

    # 嵌套 (最多 2 层, 3 层就难读了)
    matrix = [[i * 3 + j for j in range(3)] for i in range(3)]
    print(f"matrix = {matrix}")

    # 展平
    flat = [v for row in matrix for v in row]
    print(f"flat = {flat}")


def demo_dict_set_comprehension() -> None:
    banner("2. dict / set 推导式")

    # dict
    sq = {x: x * x for x in range(5)}
    print(f"sq = {sq}")

    # dict 反转
    inv = {v: k for k, v in sq.items()}
    print(f"inv = {inv}")

    # set
    lengths = {len(word) for word in ["alice", "bob", "carol", "alice"]}
    print(f"lengths (去重) = {lengths}")


def demo_generator_expression() -> None:
    banner("3. 生成器表达式 (惰性)")

    # () 不是 tuple, 是 generator!
    gen = (x * x for x in range(10_000_000))   # 不爆 RAM, 不立刻算
    print(f"gen 类型 = {type(gen).__name__}")

    # 取前 3 个
    import itertools
    first3 = list(itertools.islice(gen, 3))
    print(f"前 3 个 = {first3}")

    # 生成器只能迭代一次
    again = list(itertools.islice(gen, 3))
    print(f"再取 3 个 = {again}")                # []


def demo_supervisor_count_pattern() -> None:
    banner("4. 项目里的 sum(1 for ... if ...) 计数 (13_supervisor.py)")

    # 模拟 LangChain messages
    class FakeMsg:
        def __init__(self, role, tool_calls=None):
            self.role = role
            self.tool_calls = tool_calls

    msgs = [
        FakeMsg("user"),
        FakeMsg("assistant", tool_calls=[{"name": "search"}]),
        FakeMsg("tool"),
        FakeMsg("assistant", tool_calls=[{"name": "calc"}]),
        FakeMsg("assistant"),
    ]

    # 数 "assistant 调过几次工具"
    tool_msgs = sum(1 for m in msgs if getattr(m, "tool_calls", None))
    print(f"assistant 调工具次数 = {tool_msgs}")

    # 数 "user 说了几次"
    user_msgs = sum(1 for m in msgs if m.role == "user")
    print(f"user 消息数 = {user_msgs}")

    # 等价但更显式的写法
    tool_msgs_v2 = len([m for m in msgs if getattr(m, "tool_calls", None)])
    print(f"等价的列表推导写法 = {tool_msgs_v2}")


if __name__ == "__main__":
    setup()
    demo_list_comprehension()
    demo_dict_set_comprehension()
    demo_generator_expression()
    demo_supervisor_count_pattern()
    print("\n[L1-06] 全部 demo 跑完。")
