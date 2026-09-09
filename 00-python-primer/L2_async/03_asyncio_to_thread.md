# `asyncio.to_thread` 同步函数桥接到异步

## 是什么
`await asyncio.to_thread(func, *args)` 把同步函数扔到**线程池**跑, 不阻塞事件循环。

```python
import asyncio, time

def blocking_io():
    time.sleep(1)
    return "done"

async def main():
    return await asyncio.to_thread(blocking_io)
```

## 为什么要用
- LangChain 的同步工具 (`tool.invoke()`) 在 async agent 里要桥接
- 不阻塞事件循环, 并发性能不掉
- 项目 `02_tools.py:420` 用 `asyncio.to_thread(fn.invoke, tc["args"])`

## 语法骨架

```python
result = await asyncio.to_thread(sync_func, arg1, arg2, kw=val)
```

## 项目里的真实例子

```python
# 02_tools.py:420 — 异步 agent 调同步工具
async def run_tool_call(tc):
    # fn.invoke() 是同步的, 不能直接 await
    # 用 to_thread 扔到线程池跑
    result = await asyncio.to_thread(fn.invoke, tc["args"])
    return result

# 02_tools.py:423 — 批量并发
return await asyncio.gather(*(one(tc) for tc in resp.tool_calls))
```

## 常见坑

1. **`to_thread` 只对同步阻塞 IO 有用**: CPU 密集型请用 `ProcessPoolExecutor`
2. **线程池默认 32**: 用太多线程会爆, 必要时 `loop.set_default_executor`
3. **共享状态要锁**: 线程之间共享变量需要 `threading.Lock`
4. **`asyncio.to_thread` 是 3.9+ 才有的**: 之前用 `loop.run_in_executor(None, func, *args)`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 同步转异步 | `CompletableFuture.supplyAsync(...)` | 起 goroutine | `asyncio.to_thread` |
| 线程池 | `ExecutorService` | runtime G | `ThreadPoolExecutor` |
| 默认池大小 | 手动设 | GOMAXPROCS | `min(32, os.cpu_count()+4)` (3.8+) |
