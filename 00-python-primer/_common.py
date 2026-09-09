"""
00-python-primer / _common.py
============================
每个 demo 文件都会复用这两个工具:

  banner(title)  -- 打印漂亮的分隔线和标题
  setup()        -- Windows 终端 UTF-8 修复 (和项目其它文件保持一致)

不在这里导入 LangChain / LangGraph —— 这个目录只讲 Python 本身。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 让任何子目录里的 demo .py 都能直接 `from _common import banner, setup`。
# _common.py 被首次 import 时把自身所在目录加到 sys.path 头部。
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))


def setup() -> None:
    """Windows 终端 UTF-8 修复。

    原因: Windows cmd 默认 GBK, print emoji / 中文 content 可能 UnicodeEncodeError。
    项目所有 .py 文件顶部都会调用这个函数,这里保持一致。
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def banner(title: str, char: str = "=") -> None:
    """打印一个 banner 分隔,模仿项目里 _common.banner 的风格 (简化版)。"""
    bar = char * 64
    print(f"\n{bar}\n  {title}\n{bar}")


# 模块级单例: 让 from _common import banner, setup 后,
# 多个 demo 文件共用同一份实现。
__all__ = ["banner", "setup"]


if __name__ == "__main__":
    # 自检: 跑这个文件能验证 banner 工作
    setup()
    banner("00-python-primer / _common.py 自检")
    print("看到这条说明 setup() 没崩, banner 工作正常。")
