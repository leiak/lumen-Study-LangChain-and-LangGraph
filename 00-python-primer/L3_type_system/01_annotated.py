"""
01_annotated.py
================
学完你能回答:
1. Annotated[T, x] 是什么?
2. LangGraph 怎么用 Annotated 挂 reducer?
3. metadata 运行时影响类型吗?
4. InjectedToolArg 加不加括号?
5. 怎么获取 Annotated 的 metadata?
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, get_args, get_origin, get_type_hints

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_annotated() -> None:
    banner("1. 基本 Annotated")

    # Annotated[T, metadata] — T 是真实类型, metadata 只是装饰
    x: Annotated[int, "用户 ID, 不可空"] = 42
    print(f"x = {x}, type = {type(x).__name__}")

    # 多个 metadata
    y: Annotated[str, "min length 3", "max length 20"] = "alice"
    print(f"y = {y!r}")

    # 运行时类型不变
    print(f"y 实际类型: {type(y).__name__}")              # str


def demo_inspect_metadata() -> None:
    banner("2. 运行时读 metadata (3.11+ / typing_extensions)")

    # 直接用 Annotated, 不绕 type alias (future annotations 下 alias 也是字符串)
    def fake_func(
        uid: Annotated[int, "用户 ID"],
        name: Annotated[str, "用户名", "必填"] = "default",
    ):
        pass

    # 拆 Annotated (拿到当前层的所有参数)
    hints = get_type_hints(fake_func, include_extras=True)
    for k, v in hints.items():
        origin = get_origin(v) or v
        metadata = [a for a in get_args(v) if a is not origin]
        print(f"  {k}: 类型={origin}, metadata={metadata}")


def demo_reducer_pattern() -> None:
    banner("3. LangGraph reducer 模式")

    from typing_extensions import TypedDict
    from operator import add

    def add_messages(current: list, new) -> list:
        """reducer: LangGraph 在更新 state 时调这个合并"""
        if isinstance(new, list):
            return current + new
        return current + [new]

    class AgentState(TypedDict):
        # 普通字段: 新值覆盖旧值
        current_step: str

        # Annotated 字段: 用 reducer 合并
        messages: Annotated[list, add_messages]
        counter: Annotated[int, add]

    # 模拟 LangGraph 内部: node 返回 dict 部分字段
    state: AgentState = {
        "current_step": "init",
        "messages": ["hello"],
        "counter": 1,
    }

    # node A 返回
    update_a = {"messages": ["hi"], "counter": 2}
    state = {**state, **update_a}                       # 普通 merge, 但 messages 是引用
    state["messages"] = add_messages(state["messages"], update_a["messages"])
    state["counter"] = add(state["counter"], update_a["counter"])
    print(f"node A 后: messages={state['messages']}, counter={state['counter']}")


def demo_injected_tool_arg() -> None:
    banner("4. InjectedToolArg marker (项目 02_tools.py:279)")

    # InjectedToolArg 是 LangChain 的 marker 类, 无括号
    class InjectedToolArg:
        """标记这个参数运行时注入, LLM 不应该填"""
        pass

    # 用法: 装饰器 + Annotated
    def my_tool(
        query: str,
        uid: Annotated[str, InjectedToolArg],          # ⚠️ 无括号!
    ) -> str:
        return f"query={query}, uid={uid}"

    # 反面: 加括号会报错
    try:
        _ = my_tool.__annotations__                    # 模拟拆 metadata
        bad = Annotated[str, InjectedToolArg()]
    except TypeError as e:
        print(f"  ❌ InjectedToolArg() 带括号 -> TypeError: {e}")

    # 正常调用
    print(f"  ✅ my_tool('OPC', 'u_001') = {my_tool('OPC', 'u_001')}")


if __name__ == "__main__":
    setup()
    demo_basic_annotated()
    demo_inspect_metadata()
    demo_reducer_pattern()
    demo_injected_tool_arg()
    print("\n[L3-01] 全部 demo 跑完。")
