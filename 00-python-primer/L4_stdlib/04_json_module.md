# `json` 模块

## 是什么
标准库 JSON 编/解码。

```python
import json

s = json.dumps({"name": "alice", "age": 30}, ensure_ascii=False)
obj = json.loads(s)
```

## 为什么要用
- LangGraph state 序列化到 SQLite / JSON 文件
- 项目 `07_persistence.py:209` 用 `json.dumps(messages, default=str)` 序列化 Pydantic 对象
- LLM 工具输入是 JSON, 经常需要手动 parse

## 语法骨架

```python
import json

# 编码
s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
#                  ↑ 中文不转 \uXXXX        ↑ Pydantic 对象走 str()

# 解码
obj = json.loads(s)

# 文件 IO
with open("f.json", "w", encoding="utf-8") as f:
    json.dump(obj, f, ensure_ascii=False, indent=2)

with open("f.json", encoding="utf-8") as f:
    obj = json.load(f)
```

## 项目里的真实例子

```python
# 07_persistence.py:209
dumped = [m.model_dump() for m in serialized]
blob = json.dumps(dumped, ensure_ascii=False, default=str)
```

## 常见坑

1. **`ensure_ascii=False`**: 默认会把中文变成 `\uXXXX`, 调试麻烦
2. **`default=str`**: 让不可序列化对象 (datetime / Path / Pydantic) 走 str()
3. **datetime 不能直接 dump**: 需要 `default=str`
4. **Pydantic 用 `model_dump_json()`**: 不要用 json.dumps 手动序列化
5. **NaN / Infinity**: JSON 标准不允许, Python 默认允许, 别的语言可能崩

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 序列化 | Jackson `ObjectMapper` | `json.Marshal` | `json.dumps` |
| 反序列化 | `mapper.readValue` | `json.Unmarshal` | `json.loads` |
| 美化 | `.writerWithDefaultPrettyPrinter()` | `MarshalIndent` | `indent=2` |
