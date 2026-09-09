# `*args` / `**kwargs` 参数收集与透传

## 是什么
- `*args`: 把多余**位置参数**打包成 tuple
- `**kwargs`: 把多余**关键字参数**打包成 dict
- 调用时 `*` 和 `**` 是**解包**

```python
def f(*args, **kwargs):
    print(args, kwargs)

f(1, 2, 3, x=4, y=5)
# args = (1, 2, 3)
# kwargs = {'x': 4, 'y': 5}
```

## 为什么要用
- 项目里 `**kwargs` 透传给 LangChain / LangGraph 函数 (它们参数版本可能变)
- 解包用于 `asyncio.gather(*(coro for coro in ...))` 批量传协程
- 装饰器 wrapper 必须用 `*args, **kwargs` 透传

## 语法骨架

```python
def f(a, b, *args, default=0, **kwargs):
    ...

# 解包
f(*[1, 2, 3])                   # 1, 2, 3
f(**{"a": 1, "b": 2})           # a=1, b=2
```

## 项目里的真实例子

```python
# 所有 _common.py 的 get_llm(temperature, **kwargs)
def get_llm(temperature: float = 0.0, **kwargs) -> BaseChatModel:
    return init_chat_model(model=..., temperature=temperature, **kwargs)

# 02_tools.py:423 — 解包协程批量并发
results = await asyncio.gather(
    *(one(tc) for tc in resp.tool_calls)         # 解包
)

# 11_langsmith_tracing.py:46 — 解包 dict
LANGSMITH_OK = bool(
    os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING") == "true"
)
# (env 取值后通过 **kwargs 透传)
```

## 常见坑

1. **`def f(a, *args, b)`: b 必须用关键字传**, 因为 *args 吞了所有位置
2. **解包 dict 必须关键字名匹配**: `f(**{"a": 1})` → `f(a=1)`
3. **不要起名遮蔽**: 自己用 `*args` / `**kwargs`, 不要叫 `*argv` 之类 (约定)
4. **PEP 448 之后**: 函数定义里也能 `def f(a, b, *, c)` 表示 c 必须 keyword

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 可变参数 | `String... args` | `args ...string` | `*args` |
| 命名参数 | 编译时 map / builder | struct literal / options pattern | `**kwargs` |
| 解包 | 不支持 (重载) | `slice...` (Go 1.22+) | `f(*list, **dict)` |
