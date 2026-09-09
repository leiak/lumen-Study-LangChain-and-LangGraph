"""
01_fstring_literals.py
=======================
学完你能回答:
1. f-string 为什么比 format() 快?
2. !r / !s / !a 三个转换符区别?
3. 怎么控制小数位 + 千分位?
4. f-string 里能写注释 / 反斜杠吗?
5. f-string 嵌套 f-string 怎么写?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_interpolation() -> None:
    banner("1. 基本嵌入")

    name = "MiniMax-M3"
    version = 3
    print(f"模型: {name}, 版本 {version}")             # 直接嵌变量
    print(f"算术: 1 + 2 = {1 + 2}")                    # 嵌表达式
    print(f"函数调用: {len(name)}")                    # 嵌函数调用
    print(f"三元: {'online' if version > 0 else 'off'}")  # 嵌三元


def demo_conversion_flags() -> None:
    banner("2. 转换符 !r !s !a")

    val = "OPC's product"
    print(f"str:    {val}")     # str(val)     = OPC's product
    print(f"repr:   {val!r}")   # repr(val)    = "OPC's product" (带引号)
    print(f"ascii:  {val!a}")   # ascii(val)   = "OPC's product" (转义非 ASCII)

    n = 255
    print(f"int:    {n}")       # 255
    print(f"hex:    {n:#x}")    # 0xff (格式说明)
    print(f"bin:    {n:b}")     # 11111111


def demo_format_spec() -> None:
    banner("3. 格式说明 (对齐 / 宽度 / 精度)")

    pi = 3.141592653589793
    big = 1234567890
    print(f"pi 保留 2 位:    {pi:.2f}")          # 3.14
    print(f"pi 宽度 10 右对齐: {pi:>10.2f}")     #       3.14
    print(f"千分位:          {big:,}")            # 1,234,567,890
    print(f"0 填充宽度 8:    {42:08d}")          # 00000042
    print(f"百分比:          {0.876:.1%}")       # 87.6%


def demo_escape_and_multiline() -> None:
    banner("4. 多行 + 嵌套 + 转义")

    user = "OPC"
    role = "admin"
    # 多行 f-string (PEP 701, 3.12 之前行尾要带反斜杠)
    msg = (
        f"用户 {user}\n"
        f"角色 {role}\n"
        f"权限 {'读写' if role == 'admin' else '只读'}"
    )
    print(msg)

    # 嵌套 f-string (Python 3.12+)
    rows = [("alice", 30), ("bob", 25)]
    for n, a in rows:
        print(f"{n:>6} -> {f'{a}岁':>6}")

    # 转义: {{ }} 输出字面 { }
    print(f"JSON 示例: {{\"key\": \"{user}\"}}")


if __name__ == "__main__":
    setup()
    demo_basic_interpolation()
    demo_conversion_flags()
    demo_format_spec()
    demo_escape_and_multiline()
    print("\n[L0-01] 全部 demo 跑完。")
