"""
00_pydantic_basics.py
======================
学完你能回答:
1. Pydantic BaseModel 自动提供什么?
2. Field(ge=, le=, description=) 干什么?
3. 校验失败抛什么异常?
4. "30" 会自动转 int 30 吗?
5. 项目里 BaseModel 用在哪?
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_model() -> None:
    banner("1. 基本 BaseModel")

    try:
        from pydantic import BaseModel
    except ImportError:
        print("  pydantic 未安装, 跳过")
        return

    class User(BaseModel):
        name: str
        age: int = 0

    u = User(name="alice", age=30)
    print(f"  u = {u}")
    print(f"  u.name = {u.name}, u.age = {u.age}")

    # 类型自动转换
    u2 = User(name="bob", age="25")                   # "25" -> 25
    print(f"  u2 = {u2}, age type = {type(u2.age).__name__}")


def demo_field_constraints() -> None:
    banner("2. Field 约束 (项目 02_tools.py:69 模式)")

    from pydantic import BaseModel, Field

    class SearchInput(BaseModel):
        query: str = Field(description="搜索关键词")
        top_k: int = Field(default=3, ge=1, le=20)
        category: Literal["news", "blog"] = Field(default="news")

    # 合法
    u = SearchInput(query="OPC", top_k=5)
    print(f"  合法: {u}")

    # 越界
    try:
        SearchInput(query="OPC", top_k=100)
    except Exception as e:
        print(f"  top_k=100 越界 -> ValidationError")

    # 必填缺失
    try:
        SearchInput()                                 # 缺 query
    except Exception as e:
        print(f"  缺 query -> ValidationError")

    # description 给 LLM 看
    print(f"\n  JSON Schema (LLM 能看到):")
    import json
    print(json.dumps(SearchInput.model_json_schema(), indent=2, ensure_ascii=False)[:300])


def demo_field_description_for_llm() -> None:
    banner("3. Field description 给 LLM 看")

    from pydantic import BaseModel, Field

    class ToolArgs(BaseModel):
        """工具入参 — docstring 也会给 LLM 看"""
        city: str = Field(description="城市名, 如 '深圳', '北京'")
        unit: Literal["celsius", "fahrenheit"] = Field(
            default="celsius",
            description="温度单位",
        )
        days: int = Field(default=1, ge=1, le=7, description="预报天数, 1-7")

    schema = ToolArgs.model_json_schema()
    for field_name, field_info in schema["properties"].items():
        print(f"  {field_name}: {field_info}")


def demo_nested_model() -> None:
    banner("4. 嵌套 model")

    from pydantic import BaseModel

    class Address(BaseModel):
        city: str
        zip: str

    class Person(BaseModel):
        name: str
        address: Address                                   # 嵌套

    p = Person(
        name="alice",
        address={"city": "深圳", "zip": "518000"},        # dict 自动转 Address
    )
    print(f"  p = {p}")
    print(f"  p.address.city = {p.address.city}")


if __name__ == "__main__":
    setup()
    demo_basic_model()
    demo_field_constraints()
    demo_field_description_for_llm()
    demo_nested_model()
    print("\n[L5-00] 全部 demo 跑完。")
