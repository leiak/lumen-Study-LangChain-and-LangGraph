"""
02_private_naming.py
=====================
学完你能回答:
1. _name 和 __name 区别?
2. 单下划线外部能 import 吗?
3. 双下划线真的私有吗?
4. 项目里 _ROOT 是什么约定?
5. dunder 能自定义吗?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_single_underscore() -> None:
    banner("1. 单下划线: 软私有")

    # 模块级私有 (PEP 8 约定)
    _PLACEHOLDER = {"", "sk-", "your-key-here"}

    def _is_valid_key(value: str) -> bool:
        """下划线开头 = '别从外部 import 我'"""
        return value not in _PLACEHOLDER and len(value) > 5

    # 但其实能正常用
    print(f"  _PLACEHOLDER = {_PLACEHOLDER}")
    print(f"  _is_valid_key('sk-real123') = {_is_valid_key('sk-real123')}")
    print(f"  _is_valid_key('sk-')       = {_is_valid_key('sk-')}")
    print()
    print("  单下划线是约定, 不是强制")
    print("  from module import _PLACEHOLDER  # 能, 但别人会皱眉")


def demo_double_underscore() -> None:
    banner("2. 双下划线: 名字改编 (name mangling)")

    class BankAccount:
        def __init__(self, balance):
            # 双下划线: 实际存为 _BankAccount__balance
            self.__balance = balance

        def get_balance(self):
            return self.__balance                        # 内部能访问

    acc = BankAccount(100)
    print(f"  acc.get_balance()      = {acc.get_balance()}")

    # 外部直接访问报错
    try:
        _ = acc.__balance
    except AttributeError as e:
        print(f"  acc.__balance          -> AttributeError: {e}")

    # 但能通过改编后的名字访问 (不推荐)
    print(f"  acc._BankAccount__balance = {acc._BankAccount__balance}")
    print()
    print("  → 双下划线不是真私有, 只是防误用")
    print("  → 99% 场景用单下划线就够了")


def demo_module_private_constants() -> None:
    banner("3. 项目 _common.py 私有常量")

    # 模拟项目 _common.py 的私有配置
    _ROOT = Path(__file__).resolve().parent.parent
    _PLACEHOLDER_VALUES = {"sk-", "", "your-key-here"}
    _DEFAULT_TEMPERATURE = 0.0

    def _is_real_key(value):
        return value and value not in _PLACEHOLDER_VALUES

    print(f"  _ROOT = {_ROOT.name}")
    print(f"  _PLACEHOLDER_VALUES = {_PLACEHOLDER_VALUES}")
    print(f"  _is_real_key('sk-real') = {_is_real_key('sk-real')}")
    print()
    print("  约定:")
    print("    模块私有: _NAME / _function()")
    print("    公开 API: NAME / function()  (无下划线)")
    print("    from _common import banner  ← 公开")
    print("    _common._ROOT              ← 私有, 外部别碰")


def demo_dunder_warning() -> None:
    banner("4. dunder (__name__) 别乱定义")

    # 系统保留: __init__ / __str__ / __repr__ / __eq__ 等
    # 自己造 dunder 容易冲突

    class BadIdea:
        # 不要这样做! 系统可能依赖这些名字
        def __my_magic__(self):
            return "this is dangerous"

    obj = BadIdea()
    try:
        # 一些工具 (pickle / dataclasses) 会遍历 dunder, 冲突可能崩
        import pickle
        # pickle.dumps(obj)  # 可能崩
    except Exception:
        pass

    print("  ⚠️ 自定义 dunder 方法名 (前后双下划线) 是反模式")
    print("  → Python 保留这些名字给语言/标准库用")
    print("  → 自己命名用单下划线前缀 _my_method 即可")


def demo_class_private_vs_protected() -> None:
    banner("5. Java 对比: private / protected / public")

    print("  Java 三级:")
    print("    public    int x;     // 任何地方")
    print("    protected int y;     // 子类 + 同包")
    print("    private   int z;     // 只本类")
    print()
    print("  Python 一个约定: 下划线前缀")
    print("    x      // 公开")
    print("    _y     // 'protected' (子类能用, 外部别用)")
    print("    __z    // 'private' (名字改编, 防误用)")
    print()
    print("  Python 哲学: 'we are all consenting adults'")
    print("  → 不强制, 靠信任 + 文档")


if __name__ == "__main__":
    setup()
    demo_single_underscore()
    demo_double_underscore()
    demo_module_private_constants()
    demo_dunder_warning()
    demo_class_private_vs_protected()
    print("\n[L6-02] 全部 demo 跑完。")
