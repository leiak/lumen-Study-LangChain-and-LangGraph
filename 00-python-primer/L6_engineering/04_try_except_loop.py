"""
04_try_except_loop.py
======================
学完你能回答:
1. 项目 demo 入口怎么容错跑多个 demo?
2. 为什么用 Exception 而不是 BaseException?
3. 错误信息截短防止刷屏?
4. 怎么汇总所有 demo 的失败?
5. 这个模式有什么风险?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_1_basic() -> None:
    """正常 demo"""
    print("  [demo_1] running...")
    print("  [demo_1] ✓ 成功")


def demo_2_fails() -> None:
    """故意失败"""
    print("  [demo_2] running...")
    raise ValueError("演示失败, 这里模拟 LLM 拒答")


def demo_3_also_fails() -> None:
    """另一个失败"""
    print("  [demo_3] running...")
    raise RuntimeError("API key 无效")


def demo_4_ok() -> None:
    """正常 demo"""
    print("  [demo_4] running...")
    print("  [demo_4] ✓ 成功")


# === 项目惯例的入口循环 ===
DEMOS = [
    ("demo_1_basic", demo_1_basic),
    ("demo_2_fails", demo_2_fails),
    ("demo_3_also_fails", demo_3_also_fails),
    ("demo_4_ok", demo_4_ok),
]


def demo_basic_pattern() -> None:
    banner("1. 基本 try/except 循环模式")

    for name, fn in DEMOS:
        try:
            fn()
        except Exception as e:
            msg = str(e)[:80]
            print(f"  [{name}] ✗ 跳过: {type(e).__name__}: {msg}")

    print("\n  → 所有 demo 都尝试了, 失败的优雅跳过")


def demo_aggregate_errors() -> None:
    banner("2. 累积错误, 最后汇报")

    errors: list[tuple[str, str]] = []

    for name, fn in DEMOS:
        try:
            fn()
        except Exception as e:
            errors.append((name, f"{type(e).__name__}: {str(e)[:80]}"))

    print(f"\n  汇总: {len(errors)}/{len(DEMOS)} demo 失败")
    for name, msg in errors:
        print(f"    [{name}] {msg}")


def demo_exception_vs_baseexception() -> None:
    banner("3. Exception vs BaseException")

    # Exception: 业务异常 (ValueError, RuntimeError)
    # BaseException: 包括 KeyboardInterrupt, SystemExit (用户想中断)

    print("  ❌ 反例: except BaseException 吞掉 KeyboardInterrupt")
    print("     用户按 Ctrl+C 也没反应 → 卡死")
    print()
    print("  ✅ 正确: except Exception 让 Ctrl+C 正常中断")
    print("     ValueError / RuntimeError / KeyError 都被捕获")
    print("     但 KeyboardInterrupt 透传给系统")
    print()

    # 演示
    def risky():
        raise ValueError("业务错误")

    try:
        risky()
    except Exception as e:
        print(f"  ✓ Exception 捕获: {type(e).__name__}: {e}")


def demo_message_truncation() -> None:
    banner("4. 错误信息截短 (项目惯例 [:120])")

    long_msg = "x" * 500                                # 模拟长错误

    truncated = long_msg[:120]
    print(f"  原长度: {len(long_msg)}")
    print(f"  截后:   {len(truncated)}")
    print(f"  内容: {truncated}...")
    print()
    print("  → 防止一个超长 stacktrace 刷屏")
    print("  → 真实 stacktrace 用 traceback.print_exc()")


def demo_logging_pattern() -> None:
    banner("5. 进阶: 用 logging 而不是 print")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    logger = logging.getLogger("primer")

    for name, fn in DEMOS:
        try:
            fn()
        except Exception as e:
            logger.exception(f"[{name}] 失败")           # 带 stacktrace
            # 或者用 logger.error(f"[{name}] 跳过: {e}") # 只错误信息


def run_project_style() -> None:
    """项目惯例的 __main__ 写法"""
    print("\n[__main__] 项目惯例入口:\n")
    for name, fn in DEMOS:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    setup()
    demo_basic_pattern()
    demo_aggregate_errors()
    demo_exception_vs_baseexception()
    demo_message_truncation()
    demo_logging_pattern()
    run_project_style()
    print("\n[L6-04] 全部 demo 跑完。")
