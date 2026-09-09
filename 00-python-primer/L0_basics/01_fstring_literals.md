# f-string 与字符串字面量 (PEP 498)

## 是什么
f-string = `f"..."` 前面带 `f` 的字符串,内部用 `{}` 嵌入表达式,运行时求值。

```python
name = "OPC"
print(f"hi {name}")          # hi OPC
print(f"sum = {1 + 2}")      # sum = 3
print(f"{name!r}")           # 'OPC'  (repr)
print(f"{3.14159:.2f}")      # 3.14  (格式说明)
```

## 为什么要用
- 比 `"%s" % x` 和 `"{}".format(x)` 都快 (CPython 优化过)
- 表达式可以任意复杂 (调用函数、三元、算术)
- 项目里几乎所有 `print()` 都用它

## 语法骨架

```python
f"{value}"               # 直接嵌入
f"{value!r}"             # !r = repr()   !s = str()   !a = ascii()
f"{value:>10}"           # 右对齐 10 宽
f"{value:.2f}"           # 浮点保留 2 位
f"{value:,}"             # 千分位
f"{value:04d}"           # 0 填充宽度 4
```

## 项目里的真实例子

```python
# 07_persistence.py:267 — 多行 banner
bar = "=" * 60
print(f"\n{bar}\n  {title}\n{bar}")

# 14_handoff.py:51 — 字符串重复 + 嵌入
tool_name = f"transfer_to_{target_agent}"

# 02_tools.py:169 — 表达式 + 格式化
print(f"并发抓取 {len(results)} 个 URL, 耗时 {elapsed:.2f}s")
```

## 常见坑

1. **大括号要写两次**: `f"{{}}"` 输出 `{}`
2. **不能反斜杠**: `f"{'\n'}"` 不行,要么先赋值再嵌,要么用 `\\n`
3. **不能写注释**: `f"{x # 注释}"` 语法错
4. **引号嵌套**: `f"{'he said \"hi\"'}"` 里外引号要错开

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 模板 | `String.format("%s = %d", k, v)` | `fmt.Sprintf("%s = %d", k, v)` | `f"{k} = {v}"` |
| 嵌套引号 | 繁琐 | 繁琐 | 直接 |
| 格式说明 | `%.2f` | `%.2f` | `{:.2f}` |
