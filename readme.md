LangChain **2026 年 9 月的官方文档**。([Docs by LangChain][1])

---

## 快速开始

### 安装

```bash
git clone https://github.com/leiak/lumen-Study-LangChain-and-LangGraph.git
cd lumen-Study-LangChain-and-LangGraph

# 基础依赖 (L1-L7 + 09/10/11)
pip install -e .

# 或装可选依赖组
pip install -e ".[async]"   # 12-async-pipeline 用的 FastAPI / uvicorn / websockets
pip install -e ".[cli]"     # 08-cli-assistant MySQL 用的 sqlalchemy
pip install -e ".[eval]"    # deepeval 离线评估
pip install -e ".[mcp]"     # 13-mcp-protocol 用的 mcp SDK + langchain-mcp-adapters
pip install -e ".[all]"     # 全部

# 或直接用 requirements.txt
pip install -r requirements.txt
```

需要至少一个 LLM provider 的 API key (`.env`):

```bash
echo "ANTHROPIC_API_KEY=..." > .env       # 优先级 1
echo "DEEPSEEK_API_KEY=..." >> .env       # 优先级 2
echo "MINIMAX_API_KEY=..." >> .env         # 优先级 3
echo "OPENAI_API_KEY=..." >> .env         # 优先级 4
```

> 完整 provider 切换逻辑见 `01-langchain-basics/_common.py` 的 `get_llm()`.

### Docker 跑

```bash
# build image (多阶段, 包含 L1-L12 全部 deps)
docker build -t lumen-langchain .

# 默认跑 01-langchain-basics 第一个 demo
docker run --rm -it lumen-langchain

# 跑 08-cli-assistant 端到端 CLI
docker run --rm -it \
  -e ANTHROPIC_API_KEY \
  -v $(pwd)/08-cli-assistant/data:/app/08-cli-assistant/data \
  lumen-langchain python 08-cli-assistant/main.py

# 跑 12-async-pipeline SSE server (暴露 8000)
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY \
  lumen-langchain \
  uvicorn 04_sse_server:app --host 0.0.0.0 --port 8000

# 然后另开 terminal: curl -N "http://localhost:8000/chat?q=hi"
```

### CI

