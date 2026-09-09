"""
01_sys_stdout.py
=================
学完你能回答:
1. Windows 终端为什么 GBK 崩?
2. sys.stdout.reconfigure 干什么?
3. errors='replace' vs 'strict' 区别?
4. 为什么项目所有文件顶部都有这段?
5. Linux 上需要这个吗?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_default_encoding() -> None:
    banner("1. 默认 stdout 编码")

    print(f"  sys.stdout.encoding = {sys.stdout.encoding!r}")
    print(f"  sys.platform = {sys.platform!r}")

    if sys.platform == "win32":
        print("  Windows 默认可能是 'gbk' / 'cp936' → 中文可能崩")
    else:
        print("  Linux/macOS 默认 'utf-8' → 一般没问题")


def demo_reconfigure_basic() -> None:
    banner("2. reconfigure 改编码")

    if not hasattr(sys.stdout, "reconfigure"):
        print("  当前 stdout 不支持 reconfigure (Jupyter 等)")
        return

    old_enc = sys.stdout.encoding
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"  改前: {old_enc!r}")
    print(f"  改后: {sys.stdout.encoding!r}")

    # 打印 emoji + 中文, 不应该崩
    print("  测试 emoji + 中文: hello, OPC, MiniMax-M3")


def demo_errors_replace_vs_strict() -> None:
    banner("3. errors='replace' vs 'strict'")

    # 模拟一个不可编码字符
    test_str = "测试中文"                                # 现代都能编

    # replace 模式: 编码失败用 ? 代替
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="replace")
        try:
            print(f"  [ascii+replace] {test_str!r} -> ", end="")
            sys.stdout.write(test_str + "\n")
            sys.stdout.flush()
        except UnicodeEncodeError as e:
            print(f"  仍然报错: {e}")

        # strict 模式: 报错 (用 ASCII 字符串避免编码失败)
        sys.stdout.reconfigure(encoding="ascii", errors="strict")
        try:
            sys.stdout.write("ascii only\n")
            sys.stdout.flush()
        except UnicodeEncodeError as e:
            print(f"  [ascii+strict] expected UnicodeEncodeError: {e}")

        # 恢复 utf-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def demo_project_pattern() -> None:
    banner("4. 项目惯例: 顶部 setup() 调用")

    # 这是项目 _common.setup() 的核心代码
    print("  项目 _common.setup():")
    print("    if hasattr(sys.stdout, 'reconfigure'):")
    print("        sys.stdout.reconfigure(encoding='utf-8', errors='replace')")
    print()
    print("  为什么不直接 sys.stdout.reconfigure()?")
    print("    - Jupyter / IPython 早期版本没 reconfigure 方法")
    print("    - hasattr 守卫更兼容")
    print()
    print("  为什么每个 .py 都调一次?")
    print("    - 入口文件可能单独跑, 不依赖 _common")
    print("    - 双重保险 (兜底)")


if __name__ == "__main__":
    setup()                                          # 已经 reconfigure 过
    demo_default_encoding()
    demo_reconfigure_basic()
    demo_errors_replace_vs_strict()
    demo_project_pattern()
    print("\n[L4-01] 全部 demo 跑完。")
