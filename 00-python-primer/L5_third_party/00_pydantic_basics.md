# Pydantic `BaseModel` + `Field` (v2)

## 是什么
Pydantic 是 Python 最流行的**数据校验 / 序列化**库。`BaseModel` 子类自动获得:
- 类型校验 (传入字段类型不对就抛 `ValidationError`)
- 序列化 (`model_dump()` / `model_dump_json()`)
- JSON schema 生成
- IDE 提示

```python
from pydantic import BaseModel, Field

class User(BaseModel):
    name: str = Field(description="用户名")
    age: int = Field(default=0, ge=0, le=150)

u = User(name="alice", age=30)            # OK
u = User(name="alice", age=200)           # ValidationError: le=150
```

## 为什么要用
- LangChain 工具的参数 schema 必须是 Pydantic BaseModel
- LangChain 1.x `with_structured_output()` 内部用 Pydantic 校验
- 项目 `02_tools.py:69` 大量用 BaseModel + Field

## 语法骨架

```python
from pydantic import BaseModel, Field
from typing import Literal

class SearchInput(BaseModel):
    query: str = Field(description="搜索关键词")           # 描述给 LLM 看
    top_k: int = Field(default=3, ge=1, le=20)            # 范围约束
    category: Literal["news", "blog"] = "news"            # 枚举
```

## 项目里的真实例子

```python
# 02_tools.py:69
class SearchInput(BaseModel):
    query: str = Field(description="搜索关键词")
    top_k: int = Field(default=3, ge=1, le=20)
    # ge=1: 大于等于 1
    # le=20: 小于等于 20
    # 这些约束 LLM 也能看到, 帮它给合理参数
```

## 常见坑

1. **默认必须用 `Field(default=...)`**: `top_k: int = 3` 在 Pydantic 也 OK, 但 Field 更显式
2. **`Field(...)` 必填**: 没 default 就是必填
3. **校验失败的错误**: `ValidationError` (不是 `ValueError`)
4. **类型强制转换**: `"30"` 会自动转 `int 30` (Pydantic v2 默认 smart 模式)
5. **`BaseModel` 不可变 (默认)**: 字段赋值需要 `model_config = ConfigDict(frozen=False)`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 校验 | Bean Validation / Lombok | `validator` tag | Pydantic `Field(...)` |
| POJO | record class | struct | `BaseModel` |
| 序列化 | Jackson | json.Marshal | `model_dump_json()` |
