# 13-mcp-protocol — MCP (Model Context Protocol)

L1/L2/L11 之后, 真实 production agent 系统通常需要 **跨进程 / 跨语言 / 跨团队** 共享 tool/resource/prompt.
MCP (Anthropic 2024-11 发布) 是事实标准, 2026 已成生态: Claude Desktop / Cursor / Cline / LangChain / LlamaIndex 全支持.

## 为什么需要这个模块

| 场景 | 11 本地 @tool 做不到 | 13 MCP 解决 |
|---|---|---|
| 跨语言 tool (Go/Rust/JS 写的服务) | ❌ Python only | ✅ 任意语言实现 server |
| tool 独立部署 (微服务化) | ❌ 必须同进程 | ✅ docker / k8s |
| 团队共享 tool 库 | ❌ 复制代码 | ✅ MCP server 中心化 |
| 标准化协议 (VSCode/IDE 集成) | ❌ 各搞各的 | ✅ Inspector + Claude Desktop 直接连 |
| 鉴权 / 监控 / 横向扩展 | ❌ 进程内 | ✅ HTTP + Bearer + Prometheus |

本模块 6 个 demo 每个讲一个, 共用 `_common.py` (复用 L1 banner + LLM) 和 `mcp_helpers.py` (stdio/HTTP/ASGI session).

## 学完你能回答 N 个问题

1. **MCP 基础** — 3 类 primitive (Resource / Tool / Prompt) 是什么? FastMCP 高层 API 怎么用? stdio transport 怎么跑?
2. **MCP + LangChain** — `load_mcp_tools` 怎么把 server 转 BaseTool? `create_agent` 怎么用 MCP tool? 跟本地 @tool 区别?
3. **MCP Prompts** — `@mcp.prompt()` 怎么定义模板? 客户端怎么 list/render? 怎么注入 LangChain system?
4. **多 server** — 怎么同时连 2+ server? Tool 命名冲突怎么处理? 并发调度性能?
5. **HTTP transport** — Streamable HTTP vs stdio 维度对比? FastMCP 怎么跑 HTTP? in-process ASGI 测试? Bearer auth 怎么加?
6. **生产实践** — Session Pool 怎么复用? Retry + 退避怎么做? Observability (tool_call duration)? Graceful shutdown? FastAPI 集成?

## Demo 表

| # | 主题 | 步骤 | 跑法 | LLM | 状态 |
|---|---|---|---|---|---|
| 01 | Basic Server (FastMCP stdio + resources + tools) | 5 | `python 01_basic_server.py` | ❌ | ✅ |
| 02 | Client + LangChain (load_mcp_tools + create_agent) | 5 | `python 02_client_langchain.py` | ✅ | ✅ |
| 03 | MCP Prompts (template + LangChain system) | 4 | `python 03_prompts.py` | ✅ | ✅ |
| 04 | Multi-Server (filesystem + search 合并) | 4 | `python 04_multi_server.py` | ✅ | ✅ |
| 05 | Streamable HTTP (FastMCP uvicorn + ASGITransport) | 6 | `python 05_http_transport.py` | ✅ (Step 4) | ✅ |
| 06 | Production (Pool / Retry / Auth / Observability) | 7 | `python 06_production_mcp.py` | ❌ | ✅ |

> LLM 标记 ✅ 的 demo 需 API key, 没有会自动跳过 LLM 部分 (跑非 LLM step).

## 文件结构

```
13-mcp-protocol/
├── _common.py              # 复用 L1 banner + get_llm (importlib)
├── mcp_helpers.py          # stdio_session + check_mcp_available + 工厂
├── 01_basic_server.py      # FastMCP server (3 primitive + serve 命令)
├── 02_client_langchain.py  # MCP client + LangChain agent
├── 03_prompts.py           # @mcp.prompt + get_prompt + 注入 LangChain
├── 04_multi_server.py      # 多 server 合并 + 并行 tool_call
├── 05_http_transport.py    # Streamable HTTP + Bearer + multi-client
├── 06_production_mcp.py    # Pool + Retry + Observability + FastAPI
├── output/                 # (空 — 本模块无文件输出)
├── .gitignore              # output/ + __pycache__/
├── README.md               # 本文件
└── STATUS.md               # 能力矩阵 + 已知坑 + 升级路径
```

## 快速跑

```bash
# 默认 stdio 测试 (不需 API key)
python 01_basic_server.py

# 跑全部 6 demo
for f in 0{1,2,3,4,5,6}_*.py; do PYTHONIOENCODING=utf-8 python "$f"; done

# 真起 server (等待 client)
python 01_basic_server.py serve        # stdio
python 01_basic_server.py serve        # Inspector 也连这个
```

## 关键依赖

```
mcp==1.30.0                          # MCP Python SDK (含 FastMCP)
langchain-mcp-adapters==0.3.2        # LangChain ↔ MCP 桥
uvicorn                              # HTTP server (Step 5/6)
httpx                                # ASGI / HTTP client
pydantic                             # URL 校验
```

## 实战 tips

### 1. Server 设计

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("my-server")

@mcp.tool()
def my_tool(x: str) -> str:
    """工具描述 (LLM 看到这个)."""
    return x

@mcp.resource("data://{name}")      # 注意: 不要用 file://{path} (Pydantic 加 slash 错配)
def my_resource(name: str) -> str:
    return name

@mcp.prompt()
def my_prompt(topic: str) -> str:
    return f"请讨论 {topic}"

mcp.run(transport="stdio")            # 或 "streamable-http"
```

### 2. Client (LangChain)

```python
from langchain_mcp_adapters.sessions import create_session
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_agent

async with create_session({
    "transport": "stdio",
    "command": sys.executable,
    "args": ["my_server.py"],
}) as session:
    await session.initialize()
    tools = await load_mcp_tools(session)
    agent = create_agent(model=llm, tools=tools)
```

### 3. Bearer Auth (HTTP)

```python
async with create_session({
    "transport": "http",
    "url": "https://mcp.example.com/mcp",
    "headers": {"Authorization": "Bearer sk-xxx"},
}) as session: ...
```

## 跟 11-tool-fabric 的关系

| 维度 | 11 本地 @tool | 13 MCP |
|---|---|---|
| 进程 | 同进程 | 子进程 / HTTP |
| 性能 | 直接 call (ns) | JSON-RPC (ms) |
| 跨语言 | ❌ Python | ✅ 任意语言 |
| 重启 | 改代码重启 | 单独 restart server |
| 鉴权 | OS 权限 | Bearer / OAuth |
| 适用 | 快速 demo / 单体 | 微服务 / 跨团队 |

**实战选择:**
- 单体 Python app → 11 @tool (简单)
- 微服务 / 跨语言 / 跨团队 → 13 MCP (标准)
- IDE / Desktop 集成 (Claude Desktop / Cursor) → 13 MCP (唯一选项)

## 跟 12-async-pipeline 的关系

13 是 12 的工具层补充:
- 12 教你 asyncio 编排 LangGraph
- 13 教你把 tool 调用从进程内移到 MCP server (异步、远程)
- 实战: 12 的 astream_events + 13 的 ainvoke = 实时显示远程 tool 调用过程

## 相关资源

- [MCP 官方文档](https://modelcontextprotocol.io) — Anthropic 标准
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — FastMCP 实现
- [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters) — LangChain 集成
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector) — 调试工具 (npx)

## 下一步

- 14-observability-deep-dive (LangSmith + OpenTelemetry + MCP tracing)
- 14-deployment (docker + k8s + MCP server 集群)
- 14-security (RBAC + OAuth2 + 沙箱化 MCP)
