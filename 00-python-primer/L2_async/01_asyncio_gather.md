# `asyncio.gather` 并发

## 是什么
把多个协程**并发执行**, 等所有完成后返回结果列表 (按传入顺序)。

```python
import asyncio

async def work(i):
    await asyncio.sleep(0.1)
    return i * 2

results = await asyncio.gather(work(1), work(2), work(3))
# [2, 4, 6], 总耗时 ~0.1s (而不是 0.3s)
```

## 为什么要用
- LangChain 多工具并发调用 (`asyncio.gather` 一批 LLM / 工具调用)
- 项目 `02_tools.py:165` 并发抓多个 URL
- 比串行 await 快 N 倍

## 语法骨架

```python
results = await asyncio.gather(
    coro1, coro2, coro3,
    return_exceptions=True,            # 一个失败不影响其他
)
```

## 项目里的真实例子

```python
# 02_tools.py:165
results = await asyncio.gather(
    fetch_url.ainvoke({"url": "https://a.com"}),
    fetch_url.ainvoke({"url": "https://b.com"}),
)
# ~0.1s, 不是 ~0.2s

# 02_tools.py:423 — 解包生成器批量并发
return await asyncio.gather(*(one(tc) for tc in resp.tool_calls))
```

## 常见坑

1. **默认一个失败全部失败**: 用 `return_exceptions=True` 让单个失败不传染
2. **传入的是协程, 不是 await 后的值**: `gather(work(1))` 不是 `gather(await work(1))`
3. **gather vs TaskGroup (3.11+)**: TaskGroup 更现代, 失败处理更优雅
4. **不能并发无限多个**: 太多会耗 fd / 内存, 实际项目用 semaphore 限流

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 并发等待 | `CompletableFuture.allOf(...)` | `sync.WaitGroup` | `asyncio.gather` |
| 错误传播 | 一个失败 allOf 失败 | errgroup 一个失败 cancel | 默认传播, `return_exceptions` 关掉 |
