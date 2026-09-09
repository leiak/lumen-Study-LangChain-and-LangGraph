"""
02_literal.py
===============
学完你能回答:
1. Literal 限定哪些值?
2. Literal 运行时检查吗?
3. Literal 和 Enum 区别?
4. 项目里 Literal 用在路由决策?
5. Literal["a"] vs Literal["a", "b"] 区别?
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_literal() -> None:
    banner("1. 基本 Literal")

    Mode = Literal["sync", "async"]
    mode: Mode = "sync"
    print(f"mode = {mode!r}")

    # 运行时还是普通 str
    mode_wrong = "parallel"                             # mypy 会抓, 运行时不抓
    print(f"mode_wrong = {mode_wrong!r}, type = {type(mode_wrong).__name__}")


def demo_router_pattern() -> None:
    banner("2. 路由决策模式 (项目 06_state_graph.py)")

    from typing_extensions import TypedDict

    Category = Literal["weather", "order", "general"]

    class RouterState(TypedDict):
        query: str
        category: Category

    # 路由函数: 接 state 返回 category, 然后 LangGraph 查 mapping
    def route(state: RouterState) -> Category:
        q = state["query"]
        if "天气" in q:
            return "weather"
        elif "订单" in q:
            return "order"
        return "general"

    mapping: dict[Category, str] = {
        "weather": "weather_node",
        "order": "order_node",
        "general": "general_node",
    }

    for query in ["北京天气?", "查订单 ORD-001", "你们是干嘛的?"]:
        state: RouterState = {"query": query, "category": "general"}
        cat = route(state)
        next_node = mapping[cat]
        print(f"  {query!r} -> category={cat} -> {next_node}")


def demo_literal_vs_enum() -> None:
    banner("3. Literal vs Enum")

    from enum import Enum

    # Literal: 仅类型层, 运行时就是普通 str
    LMode = Literal["sync", "async"]
    a: LMode = "sync"
    print(f"Literal: a={a!r}, type={type(a).__name__}")  # str

    # Enum: 运行时是 Enum 实例
    class EMode(Enum):
        SYNC = "sync"
        ASYNC = "async"

    b = EMode.SYNC
    print(f"Enum:    b={b!r}, type={type(b).__name__}")  # EMode
    print(f"Enum.value = {b.value}, name = {b.name}")

    # Enum 适合需要运行时比较/序列化, Literal 适合纯类型约束
    print("\n  Literal 适合: 状态机 / 路由决策 (LangGraph)")
    print("  Enum    适合: 业务枚举 (订单状态 / 用户角色)")


def demo_final_decision() -> None:
    banner("4. Final 决策: 项目里为什么用 Literal")

    # LangGraph 路由决策需要:
    # 1. 类型约束 (Literal 提供)
    # 2. 字典映射 (dict[Category, str])
    # 3. LLM 输出的字符串恰好能匹配
    # 用 Enum 太重, 用 str 没约束, Literal 最合适

    Decision = Literal["approve", "reject", "escalate"]

    def llm_classify(text: str) -> Decision:           # 假装 LLM 输出
        text = text.lower()
        if "approve" in text or "通过" in text:
            return "approve"
        if "reject" in text or "拒绝" in text:
            return "reject"
        return "escalate"

    for text in ["please approve", "reject this", "not sure"]:
        d = llm_classify(text)
        print(f"  {text!r} -> {d}")


if __name__ == "__main__":
    setup()
    demo_basic_literal()
    demo_router_pattern()
    demo_literal_vs_enum()
    demo_final_decision()
    print("\n[L3-02] 全部 demo 跑完。")
