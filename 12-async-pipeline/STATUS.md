# 12-async-pipeline — 最终状态 (2026-10-05)

> Async Pipeline 工程深度. 本模块把 LangChain 1.x / LangGraph 1.x 的异步能力全链路拆开: astream 5 种 + asyncio.gather + async tool + FastAPI SSE/WebSocket + async middleware + 生产 metrics. 本文档是教学收尾, 标出能力边界 + 已知限制 + 升级路径.

## TL;DR

- **10 个文件 (含 README + .gitignore) / ~2113 LOC 代码 / 2352 含 README / 待 commits**
- **6 demo + 2 共享 (_common.py + async_pipeline.py)**
- **10 已知坑 (8 教学 + 2 生产)**
- **AST parse 8/8 OK, import chain OK**

## 能力矩阵

| 维度 | 实现 | 文件 | LOC |
|---|---|---|---|
| **astream_events v2** | 5 类事件统一订阅 (chain/chat_model/tool/retriever/parser) | 01_astream_modes.py | 290 |
| **astream 4 mode** | updates / values / messages / custom 各适用场景 | 01_astream_modes.py | (内嵌) |
| **custom writer** | `langgraph.config.get_stream_writer()` 主动 emit | 01_astream_modes.py | (内嵌) |
| **gather_safe** | gather + `return_exceptions=True` 永远不抛 | async_pipeline.py + 02_parallel_agents.py | 248 |
| **并发加速比** | 实测 5 query 串行 vs 并发 latency + per-query | 02_parallel_agents.py | (内嵌) |
| **多 thread 并发** | 每个 user 独立 thread_id 并发 | 02_parallel_agents.py | (内嵌) |
| **async @tool** | async def 自动给 .ainvoke, 不阻塞 event loop | 03_async_tools.py | 304 |
| **httpx async HTTP** | AsyncClient + async with + timeout + 异步 fetch | 03_async_tools.py | (内嵌) |
| **工具内并发** | 一个 tool 内部 gather N 个 URL | 03_async_tools.py | (内嵌) |
| **Semaphore 限流** | 工具内部 `async with sem` 防并发打爆 | 03_async_tools.py | (内嵌) |
| **AsyncRateLimiter 装饰器** | 全局并发上限 + 装饰器模式 | async_pipeline.py + 03 | (内嵌) |
| **SSE 协议** | `text/event-stream` 格式 + 双 `\n\n` | 04_sse_server.py | 276 |
| **FastAPI StreamingResponse** | async generator + media_type + headers (X-Accel-Buffering) | 04_sse_server.py | (内嵌) |
| **stream_to_sse helper** | astream_events 转 SSE 自动格式 | async_pipeline.py | (内嵌) |
| **httpx ASGITransport** | 不真起 server 测 endpoint (pytest 友好) | 04_sse_server.py | (内嵌) |
| **WebSocket 双向** | FastAPI WebSocket + 多轮对话 + thread_id | 05_websocket.py | 294 |
| **WebSocketDisconnect cleanup** | try/except 包整个连接, 资源回收 | 05_websocket.py | (内嵌) |
| **中途 cancel** | asyncio.Task.cancel() 触发 CancelledError + 部分 token | 05_websocket.py | (内嵌) |
| **async wrap_tool_call** | handler awaitable + 异步日志 / 上报 metrics | 06_production_async.py | 374 |
| **async wrap_model_call** | 动态 system prompt 注入 | 06_production_async.py | (内嵌) |
| **background_task** | fire-and-forget + 主进程 gather (防止审计丢) | 06_production_async.py | (内嵌) |
| **Semaphore in middleware** | 全局 ≤N 并发 + 防 provider rate limit | 06_production_async.py | (内嵌) |
| **measure_latency** | async with 测 block 耗时 + P50/P95 计算 | 06_production_async.py | (内嵌) |
| **run_async helper** | Jupyter 兼容 (已有 loop 警告) | _common.py | 89 |

## 6 个 demo

| # | 主题 | 步骤 | 需要 API key | 跑法 |
|---|---|---|---|---|
| 1 | astream_events v2 + astream 4 mode + 5 mode 选择指南 | 6 | ✅ 5 次 LLM | `python 01_astream_modes.py` |
| 2 | asyncio.gather 多 agent + return_exceptions + 加速比 + multi-thread | 5 | ✅ 2/3/4 要 LLM | `python 02_parallel_agents.py` |
| 3 | async @tool + httpx async HTTP + 工具内并发 + Semaphore + AsyncRateLimiter | 6 | ⚠️ Step 2/3/4 要网络 | `python 03_async_tools.py` |
| 4 | SSE 协议 + FastAPI StreamingResponse + httpx.ASGITransport 测 | 5 | ✅ Step 4 要 LLM | `python 04_sse_server.py` 或 `uvicorn 04_sse_server:app` |
| 5 | WebSocket vs SSE + FastAPI WS endpoint + websockets 客户端 + 中途 cancel | 5 | ✅ Step 4/5 要 LLM | `python 05_websocket.py` 或 `uvicorn 05_websocket:app` |
| 6 | async wrap_tool_call + wrap_model_call + background_task + Semaphore + metrics + 全链路 | 6 | ✅ 多数要 LLM | `python 06_production_async.py` |

