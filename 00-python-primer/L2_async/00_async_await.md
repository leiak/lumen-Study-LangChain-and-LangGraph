# `async def` / `await` (PEP 492, 3.5+)

## 是什么
- `async def` 定义**协程函数**, 调用返回一个**协程对象** (coroutine)
- `await` 挂起当前协程, 等待另一个协程 / Future / Task 完成
- 协程运行在**同一个线程**, 通过事件循环调度, 实现非阻塞 IO

```python
import asyncio

async def fetch(url):
    await asyncio.sleep(0.1)            # 模拟 IO
    return f"<{url}>"

async def main():
    html = await fetch("https://a.com")
    print(html)
```

## 为什么要用
- LangChain 工具的 `_arun` / `ainvoke` / `astream` 都是 async
- LLM 调用本质是网络 IO, async 能并发处理多个请求
- FastAPI / 异步 web 服务必须用

## 语法骨架

```python
async def coro() -> T:
    result = await another_coro()      # await 一个协程
    return result

# 普通函数里不能 await
def sync_func():
    await coro()                        # SyntaxError
```

## 项目里的真实例子

```python
# 02_tools.py:157
async def fetch_url(url: str) -> str:
    await asyncio.sleep(0.1)
    return f"<html>{url} 的内容...</html>"
```

## 常见坑

1. **`async def` 直接调不执行**: `fetch("url")` 返回 coroutine 对象, 必须 `await` 或 `asyncio.run`
2. **混用 sync / async**: `def` 里不能 `await`, `async def` 里能调 `def` 但会阻塞事件循环
3. **`asyncio.sleep(0)` 让出控制权**, `time.sleep(0)` 不让
4. **Python 3.10+ 取消**: `task.cancel()` 触发 `CancelledError`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 并发单元 | Thread | goroutine | coroutine |
| 同步 | `Future.get()` | channel | `await coro` |
| 调度 | OS / Executor | Go runtime | asyncio event loop |
| 单线程 | NIO event loop | goroutine 协作 | asyncio 协作 |
