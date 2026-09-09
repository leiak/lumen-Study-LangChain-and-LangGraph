"""
00_os_environ.py
================
学完你能回答:
1. os.getenv 和 os.environ[] 区别?
2. 环境变量值永远是字符串吗?
3. 空字符串和 None 一样吗?
4. .env 文件怎么加载到环境变量?
5. 项目里为什么不用 os.environ[]?
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_getenv_basic() -> None:
    banner("1. os.getenv 基础")

    # 设置测试变量 (当前进程有效)
    os.environ["DEMO_PORT"] = "8080"
    os.environ["DEMO_DEBUG"] = ""                    # 空串 (有但空)

    # 读
    port = os.getenv("DEMO_PORT")
    port_default = os.getenv("DEMO_PORT_MISSING", "3000")
    debug = os.getenv("DEMO_DEBUG")
    debug_default = os.getenv("DEMO_DEBUG") or "false"

    print(f"  getenv('DEMO_PORT')           = {port!r}")
    print(f"  getenv('DEMO_PORT_MISSING', '3000') = {port_default!r}")
    print(f"  getenv('DEMO_DEBUG')          = {debug!r} (空字符串)")
    print(f"  getenv('DEMO_DEBUG') or 'false' = {debug_default!r}")


def demo_environ_subscript() -> None:
    banner("2. os.environ[] vs getenv")

    # 模拟存在的环境变量
    os.environ["REAL_VAR"] = "value"

    try:
        v = os.environ["REAL_VAR"]
        print(f"  environ['REAL_VAR'] = {v!r}")
    except KeyError as e:
        print(f"  KeyError: {e}")

    try:
        v = os.environ["MISSING_VAR"]
    except KeyError as e:
        print(f"  environ['MISSING_VAR'] -> KeyError: {e}")

    # environ.get 不会抛错
    print(f"  environ.get('MISSING_VAR')     = {os.environ.get('MISSING_VAR')!r}")
    print(f"  environ.get('MISSING_VAR', 'd') = {os.environ.get('MISSING_VAR', 'd')!r}")


def demo_type_conversion() -> None:
    banner("3. 环境变量永远是字符串, 需要手动转换")

    os.environ["DEMO_PORT"] = "8080"
    os.environ["DEMO_ENABLED"] = "true"

    port_str = os.getenv("DEMO_PORT")
    port_int = int(os.getenv("DEMO_PORT", "0"))
    enabled = os.getenv("DEMO_ENABLED", "false").lower() == "true"

    print(f"  port_str  = {port_str!r} (type: {type(port_str).__name__})")
    print(f"  port_int  = {port_int} (type: {type(port_int).__name__})")
    print(f"  enabled   = {enabled} (type: {type(enabled).__name__})")


def demo_dotenv_pattern() -> None:
    banner("4. 项目 .env 加载模式")

    # 模拟 .env 内容
    fake_env_content = """
OPENAI_API_KEY=sk-abc123
LANGCHAIN_TRACING_V2=false
LANGSMITH_PROJECT=primer-demo
"""

    from io import StringIO
    from dotenv import dotenv_values

    # 写到临时文件
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write(fake_env_content)
        env_path = f.name

    # dotenv_values 返回 dict (不写到 os.environ)
    config = dotenv_values(env_path)
    print(f"  dotenv_values() = {dict(config)}")

    # load_dotenv 写到 os.environ
    from dotenv import load_dotenv
    load_dotenv(env_path, override=False)
    print(f"  os.getenv('OPENAI_API_KEY')     = {(os.getenv('OPENAI_API_KEY') or '')[:5]}***")
    print(f"  os.getenv('LANGCHAIN_TRACING_V2') = {os.getenv('LANGCHAIN_TRACING_V2')}")

    # 清理
    Path(env_path).unlink()
    for k in ["OPENAI_API_KEY", "LANGCHAIN_TRACING_V2", "LANGSMITH_PROJECT", "DEMO_PORT", "DEMO_DEBUG", "DEMO_ENABLED", "REAL_VAR"]:
        os.environ.pop(k, None)


if __name__ == "__main__":
    setup()
    demo_getenv_basic()
    demo_environ_subscript()
    demo_type_conversion()
    demo_dotenv_pattern()
    print("\n[L4-00] 全部 demo 跑完。")
