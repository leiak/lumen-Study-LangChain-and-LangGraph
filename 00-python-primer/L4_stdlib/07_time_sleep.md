# `time.sleep` / `time` 模块

## 是什么
- `time.sleep(seconds)`: 阻塞当前线程 N 秒
- `time.time()`: Unix 时间戳 (float, 秒)
- `time.perf_counter()`: 高精度性能计时器 (单调递增, 适合测耗时)
- `time.strftime` / `time.strptime`: 时间格式化

## 为什么要用
- 项目 `04_middleware.py:64` 用 `time.sleep(2)` 模拟慢 IO 演示 timeout middleware
- 测耗时用 `perf_counter()` 不要 `time.time()` (受系统时间影响)
- 简单延迟 / 退避重试

## 语法骨架

```python
import time

time.sleep(2.0)                                     # 睡 2 秒
t0 = time.perf_counter()
# ... 干点啥 ...
elapsed = time.perf_counter() - t0                  # 高精度耗时

ts = time.time()                                    # 当前 Unix 时间戳
print(time.strftime("%Y-%m-%d", time.localtime(ts)))
```

## 项目里的真实例子

```python
# 04_middleware.py:64
@tool
def slow_lookup(query: str) -> str:
    import time
    time.sleep(2)                                   # 模拟慢 IO
    return f"results for {query}"

# 项目里大量用 perf_counter() 测耗时
t0 = time.perf_counter()
# ... invoke ...
elapsed = time.perf_counter() - t0
```

## 常见坑

1. **`time.sleep` 会阻塞整个线程**: 在 async 函数里用会阻塞事件循环 (用 `asyncio.sleep`)
2. **`time.time()` 受系统时间影响** (改时间会跳), `perf_counter()` 单调递增 (测时差用)
3. **Windows `time.sleep` 不精确**: 实际可能睡比请求时间长一点点
4. **time 模块和 datetime 区别**: `time` 是 Unix 时间戳 float, `datetime` 是对象

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| sleep | `Thread.sleep(ms)` | `time.Sleep(d)` | `time.sleep(s)` |
| 测耗时 | `System.nanoTime()` | `time.Since(start)` | `time.perf_counter()` |
| 时间戳 | `System.currentTimeMillis()` | `time.Now().Unix()` | `time.time()` |
