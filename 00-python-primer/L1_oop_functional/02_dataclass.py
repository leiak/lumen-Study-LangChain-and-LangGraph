"""
02_dataclass.py
===============
学完你能回答:
1. @dataclass 自动生成哪些 dunder?
2. 默认值为什么不能直接写可变类型?
3. frozen=True 干什么?
4. dataclass 和 Pydantic BaseModel 区别?
5. field(default_factory=...) 什么时候必须用?
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_dataclass() -> None:
    banner("1. 基本 @dataclass")

    @dataclass
    class Point:
        x: float
        y: float
        label: str = "origin"           # 默认值

    p1 = Point(1.0, 2.0)
    p2 = Point(1.0, 2.0, "p2")
    print(f"p1 = {p1}")                  # 自动 __repr__
    print(f"p1 == p2  = {p1 == Point(1, 2)}")   # 自动 __eq__
    print(f"p1 == p2  = {p1 == p2}")     # label 不同, False


def demo_default_factory() -> None:
    banner("2. 可变默认值必须用 default_factory")

    # 反面教材: Python 3.11+ 在类定义时就会报错, 演示用字符串版避免崩
    try:
        @dataclass
        class BadUser:
            name: str
            tags: list[str] = []        # 3.11+ 直接报错

        u1 = BadUser("alice"); u1.tags.append("vip")
        u2 = BadUser("bob")
        print(f"BadUser: u1.tags = {u1.tags}, u2.tags = {u2.tags}")
    except ValueError as e:
        print(f"  反面教材 (3.11+): {e}")

    print("  老版本 (<3.11) 这样写会让所有实例共享同一 list → bug")
    print("  即使不报错也千万别这么写\n")

    # 正确写法: 用 default_factory
    @dataclass
    class GoodUser:
        name: str
        tags: list[str] = field(default_factory=list)

    u3 = GoodUser("alice"); u3.tags.append("vip")
    u4 = GoodUser("bob")
    print(f"GoodUser: u3.tags = {u3.tags}, u4.tags = {u4.tags}")


def demo_frozen_dataclass() -> None:
    banner("3. frozen=True 不可变 dataclass")

    @dataclass(frozen=True)
    class FrozenPoint:
        x: float
        y: float

    p = FrozenPoint(1.0, 2.0)
    print(f"p = {p}")
    try:
        p.x = 99.0
    except Exception as e:
        print(f"  试图修改 frozen 实例: {type(e).__name__}: {e}")


def demo_dataclass_with_methods() -> None:
    banner("4. dataclass 加自定义方法 (项目 12 模式)")

    @dataclass
    class EvalSummary:
        n_examples: int
        avg_scores: dict[str, float]
        pass_rate: float

        def __str__(self) -> str:
            lines = [
                f"  examples: {self.n_examples}",
                f"  pass_rate: {self.pass_rate:.1%}",
                f"  scores:",
            ]
            for k, v in self.avg_scores.items():
                lines.append(f"    {k}: {v:.3f}")
            return "\n".join(lines)

    summary = EvalSummary(
        n_examples=42,
        avg_scores={"accuracy": 0.92, "f1": 0.87},
        pass_rate=0.85,
    )
    print(summary)


if __name__ == "__main__":
    setup()
    demo_basic_dataclass()
    demo_default_factory()
    demo_frozen_dataclass()
    demo_dataclass_with_methods()
    print("\n[L1-02] 全部 demo 跑完。")
