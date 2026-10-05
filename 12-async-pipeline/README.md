# 12-async-pipeline — Async Pipeline Deep Dive

L2 提过 `astream` (messages / updates 模式), L5 deep agent 走过 streaming. 实战生产 LLM 服务需要**全异步架构**: astream_events + asyncio.gather + FastAPI SSE/WebSocket + async middleware + Semaphore 限流 + 后台任务. 本模块 6 个 demo 把这些都过一遍.

## 为什么需要这个模块

| 进阶能力 | L2 / 08 没讲 | 实战必备 |
|---|---|---|
| `astream_events` v2 (5 类事件) | ⚠️ demo 提过 | ✅ |
| `astream` 4 种 mode 选择 | ❌ | ✅ |
| `asyncio.gather` 多 agent 并发 | ❌ | ✅ |
| async `@tool` + `httpx.AsyncClient` | ❌ | ✅ |
| FastAPI + SSE 流式部署 | ❌ | ✅ |
| WebSocket 双向 + 中途打断 | ❌ | ✅ |
| Async middleware (`@wrap_tool_call` async) | ❌ | ✅ |
| `Semaphore` 限流 + `background_task` | ❌ | ✅ |
| `measure_latency` 上报 P50/P95 | ❌ | ✅ |

08-cli-assistant 的 streaming 是**同步简化版**, 真要部署生产 LLM 服务需要**全异步链路**. 本模块过一遍.

## 学完你能回答 N 个问题

1. **astream_events v2** — 5 类事件 (chain / chat_model / tool / retriever / parser) 怎么订阅? version="v2" 跟 v1 字段差什么?
2. **astream 4 mode** — `updates` / `values` / `messages` / `custom` 怎么选? 哪个给前端用? 哪个给监控用?
3. **asyncio.gather** — `return_exceptions=True` 为什么必加? 多 agent 并发加速比实测几倍?
4. **async tool** — `async def + @tool` 自动给 `.ainvoke` 吗? sync tool 在 async 上下文里会怎样?
5. **httpx 异步** — `AsyncClient` timeout / `async with` 怎么写? 一个工具内部 `gather N 个 fetch` 实战?
6. **Semaphore** — 工具内 `async with sem` 限并发跟全局 lock? `AsyncRateLimiter` 装饰器模式实战?
8. **SSE 协议** — `text/event-stream` 格式 (`event: / data: / \n\n`)? `curl -N` 怎么测? FastAPI `StreamingResponse` 实战?
9. **WebSocket vs SSE** — 双向 vs 单向, 什么时候选 WS? `WebSocketDisconnect` 怎么 cleanup?
10. **中途打断** — `asyncio.Task.cancel()` 触发 `CancelledError` + 部分 token 已发, 客户端怎么处理?
11. **async middleware** — `@wrap_tool_call async def` 跟 sync 区别? `background_task` fire-and-forget 上报 metrics 实战?
12. **measure_latency** — `async with measure_latency() as t: ... t.elapsed_ms` 怎么嵌 metrics 管线?
13. **全链路 async** — 生产 LLM 服务从 WS 到 provider 全异步架构? Prometheus + Grafana 怎么嵌?

## Demo 表

| Demo | 内容 | 需要 API key | 跑法 |
|---|---|---|---|
| `01_astream_modes.py` | astream_events v2 + astream 4 mode + 5 mode 选择指南 | ✅ 5 次 LLM | `python 01_astream_modes.py` |
| `02_parallel_agents.py` | gather_safe 多 agent + return_exceptions + 加速比实测 + multi-thread | ✅ 2/3/4 要 LLM | `python 02_parallel_agents.py` |
| `03_async_tools.py` | async @tool + httpx async HTTP + 工具内并发 + Semaphore + AsyncRateLimiter | ⚠️ Step 2/3/4 要网络 | `python 03_async_tools.py` |
| `04_sse_server.py` | SSE 协议 + FastAPI StreamingResponse + httpx.ASGITransport 测 | ✅ Step 4 要 LLM | `python 04_sse_server.py` 或 `uvicorn 04_sse_server:app` |
| `05_websocket.py` | WebSocket vs SSE + FastAPI WS endpoint + websockets 客户端 + 中途 cancel | ✅ Step 4/5 要 LLM | `python 05_websocket.py` 或 `uvicorn 05_websocket:app` |
| `06_production_async.py` | async wrap_tool_call + wrap_model_call + background_task + Semaphore + metrics | ✅ 多数要 LLM | `python 06_production_async.py` |

## 文件结构

