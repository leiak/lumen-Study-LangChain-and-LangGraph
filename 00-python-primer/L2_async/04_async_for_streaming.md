# `async for` 流式迭代

## 是什么
`async for` 是异步版本的 `for`, 每次迭代调用 `__aiter__()` / `__anext__()`。
**`async for` 必须 await**, 普通 `for` 不能用于异步生成器。

```python
async for chunk in async_stream:
    print(chunk)
```

## 为什么要用
- LangChain 的 `astream(stream_mode="updates"|"messages")` 返回异步生成器
- 实时显示 LLM token 输出 (09_streaming.py 的 demo)
- 不一次性加载所有结果, 内存友好

## 语法骨架

```python
async def aiter():
    for i in range(3):
        await asyncio.sleep(0.1)
        yield i                       # 异步生成器

async for x in aiter():
    print(x)

# 异步生成器表达式 (PEP 530)
gen = (x async for x in aiter() if x > 0)
```

## 项目里的真实例子

```python
# 09_streaming.py:221
async for chunk in agent.astream(
    {"messages": [HumanMessage("深圳?")]},
    stream_mode="updates",
):
    print(chunk)
```

## 常见坑

1. **不能用普通 `for`**: `for x in async_gen()` 会得到 generator 对象, 不会执行
2. **异步生成器只能迭代一次**: 想重新消费要重调函数
3. **`async for` 只能在 async 函数里用**
4. **`async with` 配异步 CM** (3.5+): `async with lock:` / `async with session:`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 异步迭代 | `Stream.forEach` + reactive | channel for-range | `async for` |
| 背压 | Reactive Subscriber | channel buffer | 流控靠调用方暂停 |
| 流式 LLM | SSE / WebFlux | SSE / channel | `astream` + `async for` |
