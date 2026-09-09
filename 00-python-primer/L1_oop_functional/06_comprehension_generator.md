# 推导式 + 生成器表达式 (Comprehension + Generator)

## 是什么
**推导式**: 用一个表达式创建 list / dict / set。
**生成器表达式**: 类似推导式但用 `()`, 惰性求值, 不一次性建整个列表。

```python
# 列表推导式
squares = [x*x for x in range(5)]             # [0, 1, 4, 9, 16]

# 带条件
evens = [x for x in range(10) if x % 2 == 0]  # [0, 2, 4, 6, 8]

# 字典推导式
sq = {x: x*x for x in range(3)}              # {0: 0, 1: 1, 2: 4}

# 生成器表达式
gen = (x*x for x in range(5))
print(list(gen))                              # [0, 1, 4, 9, 16]
```

## 为什么要用
- 比 `for + append` 简洁 5 倍, 也更快
- 生成器表达式省内存 (10 亿条不会炸 RAM)
- 项目里大量用 `sum(1 for m in ... if ...)` / `[f(x) for x in xs]`

## 语法骨架

```python
[expr for x in iterable if condition]
{key_expr: val_expr for x in iterable if condition}
{expr for x in iterable}                      # set 推导
(expr for x in iterable if condition)         # generator
```

## 项目里的真实例子

```python
# 13_supervisor.py:398
a_tools = sum(1 for m in ra["messages"] if getattr(m, "tool_calls", None))

# 14_handoff.py:51
tool_name = f"transfer_to_{target_agent}"

# 02_tools.py:423
return await asyncio.gather(*(one(tc) for tc in resp.tool_calls))
#                                              ^^^^^^^^ 生成器表达式 + 解包
```

## 常见坑

1. **别写三层嵌套**: 立刻换 `for` 循环
2. **生成器只能迭代一次**: 第二次 `list(gen)` 得 `[]`
3. **推导式不能有副作用**: 想要 side effect 用 for 循环
4. **dict 推导 key 不能重复**: 后值覆盖前值
5. **walrus (`:=`) 在推导式里 (3.8+)**: `[(y, x) for x in xs if (y := f(x)) > 0]`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 列表 | Stream `xs.stream().map().collect()` | 手动循环 | `[f(x) for x in xs]` |
| 过滤 | `.filter()` | 手动 if | `if cond` 在末尾 |
| 惰性 | Stream 本身就是惰性 | channel | 生成器表达式 |
