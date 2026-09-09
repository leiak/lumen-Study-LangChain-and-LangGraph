# 字符串方法 (str.strip / lower / startswith / replace)

## 是什么
`str` 是不可变序列,内置几十个方法, 项目里最高频的几个:

| 方法 | 作用 | 项目例子 |
|---|---|---|
| `s.strip()` | 去掉首尾空白 | 解析 LLM 输出 |
| `s.lower() / upper()` | 大小写 | env key 归一 |
| `s.startswith(p) / endswith(p)` | 前后缀判断 | `transfer_to_*` 工具名 |
| `s.replace(old, new)` | 替换 | 去掉前缀 |
| `s.split(sep)` | 拆分 | 解析 csv / 空格分词 |
| `s.join(iter)` | 拼接 | `" ".join(words)` |
| `s.find(sub) / s.index(sub)` | 查找 (None vs 抛错) | 找关键字位置 |

## 为什么要用
字符串处理是 LangChain 解析 LLM 输出的核心 (剥 `<think>` 标签、解析 tool_call name 等)。
Python 字符串方法多到不需要 `re` 就能解决 80% 的活。

## 项目里的真实例子

```python
# 14_handoff.py:132
if tc["name"].startswith("transfer_to_"):
    target = tc["name"].replace("transfer_to_", "")

# 11_langsmith_tracing.py:46
LANGSMITH_OK = bool(
    os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING") == "true"
)
# "true" 字符串比较 (环境变量永远是字符串)

# 01_models.py:24 — re.sub 剥 <think> 标签
cleaned = _THINK_RE.sub("", text).strip()
```

## 常见坑

1. **strip() 默认去所有空白**: `s.strip()` 去掉 `\n \t \r `, 不只是空格
2. **不可变**: 所有方法都返回新字符串, 原字符串不变
3. **find 返回 -1, index 抛错**: `find` 更安全
4. **split 不带参按任意空白拆**: `"a  b\nc".split()` -> `["a", "b", "c"]`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 不可变 | `String` 不可变 | `string` 不可变 | `str` 不可变 |
| 大小写 | `s.toLowerCase()` | `strings.ToLower(s)` | `s.lower()` |
| 去前缀 | `s.replaceFirst(...)` 或 regex | `strings.TrimPrefix` | `s.removeprefix(p)` (3.9+) |
