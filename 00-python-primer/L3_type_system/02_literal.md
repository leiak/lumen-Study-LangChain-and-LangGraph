# Literal (PEP 586)

## 是什么
类型注解为**有限字面量集合**, 只允许这几个值。

```python
from typing import Literal

Mode = Literal["sync", "async"]
Status = Literal["pending", "running", "done"]

m: Mode = "sync"                       # OK
# m: Mode = "parallel"                 # mypy 报错
```

## 为什么要用
- LangGraph 用它做**路由决策**: `category: Literal["weather", "order"]`
- LLM 输出枚举化 (强制答非所问时按预设分类)
- 项目里 `06_state_graph.py:45` 状态机必备

## 语法骨架

```python
from typing import Literal

# 字符串字面量
Mode = Literal["sync", "async"]

# 数字字面量
Port = Literal[80, 443, 8080]

# 混合
EventType = Literal["click", "submit", 1, 2]
```

## 项目里的真实例子

```python
# 06_state_graph.py:45
class RouterState(TypedDict):
    category: Literal["weather", "order", "general"]
# add_conditional_edges 里就能精确映射
graph.add_conditional_edges(
    "classify",
    lambda s: s["category"],
    {"weather": "weather_node", "order": "order_node"},
)
```

## 常见坑

1. **运行时还是 str**: `m = "wrong"` 不会报错, mypy 才查
2. **拼写错不会被发现**: `m: Literal["async"] = "asnyc"` 运行时 OK, 但 mypy 抓
3. **`Literal` 不限制函数参数值**: 只是类型注解
4. **PEP 675 之后的 LiteralString**: 还有 `LiteralString` 限制字符串来源

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 枚举 | `enum` | `const ( ... )` / 自定义类型 | `Literal[...]` (类型层) / `enum.Enum` (运行时) |
| 有限字面量 | 无 (enum 代替) | 无原生 | `Literal[...]` |
