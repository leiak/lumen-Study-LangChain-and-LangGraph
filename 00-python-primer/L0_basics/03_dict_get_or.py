"""
03_dict_get_or.py
=================
学完你能回答:
1. d[k] 和 d.get(k) 区别?
2. d.get(k, default) 在 key 存在但值是 0 时会走 default 吗?
3. d.get(k) or default 和 d.get(k, default) 区别?
4. 为什么项目里大量用 .get() 而不是 []?
5. setdefault 和 get 区别?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_get_vs_subscript() -> None:
    banner("1. d[k] vs d.get(k)")

    d = {"name": "OPC", "age": 0}

    # 直接下标: key 不存在 -> KeyError
    try:
        _ = d["missing"]
    except KeyError as e:
        print(f"d['missing'] -> KeyError: {e}")

    # .get(): 不存在返回 None
    v = d.get("missing")
    print(f"d.get('missing') -> {v!r}")

    # .get(key, default)
    print(f"d.get('age', 99)   -> {d.get('age', 99)}")        # 0 (key 在)
    print(f"d.get('score', 0) -> {d.get('score', 0)}")        # 0 (走 default)


def demo_or_short_circuit() -> None:
    banner("2. or 短路: 区分 falsy 和缺失")

    d = {"count": 0, "name": "", "flag": False}

    # .get() + or: 0 / "" / False 都被当成"缺"
    print(f"d.get('count') or 100 = {d.get('count') or 100}")      # 100 (0 falsy)
    print(f"d.get('name')  or '匿名' = {d.get('name') or '匿名'}")  # '匿名' (空串 falsy)
    print(f"d.get('flag')  or True = {d.get('flag') or True}")     # True (False falsy)

    print("\n提示: 如果 'count=0' 是合法值, 不要用 or, 用 .get('count', 100)")


def demo_env_fallback_pattern() -> None:
    banner("3. 项目级 .env 兜底 (11_langsmith_tracing.py:62)")

    import os

    # 模拟: 项目同时支持 OPENAI / MINIMAX 两套 key
    # 实际项目中 os.getenv() 才是 dict-like 行为, 演示用 dict 模拟
    env = {"MINIMAX_API_KEY": "mm-abc123"}

    api_key = env.get("OPENAI_API_KEY") or env.get("MINIMAX_API_KEY")
    print(f"最终使用 key 前缀: {api_key[:5]}***")


def demo_setdefault() -> None:
    banner("4. setdefault: 不存在才设值")

    counts: dict[str, int] = {}

    # 累加器惯用法
    for kind in ["a", "b", "a", "c", "b", "a"]:
        counts[kind] = counts.get(kind, 0) + 1

    print(f"counts = {counts}")

    # 等价写法: setdefault
    counts2: dict[str, int] = {}
    for kind in ["a", "b", "a", "c", "b", "a"]:
        # setdefault: key 缺失才设置, 返回该 key 的值
        counts2[kind] = counts2.setdefault(kind, 0) + 1
    print(f"counts2 = {counts2}")


if __name__ == "__main__":
    setup()
    demo_get_vs_subscript()
    demo_or_short_circuit()
    demo_env_fallback_pattern()
    demo_setdefault()
    print("\n[L0-03] 全部 demo 跑完。")
