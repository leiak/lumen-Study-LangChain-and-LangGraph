# tuple 多返回值 / `*` 解构

## 是什么
Python 函数可以一次返回多个值 (本质是返回 tuple),调用方用对应数量的变量接收。

```python
def divide(a, b):
    return a // b, a % b      # 返回 tuple

q, r = divide(10, 3)          # 解构: q=3, r=1
```

## 为什么要用
- 避免专门造一个 Result class
- 函数语义"返回多值"更直观
- 项目里 `_run` / `invoke` 经常返回 `(content, artifact)`

## 语法骨架

```python
# 基本解构
a, b = (1, 2)

# 带 * 收集剩余
first, *middle, last = [1, 2, 3, 4, 5]
# first=1, middle=[2,3,4], last=5

# 函数返回多值 (本质就是返回 tuple)
def foo() -> tuple[int, str]:
    return 42, "ok"

n, s = foo()
```

## 项目里的真实例子

```python
# 02_tools.py:257 — tool 返回 (content, artifact)
content, rows = query_database.invoke({"sql": "SELECT * FROM t"})
# content 给 LLM 看, rows 是大数据量原始结果

# 14_handoff.py:51 — 元组用于命名风格
tool_name = f"transfer_to_{target_agent}"
```

## 常见坑

1. **数量不匹配**: `a, b = (1, 2, 3)` 会 `ValueError: too many values`
2. **嵌套解构**: `a, (b, c) = 1, (2, 3)` 可以,但读起来绕
3. **单元素 tuple**: `(1,)` 必须带逗号,`(1)` 是 int
4. **`*` 只能用一个**: `a, *b, *c = ...` 语法错

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 多返回值 | 写 Result / Pair 类 | `func f() (int, string)` 原生 | `return a, b` 原生 |
| 接收 | `var r = f(); r.first()` | `n, s := f()` | `a, b = f()` |
