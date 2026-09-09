"""
06_main_guard.py
================
学完你能回答:
1. __name__ 在直接运行 vs import 时分别是什么?
2. if __name__ == "__main__": 的作用?
3. 不写 main 守卫有什么后果?
4. python -m 跑模块 __name__ 是什么?
5. 如何把 .py 文件既当脚本又当模块?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def helper() -> str:
    """对外可复用的函数 (无副作用)。"""
    return "helper() 被调用了"


# 这些"副作用代码"放 main 守卫里, import 时不执行
def main() -> None:
    print("  main() 在 __main__ 守卫里被调用")
    print(f"  helper() -> {helper()}")


# 这个文件被直接运行时, __name__ == "__main__"
# 这个文件被 import 时,    __name__ == "06_main_guard"
if __name__ == "__main__":
    setup()
    banner("演示 if __name__ == '__main__': 的行为")

    print(f"当前 __name__ = {__name__!r}")

    # 打印模块属性
    print(f"模块 docstring: {__doc__.splitlines()[0] if __doc__ else None!r}")
    print(f"模块文件:       {__file__}")

    banner("调用 main()")
    main()

    banner("现在 import 自己试试")
    # 在 main 守卫内 import 自己, __name__ 已经是 "__main__", 不是 "06_main_guard"
    # 如果想看 import 视角, 需要另一个 .py 文件 import 本文件

    print("\n如果另一个文件 import 本文件:")
    print("  → __name__ 变成 '06_main_guard'")
    print("  → 不会执行 main()")
    print("  → 这就是 main 守卫的意义: 让 .py 既能当脚本也能当模块")

    print("\n[L0-06] demo 跑完。")
