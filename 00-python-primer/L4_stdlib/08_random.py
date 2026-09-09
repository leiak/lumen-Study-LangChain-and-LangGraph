"""
08_random.py
=============
学完你能回答:
1. random.random() 范围?
2. randint 和 randrange 区别?
3. random.shuffle 返回什么?
4. 项目里 random.random() < 0.1 干什么?
5. random 能用于安全场景吗?
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_random() -> None:
    banner("1. 基本 random 函数")

    print(f"  random()         = {random.random():.4f} (范围 [0, 1))")
    print(f"  uniform(1, 10)   = {random.uniform(1, 10):.4f}")
    print(f"  randint(1, 100)  = {random.randint(1, 100)} (含两端)")
    print(f"  randrange(1, 100)= {random.randrange(1, 100)} (不含右端)")

    # choice
    fruits = ["apple", "banana", "cherry"]
    print(f"  choice(fruits)   = {random.choice(fruits)!r}")

    # sample (不重复)
    nums = list(range(20))
    print(f"  sample(nums, 5)  = {random.sample(nums, 5)}")


def demo_shuffle() -> None:
    banner("2. shuffle (原地洗牌)")

    items = [1, 2, 3, 4, 5]
    print(f"  洗牌前: {items}")
    ret = random.shuffle(items)                       # 原地改, 返回 None
    print(f"  洗牌后: {items}")
    print(f"  返回值: {ret}")                            # None
    print("  ⚠️ 别写 ret = random.shuffle(items) 然后用 ret, 会拿到 None")


def demo_seed() -> None:
    banner("3. seed 让随机可复现")

    random.seed(42)
    print(f"  seed(42) 第一次: {random.random():.4f}, {random.randint(1, 100)}")

    random.seed(42)                                   # 同样的种子
    print(f"  seed(42) 第二次: {random.random():.4f}, {random.randint(1, 100)}")
    print("  ↑ 完全相同 → 种子让随机可复现, 测试必备")


def demo_sampling_pattern() -> None:
    banner("4. 项目级 10% 采样上报 (11_langsmith_tracing.py:388)")

    random.seed(0)
    sent = 0
    total = 1000

    # 模拟: 1000 次调用, 10% 概率真正上报 (避免 LangSmith 配额爆)
    for i in range(total):
        if random.random() < 0.1:
            sent += 1

    print(f"  总调用: {total}")
    print(f"  实际上报: {sent}")
    print(f"  实际概率: {sent / total:.3f} (期望 0.100)")


def demo_security_warning() -> None:
    banner("5. random 不用于安全场景")

    print("  random 是 Mersenne Twister 算法, 不抗预测")
    print("  密码 / token / session id 必须用 secrets 模块:")
    print()

    import secrets
    print(f"  secrets.token_hex(16)  = {secrets.token_hex(16)}")
    print(f"  secrets.token_urlsafe  = {secrets.token_urlsafe(16)}")
    print(f"  secrets.randbelow(100) = {secrets.randbelow(100)}")


if __name__ == "__main__":
    setup()
    demo_basic_random()
    demo_shuffle()
    demo_seed()
    demo_sampling_pattern()
    demo_security_warning()
    print("\n[L4-08] 全部 demo 跑完。")
