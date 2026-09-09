"""
03_factory_closure.py
======================
学完你能回答:
1. 工厂函数和普通函数区别?
2. 闭包怎么捕获外部变量?
3. for 循环里的闭包有什么坑?
4. nonlocal 什么时候用?
5. 工厂函数比 class 轻量在哪?
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_simple_closure() -> None:
    banner("1. 基本闭包: make_adder")

    def make_adder(n: int) -> Callable[[int], int]:
        def adder(x: int) -> int:
            return x + n                          # adder 闭包捕获 n
        return adder

    add5 = make_adder(5)
    add10 = make_adder(10)
    print(f"add5(3)  = {add5(3)}")                 # 8
    print(f"add10(3) = {add10(3)}")               # 13

    # 查看闭包变量 (高级调试用)
    print(f"add5.__closure__[0].cell_contents = {add5.__closure__[0].cell_contents}")


def demo_nonlocal_modify() -> None:
    banner("2. nonlocal 修改闭包变量")

    def make_counter(start: int = 0) -> Callable[[], int]:
        count = start
        def counter() -> int:
            nonlocal count                        # 声明要改外部变量
            count += 1
            return count
        return counter

    c = make_counter(10)
    print(f"c() = {c()}, c() = {c()}, c() = {c()}")    # 11, 12, 13


def demo_handoff_factory() -> None:
    banner("3. Handoff 工具工厂 (项目 14_handoff.py 模式)")

    def make_tool(name: str, default_msg: str) -> Callable[[str], str]:
        """模拟 LangChain @tool: name 不同, 但都接 reason 参数"""
        def tool(reason: str) -> str:
            return f"[{name}] (默认: {default_msg}) 原因: {reason}"
        tool.tool_name = name                     # 挂元数据
        return tool

    refund_tool = make_tool("transfer_to_refund", "转退款")
    tech_tool = make_tool("transfer_to_tech", "转技术")

    print(refund_tool("客户要全额退款"))
    print(tech_tool("API 报 500"))
    print(f"refund_tool.tool_name = {refund_tool.tool_name}")


def demo_loop_closure_trap() -> None:
    banner("4. 循环闭包陷阱 + 修复")

    # 反例: 全部捕获同一个 i (Python 3 之前)
    funcs_bad = []
    for i in range(3):
        funcs_bad.append(lambda: i)              # 所有 lambda 共享同一个 i
    print(f"反例: {[f() for f in funcs_bad]}")    # [2, 2, 2]

    # 修复 1: 用工厂参数包一层
    funcs_good = []
    for i in range(3):
        funcs_good.append(lambda i=i: i)        # 默认参数在定义时就绑定
    print(f"修复 1: {[f() for f in funcs_good]}")  # [0, 1, 2]

    # 修复 2 (Python 3+): 列表推导式自带作用域, 没问题
    funcs_py3 = [lambda j=j: j for j in range(3)]
    print(f"修复 2: {[f() for f in funcs_py3]}")   # [0, 1, 2]


if __name__ == "__main__":
    setup()
    demo_simple_closure()
    demo_nonlocal_modify()
    demo_handoff_factory()
    demo_loop_closure_trap()
    print("\n[L1-03] 全部 demo 跑完。")
