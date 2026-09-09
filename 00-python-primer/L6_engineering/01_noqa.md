# `# noqa: F401` 抑制 linter 警告

## 是什么
`# noqa: 错误码` 给 flake8 / ruff / pylint 看, 抑制该行的风格警告。

```python
from langchain_community import something  # noqa: F401
#                                       ↑ F401: imported but unused
```

## 为什么要用
- 项目 `16_deep_agents.py:45` `from deepagents import create_deep_agent  # noqa: F401`
- 故意 import 不直接用 (比如 re-export, type checking)
- 比 `# noqa` (无错误码) 更精确

## 语法骨架

```python
# 常用错误码
import x  # noqa: F401       # imported but unused
import x  # noqa: E501       # line too long
import x  # noqa: F401,E501  # 多个
```

## 项目里的真实例子

```python
# 16_deep_agents.py:45
from deepagents import create_deep_agent  # noqa: F401
# L5 deep_agents 用了 fallback, 这个 import 可能根本不用
# 但保留让代码意图清晰
```

## 常见坑

1. **`noqa` 不影响 mypy**: 是 flake8/ruff 体系, 不是类型检查
2. **`# noqa` (无码) 太粗暴**: 推荐指定 `F401`
3. **`# noqa: F401, E501`**: 逗号分隔, 不用 `noqa: F401 no E501`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 抑制 lint | `@SuppressWarnings` | `//nolint:xxx` | `# noqa: F401` |
| 工具 | checkstyle / spotbugs | golangci-lint | flake8 / ruff |
