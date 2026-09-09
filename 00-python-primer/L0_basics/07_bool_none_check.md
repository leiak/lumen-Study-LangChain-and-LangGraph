# 布尔 / None 判定 (`is None` / 真值判断)

## 是什么
Python 里"真假判定"有几条规则:

| 写法 | 含义 | 何时用 |
|---|---|---|
| `x is None` | x 是不是 None 对象 (单例) | 检查"没值" |
| `x is not None` | x 不是 None | 反向检查 |
| `x == None` | x 等于 None (会调 `__eq__`) | **不要用**, 子类可能重写 |
| `if x:` | x 是 truthy | 检查"非空非零" |
| `if not x:` | x 是 falsy | 检查"空/零/None" |

Falsy 值: `None`, `0`, `0.0`, `""`, `[]`, `{}`, `set()`, `False`, 自定义 `__bool__` 返回 False。

## 为什么要用
- LangChain 经常 `result.get("key")` 返回 `None`, 必须判 None
- `getattr(obj, attr, default)` 返回的可能是 None, 必须判断
- 项目里"是否触发"几乎都用 truthy 判断

## 项目里的真实例子

```python
# 08_interrupt_hitl.py:88
if getattr(last, "tool_calls", None):
    return "tools"

# 13_supervisor.py:398
a_tools = sum(1 for m in ra["messages"] if getattr(m, "tool_calls", None))

# 11_langsmith_tracing.py:46
LANGSMITH_OK = bool(
    os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING") == "true"
)
```

## 常见坑

1. **`== None` 不规范**: PEP 8 禁止用 `==` 比较 None, 用 `is`
2. **空 list/dict 是 falsy**: `if my_list:` 检查"非空"
3. **数字 0 是 falsy**: `if count:` 在 count=0 时不进
4. **`bool(None)` = False**, `bool(0)` = False, 但 `0 is False` = **False** (是不同对象)

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| null | `obj == null` | `p == nil` | `x is None` |
| 真值 | `if (obj != null && !obj.isEmpty())` | `if p != nil && len(p.Items) > 0` | `if x:` |
| 空集合判空 | `.isEmpty()` | `len() == 0` | `if not x:` |
