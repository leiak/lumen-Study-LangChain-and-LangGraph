# lambda 一行函数

## 是什么
匿名函数, 只能写一个表达式, **不能**包含语句。

```python
square = lambda x: x * x
print(square(5))                  # 25

# 等价 def
def square(x):
    return x * x
```

## 为什么要用
- 项目里 `add_conditional_edges(..., lambda s: s["category"], {...})` 用 lambda 当路由函数
- 配合 `sorted` / `map` / `filter` 一行搞定
- 简化小函数, 避免污染命名空间

## 语法骨架

```python
lambda 参数1, 参数2: 表达式
```

限制:
- 只能一个表达式 (没有 `if/else` 分支作为语句, 但有**三元**)
- 不能 `return` (表达式本身就是返回值)
- 不能 `pass` / `*` 多个语句

## 项目里的真实例子

```python
# 06_state_graph.py:495
graph.add_conditional_edges(
    "classify",
    lambda s: s["category"],                   # 路由函数
    {"weather": "weather", "general": "general"},
)
```

## 常见坑

1. **lambda 不能写 print**: `lambda: print(1)` 语法错
2. **lambda 不能赋值**: `lambda: x = 1` 语法错, 需要表达式
3. **三元当分支**: `lambda x: "big" if x > 10 else "small"` ✓
4. **多层 lambda 难读**: 嵌套超 1 层建议改 def

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 匿名函数 | `(a, b) -> a + b` (Lambda) | `func(a, b int) int { return a + b }` | `lambda a, b: a + b` |
| 多语句 | 不行 | 不行 | 不行 |
| 闭包 | 捕获 effectively final | 闭包 | 闭包 |
