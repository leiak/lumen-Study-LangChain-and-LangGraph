"""
01_pydantic_advanced.py
========================
学完你能回答:
1. model_dump vs model_dump_json 区别?
2. arbitrary_types_allowed 干什么?
3. model_rebuild 什么时候调?
4. model_validate 接收什么?
5. Pydantic v1/v2 API 区别?
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_model_dump() -> None:
    banner("1. model_dump / model_dump_json")

    try:
        from pydantic import BaseModel
    except ImportError:
        print("  pydantic 未安装, 跳过")
        return

    class User(BaseModel):
        name: str
        age: int
        tags: list[str] = []

    u = User(name="alice", age=30, tags=["vip"])
    print(f"  原对象: {u}")
    print(f"  model_dump():      {u.model_dump()}")
    print(f"  model_dump_json(): {u.model_dump_json()}")


def demo_arbitrary_types() -> None:
    banner("2. arbitrary_types_allowed (项目 01_models.py:41)")

    from pydantic import BaseModel, ConfigDict, Field

    class CustomType:
        def __init__(self, value):
            self.value = value
        def __repr__(self):
            return f"CustomType({self.value!r})"

    # 默认: 自定义类做字段会报错
    try:
        class BadModel(BaseModel):
            inner: CustomType
    except Exception as e:
        print(f"  ❌ 默认不允许自定义类: {type(e).__name__}")

    # 正确: ConfigDict 打开
    class GoodModel(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        name: str
        inner: CustomType = Field(...)

    m = GoodModel(name="x", inner=CustomType(42))
    print(f"  m = {m}")
    print(f"  m.inner.value = {m.inner.value}")


def demo_model_validate() -> None:
    banner("3. model_validate 反序列化")

    from pydantic import BaseModel

    class User(BaseModel):
        name: str
        age: int

    # 从 dict
    u1 = User.model_validate({"name": "alice", "age": 30})
    print(f"  从 dict:    {u1}")

    # 从 JSON 字符串
    u2 = User.model_validate_json('{"name": "bob", "age": 25}')
    print(f"  从 JSON:    {u2}")


def demo_model_rebuild() -> None:
    banner("4. model_rebuild (前向引用, 文件顶部有 future annotations)")

    from pydantic import BaseModel

    # 本文件顶部已经 from __future__ import annotations
    # 所以这里的注解都是字符串, Pydantic 默认不解析
    class Person(BaseModel):
        name: str
        friend: "Person | None" = None              # 字符串形式, Pydantic 不解析

    # 必须 rebuild 才能校验
    Person.model_rebuild()

    p = Person(
        name="alice",
        friend={"name": "bob", "friend": None},    # dict 自动转 Person
    )
    print(f"  p = {p}")
    print(f"  p.friend.name = {p.friend.name}")
    print(f"  p.friend.friend = {p.friend.friend}")


def demo_project_serialization() -> None:
    banner("5. 项目序列化模式 (07_persistence.py:215)")

    from pydantic import BaseModel

    class Message(BaseModel):
        role: str
        content: str
        timestamp: str = "2026-09-06T14:30:00"

    # 模拟 messages 列表
    messages = [
        Message(role="user", content="你好"),
        Message(role="assistant", content="hi"),
    ]

    # 序列化为 list of dict
    dumped = [m.model_dump() for m in messages]
    print(f"  dumped (list of dict): {dumped}")

    # 存到 JSON
    import json
    blob = json.dumps(dumped, ensure_ascii=False)
    print(f"  blob (JSON string): {blob}")

    # 从 JSON 恢复
    loaded = [Message.model_validate(item) for item in json.loads(blob)]
    print(f"  loaded: {loaded}")


if __name__ == "__main__":
    setup()
    demo_model_dump()
    demo_arbitrary_types()
    demo_model_validate()
    demo_model_rebuild()
    demo_project_serialization()
    print("\n[L5-01] 全部 demo 跑完。")