[![CI](https://github.com/leiak/lumen-Study-LangChain-and-LangGraph/actions/workflows/ci.yml/badge.svg)](https://github.com/leiak/lumen-Study-LangChain-and-LangGraph/actions/workflows/ci.yml)

`main` 上每次提交触发 AST 语义验证 (所有 12 模块的 .py 文件 parse 失败 → 红 ×).

---

## 12 个模块

| # | 模块 | 主题 | 入口 | STATUS |
|---|---|---|---|---|
| 01 | [LangChain Basics](01-langchain-basics/) | L1 Agent Framework (Models/Tools/Agents/Middleware/Retrieval) | `python 01-langchain-basics/01_models.py` | — |
| 02 | [LangGraph Orchestration](02-langgraph-orchestration/) | L2 State / Persistence / Interrupt / Durable | `python 02-langgraph-orchestration/06_state_graph.py` | — |
| 03 | [LangSmith Platform](03-langsmith-platform/) | L3 Tracing / Evaluation | `python 03-langsmith-platform/11_langsmith_tracing.py` | — |
| 04 | [Multi-Agent](04-multi-agent/) | L4 Supervisor / Handoff / Swarm | `python 04-multi-agent/13_supervisor.py` | — |
| 05 | [Deep Agents](05-deep-agents/) | L5 create_deep_agent | `python 05-deep-agents/15_deep_agents.py` | — |
| 06 | [OPC Product](06-opc-product/) | L6 端到端 AI 产品 demo | `python 06-opc-product/17_opc_product.py` | — |
| 07 | [Articles](07-articles/) | 通勤阅读笔记 | — | — |
| 08 | [CLI Assistant](08-cli-assistant/) | 端到端 CLI (10 文件 / 5 specialty / 12 场景) | `python 08-cli-assistant/main.py` | [STATUS](08-cli-assistant/STATUS.md) |
| 09 | [Codegen Agent](09-codegen-agent/) | spec → code + tests + review loop (10 demo) | `python 09-codegen-agent/01_spec_to_plan.py` | — |
| 10 | [RAG Deep Dive](10-rag-deep-dive/) | Hybrid / Rerank / Expansion / Chunking / Eval (6 demo) | `python 10-rag-deep-dive/01_hybrid_search.py` | [STATUS](10-rag-deep-dive/STATUS.md) |
| 11 | [Tool Fabric](11-tool-fabric/) | 复杂 schema / 并行 / 错误恢复 / middleware / HITL / composition (6 demo) | `python 11-tool-fabric/01_basic_tools.py` | [STATUS](11-tool-fabric/STATUS.md) |
| 12 | [Async Pipeline](12-async-pipeline/) | astream / gather / async-tool / SSE / WebSocket / 全链路 (6 demo) | `python 12-async-pipeline/01_astream_modes.py` | [STATUS](12-async-pipeline/STATUS.md) |
| 13 | [MCP Protocol](13-mcp-protocol/) | FastMCP stdio/HTTP / 3 primitive / 多 server / pool / FastAPI 集成 (6 demo) | `python 13-mcp-protocol/01_basic_server.py` | [STATUS](13-mcp-protocol/STATUS.md) |

### 推荐学习顺序

```text
01 (L1) → 02 (L2) → 03 (L3) → 04 (L4) → 05 (L5) → 06 (L6 端到端)
   ↓
08 (CLI 全栈整合)
   ↓
09 (codegen 深度方向)  → 10 (RAG 深度方向)
   ↓
11 (tool calling 深度方向) → 12 (async 生产架构)
   ↓
13 (MCP 跨进程 tool 协议 — 11 的远房兄弟)
```

每个模块独立, 互不强依赖. L1-L6 是基础, 08-13 是 13 个**深度优先**探索方向.

### 添加新模块

参考 08-12 的模式:

```text
my-module/
├── _common.py        # 复用 L1 banner/get_llm (importlib.util 路径加载)
├── README.md         # 学完你能回答 N 个问题 + demo 表 + 已知坑
├── STATUS.md         # 收尾 (能力矩阵 + 已知坑 + 升级路径)
├── shared_module.py  # 共享 utility (可选)
└── NN_*.py           # N 个独立 demo
```

提交 PR 时 CI 自动跑 AST smoke.

---

### 现在的关系

目前官方把它们定位成三个不同层次：

| 项目              | 现在的定位                       | 主要解决什么                                           |
| --------------- | --------------------------- | ------------------------------------------------ |
| **LangChain**   | Agent Framework             | Model、Tool、Agent、Middleware、RAG 等                |
| **LangGraph**   | Agent Orchestration Runtime | 状态、工作流、持久化、循环、人工介入                               |
| **LangSmith**   | Agent Platform              | Trace、评估、监控、部署                                   |
| **Deep Agents** | 更高层 Agent Harness           | Planning、Subagents、Filesystem、Context Management |

官方总结为：**LangChain 是 Agent framework，LangGraph 是 orchestration runtime，LangSmith 是平台。** ([Docs by LangChain][2])

### 一个非常重要的变化：LangChain 1.x

目前官方文档已经进入 **LangChain v1** 的架构，Agent 创建方式也明显更加简化，例如：

```python
from langchain.agents import create_agent

agent = create_agent(
    model="...",
    tools=[...],
)
```

官方目前把 `create_agent` 作为新的 Agent API，并且它底层利用 LangGraph 来提供 Agent 的运行能力。([Docs by LangChain][3])

---

## 那 LangGraph 还需要单独学吗？

**需要。**

而且如果你的目标是你之前说的：

> Java/Go 程序员 → AI Agent → OPC → 做真正能赚钱的 AI 产品

建议：

```text
LangChain
   ↓
理解 Model / Tool / Agent
   ↓
LangGraph
   ↓
理解 State / Node / Edge / Checkpoint
   ↓
Agentic Workflow
   ↓
MCP
   ↓
Multi-Agent
   ↓
AI 产品
```

原因是 LangChain 现在帮你解决的是：

> **“怎么快速做一个 Agent？”**

而 LangGraph 解决的是：

> **“这个 Agent 在真实生产环境里到底怎么可靠地跑？”**

比如：

```text
用户
 ↓
Agent
 ↓
分析任务
 ↓
调用工具
 ↓
发现信息不足
 ↓
重新搜索
 ↓
调用数据库
 ↓
人工审批？
 ├── 是 → 等待人工
 └── 否
 ↓
继续执行
 ↓
生成结果
 ↓
保存状态
```

这种**循环、条件分支、持久化、Human-in-the-loop、故障恢复**，就是 LangGraph 的核心能力。官方目前也明确把 durable execution、streaming、human-in-the-loop、persistence 等作为 LangGraph 的核心能力。([Docs by LangChain][2])

---

### 如果你准备现在开始学，我建议不要学老教程

尤其看到下面这种老代码：

```python
from langchain.chains import ...
from langchain.agents import initialize_agent
from langchain.memory import ...
```

**不要把它当成现在的主路线。**

现在更推荐：

```text
LangChain 1.x
    │
    ├── Models
    ├── Tools
    ├── Agents
    ├── Middleware
    └── Retrieval
          │
          ↓
     LangGraph
    ├── State
    ├── Nodes
    ├── Edges
    ├── Persistence
    ├── Interrupt
    └── Human-in-the-loop
          │
          ↓
      LangSmith
    ├── Trace
    ├── Evaluation
    └── Production
```


> **LangChain = Agent 开发层**
> **LangGraph = Agent 运行/编排层**
> **LangSmith = Agent 生产平台**


[1]: https://docs.langchain.com/?utm_source=chatgpt.com "Home - Docs by LangChain"
[2]: https://docs.langchain.com/oss/python/langgraph/overview?utm_source=chatgpt.com "LangGraph overview"
[3]: https://docs.langchain.com/oss/python/langchain/structured-output?utm_source=chatgpt.com "Structured output"
[4]: https://docs.langchain.com/oss/python/deepagents/overview?utm_source=chatgpt.com "Deep Agents overview"
