"""
04_string_methods.py
====================
学完你能回答:
1. str 是可变还是不可变?
2. strip / lower / startswith 各做什么?
3. find 和 index 区别?
4. split 不带参数按什么拆?
5. replace 返回新串还是改原串?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_strip_and_case() -> None:
    banner("1. strip + 大小写")

    raw = "  MiniMax-M3 \n"
    cleaned = raw.strip()
    print(f"strip 后: {cleaned!r}")

    # 大小写归一
    env_value = "True"
    print(f"'{env_value}'.lower() == 'true': {env_value.lower() == 'true'}")

    # casefold: 更激进的归一 (德语 ß -> ss)
    print(f"'Straße'.casefold() = {'Straße'.casefold()!r}")


def demo_startswith_endswith() -> None:
    banner("2. startswith / endswith")

    tool_names = ["transfer_to_refund", "transfer_to_tech", "search", "calc"]

    # 项目里识别 multi-agent handoff tool 的写法 (14_handoff.py:132)
    handoff_targets = [
        name.replace("transfer_to_", "")
        for name in tool_names
        if name.startswith("transfer_to_")
    ]
    print(f"handoff 目标: {handoff_targets}")
    print(f"非 handoff 工具: {[n for n in tool_names if not n.startswith('transfer_to_')]}")

    # endswith 检查文件后缀
    files = ["a.py", "b.md", "c.txt", "d.py"]
    py_files = [f for f in files if f.endswith(".py")]
    print(f".py 文件: {py_files}")


def demo_replace_split_join() -> None:
    banner("3. replace / split / join")

    # replace (3.9+ 还有 removeprefix/removesuffix)
    full = "transfer_to_refund"
    target = full.removeprefix("transfer_to_")
    print(f"removeprefix 后: {target}")

    # split 不带参: 按任意连续空白拆
    messy = "  hello   world\n\nfoo  bar  "
    tokens = messy.split()
    print(f"messy.split() = {tokens}")

    # join: 必须是 str 列表
    print(f"' + '.join(tokens) = {' + '.join(tokens)}")

    # split 带 sep 和 maxsplit
    log = "2026-09-06|INFO|user_login"
    date, level, msg = log.split("|", maxsplit=2)
    print(f"date={date}, level={level}, msg={msg}")


def demo_find_index() -> None:
    banner("4. find / index")

    s = "hello MiniMax-M3 world"
    print(f"s.find('MiniMax') = {s.find('MiniMax')}")          # 返回位置
    print(f"s.find('missing') = {s.find('missing')}")          # -1 不抛错

    # index: 找不到抛 ValueError
    try:
        s.index("missing")
    except ValueError as e:
        print(f"s.index('missing') -> ValueError: {e}")

    # in 操作符 (更 Pythonic)
    print(f"'MiniMax' in s = {'MiniMax' in s}")
    print(f"'missing' in s = {'missing' in s}")


if __name__ == "__main__":
    setup()
    demo_strip_and_case()
    demo_startswith_endswith()
    demo_replace_split_join()
    demo_find_index()
    print("\n[L0-04] 全部 demo 跑完。")
