"""
07_bool_none_check.py
=====================
学完你能回答:
1. is None 和 == None 区别?
2. 哪些值是 falsy?
3. 0 is False 是 True 还是 False?
4. 怎么判断 list / dict 是空?
5. 字符串 "" 是 falsy 还是 truthy?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_is_vs_eq() -> None:
    banner("1. is None vs == None")

    x = None
    print(f"x is None     = {x is None}")         # True  (推荐)
    print(f"x is not None = {x is not None}")     # False

    # == None 不规范 (PEP 8), 因为可能被子类重写 __eq__
    print(f"x == None     = {x == None}")         # True (不推荐)


def demo_truthy_falsy() -> None:
    banner("2. 全部 falsy 值")

    falsy_values = [None, 0, 0.0, "", [], {}, set(), False, 0j]
    truthy_values = [1, -1, " ", [0], {"k": None}, True, 0.001]

    print("Falsy (bool()=False):")
    for v in falsy_values:
        print(f"  bool({v!r:>8}) = {bool(v)}")

    print("\nTruthy (bool()=True):")
    for v in truthy_values:
        print(f"  bool({v!r:>10}) = {bool(v)}")


def demo_zero_vs_false() -> None:
    banner("3. 0 / False / None 是不同对象")

    print(f"0 is False  = {0 is False}")      # False
    print(f"0 == False  = {0 == False}")      # True  (因为 bool 是 int 子类)
    print(f"0 is 0      = {0 is 0}")          # True  (小整数缓存)
    print(f"None is None = {None is None}")    # True  (单例)

    # 因此:
    # if value is False: 只接布尔字面量 False
    # if not value:     接所有 falsy (None / 0 / "" / [] / False ...)


def demo_langchain_pattern() -> None:
    banner("4. LangChain 里 getattr + truthy 检查")

    # 模拟 08_interrupt_hitl.py:88 — 检查 message 是否有 tool_calls
    class FakeMessage:
        def __init__(self, content, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

    msgs = [
        FakeMessage("hi"),                                     # 没 tool_calls
        FakeMessage("tool result", tool_calls=[]),              # 空 list (falsy)
        FakeMessage("I'll search", tool_calls=[{"name": "x"}]), # 有 tool_calls
    ]

    for m in msgs:
        # getattr(obj, "tool_calls", None): 取不到返回 None
        # 然后用 truthy 判断 "有内容且非空"
        if getattr(m, "tool_calls", None):
            print(f"  -> 有工具调用: {m.tool_calls[0]['name']}")
        else:
            print(f"  -> 普通消息: {m.content!r}")


if __name__ == "__main__":
    setup()
    demo_is_vs_eq()
    demo_truthy_falsy()
    demo_zero_vs_false()
    demo_langchain_pattern()
    print("\n[L0-07] 全部 demo 跑完。")
