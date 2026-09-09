# `sys.stdout.reconfigure(encoding="utf-8")` Windows GBK 修复

## 是什么
Python 3.7+ `sys.stdout` / `sys.stderr` 有 `reconfigure()` 方法, 运行时改编码。

```python
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

## 为什么要用
- Windows cmd 默认 GBK (cp936), LLM 输出带 emoji / 中文会 `UnicodeEncodeError`
- 项目所有 .py 文件顶部 `if hasattr(sys.stdout, "reconfigure"): ...` 都会调
- `errors="replace"` 让无法编码的字符用 `?` 代替, 不崩

## 语法骨架

```python
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
```

## 项目里的真实例子

```python
# 几乎每个项目文件顶部 (在 _common.setup() 里)
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

## 常见坑

1. **没 hasattr 检查**: `sys.stdout` 在某些环境 (Jupyter 早期) 没这方法
2. **`errors="strict"` (默认)** 会抛错, `replace` 更友好
3. **不影响文件 IO**: 只对终端 stdout
4. **Linux/macOS 默认 UTF-8, 不需要**: 但加也无害

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 控制台编码 | `-Dfile.encoding=UTF-8` | `os.Stdout` 默认 UTF-8 | `sys.stdout.reconfigure(encoding="utf-8")` |
| 错误处理 | `UnsupportedEncodingException` | 不编码 (byte) | `errors=` 参数 |
