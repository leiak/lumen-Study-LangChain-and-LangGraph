"""
03_optional_union.py
====================
学完你能回答:
1. Optional[T] 和 T | None 区别?
2. Union 和 | 语法等价吗?
3. 项目里为什么大量 T | None?
4. 访问 Optional 变量前必须做什么?
5. type alias 能用 | 吗?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_pipe_syntax() -> None:
    banner("1. PEP 604 的 | 语法 (3.10+)")

    if sys.version_info >= (3, 10):
        name: str | None = "alice"
        age: int | None = None
        value: int | str | float = 3.14
        print(f"  name={name!r}, age={age!r}, value={value!r}")
    else:
        print("  需要 Python 3.10+")


def demo_typing_optional() -> None:
    banner("2. typing.Optional / Union (老写法, 3.9 兼容)")

    from typing import Optional, Union

    name: Optional[str] = "alice"
    age: Optional[int] = None
    value: Union[int, str, float] = 3.14
    print(f"  name={name!r}, age={age!r}, value={value!r}")


def demo_safe_access() -> None:
    banner("3. Optional 访问安全")

    def get_user_name(user: dict | None) -> str:
        # 必须先判 None, 否则 mypy 抓
        if user is None:
            return "<anonymous>"
        return user.get("name", "<unknown>")

    print(f"  get_user_name(None)        = {get_user_name(None)}")
    print(f"  get_user_name({{}})          = {get_user_name({})}")
    print(f"  get_user_name({{'name':'OPC'}}) = {get_user_name({'name': 'OPC'})}")


def demo_langchain_pattern() -> None:
    banner("4. LangChain 真实模式 (项目 02_tools.py)")

    # LangChain 工具返回类型经常是 content 或 Exception
    def mock_tool_call(name: str) -> str | Exception:
        if name == "fail":
            return ValueError(f"tool {name} failed")
        return f"tool {name} success"

    for tool_name in ["search", "fail", "calc"]:
        result = mock_tool_call(tool_name)
        if isinstance(result, Exception):
            print(f"  {tool_name}: 异常 -> {type(result).__name__}: {result}")
        else:
            print(f"  {tool_name}: 结果 -> {result}")


def demo_type_alias_with_pipe() -> None:
    banner("5. type alias 用 | (3.10+)")

    # 现代写法
    UserId = str | None
    Score = int | float

    u: UserId = "u_001"
    s: Score = 95.5

    # 老写法
    from typing import Optional, Union
    UserIdOld = Optional[str]
    ScoreOld = Union[int, float]

    u2: UserIdOld = None
    s2: ScoreOld = 100

    print(f"  UserId={u!r}, Score={s}")
    print(f"  UserIdOld={u2!r}, ScoreOld={s2}")


if __name__ == "__main__":
    setup()
    demo_pipe_syntax()
    demo_typing_optional()
    demo_safe_access()
    demo_langchain_pattern()
    demo_type_alias_with_pipe()
    print("\n[L3-03] 全部 demo 跑完。")
