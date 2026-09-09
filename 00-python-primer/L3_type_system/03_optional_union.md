# Optional / Union (PEP 484, PEP 604)

## 是什么
- `Optional[T]` ≡ `T | None`: 可空类型
- `Union[A, B, C]` ≡ `A | B | C`: 联合类型, 任一即可

```python
from typing import Optional, Union

name: Optional[str] = None              # str 或 None
value: Union[int, str] = 42             # int 或 str

# 现代写法 (3.10+)
name: str | None = None
value: int | str = 42
```

## 为什么要用
- LangChain 函数经常返回 `BaseMessage | ToolMessage | None`
- LLM 工具参数常可选 (`top_k: int | None = None`)
- 项目里大量用 `Embeddings | None`、`str | None`

## 语法骨架

```python
# 3.10+ 推荐: | 语法
x: int | None = None
y: int | str | float = 1.0

# 3.10 之前: typing.Optional / Union
from typing import Optional, Union
x: Optional[int] = None
y: Union[int, str] = 1
```

## 项目里的真实例子

```python
# 02_tools.py:293
def get_safe_embeddings() -> Embeddings | None: ...

# 01_models.py:111
review: MovieReview | None = None

# 02_tools.py:423
return await asyncio.gather(*(one(tc) for tc in resp.tool_calls))
# 工具返回值类型可能是 content | ToolException
```

## 常见坑

1. **`|` 不能接 type alias**: `list[int] | None` OK, 但 `T = list[int]; T | None` 语法错
2. **`Optional[X]` ≠ `X`**: 可空访问前必须判 None
3. **`Union[X, X]` 等于 X**: 重复没用
4. **运行时无检查**: 类型注解不管事

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 可空 | `@Nullable String` | `*string` | `str \| None` |
| 联合 | 无 (需要继承) | interface / any | `Union[A, B]` / `A \| B` |
