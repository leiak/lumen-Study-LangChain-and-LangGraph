# `re` 正则模块

## 是什么
正则表达式模块, 用于字符串模式匹配/替换/提取。

```python
import re

m = re.search(r"\d+", "abc 123 def")            # 找数字
print(m.group())                                # '123'

cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
```

## 为什么要用
- 项目 `01_models.py:24` 用 re 剥 `<think>` 标签
- 项目 `17_opc_product.py:257` 用 re 从用户消息提金额数字
- 日志脱敏 (PII 过滤) 也靠 re

## 语法骨架

```python
import re

# 1. 编译 (反复用时编译一次, 更快)
pattern = re.compile(r"\d+", flags=re.DOTALL)

# 2. 匹配
m = pattern.search("abc 123")                   # 找第一个
m = pattern.match("123 abc")                    # 从开头匹配
all_matches = pattern.findall("a1 b2 c3")       # ['1', '2', '3']

# 3. 替换
cleaned = pattern.sub("X", "a1 b2 c3")          # 'aX bX cX'

# 4. 常用 flag
# re.DOTALL (re.S): . 匹配换行
# re.IGNORECASE (re.I): 大小写不敏感
# re.MULTILINE (re.M): ^ $ 匹配每行
```

## 项目里的真实例子

```python
# 01_models.py:24 — 剥 <think> 标签
_THINK_RE = re.compile(
    r"<think>.*?</think>"
    r"|<thinking>.*?</thinking>"
    r"|<reflection>.*?</reflection>",
    flags=re.DOTALL,
)
cleaned = _THINK_RE.sub("", text).strip()

# 17_opc_product.py:257 — 提取金额
m = re.search(r"(\d+)\s*元", last_msg.content)
amount = float(m.group(1)) if m else 0.0
```

## 常见坑

1. **`.*?` 默认不跨行**: 用 `re.DOTALL` 让 `.` 匹配 `\n`
2. **`re.search` 返回 None**: 没匹配不是抛错, 先 `if m:`
3. **贪婪 vs 非贪婪**: `.*` 贪婪 (尽量多), `.*?` 非贪婪 (尽量少)
4. **反斜杠**: 写 `r"..."` raw 字符串, 不要 `"\\d+"`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 模式 | `Pattern.compile(rx)` | regexp.MustCompile | `re.compile(rx)` |
| 匹配 | `m.find()` / `m.matches()` | `re.FindAll` | `search` / `match` / `findall` |
| 替换 | `m.replaceAll(s)` | `re.ReplaceAllString` | `re.sub` |
