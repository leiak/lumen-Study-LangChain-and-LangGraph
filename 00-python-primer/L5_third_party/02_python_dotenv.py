"""
02_python_dotenv.py
====================
学完你能回答:
1. .env 文件格式是什么?
2. load_dotenv vs dotenv_values 区别?
3. override=False 什么意思?
4. .env 文件找不到会报错吗?
5. 项目惯例怎么加载多个 .env?
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_load() -> None:
    banner("1. 基本 load_dotenv")

    try:
        from dotenv import load_dotenv
    except ImportError:
        print("  python-dotenv 未安装, 跳过")
        return

    # 临时建一个 .env 文件
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write(dedent("""
        # 这是注释
        APP_NAME=primer-demo
        DEBUG=true
        PORT=8080
        # 已经有引号会被剥
        GREETING="hello OPC"
        """))
        env_path = f.name

    # 清理可能的已有值
    for k in ["APP_NAME", "DEBUG", "PORT", "GREETING"]:
        os.environ.pop(k, None)

    # 加载
    load_dotenv(env_path, override=False)

    print(f"  APP_NAME  = {os.getenv('APP_NAME')!r}")
    print(f"  DEBUG     = {os.getenv('DEBUG')!r}")
    print(f"  PORT      = {os.getenv('PORT')!r}")          # 字符串 "8080"
    print(f"  GREETING  = {os.getenv('GREETING')!r}")      # 引号剥掉

    Path(env_path).unlink()
    for k in ["APP_NAME", "DEBUG", "PORT", "GREETING"]:
        os.environ.pop(k, None)


def demo_dotenv_values_dict() -> None:
    banner("2. dotenv_values 拿 dict")

    from dotenv import dotenv_values
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write("KEY1=v1\nKEY2=v2\n")
        env_path = f.name

    config = dotenv_values(env_path)
    print(f"  dict: {config}")
    print(f"  type = {type(config).__name__}")

    # 不影响 os.environ
    print(f"\n  os.getenv('KEY1') = {os.getenv('KEY1')!r} (没注入)")

    Path(env_path).unlink()


def demo_override_behavior() -> None:
    banner("3. override 参数行为")

    from dotenv import load_dotenv
    import tempfile

    # 模拟: shell 里已经有 ENV=from_shell
    os.environ["DEMO_OVERRIDE_KEY"] = "from_shell"

    # 写一个 .env 文件, 同一个 key 给了不同值
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write("DEMO_OVERRIDE_KEY=from_dotenv\n")
        env_path = f.name

    # override=False (默认): .env 不覆盖已有
    load_dotenv(env_path, override=False)
    print(f"  override=False: {os.getenv('DEMO_OVERRIDE_KEY')!r} (shell 优先)")

    # override=True: .env 覆盖
    load_dotenv(env_path, override=True)
    print(f"  override=True:  {os.getenv('DEMO_OVERRIDE_KEY')!r} (.env 优先)")

    Path(env_path).unlink()
    os.environ.pop("DEMO_OVERRIDE_KEY", None)


def demo_project_pattern() -> None:
    banner("4. 项目 _common.py 加载模式")

    from pathlib import Path

    # 项目惯例
    print("  所有 _common.py 的标准开头:")
    print()
    print("    from pathlib import Path")
    print("    from dotenv import load_dotenv")
    print()
    print("    _ROOT = Path(__file__).resolve().parent.parent")
    print("    load_dotenv(_ROOT / '.env', override=False)")
    print("    load_dotenv(_ROOT / '.env.example', override=False)")
    print()
    print("  解释:")
    print("    - .env: 真实的 key, 不进 git")
    print("    - .env.example: 模板, 进 git (值是占位符)")
    print("    - override=False: shell 里的环境变量优先 (生产)")
    print("    - 两个都 load: .env 没设的 key 从 .env.example 兜底")


def demo_missing_file_safe() -> None:
    banner("5. .env 不存在也不报错")

    from dotenv import load_dotenv

    print("  load_dotenv('/non/existent/.env'): ", end="")
    result = load_dotenv("/non/existent/.env", override=False)
    print(f"返回 {result}")                            # False, 不抛错
    print("  → 找不到 .env 不影响代码运行 (用环境变量默认值)")


if __name__ == "__main__":
    setup()
    demo_basic_load()
    demo_dotenv_values_dict()
    demo_override_behavior()
    demo_project_pattern()
    demo_missing_file_safe()
    print("\n[L5-02] 全部 demo 跑完。")
