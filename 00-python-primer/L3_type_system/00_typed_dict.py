"""
00_typed_dict.py
=================
学完你能回答:
1. TypedDict 和普通 dict 区别?
2. TypedDict 运行时检查字段吗?
3. NotRequired 怎么用?
4. total=False 干什么?
5. LangGraph state 为啥必须 TypedDict?
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_typed_dict() -> None:
    banner("1. 基本 TypedDict")

    class User(TypedDict):
        name: str
        age: int

    u: User = {"name": "alice", "age": 30}
    print(f"u = {u}")
    print(f"u['name'] = {u['name']}")

    # 运行时还是 dict
    print(f"type(u) = {type(u).__name__}")              # dict

    # 运行时缺字段不报错 (只有 mypy 会说)
    u2 = {"name": "bob"}                                # OK 运行时
    print(f"u2 = {u2}")
    try:
        _ = u2["age"]                                   # KeyError
    except KeyError as e:
        print(f"  运行时取不存在的 key: KeyError: {e}")


def demo_total_false() -> None:
    banner("2. total=False — 所有字段都可选")

    class PartialUser(TypedDict, total=False):
        name: str
        age: int
        email: str

    p: PartialUser = {}                                 # 空 dict 也合法
    print(f"空 dict 也合法: {p}")

    p2: PartialUser = {"name": "alice"}
    print(f"部分字段: {p2}")


def demo_not_required() -> None:
    banner("3. NotRequired — 3.11+ 字段级可选")

    if sys.version_info < (3, 11):
        # 3.11 之前用 typing_extensions
        try:
            from typing_extensions import NotRequired
        except ImportError:
            print("  需要 typing_extensions, 跳过")
            return
    else:
        from typing import NotRequired

    class User(TypedDict):
        name: str                                       # 必有
        age: NotRequired[int]                           # 可选

    u1: User = {"name": "alice", "age": 30}
    u2: User = {"name": "bob"}                          # OK, age 缺
    print(f"u1 = {u1}")
    print(f"u2 = {u2}, has age: {'age' in u2}")


def demo_langgraph_state_pattern() -> None:
    banner("4. LangGraph state 模式 (06_state_graph.py:41)")

    from typing import Annotated, Literal
    from typing_extensions import TypedDict

    class RouterState(TypedDict):
        query: str
        category: Literal["weather", "order", "general"]
        answer: str

    # LangGraph 调用 node 时传 state dict, node 返回更新
    initial: RouterState = {
        "query": "深圳天气?",
        "category": "weather",
        "answer": "",
    }

    def classify_node(state: RouterState) -> dict:
        """节点函数返回部分字段即可, LangGraph 会 merge"""
        return {"answer": f"分类: {state['category']}"}

    updated = {**initial, **classify_node(initial)}
    print(f"更新后 state: {updated}")


if __name__ == "__main__":
    setup()
    demo_basic_typed_dict()
    demo_total_false()
    demo_not_required()
    demo_langgraph_state_pattern()
    print("\n[L3-00] 全部 demo 跑完。")
