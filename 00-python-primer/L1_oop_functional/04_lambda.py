"""
04_lambda.py
============
学完你能回答:
1. lambda 只能写表达式吗?
2. lambda 里能 print / 赋值吗?
3. 三元表达式能在 lambda 里用吗?
4. 项目里 LangGraph 路由函数为什么用 lambda?
5. lambda 嵌套超 1 层怎么办?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_lambda() -> None:
    banner("1. 基本 lambda")

    square = lambda x: x * x                    # noqa: E731 (PEP 8 不让这样赋名)
    print(f"square(5) = {square(5)}")

    add = lambda a, b: a + b
    print(f"add(2, 3) = {add(2, 3)}")


def demo_lambda_with_ternary() -> None:
    banner("2. lambda + 三元当分支")

    classify = lambda x: "big" if x > 10 else "small"
    for n in [3, 15, 8]:
        print(f"  classify({n}) = {classify(n)}")


def demo_lambda_in_sorted_filter() -> None:
    banner("3. sorted / filter / map 里的 lambda")

    items = [("alice", 30), ("bob", 25), ("carol", 35)]

    # 按年龄排
    sorted_by_age = sorted(items, key=lambda t: t[1])
    print(f"按年龄升序: {sorted_by_age}")

    # 取年龄 > 28 的
    filtered = list(filter(lambda t: t[1] > 28, items))
    print(f"年龄 > 28: {filtered}")

    # 提取名字
    names = list(map(lambda t: t[0], items))
    print(f"提取名字: {names}")


def demo_langgraph_router_lambda() -> None:
    banner("4. LangGraph 路由函数 (项目 06_state_graph.py 模式)")

    # 模拟 LangGraph state
    def add_conditional_edges(router_fn, mapping):
        """简化版 LangGraph add_conditional_edges"""
        def route(state):
            key = router_fn(state)
            return mapping.get(key, "__end__")
        return route

    # 路由函数: 根据 state["category"] 返回下一个节点
    router = add_conditional_edges(
        lambda s: s["category"],                 # <-- 关键: 用 lambda 提 state 字段
        {"weather": "weather_node", "order": "order_node"},
    )

    for state in [
        {"category": "weather"},
        {"category": "order"},
        {"category": "unknown"},
    ]:
        print(f"  state={state} -> next={router(state)}")


if __name__ == "__main__":
    setup()
    demo_basic_lambda()
    demo_lambda_with_ternary()
    demo_lambda_in_sorted_filter()
    demo_langgraph_router_lambda()
    print("\n[L1-04] 全部 demo 跑完。")
