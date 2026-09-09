# `asyncio.run` 同步入口跑异步

## 是什么
`asyncio.run(coro)` 创建事件循环, 跑传入的协程到结束, **关闭循环**。

```python
import asyncio

async def main():
    print("async world")

asyncio.run(main())
```

## 为什么要用
- 同步入口 (`python XX.py` / `if __name__ == "__main__":`) 想跑异步代码的唯一干净写法
- 项目里 `02_tools.py:425` 的 demo 入口用 `asyncio.run(_run_parallel())`
- 比手动 `loop = asyncio.new_event_loop()` 安全 100 倍

## 语法骨架

```python
# 顶层入口 (不要再包 try / 嵌套)
asyncio.run(main())
```

## 项目里的真实例子

```python
# 02_tools.py:425 — 同步入口跑并发 demo
results = asyncio.run(_run_parallel())
```

## 常见坑

1. **`asyncio.run` 不能嵌套**: 一个 loop 里再调 `asyncio.run` 会 `RuntimeError`
2. **`asyncio.run` 只调一次**: 退出后 loop 已关闭, 第二次会创建新 loop (但有警告)
3. **`asyncio.run` 接 coro, 不是 await 后的值**: `asyncio.run(await coro)` 错
4. **Jupyter / IPython 自带 loop**: 用 `await coro` 直接调, 不要 `asyncio.run`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 启动协程 | `Thread.start()` / `Executor.submit` | `go func()` | `asyncio.run(coro)` |
| 等待完成 | `Future.get()` | `wg.Wait()` | `await coro` |
| 入口主函数 | `public static void main` | `func main()` | `asyncio.run(main())` |
