"""
09_getattr_reflection.py
=========================
学完你能回答:
1. getattr(o, 'x', default) 找不到时怎么办?
2. setattr / delattr / hasattr 各自干什么?
3. 项目里为什么大量 getattr(last, 'tool_calls', None)?
4. hasattr 有什么副作用?
5. 怎么动态调用方法?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_getattr() -> None:
    banner("1. getattr 基础")

    class User:
        name = "alice"
        age = 30

    u = User()
    print(f"getattr(u, 'name')         = {getattr(u, 'name')}")
    print(f"getattr(u, 'age', 0)       = {getattr(u, 'age', 0)}")
    print(f"getattr(u, 'score', 0)     = {getattr(u, 'score', 0)}")    # default

    try:
        getattr(u, "score")                 # 没 default, 找不到抛错
    except AttributeError as e:
        print(f"getattr(u, 'score') 无 default -> AttributeError: {e}")


def demo_hasattr_setattr() -> None:
    banner("2. hasattr / setattr / delattr")

    class Box:
        pass

    b = Box()
    print(f"hasattr(b, 'x')   = {hasattr(b, 'x')}")    # False

    setattr(b, "x", 42)                               # 动态加属性
    print(f"setattr 后 hasattr(b, 'x') = {hasattr(b, 'x')}, x = {b.x}")

    delattr(b, "x")
    print(f"delattr 后 hasattr(b, 'x') = {hasattr(b, 'x')}")


def demo_dynamic_method_call() -> None:
    banner("3. 动态方法调用")

    class Calculator:
        def add(self, a, b):
            return a + b

        def mul(self, a, b):
            return a * b

    c = Calculator()

    # 根据字符串调用方法
    for method_name in ["add", "mul"]:
        method = getattr(c, method_name)              # 取方法对象
        result = method(3, 4)                          # 调用
        print(f"  c.{method_name}(3, 4) = {result}")


def demo_langchain_message_pattern() -> None:
    banner("4. LangChain Message 字段反射 (项目 08_interrupt_hitl.py:88)")

    # 模拟 AIMessage / ToolMessage / HumanMessage
    class FakeAIMsg:
        content = "I'll search"
        tool_calls = [{"name": "search", "args": {"q": "OPC"}}]

    class FakeToolMsg:
        content = "search result"
        # 没有 tool_calls 属性

    msgs = [FakeAIMsg(), FakeToolMsg()]

    # 项目惯用法: 检查消息有没有 tool_calls 字段
    for m in msgs:
        tc = getattr(m, "tool_calls", None)
        if tc:
            print(f"  [AI] 工具调用: {tc[0]['name']}({tc[0]['args']})")
        else:
            print(f"  [其他] content = {m.content!r}")


if __name__ == "__main__":
    setup()
    demo_basic_getattr()
    demo_hasattr_setattr()
    demo_dynamic_method_call()
    demo_langchain_message_pattern()
    print("\n[L1-09] 全部 demo 跑完。")
