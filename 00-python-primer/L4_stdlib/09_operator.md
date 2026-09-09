# `operator` 模块 (常用: `operator.add`)

## 是什么
标准库提供"函数版"的操作符, 替代 lambda。

```python
from operator import add, mul, itemgetter, attrgetter

add(1, 2)                  # 3, 等价 lambda a, b: a + b
itemgetter("name")(d)      # d["name"]
attrgetter("name")(obj)    # obj.name
```

## 为什么要用
- LangGraph 用 `operator.add` 当 reducer (累加整数/列表)
- `itemgetter` 比 lambda 快, 也更声明式
- 项目 `03_agents.py:22` `from operator import add as add_int`

## 语法骨架

```python
from operator import add, mul, sub, itemgetter, attrgetter, methodcaller

# 数学
add(1, 2)                          # 3
mul(3, 4)                          # 12

# 取字段
get_name = itemgetter("name")      # 相当于 lambda d: d["name"]
get_name({"name": "alice"})         # "alice"

# 取属性
get_age = attrgetter("age")
get_age(obj)                        # obj.age

# 调方法
upper = methodcaller("upper")
upper("hello")                      # "HELLO"
```

## 项目里的真实例子

```python
# 03_agents.py:22
from operator import add as add_int

class CustomState(AgentState):
    turn_count: Annotated[int, add_int] = 0
    #               ↑ LangGraph 用这个 reducer 累加 turn_count
```

## 常见坑

1. **`operator.add` 对 list**: 是 list 拼接 `[1,2] + [3,4]`, 不是元素相加
2. **`itemgetter` 比 lambda 快**: 在 hot path 用
3. **`attrgetter` 可以多级**: `attrgetter("a.b.c")` 取嵌套属性

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 函数化操作符 | `BinaryOperator<Integer> add = (a, b) -> a + b` | `func(a, b int) int` | `from operator import add` |
| 字段取 | `map.get(k)` | `m[k]` | `itemgetter(k)` |
