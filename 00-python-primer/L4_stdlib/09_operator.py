"""
09_operator.py
================
学完你能回答:
1. operator.add 和 lambda a, b: a+b 区别?
2. itemgetter 怎么用?
3. attrgetter 能取嵌套属性吗?
4. operator.add 对 list 是什么行为?
5. 项目里 add_int 当 reducer 干什么?
"""
from __future__ import annotations

import sys
from operator import add, attrgetter, itemgetter, methodcaller, mul
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_add_mul() -> None:
    banner("1. add / mul 函数化操作符")

    print(f"  add(3, 4) = {add(3, 4)}")
    print(f"  mul(3, 4) = {mul(3, 4)}")
    print(f"  等价 lambda: (lambda a, b: a + b)(3, 4) = {(lambda a, b: a + b)(3, 4)}")


def demo_list_concat() -> None:
    banner("2. operator.add 对 list 是拼接")

    a = [1, 2, 3]
    b = [4, 5]
    result = add(a, b)
    print(f"  add([1,2,3], [4,5]) = {result}")
    print("  注意: 不是 [5,7] (元素相加), 是 [1,2,3,4,5] (列表拼接)")


def demo_itemgetter() -> None:
    banner("3. itemgetter 字典取值")

    users = [
        {"name": "alice", "age": 30},
        {"name": "bob", "age": 25},
        {"name": "carol", "age": 35},
    ]

    # 按 name 排序
    by_name = sorted(users, key=itemgetter("name"))
    print(f"  按 name 排序: {[u['name'] for u in by_name]}")

    # 按 age 排序
    by_age = sorted(users, key=itemgetter("age"))
    print(f"  按 age 排序: {[u['name'] for u in by_age]}")

    # 多字段 (name, age 组合)
    by_name_age = sorted(users, key=itemgetter("name", "age"))
    print(f"  按 name, age 排序: {[(u['name'], u['age']) for u in by_name_age]}")


def demo_attrgetter() -> None:
    banner("4. attrgetter 对象属性")

    class User:
        def __init__(self, name, age):
            self.name = name
            self.age = age

    users = [User("alice", 30), User("bob", 25)]

    get_name = attrgetter("name")
    print(f"  get_name(users[0]) = {get_name(users[0])}")

    # 多字段
    get_name_age = attrgetter("name", "age")
    print(f"  get_name_age(users[0]) = {get_name_age(users[0])}")


def demo_langgraph_reducer() -> None:
    banner("5. LangGraph reducer 模式 (03_agents.py:22)")

    # 模拟 LangGraph state 更新
    state = {"turn_count": 0, "messages": ["hello"]}

    # node 返回 {"turn_count": 1, "messages": ["hi"]}
    update = {"turn_count": 1, "messages": ["hi"]}

    # 普通字段直接覆盖
    state["turn_count"] = update["turn_count"]

    # Annotated 字段用 add reducer 合并
    state["messages"] = add(state["messages"], update["messages"])

    print(f"  state = {state}")

    # 再来一次
    update2 = {"turn_count": 1, "messages": ["how are you?"]}
    state["turn_count"] = add(state["turn_count"], update2["turn_count"])
    state["messages"] = add(state["messages"], update2["messages"])
    print(f"  state (after 2 updates) = {state}")


def demo_methodcaller() -> None:
    banner("6. methodcaller 调用方法")

    upper = methodcaller("upper")
    print(f"  upper('hello') = {upper('hello')}")

    strip = methodcaller("strip")
    print(f"  strip('  hi  ') = {strip('  hi  ')!r}")


if __name__ == "__main__":
    setup()
    demo_add_mul()
    demo_list_concat()
    demo_itemgetter()
    demo_attrgetter()
    demo_langgraph_reducer()
    demo_methodcaller()
    print("\n[L4-09] 全部 demo 跑完。")