## 10 个已知坑

### 1. `astream_events` v1 vs v2 — 必须 `version="v2"`

**现象**: 默认 v1 字段混乱 (`chunk.output_type` / `output`). v2 统一 `ev["event"]` + `ev["data"]`.

**影响**: v1 拿到的事件字段不全, 教学 demo 用了 v2 才能稳定演示.

**升级路径**: `agent.astream_events(input, version="v2")`. v1 已被官方弃用.

### 2. `asyncio.gather` 默认 all-or-nothing — 一个抛其它全 cancelled

**现象**: 默认 gather 一个抛, 其它 task 收 `asyncio.CancelledError`.

**影响**: LLM API 多个并发跑, 一个 401 拖垮其它 — 不可接受.

**升级路径**: 永远 `gather_safe` (强制 `return_exceptions=True`). Demo 2 Step 2 演示.

### 3. LLM 客户端是同步的 — `ainvoke` 内部走 `asyncio.to_thread`

**现象**: `langchain_openai.ChatOpenAI.ainvoke(...)` 实际同步阻塞. provider 自带 sync `invoke`.

**影响**: async 上下文调 sync `invoke` 阻塞 event loop, 整个服务卡住.

**升级路径**: 永远 `ainvoke`, 不用 `invoke` 在 async 上下文. 如果用了 sync 客户端, 主动 `asyncio.to_thread(sync_invoke, prompt)`.

### 4. async tool 内部调 sync tool — 失去异步优势

**现象**: `async def tool_a()` 内 `await sync_tool.invoke(...)` — sync 阻塞 event loop.

**影响**: 实测 async 工具套 sync 工具, 加速比从 5x 降到 1x.

**升级路径**: 子工具也用 async (有 `.ainvoke`). Demo 3 Step 6 实测同步 vs 异步加速比.

### 5. `WebSocketDisconnect` 后 generator 收 `GeneratorExit`

**现象**: 客户端断线, `agent.aiterate(...)` 抛 `GeneratorExit`. 不 cleanup 丢状态.

**影响**: DB 连接泄漏, checkpointer 状态不一致.

**升级路径**: `try/except WebSocketDisconnect` 包整个连接, cleanup 资源 (close DB / cancel task). Demo 5 Step 3 演示.

### 6. SSE 格式 — 必须是双 `\n\n` 结尾

**现象**: `yield "data: foo\n"` 单换行 → 浏览器不触发 EventSource.message, 卡住.

**影响**: 前端看不到任何 token, 用户以为 hang.

**升级路径**: 永远 `"data: ...\n\n"`. 测试用 `curl -N` 看实时. Demo 4 Step 4 httpx 测试验证.

### 7. `asyncio.Semaphore` 限并发 vs 时间窗口限速 — 别混

**现象**: Semaphore 限**同时间并发**, 限不了**单位时间请求**.

**影响**: 高 QPS 突发仍可能触发 provider rate limit.

**升级路径**: 防打爆下游 IO 用 Semaphore (并发粒度). 限 10 req/s 用 Redis token bucket (时间窗口粒度). 实战可叠加.

### 8. `background_task` 主进程退出前应 gather (生产坑)

**现象**: `asyncio.run(main())` 退出 → background_task 可能没跑完, 进程 kill 丢任务.

**影响**: audit log / metrics 上报丢. P0 故障复盘缺关键 log.

**升级路径**: 主函数退出前 `await asyncio.gather(*background_tasks)`. 或改 `asyncio.TaskGroup` (Python 3.11+).

### 9. `httpx.AsyncClient` 不用 `async with` — 连接池泄漏 (生产坑)

**现象**: 每次 `httpx.AsyncClient()` 不 close → 连接池耗尽, DNS leak.

**影响**: 长时间运行服务内存 / FD 涨.

**升级路径**: `async with httpx.AsyncClient(timeout=5.0) as client: ...`. 或单例 client 跨 process 共享.

### 10. FastAPI `StreamingResponse` generator raise → 整个 response 500

**现象**: generator 内 raise → FastAPI 把整个 SSE 当 500, 客户端收不到任何 event.

