# 类型注解基础 (PEP 484 / 585)

## 是什么
Python 3.5+ 引入的类型提示 (Type Hints)。**运行时完全不检查**,只是给 IDE / mypy / pyright 看的。

```python
def add(a: int, b: int) -> int:
    return a + b
```

`a: int` 是注解,运行时 `a` 仍然是 `object`,不限制类型。

## 为什么要用
- IDE 自动补全更准 (`list[Message].append(...)` 能联想方法)
- mypy 能在 CI 阶段发现 `str + int` 这种 bug
- LangGraph 的 `StateGraph` 必须用 TypedDict,没有类型注解根本写不出来

## 语法骨架 (项目里实际用到的)

| 写法 | 含义 | 项目例子 |
|---|---|---|
| `int` `str` `bool` `float` | 基础类型 | `01_models.py:42` |
| `list[T]` `dict[K, V]` `tuple[A, B]` | 容器 (PEP 585, 3.9+) | `03_agents.py:55` `list[BaseMessage]` |
| `T \| None` `Optional[T]` | 可空 | `02_tools.py:293` `Embeddings \| None` |
| `Any` | 任意类型 | `11_langsmith_tracing.py:113` |
| `T \| U` `Union[T, U]` | 联合类型 (PEP 604, 3.10+) | `02_tools.py:423` |

## 项目里的真实例子

```python
# 03_agents.py:55
def stream_agent(agent, messages: list[BaseMessage]) -> list[BaseMessage]:
    ...

# 11_langsmith_tracing.py:113
def user_login(user_id: str, password: str) -> dict[str, Any]:
    ...
```

## 常见坑

1. **`list` 不带参数** 在 3.9+ 不合法,要写 `list[int]`,不是 `List[int]` (那是 typing 时代写法)
2. **运行时无检查**: 注解写错不会报错,IDE 不高亮就要靠 mypy
3. **前向引用**: `class Node: def make(self) -> 'Node': ...` —— 字符串化或用 `from __future__ import annotations`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 声明 | `int x;` 强制 | `var x int` 强制 | `x: int = 0` 仅提示 |
| 检查时机 | 编译时强制 | 编译时强制 | mypy / 运行时无 |
| 泛型 | `List<String>` | `[]string` | `list[str]` |