```
12-async-pipeline/
├── _common.py                  L1 wrapper + step/output_dir/run_async 工厂
├── async_pipeline.py           5 共享 async helpers (gather_safe / stream_to_sse / AsyncRateLimiter / background_task / measure_latency)
├── 01_astream_modes.py         Demo 1: astream_events v2 + astream 4 mode
├── 02_parallel_agents.py       Demo 2: asyncio.gather 多 agent + 加速比
├── 03_async_tools.py           Demo 3: async @tool + httpx + Semaphore
├── 04_sse_server.py            Demo 4: FastAPI + SSE 流式部署 + ASGITransport 测
├── 05_websocket.py             Demo 5: WebSocket 双向 + 中途打断
├── 06_production_async.py      Demo 6: async middleware + 全链路生产模式
├── README.md                   本文件
├── .gitignore                   output/ + __pycache__/
└── STATUS.md                   收尾 (能力矩阵 + 已知坑 + 升级路径)
```

## 跑法

```bash
cd D:/work-ai/0401-langchain-langgraph-v1

# 不需要 API key 的 demo (纯工具 / 异步 helper)
python 12-async-pipeline/03_async_tools.py     # 多数 step 不需要 LLM, 只要 httpx
python 12-async-pipeline/06_production_async.py  # Step 3 不需要

# 需要 LLM 的 demo
python 12-async-pipeline/01_astream_modes.py
python 12-async-pipeline/02_parallel_agents.py
python 12-async-pipeline/04_sse_server.py      # 自带 ASGITransport 测试, 不真起 server
python 12-async-pipeline/05_websocket.py       # 自带客户端模拟, 不真起 server
python 12-async-pipeline/06_production_async.py  # 其它 step 要 LLM

# 真起 server (另开 terminal)
uvicorn 04_sse_server:app --port 8000
uvicorn 05_websocket:app --port 8000

# curl 测试 SSE
curl -N "http://localhost:8000/chat?q=hi"
```

LLM provider 配置见 `01-langchain-basics/_common.py` 的 `get_llm()` — 优先级 Anthropic > DeepSeek > MiniMax > OpenAI, `.env` 配 key 即可.

## 核心概念

### 1. 5 共享 async helpers (`async_pipeline.py`)

| Helper | 作用 | 关键代码 |
|---|---|---|
| `gather_safe(*coros)` | gather + `return_exceptions=True` 永远不抛 | `asyncio.gather(*coros, return_exceptions=True)` |
| `stream_to_sse(events)` | astream_events 转 SSE 格式 | `event: {name}\ndata: {json}\n\n` |
| `AsyncRateLimiter(max=N)` | Semaphore 并发限流 + 装饰器模式 | `async with self._sem: ...` |
| `background_task(coro)` | fire-and-forget 后台 task | `asyncio.create_task(_wrap())` |
| `measure_latency()` | async context manager 测耗时 | `time.perf_counter()` |

### 2. astream 5 种模式 (Demo 1)

| Mode | 用途 | 输出 |
|---|---|---|
| `updates` | 监控/debug | `{node: state_delta}` |
| `values` | 批量数据导出 | 全 state snapshot |
| `messages` | 前端 token 流 | `(AIMessageChunk, meta)` |
| `custom` | 业务 progress | `writer({phase, progress})` |
| `events` (v2) | 5 类事件统一 | `{event, data, name, ...}` |

### 3. 5 种事件类型 (astream_events v2)

```
on_chain_start / end          — chain 边界
on_chat_model_start / stream / end — LLM 边界 (stream = 每个 token)
on_tool_start / end           — 工具调用边界
on_retriever_start / end      — 检索边界
on_parser_start / end         — 输出解析边界
```

### 4. WebSocket vs SSE 选择 (Demo 5)

| 场景 | 选 SSE | 选 WS |
|---|---|---|
| 简单 chat 流 (OpenAI/Claude API) | ✅ | |
| 多轮实时 (中途打断) | | ✅ |
| 协同编辑 / 游戏 | | ✅ |
| HTTP 代理穿透 | ✅ | |

### 5. Demo 6 全链路架构

```
Client (WS)
   │
   ▼
FastAPI + uvicorn
   │
   ▼
agent.aastream_events(v="v2")
   │
   ▼
async middleware chain:
   async_log_mw        → background_task 上报 metrics
   async_semaphore_mw  → 全局 ≤5 并发
   async_inject_mw     → 动态 system prompt
   │
   ▼
async tools:
   httpx async fetch   → N URL 并发
   asyncpg async DB
   │
   ▼
Provider (OpenAI / Anthropic / MCP)
   │
   ▼
metrics (Prometheus / OpenTelemetry)
   │
   ▼
Grafana / Datadog
```

