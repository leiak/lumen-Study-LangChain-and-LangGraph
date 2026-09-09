"""
05_exception_handling.py
========================
学完你能回答:
1. except Exception 和裸 except: 区别?
2. 怎么捕获多种异常?
3. raise from 是什么?
4. else / finally 什么时候走?
5. ToolException 在项目里干什么用?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_try_except() -> None:
    banner("1. try / except 基础")

    def parse_int(s: str) -> int:
        try:
            return int(s)
        except ValueError as e:
            print(f"  [解析失败] {s!r} 不是整数 ({e})")
            return -1

    print(f"parse_int('42')  = {parse_int('42')}")
    print(f"parse_int('abc') = {parse_int('abc')}")


def demo_multiple_and_order() -> None:
    banner("2. 多个 except + 顺序敏感")

    def classify(value):
        try:
            result = 100 / value
        except ZeroDivisionError as e:                # 必须先于父类
            print(f"  ZeroDivisionError: {e}")
            return "inf"
        except (TypeError, ValueError) as e:          # 多个一起
            print(f"  Type/Value: {e}")
            return "nan"
        except ArithmeticError as e:                  # 父类, 不可能走到了 (上面已经处理)
            print(f"  ArithmeticError: {e}")
            return "?"
        else:
            print(f"  成功: {result}")
            return "ok"

    print(f"classify(0)    = {classify(0)}")
    print(f"classify('x')  = {classify('x')}")
    print(f"classify(4)    = {classify(4)}")


def demo_raise_from_and_reraise() -> None:
    banner("3. raise from + 重新抛出")

    def load_config(path: str):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError as e:
            # raise X from Y: Y 是 cause, 串到 traceback
            raise RuntimeError(f"无法加载配置: {path}") from e

    try:
        load_config("/non/existent/path.env")
    except RuntimeError as e:
        print(f"外层异常: {e}")
        print(f"  cause: {type(e.__cause__).__name__}: {e.__cause__}")

    # 重新抛出 (不带参数) — 用一个外层 try 防止文件异常退出
    try:
        try:
            int("abc")
        except ValueError:
            print("  记录日志后重新抛出")
            raise                            # 不带参数 = re-raise
    except ValueError as e:
        print(f"  外层接住 (演示 re-raise): {e}")


def demo_finally_and_else() -> None:
    banner("4. finally / else")

    def fetch():
        try:
            print("  try: 打开资源")
            return "data"
        except Exception as e:
            print(f"  except: {e}")
            return None
        else:
            print("  else: 只在 try 成功时执行 (return 前)")
        finally:
            print("  finally: 始终执行 (return 前也走)")

    print(f"fetch() 返回: {fetch()}")


def demo_tool_exception_pattern() -> None:
    banner("5. ToolException 模式 (项目 02_tools.py)")

    # LangChain 工具的"业务异常"惯例
    class ToolException(Exception):
        """框架会自动把 ToolException 转成 ToolMessage 返回给 LLM"""
        pass

    def lookup_order(order_id: str) -> str:
        if not order_id.startswith("ORD"):
            raise ToolException(f"订单号必须以 ORD 开头, 收到 {order_id!r}")
        return f"订单 {order_id}: 已发货"

    # 模拟 LLM 调工具
    for oid in ["ORD-001", "BAD-002"]:
        try:
            print(f"  {lookup_order(oid)}")
        except ToolException as e:
            print(f"  [ToolException] -> 转 ToolMessage 回 LLM: {e}")


if __name__ == "__main__":
    setup()
    demo_basic_try_except()
    demo_multiple_and_order()
    demo_raise_from_and_reraise()
    demo_finally_and_else()
    demo_tool_exception_pattern()
    print("\n[L0-05] 全部 demo 跑完。")
