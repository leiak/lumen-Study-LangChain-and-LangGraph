"""
10_dict_helpers.py
===================
学完你能回答:
1. dict.get(k, 0) 和 dict.setdefault(k, 0) 区别?
2. collections.Counter 怎么用?
3. dict 怎么按 value 排序?
4. 怎么反转 dict (key/value 互换)?
5. 项目里哪种写法最常见?
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_counter_three_ways() -> None:
    banner("1. 计数器: 3 种写法")

    items = ["apple", "banana", "apple", "cherry", "banana", "apple"]

    # 方法 1: get + += (项目惯例)
    counts1: dict[str, int] = {}
    for item in items:
        counts1[item] = counts1.get(item, 0) + 1
    print(f"  方法 1 (get):  {counts1}")

    # 方法 2: setdefault
    counts2: dict[str, int] = {}
    for item in items:
        counts2[item] = counts2.setdefault(item, 0) + 1
    print(f"  方法 2 (setdefault): {counts2}")

    # 方法 3: Counter (一行)
    counts3 = Counter(items)
    print(f"  方法 3 (Counter): {dict(counts3)}")

    # Counter 还能取 top N
    print(f"  most_common(2): {counts3.most_common(2)}")


def demo_defaultdict() -> None:
    banner("2. defaultdict: 缺 key 自动建默认值")

    from collections import defaultdict

    # 反面: 每次都要 setdefault
    groups1: dict[str, list[str]] = {}
    for word in ["apple", "ant", "banana", "berry", "cherry"]:
        key = word[0]
        groups1.setdefault(key, []).append(word)
    print(f"  setdefault: {dict(groups1)}")

    # 正面: defaultdict 自动建
    groups2: defaultdict[str, list[str]] = defaultdict(list)
    for word in ["apple", "ant", "banana", "berry", "cherry"]:
        groups2[word[0]].append(word)
    print(f"  defaultdict: {dict(groups2)}")


def demo_sort_dict() -> None:
    banner("3. dict 排序")

    scores = {"alice": 85, "bob": 92, "carol": 78}

    # 按 key 排 (字母序)
    by_key = sorted(scores.items())
    print(f"  按 key: {by_key}")

    # 按 value 升序
    by_value_asc = sorted(scores.items(), key=lambda kv: kv[1])
    print(f"  按 value 升序: {by_value_asc}")

    # 按 value 降序
    by_value_desc = sorted(scores.items(), key=lambda kv: -kv[1])
    print(f"  按 value 降序: {by_value_desc}")

    # 取 top 1
    top1 = max(scores.items(), key=lambda kv: kv[1])
    print(f"  最高分: {top1}")


def demo_invert_dict() -> None:
    banner("4. 反转 dict (key<->value)")

    old = {"a": 1, "b": 2, "c": 3}
    inv = {v: k for k, v in old.items()}
    print(f"  原: {old}")
    print(f"  反: {inv}")

    # 反面: 值有重复会丢
    bad = {"a": 1, "b": 1, "c": 2}
    inv_bad = {v: k for k, v in bad.items()}
    print(f"\n  值有重复: {bad}")
    print(f"  反转后 (会丢): {inv_bad}")            # 只有 'c': 2 保留


def demo_supervisor_pattern() -> None:
    banner("5. 项目 supervisor 模式 (13_supervisor.py:398)")

    # 模拟 LangChain messages
    class FakeMsg:
        def __init__(self, kind):
            self.kind = kind

    msgs = [FakeMsg("user"), FakeMsg("ai"), FakeMsg("tool"), FakeMsg("ai"), FakeMsg("user")]

    # 分类计数
    counts: dict[str, int] = {}
    for m in msgs:
        counts[m.kind] = counts.get(m.kind, 0) + 1

    print(f"  消息计数: {counts}")

    # 按数量降序输出
    for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {kind}: {n}")


if __name__ == "__main__":
    setup()
    demo_counter_three_ways()
    demo_defaultdict()
    demo_sort_dict()
    demo_invert_dict()
    demo_supervisor_pattern()
    print("\n[L4-10] 全部 demo 跑完。")
