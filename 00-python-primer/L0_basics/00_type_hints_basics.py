"""
00_type_hints_basics.py
=======================
学完你能回答:
1. Python 类型注解运行时会不会报错?
2. list[int] 和 List[int] 哪个新?
3. | 语法 (PEP 604) 什么时候引入?
4. 函数注解和变量注解语法有什么区别?
5. 为什么 LangGraph 强制用 TypedDict 而不是 class?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


# === demo 1: 变量 / 参数 / 返回值 三种位置的注解 ===
def demo_basic_annotations() -> None:
    banner("1. 变量 / 参数 / 返回值 注解")

    # 变量注解 (PEP 526)
    name: str = "MiniMax M3"
    temperature: float = 0.0
    is_streaming: bool = True

    # 函数参数 + 返回值
    def greet(user: str, times: int = 1) -> str:
        return f"hi {user} " * times

    msg: str = greet("OPC", 3)
    print(f"name={name!r}, temperature={temperature}, is_streaming={is_streaming}")
    print(f"greet() -> {msg.strip()!r}")
    print("提示: 注解写错 IDE 不会报错, 必须跑 mypy 才会发现")


# === demo 2: 容器类型参数化 (PEP 585, Python 3.9+) ===
def demo_container_types() -> None:
    banner("2. 容器类型参数化")

    # list[T] / dict[K, V] / tuple[A, B, ...]  (3.9+ 内置类型直接支持泛型)
    messages: list[str] = ["hello", "world"]
    scores: dict[str, float] = {"accuracy": 0.95, "latency_ms": 230.0}
    pair: tuple[str, int] = ("MiniMax-M3", 2026)

    # 嵌套
    nested: list[dict[str, list[int]]] = [{"ids": [1, 2, 3]}]

    print(f"messages = {messages}")
    print(f"scores = {scores}")
    print(f"pair = {pair}")
    print(f"nested = {nested}")


# === demo 3: 联合类型 T | U (PEP 604, Python 3.10+) ===
def demo_union_types() -> None:
    banner("3. 联合类型 (PEP 604)")

    # 现代写法: X | None / X | Y
    api_key: str | None = None
    llm_response: str | int | float = "ok"  # 三选一

    # 老写法 (typing.Optional, 3.10 之前只能用这个)
    from typing import Optional, Union  # noqa: F401
    # old_style: Optional[str] = None
    # old_union: Union[int, str] = 1

    print(f"api_key = {api_key}")
    print(f"llm_response = {llm_response!r} (类型 {type(llm_response).__name__})")


# === demo 4: Any 和 嵌套组合 ===
def demo_any_and_nested() -> None:
    banner("4. Any 与复杂嵌套")

    from typing import Any

    # 任何类型都能塞 (逃避 mypy 的便利)
    payload: dict[str, Any] = {
        "user_id": "u_001",
        "metadata": {"score": 0.9, "tags": ["vip", "test"]},
        "history": [1, 2, 3],
    }

    # 多层嵌套 (项目里真实存在)
    config: dict[str, dict[str, list[str]]] = {
        "model": {"name": ["MiniMax-M3"]},
        "tools": {"enabled": ["search", "calc"]},
    }

    print(f"payload = {payload}")
    print(f"config = {config}")


if __name__ == "__main__":
    setup()
    demo_basic_annotations()
    demo_container_types()
    demo_union_types()
    demo_any_and_nested()
    print("\n[L0-00] 全部 demo 跑完。")