## 已知坑 (10 个)

### 1. `astream_events` v1 vs v2 — 必须 `version="v2"`

**现象**: 默认调用 v1, event 字段格式混乱 (chunk.output_type / output 等)。新版是 `ev["event"]` + `ev["data"]` 统一。

**原因**: v1 设计粗糙, v2 是 LangChain 1.x 推荐的现代 API。

**实战**: `agent.astream_events(input, version="v2")`. 否则拿到的事件可能字段不全。

### 2. `asyncio.gather` 默认 all-or-nothing

**现象**: 默认 gather 一个抛, 其它全 cancelled. `asyncio.CancelledError` 噪音。

**实战**: 永远 `gather_safe` (强制 `return_exceptions=True`) 或显式 `return_exceptions=True`. Demo 2 Step 2 演示了"什么不一样"。

### 3. LLM 客户端是同步的 — 阻塞 event loop

**现象**: `langchain_openai.ChatOpenAI.ainvoke(...)` 内部 `asyncio.to_thread(sync_invoke, prompt)`. 但 provider 自己的 sync `invoke` 阻塞。

**实战**: 永远用 `ainvoke`, 不用 `invoke` 在 async 上下文。如果用了 sync 客户端 (LibSync, 等), 主动包 `asyncio.to_thread`.

### 4. async tool 内部调 sync tool — 失去异步

**现象**: `async def tool_a()` 内 `await sync_tool.invoke()` — sync 阻塞 event loop, async 优势消失。

**实战**: 子工具也用 async (有 `.ainvoke`)。Demo 3 Step 6 实测了 sync vs async 加速比。

### 5. `WebSocketDisconnect` 后 generator 收 `GeneratorExit`

**现象**: 客户端断线时, 正在跑的 `agent.aaiterate(...)` 抛 `GeneratorExit`. 不 cleanup 会丢状态。

**实战**: `try/except WebSocketDisconnect` 包整个连接, cleanup 资源 (close DB / cancel task)。Demo 5 Step 3 演示。

### 6. SSE 格式 — 必须是双 `\n\n` 结尾

**现象**: yield `"data: foo\n"` (单换行) → 浏览器不触发 EventSource.message, 卡住。

**实战**: 永远 `"data: ...\n\n"` (双换行). 测试用 `curl -N` 看实时。

### 7. `asyncio.Semaphore` 限并发 vs 时间窗口限速

**现象**: 两者不一样。Semaphore 限**同时间**, 不限**单位时间**。

**实战**: 防打爆下游 IO 用 Semaphore (并发控制粒度). 限 10 req/s 用 Redis token bucket (时间窗口粒度)。可叠加。

### 8. `background_task` 主进程退出前应 gather

**现象**: `asyncio.run(main())` 退出 → background_task 可能还没跑完, 进程 kill 丢任务。

**实战**: 主函数退出前 `await asyncio.gather(*background_tasks)` 或用 `asyncio.TaskGroup`. 否则 audit log / metrics 上报丢。

### 9. `httpx.AsyncClient` 不用 `async with` — 连接池泄漏

**现象**: 每次 `httpx.AsyncClient()` 不 close → 连接池耗尽, DNS leak。

**实战**: `async with httpx.AsyncClient(timeout=5.0) as client: ...`. 或者全局一个 client, process life 共享。

### 10. FastAPI `StreamingResponse` 不能 raise — generator 抛错客户端收 HttpError

**现象**: generator 里 raise → FastAPI 把整个 response 当 500, 客户端收不到 SSE event。

**实战**: generator 内 try/except 包逻辑, 失败 yield `event: error\n\n` 而不是 raise. 或者 yield 后用 try/finally 清理。

## 进阶阅读

- **LangGraph astream_events v2**: <https://langchain-ai.github.io/langgraph/concepts/streaming/>
- **FastAPI SSE**: <https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse>
- **FastAPI WebSocket**: <https://fastapi.tiangolo.com/advanced/websockets/>
- **asyncio 实战**: <https://docs.python.org/3/library/asyncio.html>
- **httpx async**: <https://www.python-httpx.org/async/>

## 相关模块

- `01-langchain-basics/04_middleware.py` — L1 基础 middleware (sync)
- `02-langgraph-orchestration/09_streaming.py` — L2 astream 基础模式
- `08-cli-assistant/` — 端到端 CLI (含简化版 streaming)
- `11-tool-fabric/04_middleware.py` — 同步 `@wrap_tool_call` middleware (vs 本模块 async)