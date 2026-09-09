# `os.getenv` / `os.environ` 环境变量

## 是什么
- `os.getenv(name, default=None)`: 取环境变量, 缺返回 default (不抛错)
- `os.environ[name]`: 取环境变量, 缺抛 KeyError (类似 dict)
- `os.environ.get(name, default)`: 同 getenv 但通过 environ dict

```python
api_key = os.getenv("OPENAI_API_KEY")              # None if missing
api_key = os.getenv("OPENAI_API_KEY", "")          # "" if missing
api_key = os.environ["OPENAI_API_KEY"]             # KeyError if missing
```

## 为什么要用
- LLM API key / LangSmith key 等敏感信息不进代码, 通过环境变量注入
- 项目所有 `_common.py:15` 用 `load_dotenv` 把 `.env` 文件注入到 `os.environ`
- 项目所有文件顶部都用 `os.getenv(...)` 取 key

## 语法骨架

```python
import os

# 读
v = os.getenv("KEY")                       # None 默认
v = os.getenv("KEY", "default")            # 自定义 default
v = os.environ.get("KEY")                  # 等价 getenv
v = os.environ["KEY"]                      # 必须存在

# 写 (测试用)
os.environ["KEY"] = "value"                # 当前进程有效

# 判断
if os.getenv("DEBUG") == "true":
    ...
```

## 项目里的真实例子

```python
# 11_langsmith_tracing.py:46
LANGSMITH_OK = bool(
    os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING") == "true"
)

# 所有 _common.py
load_dotenv(_ROOT / ".env", override=False)
# → load_dotenv 把 .env 内容写入 os.environ

# 02_tools.py:284 — 双重 fallback
api_key = os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY")
```

## 常见坑

1. **值永远是字符串**: `os.getenv("PORT")` 拿到 "8080", 不是 8080
2. **大小写敏感**: Windows 默认不敏感, Linux/macOS 敏感
3. **空字符串和 None**: `os.getenv("X") == ""` 和 `os.getenv("Y") is None` 不同
4. **`or` 兜底**: `os.getenv("X") or "default"` 把空串也当成缺失

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 取 env | `System.getenv("KEY")` | `os.Getenv("KEY")` | `os.getenv("KEY")` |
| 缺省 | null | "" | None (要显式 default) |
| 写 | 不允许 (只读) | `os.Setenv("KEY", "v")` | `os.environ["KEY"] = "v"` |
