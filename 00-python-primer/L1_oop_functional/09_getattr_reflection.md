# `getattr` 反射

## 是什么
`getattr(obj, name, default)` 运行时按字符串名取属性, 找不到返回 default (不抛 AttributeError)。

```python
class User:
    name = "alice"

getattr(User(), "name")             # "alice"
getattr(User(), "age", 0)          # 0 (找不到走 default)
```

兄弟函数:
- `setattr(obj, name, value)` — 设属性
- `delattr(obj, name)` — 删属性
- `hasattr(obj, name)` — 是否有属性

## 为什么要用
- LangChain 的消息对象字段不固定 (AIMessage 有 `tool_calls`, ToolMessage 没有), 必须用 getattr + default
- 写通用代码 (框架) 时无法提前知道属性名
- 项目里 `getattr(last, "tool_calls", None)` 出现 10+ 次

## 项目里的真实例子

```python
# 08_interrupt_hitl.py:88
if getattr(last, "tool_calls", None):
    return "tools"

# 13_supervisor.py:398
a_tools = sum(1 for m in ra["messages"] if getattr(m, "tool_calls", None))
```

## 常见坑

1. **name 是字符串**: 不能传变量表达式, 必须先拼好字符串
2. **default 任意类型**: 默认 None / 0 / 空字符串都行
3. **找不到 + 没 default → AttributeError**
4. **`hasattr` 会吞所有异常**, 慎用 (可能掩盖逻辑错误)

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 取属性 | `obj.getClass().getField(name)` | reflect | `getattr(obj, name, default)` |
| 运行时检查 | `instanceof` / reflection | type assertion / type switch | `isinstance` / `hasattr` |
| 动态调用 | `method.invoke(obj)` | reflect.Value.Call | `getattr(obj, name)()` |
