"""
01_noqa.py
===========
学完你能回答:
1. # noqa 干什么?
2. F401 是什么错误码?
3. # noqa 和 # type: ignore 区别?
4. 怎么一次性抑制多个警告?
5. 项目里 noqa 用在哪?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_noqa_f401() -> None:
    banner("1. noqa: F401 (imported but unused)")

    # 故意 import 但不用
    import json  # noqa: F401

    print("  import json 但没用 (noqa: F401 抑制 F401 警告)")
    print("  → 即使没引用也不会报 'imported but unused'")


def demo_multiple_codes() -> None:
    banner("2. 多个错误码一起抑制")

    # F401: unused import
    # E501: line too long (演示用)
    long_line = "this is a very long string that might exceed typical line length limits in strict configs"  # noqa: E501
    print(f"  long_line = {long_line!r}")

    # 多个错误码用逗号
    import os  # noqa: F401, E402
    print("  import os 抑制了 F401 + E402 (E402 是 module level import not at top)")


def demo_re_export_pattern() -> None:
    banner("3. re-export 模式 (项目级用法)")

    # 实际项目里: 一个模块 import 然后 re-export
    # from package import important_function  # noqa: F401

    # 模拟: utils.py 把某个东西 re-export 给上层
    print("  模式: utils.py 顶部")
    print("    from _core import important_helper  # noqa: F401")
    print("    __all__ = ['important_helper']")
    print()
    print("  → noqa 防止 lint 说 'imported but unused'")
    print("  → 实际它通过 __all__ re-export 出去")


def demo_noqa_vs_type_ignore() -> None:
    banner("4. noqa vs type: ignore (两套独立系统)")

    print("  # noqa            给 flake8 / ruff 看 (lint)")
    print("  # type: ignore    给 mypy / pyright 看 (类型)")
    print()
    print("  两者可以同时用:")
    print("    from x import y  # noqa: F401  # type: ignore[import]")
    print()
    print("  错误码体系:")
    print("    noqa:    F401, E501, E402, W503 ...")
    print("    type:    [assignment], [arg-type], [return-value] ...")
    print()
    print("  工具支持:")
    print("    noqa:      flake8, ruff, pylint")
    print("    type ignore: mypy, pyright, pyre")


def demo_project_fallback() -> None:
    banner("5. 项目 fallback import 模式 (16_deep_agents.py)")

    # 项目里 deep_agents 可能没装, 用 try/except 兜底
    print("  模式:")
    print("    try:")
    print("        from deepagents import create_deep_agent  # noqa: F401")
    print("        DEEP_AGENTS_AVAILABLE = True")
    print("    except ImportError:")
    print("        DEEP_AGENTS_AVAILABLE = False")
    print()
    print("  → noqa: F401 是因为 try 块可能根本没用 (fallback 走了 except)")
    print("  → 保留 import 让 mypy 知道类型")


if __name__ == "__main__":
    setup()
    demo_noqa_f401()
    demo_multiple_codes()
    demo_re_export_pattern()
    demo_noqa_vs_type_ignore()
    demo_project_fallback()
    print("\n[L6-01] 全部 demo 跑完。")
