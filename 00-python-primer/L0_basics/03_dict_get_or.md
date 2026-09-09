# dict `.get()` 与 `or` 短路取值

## 是什么
两个"安全从 dict 取值"的惯用法:

```python
# 方式 1: dict.get(key, default)
v = d.get("missing_key", 0)        # 缺失返回 0, 不抛 KeyError

# 方式 2: or 短路
v = d.get("missing_key") or 0      # 缺失 OR 值本身 falsy 都返回 0
```

## 为什么要用
- `d["key"]` 在 key 不存在时 `KeyError`
- LLM 工具调用返回的 `args` dict 经常字段不全,必须用 `.get()`
- `or` 还能覆盖"值是空字符串/0/None"的情况

## 语法骨架

```python
d = {"a": 1}

# 缺失返回 None
v = d.get("a")                # 1
v = d.get("missing")          # None

# 缺失返回默认值
v = d.get("missing", 0)       # 0

# or 短路: 缺失 OR falsy 都用右边
v = d.get("a") or "default"   # 1
v = d.get("missing") or "d"   # "d"
v = d.get("a") or "d"         # "d" (因为 1 是 truthy 所以不用, 但 0 是 falsy 会用)
```

## 项目里的真实例子

```python
# 08_interrupt_hitl.py:136
amount = tc["args"].get("amount", 0)
# LLM 调工具时如果漏说 amount, 默认 0, 不崩

# 11_langsmith_tracing.py:46
LANGSMITH_OK = bool(
    os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING") == "true"
)

# 11_langsmith_tracing.py:62 — or 兜底
api_key = os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY")
```

## 常见坑

| 写法 | `d = {"x": 0}` 时返回 | 适用场景 |
|---|---|---|
| `d["x"]` | 0 | 必定有 key |
| `d.get("x")` | 0 | 必有, 但类型 Optional |
| `d.get("x", 5)` | 0 (有 key 不走 default) | 必有 + 缺失兜底 |
| `d.get("x") or 5` | **5** (因为 0 falsy) | 想要 "缺失 OR 假值" 兜底 |

注意 `or` 会把 `0` / `""` / `False` 都当成"缺",这有时候是 bug。

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 取值 | `map.get(k)` 返回 `V` (Go 多值) | `map[k]` 不存在返零值 | `d[k]` 抛错 / `d.get(k)` 返回 None |
| 默认值 | `map.getOrDefault(k, d)` | `v, ok := m[k]; if !ok { v = d }` | `d.get(k, d)` |
