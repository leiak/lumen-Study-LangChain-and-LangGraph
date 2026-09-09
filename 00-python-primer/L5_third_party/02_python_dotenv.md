# `python-dotenv` 的 `load_dotenv`

## 是什么
从 `.env` 文件读 KEY=VALUE, 注入到 `os.environ`。

```
# .env
OPENAI_API_KEY=sk-abc123
LANGCHAIN_TRACING_V2=false
```

```python
from dotenv import load_dotenv
load_dotenv(".env", override=False)
# → os.getenv("OPENAI_API_KEY") 拿到 "sk-abc123"
```

## 为什么要用
- 敏感信息 (API key) 不进代码 / git
- 项目所有 `_common.py:15` 都用 `load_dotenv`
- 团队 / 不同环境用不同 .env

## 语法骨架

```python
from dotenv import load_dotenv, dotenv_values

# 1. 加载到 os.environ
load_dotenv(path=".env", override=False)
#               ↑ override=False: 已存在的环境变量优先

# 2. 不写 os.environ, 直接拿 dict
config = dotenv_values(".env")
print(config["OPENAI_API_KEY"])

# 3. 项目惯例
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / ".env.example", override=False)   # 兜底
```

## 项目里的真实例子

```python
# 所有 _common.py
from dotenv import load_dotenv
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / ".env.example", override=False)
```

## 常见坑

1. **`override=False`**: 默认 False, 已存在 env 优先 (生产环境覆盖 .env)
2. **找不到文件不报错**: load_dotenv 找不到 .env 静默
3. **不解析 shell 变量**: `$VAR` 不会被展开
4. **空行 / 注释 / 引号**: `#` 是注释, `KEY="value"` 引号会被剥
5. **多行值**: 用 `"""..."""` 包

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| .env 库 | spring-cloud-config / dotenv-java | `github.com/joho/godotenv` | `python-dotenv` |
| 加载 | 自动 (Spring Boot) | `godotenv.Load()` | `load_dotenv(...)` |
