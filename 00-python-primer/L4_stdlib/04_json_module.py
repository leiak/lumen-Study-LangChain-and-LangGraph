"""
04_json_module.py
==================
学完你能回答:
1. json.dumps 怎么保留中文?
2. datetime 怎么序列化?
3. Pydantic 对象怎么 JSON 化?
4. ensure_ascii=False 干什么?
5. json.dumps vs Pydantic model_dump_json?
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_dump_load() -> None:
    banner("1. 基本 dump / load")

    data = {"name": "alice", "age": 30, "tags": ["vip", "test"]}

    s = json.dumps(data)
    print(f"  dumps 默认: {s}")

    s_utf8 = json.dumps(data, ensure_ascii=False)
    print(f"  ensure_ascii=False: {s_utf8}")

    obj = json.loads(s_utf8)
    print(f"  loads 回来: {obj}")


def demo_chinese_encoding() -> None:
    banner("2. 中文 ensure_ascii 区别")

    text = {"city": "深圳", "weather": "晴"}

    s_default = json.dumps(text)
    print(f"  默认 (ensure_ascii=True):  {s_default}")

    s_utf8 = json.dumps(text, ensure_ascii=False)
    print(f"  ensure_ascii=False:        {s_utf8}")
    print("  ↑ 中文不变成 \\uXXXX")


def demo_default_str() -> None:
    banner("3. default=str 处理不可序列化对象")

    payload = {
        "name": "OPC",
        "now": datetime.now(),
        "today": date.today(),
        "path": Path("/tmp/test.txt"),
    }

    # 默认会报 TypeError
    try:
        json.dumps(payload)
    except TypeError as e:
        print(f"  默认会报错: {e}")

    # default=str 让不可序列化对象走 str()
    s = json.dumps(payload, default=str, ensure_ascii=False)
    print(f"  default=str 后: {s}")


def demo_pydantic_in_json() -> None:
    banner("4. Pydantic 模型序列化")

    try:
        from pydantic import BaseModel

        class User(BaseModel):
            name: str
            age: int = 0

        u = User(name="alice", age=30)

        # 方法 1: model_dump() 转 dict 再 json.dumps
        s1 = json.dumps(u.model_dump(), ensure_ascii=False)
        print(f"  model_dump + dumps: {s1}")

        # 方法 2: model_dump_json() 一行搞定 (推荐)
        s2 = u.model_dump_json()
        print(f"  model_dump_json:    {s2}")

        # 方法 3: json.dumps(pydantic) 错! 要先 model_dump
        try:
            json.dumps(u)
        except TypeError as e:
            print(f"  ❌ 直接 dumps 报错: {e}")

    except ImportError:
        print("  pydantic 未安装, 跳过")


def demo_indent_and_file() -> None:
    banner("5. 美化输出 + 文件 IO")

    data = {"users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]}

    s = json.dumps(data, indent=2, ensure_ascii=False)
    print("  indent=2 美化输出:")
    for line in s.splitlines():
        print(f"    {line}")


if __name__ == "__main__":
    setup()
    demo_basic_dump_load()
    demo_chinese_encoding()
    demo_default_str()
    demo_pydantic_in_json()
    demo_indent_and_file()
    print("\n[L4-04] 全部 demo 跑完。")
