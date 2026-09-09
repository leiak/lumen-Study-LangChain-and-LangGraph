# Pydantic v2 进阶 (`model_config` / `model_dump` / `model_rebuild` / `model_validate`)

## 是什么
Pydantic v2 的模型生命周期方法:

| 方法 | 用途 |
|---|---|
| `model_dump()` | 转 dict |
| `model_dump_json()` | 转 JSON 字符串 |
| `model_validate(obj)` | 从 dict / JSON 重建 |
| `model_json_schema()` | 生成 JSON Schema |
| `model_rebuild()` | 重建 (前向引用后调用) |
| `model_config` | 配置 (arbitrary_types_allowed / frozen ...) |

```python
from pydantic import BaseModel, ConfigDict

class MyModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str
    other: SomeCustomType = None                         # 自定义类不被 Pydantic 检查

m = MyModel(name="x", other=SomeCustomType())
d = m.model_dump()                                      # {'name': 'x', 'other': <obj>}
```

## 为什么要用
- 项目 `01_models.py:41` `model_config = {"arbitrary_types_allowed": True}` 让 Pydantic 接受 `BaseOutputParser`
- 项目 `07_persistence.py:215` 用 `model_dump()` 序列化 messages
- 序列化到磁盘 / 网络几乎必用

## 项目里的真实例子

```python
# 01_models.py:41
class StripThinkParser(BaseOutputParser):
    model_config = {"arbitrary_types_allowed": True}
    inner: BaseOutputParser = Field(...)

StripThinkParser.model_rebuild()                         # 前向引用重建

# 07_persistence.py:215
dumped = [m.model_dump() for m in serialized]
blob = json.dumps(dumped, ensure_ascii=False, default=str)
```

## 常见坑

1. **model_dump() 默认不会序列化为 JSON 字符串**: 用 `model_dump_json()` 才对
2. **`arbitrary_types_allowed=True`**: 必须设置才能让非 Pydantic 类型做字段
3. **`model_rebuild()`**: 用于前向引用 (`from __future__ import annotations` 后常用)
4. **`model_validate()` 接收 dict 或 JSON 字符串**: 不是 model_dump 的反向
5. **V1 vs V2**: `dict()` / `parse_obj()` / `schema()` 已废弃, 用 `model_*`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| dump | Jackson `writeValueAsString` | `json.Marshal` | `model_dump_json()` |
| load | `readValue` | `json.Unmarshal` | `model_validate(json)` |
| 配置 | `@JsonIgnore` | struct tag | `ConfigDict(...)` |
