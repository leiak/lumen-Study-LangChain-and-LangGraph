# `tempfile.TemporaryDirectory` 临时目录

## 是什么
自动清理的临时目录/文件 (退出 with 时删除)。

```python
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmp:
    db_path = Path(tmp) / "state.db"
    # ... 用 db_path ...
# with 退出, tmp 自动删
```

## 为什么要用
- 项目 `07_persistence.py:235` 给 SqliteSaver 造临时 db, 不污染文件系统
- 测试时造临时数据
- 避免手动 `shutil.rmtree`

## 语法骨架

```python
import tempfile

# 1. 临时目录 (with 退出自动删)
with tempfile.TemporaryDirectory() as tmp:
    ...

# 2. 临时目录 (不自动删, 手动 cleanup)
tmp = tempfile.mkdtemp()
# ... 用完 ...
shutil.rmtree(tmp)

# 3. 临时文件
with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
    f.write("content")
    path = f.name
```

## 项目里的真实例子

```python
# 07_persistence.py:235
with tempfile.TemporaryDirectory() as tmp:
    db_path = str(Path(tmp) / "state.db")
    with SqliteSaver.from_conn_string(db_path) as cp:
        agent = create_agent(..., checkpointer=cp)
        ...
```

## 常见坑

1. **`delete=False` 不自动删**: NamedTemporaryFile 默认 delete=True (with 退出删)
2. **跨平台路径**: Linux `/tmp/xxx`, Windows `C:\Users\...\Temp\xxx`
3. **路径是字符串**: `Path(tmp)` 才能用 Path 操作
4. **NamedTemporaryFile Windows 不支持 reopen**: Linux/macOS 可, Windows 不可

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 临时目录 | `Files.createTempDirectory` | `os.MkdirTemp` | `tempfile.TemporaryDirectory` |
| 自动清理 | try-with-resources | 手动 defer | `with` |
