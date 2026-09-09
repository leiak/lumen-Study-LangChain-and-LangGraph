# `pathlib.Path` (PEP 428)

## 是什么
面向对象的文件系统路径, 取代 `os.path`。

```python
from pathlib import Path

p = Path(".") / "subdir" / "file.txt"
print(p.exists(), p.is_file(), p.suffix, p.stem)
```

## 为什么要用
- 跨平台: `/` 拼接在 Windows/Linux 都对
- 链式: `Path(a).parent / "b" / "c.txt"`
- 自带 IO: `.read_text()` / `.write_text()` / `.glob()`

## 语法骨架

```python
from pathlib import Path

# 构造
p = Path("foo/bar.txt")
p = Path("/abs/path")
p = Path(__file__).resolve().parent                # 当前文件父目录

# 拼接
new = p / "subdir" / "f.txt"

# 拆
print(p.name, p.stem, p.suffix, p.parent)
print(p.parts)                                      # ('foo', 'bar.txt')

# 判断
print(p.exists(), p.is_file(), p.is_dir())

# IO
p.write_text("content", encoding="utf-8")
content = p.read_text(encoding="utf-8")
size = p.stat().st_size

# 遍历
for f in Path(".").glob("*.py"):
    print(f)
```

## 项目里的真实例子

```python
# 01-langchain-basics/_common.py:15
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)

# 02-langgraph-orchestration/07_persistence.py:235
db_path = str(Path(tmp) / "state.db")
(tmp_dir / f"{d['title']}.txt").write_text(d["content"], encoding="utf-8")
for txt_file in tmp_dir.glob("*.txt"):
    print(f.name, f.stat().st_size)
```

## 常见坑

1. **Windows 反斜杠**: 用 `/` 拼接, Path 自动转
2. **`Path` 对象不能直接传给所有 os 函数**: 需要 `str(p)`
3. **`resolve()` 解析符号链接**: 可能返回真实路径而不是符号路径
4. **glob 不递归**: 用 `rglob` 递归
5. **不存在 `.parent` 不报错**: `.parent` 永远返回

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 路径类 | `java.nio.file.Path` | 无 (字符串) | `pathlib.Path` |
| 拼接 | `Paths.get(a, b)` | `filepath.Join(a, b)` | `Path(a) / b` |
| 父目录 | `path.getParent()` | `filepath.Dir(p)` | `p.parent` |
