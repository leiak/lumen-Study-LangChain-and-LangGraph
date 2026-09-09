"""
00_type_ignore.py
==================
学完你能回答:
1. # type: ignore 干什么?
2. 不带 [code] 和带 [code] 区别?
3. 常见错误码有哪些?
4. 项目里为什么用 type:ignore?
5. # noqa 和 # type: ignore 是同一个东西吗?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_ignore() -> None:
    banner("1. 基本 type:ignore")

    # 这些代码有类型问题, 但我们故意写
    x: int = "this is a string"                       # type: ignore[assignment]
    print(f"  x = {x!r}")

    # 不带错误码: 忽略该行所有类型检查
    y: list[int] = {"key": "value"}                  # type: ignore
    print(f"  y = {y!r}")


def demo_common_error_codes() -> None:
    banner("2. 常见错误码")

    # [assignment]: 赋值类型不对
    n: int = "hello"                                  # type: ignore[assignment]
    print(f"  [assignment]     n = {n!r}")

    # [arg-type]: 参数类型不对
    def takes_int(x: int) -> int:
        return x * 2
    takes_int("abc")                                  # type: ignore[arg-type]
    print("  [arg-type]        takes_int('abc')")

    # [return-value]: 返回值类型不对
    def returns_str() -> str:
        return 42                                     # type: ignore[return-value]
    print(f"  [return-value]    returns_str() = {returns_str()!r}")


def demo_third_party_untyped() -> None:
    banner("3. 第三方库类型不完整 (项目 01_models.py 模式)")

    # 模拟 LangChain 1.x 某些 API: 返回类型签名不准确
    class FakeLLM:
        def with_structured_output(self, schema, method="auto"):
            # 实际 invoke 才返回 schema, 但类型签名声明返回 Runnable
            class Runnable:
                def invoke(self, prompt):
                    return schema(query=prompt)
            return Runnable()

        def invoke(self, prompt):
            return "raw text"

    class MovieReview:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def __repr__(self):
            attrs = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
            return f"MovieReview({attrs})"

    llm = FakeLLM()

    # 项目 01_models.py:118 的写法
    review = llm.with_structured_output(             # type: ignore[assignment]
        MovieReview, method="function_calling"
    ).invoke("评一下深圳天气")

    print(f"  review = {review}")


def demo_when_to_use() -> None:
    banner("4. 什么时候该用 type:ignore")

    print("  ✅ 合适使用:")
    print("    1. 第三方库类型签名不完整 (LangChain 早期版本常见)")
    print("    2. 动态代码 (getattr / __annotations__ 反射)")
    print("    3. 框架强制类型不匹配 (Pydantic + Annotated)")
    print()
    print("  ❌ 不该用:")
    print("    1. 业务代码类型错 (应该改代码)")
    print("    2. 大量 ignore (说明类型设计有问题)")
    print("    3. 不指定错误码 (太粗暴)")


def demo_noqa_vs_type_ignore() -> None:
    banner("5. # noqa vs # type: ignore (两套系统)")

    print("  # noqa:        给 flake8 / ruff 看, 抑制风格警告")
    print("  # type: ignore: 给 mypy / pyright 看, 抑制类型错误")
    print()
    print("  可以同时使用:")
    example = '''
    from unused import something  # noqa: F401  # type: ignore[import]
    '''
    print(example)


if __name__ == "__main__":
    setup()
    demo_basic_ignore()
    demo_common_error_codes()
    demo_third_party_untyped()
    demo_when_to_use()
    demo_noqa_vs_type_ignore()
    print("\n[L6-00] 全部 demo 跑完。")
