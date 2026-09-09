# Annotated (PEP 593)

## 是什么
给类型注解附加**元数据**, 不改类型本身。

```python
from typing import Annotated

# x: int 加了 "用户 ID" 的描述, 但 x 仍然是 int
x: Annotated[int, "用户 ID"] = 42
```

## 为什么要用
- LangGraph 用 `Annotated[T, reducer_function]` 声明**字段的合并规则**
- LangChain 用 `Annotated[T, InjectedToolArg]` 标记"运行时注入, 不让 LLM 看到"
- 第三方库 (FastAPI / Pydantic) 用它挂校验规则

## 语法骨架

```python
from typing import Annotated

# 1. 单个 metadata
x: Annotated[int, "desc"]

# 2. 多个 metadata (3.11+ 也支持更多)
y: Annotated[int, "min", "max"]

# 3. LangGraph reducer 模式
class State(TypedDict):
    messages: Annotated[list, add_messages]     # 列表用 add_messages 合并
    counter: Annotated[int, add]                # 整数用 add 累加

# 4. LangChain InjectedToolArg
@tool(args_schema=...)
def my_tool(uid: Annotated[str, InjectedToolArg()]) -> str:
    ...
```

## 项目里的真实例子

```python
# 08_interrupt_hitl.py:334
class State(TypedDict):
    messages: Annotated[list, add_messages]
    turn_count: Annotated[int, add_int]

# 03_agents.py:22 — 累加器 reducer
from operator import add as add_int
class CustomState(AgentState):
    turn_count: Annotated[int, add_int] = 0

# 02_tools.py:279 — 标记注入参数
from langchain_core.tools import InjectedToolArg
def my_tool(uid: Annotated[str, InjectedToolArg()]) -> str: ...
```

## 常见坑

1. **metadata 不影响运行时类型**: `Annotated[int, "x"]` 还是 int
2. **`Annotated` 用 typing_extensions**: 3.9+ 才有 typing.Annotated
3. **reducer 函数签名**: 接收 (current, new) 返回 merged
4. **`InjectedToolArg` 是 marker class**: **无括号**, 加括号会 `TypeError: takes no arguments`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 类型元数据 | Annotation (`@NotNull`) | struct tag (`json:"name"`) | `Annotated[T, metadata]` |
| 运行时读取 | 反射 | reflect | `get_type_hints(..., include_extras=True)` |
