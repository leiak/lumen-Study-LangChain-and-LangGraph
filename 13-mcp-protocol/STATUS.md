# 13-mcp-protocol — 最终状态 (2026-10-05)

> 6 demo + 2 共享 + README, MCP 协议全栈. 本文档是教学收尾, 标出能力边界 + 已知限制 + 升级路径.

## TL;DR

- **9 个文件 (含 .gitignore/README/STATUS) / ~1850 LOC / 8 atomic commits**
- **6 demo + 2 共享 (_common / mcp_helpers)**
- **6 已知坑 (MultiServerMCPClient 缺 / send_request result_type / banner stdout 污染 / file:// template slash / ASGITransport task group / uvicorn event loop 跨 run)**
- **AST parse 7/7 OK, 6 demo 全跑通**

## 能力矩阵

| 维度 | 实现 | 文件 | LOC |
|---|---|---|---|
| **FastMCP server** | @mcp.tool / @mcp.resource / @mcp.prompt + stdio/HTTP 双 transport | 01, 03, 05, 06 | ~280 |
| **MCP client (LangChain)** | create_session + load_mcp_tools + create_agent | 02, 04 | ~340 |
| **stdio session helper** | async with create_session(transport="stdio", ...) | mcp_helpers.py | 80 |
| **HTTP transport** | FastMCP.streamable_http_app + uvicorn + ASGITransport (限制) + httpx_client_factory | 05 | ~370 |
| **多 server 合并** | 并发 gather + tool list 拼接 + 命名冲突策略 | 04 | ~315 |
| **生产 Pool** | MCPSessionPool (queue + in_use flag + acquire/release) | 06 | ~310 |
| **Retry 模式** | tenacity 示例 + 错误分类 + 退避 | 06 | (in 06) |
| **Bearer auth** | headers={"Authorization": "Bearer ..."} | 05, 06 | (in 05/06) |
| **Observability** | ToolCallStat (duration / success / error) + 聚合 | 06 | (in 06) |
| **Graceful shutdown** | uvicorn.should_exit + drain + session close | 05, 06 | (in 05/06) |
| **FastAPI 集成** | lifespan + pool + /chat endpoint (模式演示) | 06 | (in 06) |

## 6 个 demo

| # | 主题 | 步骤数 | 跑法 | LLM |
|---|---|---|---|---|
| 1 | Basic Server (FastMCP stdio + resources + tools) | 5 | `python 01_basic_server.py` | ❌ |
| 2 | Client + LangChain (load_mcp_tools + create_agent) | 5 | `python 02_client_langchain.py` | ✅ |
| 3 | MCP Prompts (template + LangChain system) | 4 | `python 03_prompts.py` | ✅ |
| 4 | Multi-Server (filesystem + search 合并) | 4 | `python 04_multi_server.py` | ✅ |
| 5 | Streamable HTTP (FastMCP uvicorn + ASGITransport) | 6 | `python 05_http_transport.py` | ✅ (Step 4) |
| 6 | Production (Pool / Retry / Auth / Observability) | 7 | `python 06_production_mcp.py` | ❌ |

## 9 已知坑 (踩过的)

### 1. langchain-mcp-adapters 0.3.x 没有 MultiServerMCPClient (2026-09 验证)
- 0.2.x docs 教 `MultiServerMCPClient({...})`
- 0.3.x 重命名/拆分成 `stdio_client` + `create_session` + `load_mcp_tools`
- 解: 用统一 `create_session({"transport": "stdio|http|...", ...})`
- 见 `mcp_helpers.py:50` + `05_http_transport.py`

### 2. ClientSession.send_request() 缺 result_type (MCP SDK 1.x)
- 旧: `session.send_request(CallToolRequest(params=...))`
- 新: `session.send_request(CallToolRequest(...), CallToolResult)` — 必须 2 个 arg
- 实战: 改用便捷方法 `session.call_tool(name, args)` / `list_tools()` / `read_resource()` / `get_prompt()`
- 见 01/03/05 重构后用便捷方法

### 3. mcp.client.stdio 子进程 banner 污染 stdout (JSON-RPC 崩)
- 模块级 `banner(...)` 在 import 时执行 → 子进程 stdout 有非 JSON 行
- JSON-RPC 解析失败 → "Connection closed"
- 解: banner 移到 `if __name__ == "__main__"` 内, 加上 `is_subprocess = not sys.stdin.isatty()` 检测
- 见 01/03 `__main__` block

### 4. file://{path} resource template + Pydantic AnyUrl (slash 错配)
- Pydantic AnyUrl 自动给 `file://config.yaml` 加 trailing slash → `file://config.yaml/`
- FastMCP template `file://{path}` 不匹配
- 解: 改用非标准 scheme `config://{name}` / `data://{path}` / `resource://{name}`
- 见 `01_basic_server.py:45` 用 `config://{name}`

### 5. FastMCP.streamable_http_app() 不支持 httpx ASGITransport
- FastMCP 的 streamable_http_manager 需要 task group 启动
- ASGITransport 跳过 task group → `RuntimeError: Task group is not initialized`
- 解: 真起 uvicorn (subprocess 或 background task), 走真实 socket
- 见 `05_http_transport.py:122` (Step 2 文档化限制)

### 6. uvicorn.Server 跨 asyncio.run 崩 (event loop 不同)
- uvicorn.Server 内部用 anyio task group 绑一个 event loop
- 每个 `run_async(coro)` = 独立 `asyncio.run` = 新 event loop
- 多个 HTTP demo 跨 loop → `RuntimeError: Event object is bound to a different event loop`
- 解: 把所有 HTTP demo 包在 `async def all_http_demos()` 单 `asyncio.run` 里
- 见 `05_http_transport.py:441` + `06_production_mcp.py:288`

### 7. mcp_helpers.stdio_session 旧 API (transport tuple)
- 最初写: `create_session((read, write))` — 旧 API, 拿 read/write streams
- 0.3.x 不接受 tuple — 必须传 `{"transport": "stdio", "command": ..., "args": [...]}`
- 解: 改成统一 config dict
- 见 `mcp_helpers.py:50`

### 8. local_agent.get_input_jsons AttributeError (LangGraph 1.x)
- `CompiledStateGraph` 没 `get_input_jsons` 属性 (有 `get_input_jsonschema`)
- 实战: 不需要打印 agent internals — 直接说"本地 vs 远程 tool 数量"
- 见 `02_client_langchain.py:142` (替换为简洁 print)

### 9. 从 mcp 顶层 import XxxRequest 失败 (1.x 移走)
- 旧: `from mcp import ListToolsRequest, CallToolRequest`
- 新: 移到了 `mcp.types`, 顶层不导出
- 解: 用便捷方法 (session.list_tools() / call_tool()), 不直接构造 Request
- 见 01/03/05 重构后

## 升级路径 (生产)

### Phase 1: 单体 → 拆分 (当前能做的)
- ✅ FastMCP server (Python)
- ✅ load_mcp_tools + create_agent (LangChain)
- ✅ stdio + HTTP transport

### Phase 2: 部署化 (下个模块要加)
- ⬜ Dockerfile (FastMCP + uvicorn)
- ⬜ docker-compose (MCP server cluster + agent + 反代)
- ⬜ k8s manifests (Deployment + Service + HPA)
- ⬜ MCP Inspector CI (起 server → 跑 probe → 关)

### Phase 3: 生产化
- ⬜ Server middleware (Bearer validation + 401 拒绝)
- ⬜ OAuth2 flow (/token endpoint + refresh)
- ⬜ Session pool + retry + observability
- ⬜ Prometheus exporter (tool_call_total / duration_seconds / errors_total)
- ⬜ OpenTelemetry trace (跨 client → server → tool)
- ⬜ Graceful shutdown (FastAPI lifespan + drain)

### Phase 4: 规模化
- ⬜ Multi-language server (Go / Rust / TypeScript 实现同一协议)
- ⬜ Cross-team MCP registry (server catalog)
- ⬜ MCP 路由 (1 server : N client 反向代理)

## 跟其他模块的关系

| 维度 | 11 tool-fabric | 13 mcp-protocol |
|---|---|---|
| tool 定义 | `@tool` 装饰 (Python) | `@mcp.tool` 装饰 (跨语言) |
| 进程 | 同进程 | 子进程 / HTTP |
| tool 调用 | `await tool.ainvoke(args)` | `await session.call_tool(name, args)` |
| 性能 | 纳秒 | 毫秒 (JSON-RPC) |
| 跨语言 | ❌ | ✅ |
| 鉴权 | ❌ | ✅ (Bearer / OAuth) |
| 教学定位 | tool 设计模式 | tool 通信协议 |

**关系**: 11 + 13 = tool 全栈 — 11 教"怎么设计 tool", 13 教"tool 怎么跨进程通信".

## 教学价值

学完 13 你能:
- ✅ 跟同事解释 MCP 是什么 + 跟 OpenAI function calling 区别
- ✅ 选 stdio vs HTTP transport (本地 vs 生产)
- ✅ 给 LangChain agent 加 MCP tool (1 行 create_session)
- ✅ 写 FastMCP server (3 primitive + transport)
- ✅ 设计多 server 编排 + 命名空间
- ✅ 加 Bearer auth + observability
- ✅ 知道为啥 in-process ASGITransport 不能用 (task group)
- ✅ 排错 Connection closed (banner 污染 / subprocess 检测)

## 不在 13 范围内

| 主题 | 原因 |
|---|---|
| Claude Desktop 集成 | 桌面应用, 教学 demo 不深挖 |
| MCP 完整 schema 协议 (JSON-RPC message types) | 太底层, demo 用 SDK 足够 |
| OAuth2 完整 flow (PKCE / state) | 生产单独 module |
| MCP 反向代理 (1 server : N clients 路由) | 类似 nginx, 教学用 Step 6 多 client 演示 |
| Go/Rust MCP server 实现 | 跨语言实战在 Phase 4 |

## 下一步

- 13 教学收尾, 实战走 Phase 2 升级路径
- 下一个 module 候选: 14-observability-deep-dive / 14-deployment / 14-security / 14-multi-language-mcp
