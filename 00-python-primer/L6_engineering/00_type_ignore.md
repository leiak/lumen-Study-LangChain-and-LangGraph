# `# type: ignore[xxx]` 注释

## 是什么
在代码行后加 `# type: ignore[错误代码]`, 让 mypy/pyright 跳过该行的类型检查。

```python
# mypy 会因为类型不匹配报错
result = something_that_returns_wrong_type()  # type: ignore[assignment]
```

## 为什么要用
- 第三方库类型不完整, 框架返回值类型不对时
- 项目 `01_models.py:118` `review = llm.with_structured_output(...)  # type: ignore[assignment]`
- 比改一行错代码更轻量

## 语法骨架

```python
# 不指定错误码: 忽略所有
x = wrong()                            # type: ignore

# 指定错误码 (推荐)
x = wrong()                            # type: ignore[assignment]
y = None                               # type: ignore[assignment]
```

常用错误码:
- `[assignment]`: 赋值类型不匹配
- `[arg-type]`: 参数类型不匹配
- `[return-value]`: 返回值类型不匹配
- `[attr-defined]`: 属性不存在
- `[import]`: import 有问题

## 项目里的真实例子

```python
# 01_models.py:118
review = llm.with_structured_output(    # type: ignore[assignment]
    MovieReview, method="function_calling"
).invoke(prompt)
# with_structured_output 返回 Runnable, invoke 才返回 MovieReview
# 但 mypy 看不到, 加 type:ignore 跳过
```

## 常见坑

1. **`# type: ignore` 不是注释**: 严格按格式 `# type: ignore[code]`, 多一个空格不行
2. **指定错误码更好**: 不指定会让所有检查失效
3. **不要滥用**: 大量 ignore 说明类型系统设计有问题
4. **`# noqa` (flake8) 和 `# type: ignore` (mypy) 不同**: 两个独立系统

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 抑制类型 | `@SuppressWarnings("unchecked")` | 注释 `//nolint:xxx` (golangci-lint) | `# type: ignore[code]` |
| 编译器 | javac | go vet / build | mypy / pyright (外部工具) |
