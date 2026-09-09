# 上下文管理器 `with` (Context Manager)

## 是什么
`with` 语句自动管理资源的**进入**和**退出**, 即便中间抛异常也会清理。

```python
with open("f.txt") as f:
    data = f.read()
# f 自动 close (无论是否抛异常)
```

## 为什么要用
- LangGraph 的 `SqliteSaver.from_conn_string()` / `InMemorySaver()` 都用 `with` 包
- `tempfile.TemporaryDirectory()` 也靠 `with`
- 比 `try/finally` 简洁, 不容易漏

## 语法骨架

```python
# 1. 内置 (文件 / 锁 / db connection)
with open(path) as f: ...

# 2. 多个 with
with open(a) as fa, open(b) as fb: ...

# 3. contextlib.contextmanager (装饰器写法)
from contextlib import contextmanager

@contextmanager
def my_ctx():
    setup()
    yield "value"                 # with ... as x 接到这个
    cleanup()

with my_ctx() as x:
    print(x)
```

## 项目里的真实例子

```python
# 07_persistence.py:239
with SqliteSaver.from_conn_string(db_path) as checkpointer:
    agent = create_agent(model, checkpointer=checkpointer, ...)
    ...

# 07_persistence.py:235
with tempfile.TemporaryDirectory() as tmp:
    db_path = str(Path(tmp) / "state.db")
    ...
```

## 常见坑

1. **资源必须实现 `__enter__` / `__exit__`** 才能用 with
2. **`__exit__` 返回 True 吞掉异常**, False / None 抛出
3. **`@contextmanager` 函数里 `yield` 只能一次**
4. **contextlib.suppress(...)**: 临时抑制特定异常

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 资源释放 | `try-with-resources` (实现 AutoCloseable) | `defer` | `with` (实现 `__enter__/__exit__`) |
| 简化写法 | Lombok `@Cleanup` | 隐式 defer | `@contextmanager` |