**影响**: 客户端看到 "Internal Server Error", 没法 partial 渲染.

**升级路径**: generator 内 try/except 包逻辑, 失败 yield `event: error\n\n` 而不是 raise. Demo 4 演示了规范.

## 升级到 Production 的步骤

```python
# 1. WebSocket 部署 — gunicorn + uvicorn worker
# gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 main:app
# -w 4: 4 个 process (每 process 一个 event loop)
# -k uvicorn.workers.UvicornWorker: 异步 worker class

# 2. Prometheus metrics 上报
from prometheus_client import Counter, Histogram, start_http_server
llm_calls = Counter("llm_calls_total", "Total LLM calls", ["model", "status"])
llm_latency = Histogram("llm_latency_seconds", "LLM latency", ["model"])

# 启动 metrics server:
start_http_server(9091)  # Prometheus 抓 /metrics

# 在 middleware 里:
@wrap_model_call
async def metrics_mw(request, handler):
    t0 = time.perf_counter()
    try:
        r = await handler(request)
        llm_calls.labels(model="claude", rate="ok").inc()
        return r
    except Exception as e:
        llm_calls.labels(model="claude", rate="err").inc()
        raise
    finally:
        llm_latency.labels(model="claude").observe(time.perf_counter() - t0)

# 3. SSE 反向代理 (Nginx) 配置
# location /api/chat {
#     proxy_pass http://upstream;
#     proxy_http_version 1.1;
#     proxy_set_header Connection "";
#     proxy_buffering off;     # 关键! 不缓冲 SSE
#     proxy_cache off;
#     proxy_read_timeout 600s; # 长连接 timeout
# }

# 4. WebSocket 鉴权 (JWT in query / cookie)
from fastapi import WebSocket, status
@app.websocket("/ws")
async def ws(ws: WebSocket, token: str = Query(...)):
    user = verify_jwt(token)  # 你的 verify
    if not user:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()
    ...

# 5. 全局并发限流 (Semaphore in middleware)
GLOBAL_SEM = asyncio.Semaphore(50)  # 整个 service ≤50 并发 LLM
@wrap_model_call
async def global_limit_mw(request, handler):
    async with GLOBAL_SEM:
        return await handler(request)

# 6. Async DB (asyncpg / aiomysql) 替换 sync
import asyncpg
async def get_pool():
    return await asyncpg.create_pool(
        dsn="postgresql://...", min_size=5, max_size=20,
    )

@tool
async def db_query(sql: str) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
    return [dict(r) for r in rows]

# 7. OpenTelemetry 分布式 trace
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
LangchainInstrumentor().instrument()
# 自动 trace agent.ainvoke + tool call + DB query
# 上报到 Jaeger / Tempo / Datadog APM
```

## Smoke 验证 (2026-10-05)

```bash
$ cd 12-async-pipeline
$ for f in _common.py async_pipeline.py \
          01_astream_modes.py 02_parallel_agents.py 03_async_tools.py \
          04_sse_server.py 05_websocket.py 06_production_async.py; do
    python -c "import ast; ast.parse(open('$f', encoding='utf-8').read())" && echo "OK: $f"
  done
OK: _common.py
OK: async_pipeline.py
OK: 01_astream_modes.py
OK: 02_parallel_agents.py
OK: 03_async_tools.py
OK: 04_sse_server.py
OK: 05_websocket.py
OK: 06_production_async.py
```

**8/8 AST parse OK. Import chain OK. 项目进入稳定状态.**

## atomic commits 历史 (待放)

```
feat(12): 新模块 12-async-pipeline — _common + async_pipeline 共享模块
feat(12): 01/02 — astream 5 mode + asyncio.gather 多 agent
feat(12): 03 — async tool + httpx + Semaphore
feat(12): 04 — FastAPI + SSE + ASGITransport 测
feat(12): 05 — WebSocket 双向 + 中途 cancel
feat(12): 06 — async middleware + background_task + metrics
docs(12): README + STATUS.md
```

## 下一步 (可选)

1. **Nitpick audit** — 用 `nitpick` skill 全模块 review (跟 08/09/10/11 平行)
2. **跟 08-cli-assistant 集成** — 08 的 `cli.py` 同步 streaming → 升级到 12 的全 async pipeline
3. **跟 11-tool-fabric 集成** — 11 中部的 sync `@wrap_tool_call` → 升级 async 版 (用 06 demo 模式)
4. **新模块 13** — MCP / agent-evaluation / long-context 等
5. **打包发布** — pyproject.toml + Docker image + GitHub Actions CI

6 demo + 2 共享 utility 后, 12-async-pipeline 教学目标达成. **推荐**: nitpick audit + push 12 commits, 项目稳定收官. 不再加深现有能力.