# TypedDict (PEP 589)

## 是什么
给 `dict` 加静态类型 — 键名固定, 值类型固定, 但运行时还是普通 dict。

```python
from typing import TypedDict

class User(TypedDict):
    name: str
    age: int

u: User = {"name": "alice", "age": 30}    # OK
u2: User = {"name": "bob"}                # mypy 报错: 缺 age
```

## 为什么要用
- **LangGraph 状态**强制用 TypedDict (`class State(TypedDict):`)
- LangChain 1.x `AgentState` 继承自 TypedDict
- 普通 dict 没类型, IDE 没法联想; TypedDict 让 IDE 给字段提示

## 语法骨架

```python
from typing import TypedDict, NotRequired

class State(TypedDict):
    messages: list[str]                 # 必有
    turn: int                           # 必有
    metadata: NotRequired[dict]         # 可选 (3.11+)
```

## 项目里的真实例子

```python
# 06_state_graph.py:41
class RouterState(TypedDict):
    query: str
    category: Literal["weather", "order", "general"]
    answer: str

# 03_agents.py:33 — 用 typing_extensions 兼容老 Python
from typing_extensions import TypedDict
```

## 常见坑

1. **运行时还是 dict**: 缺字段不报错, 只在 mypy 检查时发现
2. **`total=False`**: 所有字段都是 Optional, 访问可能 KeyError
3. **TypedDict 不能继承普通 class**: 但能继承另一个 TypedDict
4. **TypedDict 不是 dataclass**: 不会自动生成 `__init__` 等

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 类型化字典 | `Map<String, Object>` 无类型 | `struct` 字面量 | `TypedDict` |
| 字段固定 | 写 class | struct 字段 | TypedDict |
