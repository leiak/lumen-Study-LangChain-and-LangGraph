# 2026 LangChain 1.x + LangGraph 学习路线

> 面向 **Java / Go → AI Agent → OPC → AI 产品** 的实战路线。
> 全部代码使用 LangChain 1.x + LangGraph 1.x 的最新 API。

---

## 0. 30 秒决策 (先看这一段)

### 学什么

| 层 | 项目 | 定位 | 本路线对应模块 |
|---|------|------|--------------|
| L1 | **LangChain 1.x** | Agent Framework | `01-…` 5 个模块 |
| L2 | **LangGraph 1.x** | Orchestration Runtime | `02-…` 5 个模块 |
| L3 | **LangSmith** | Agent Platform | `03-…` 2 个模块 |
| L4 | **Multi-Agent** | L2 之上 | `04-…` 3 个模块 |
| L5 | **Deep Agents** | L2 之上的高级 Harness | `05-…` 1 个模块 |
| L6 | **OPC AI Product** | 整合 L1-L5 的可赚钱产品 demo | `06-…` 1 个模块 |

> 旧 `langchain.chains` / `initialize_agent` / `langchain.memory` 全部跳过，已经过时。

### 不学什么

| 不学 | 原因 |
|------|------|
| `LLMChain` / `ConversationChain` | 已被 `create_agent` 取代 |
| `initialize_agent` / `AgentExecutor` 老 API | 已被 `create_agent` 取代 |
| `langchain.memory.ConversationBufferMemory` 等 | LangGraph 持久化已经覆盖 |
| `langchain_community.chat_models` | 1.0 已删除，独立包 `langchain-ollama` |
| `langchain.text_splitter` | 拆出独立包 `langchain-text-splitters` |
| 自手写 tool-calling loop | `create_agent` 内置 5+ 轮 |

---

## 1. 总览：6 层路线图

```text
                            ┌─────────────────────────────────┐
                            │  L6  OPC AI 产品 (端到端 demo)   │
                            │  整合 L1-L5,可上线形态           │
                            └─────────────────────────────────┘
                                                ▲
                                                │
                            ┌─────────────────────────────────┐
                            │  L5  Deep Agents                 │
                            │  planning / subagents / FS       │
                            └─────────────────────────────────┘
                                                ▲
                            ┌─────────────────────────────────┐
                            │  L4  Multi-Agent                 │
                            │  supervisor / handoff / swarm    │
                            └─────────────────────────────────┘
                                                ▲
                            ┌─────────────────────────────────┐
                            │  L3  LangSmith 平台              │
                            │  trace / evaluate / production   │
                            └─────────────────────────────────┘
                                                ▲
                            ┌─────────────────────────────────┐
                            │  L2  LangGraph 编排              │
                            │  state / node / edge / ckpt /    │
                            │  interrupt / streaming           │
                            └─────────────────────────────────┘
                                                ▲
                            ┌─────────────────────────────────┐
                            │  L1  LangChain 1.x Agent Frame   │
                            │  model / tool / agent /          │
                            │  middleware / retrieval          │
                            └─────────────────────────────────┘
```

---

## 2. L1 — LangChain 1.x Agent Framework

**目标**: 知道 "一个 Agent 怎么拼出来"。

| 模块 | 关键 API | 学到什么 |
|------|---------|---------|
| `01_models.py` | `init_chat_model` / `BaseChatModel` / `bind_tools` / structured output | 怎么换 provider、怎么让模型吐出结构化 JSON |
| `02_tools.py` | `@tool` 装饰器 / `BaseTool` 子类 / `args_schema` | 怎么把 Python 函数 / 类 / API 暴露给 LLM |
| `03_agents.py` | `create_agent` | 1.0 统一入口,5+ 轮 tool loop 内置 |
| `04_middleware.py` | `@dynamic_prompt` / `@wrap_model_call` / `HumanInTheLoopMiddleware` | 在模型调用前后插桩 |
| `05_retrieval.py` | `Embeddings` / `VectorStore` / `Retriever` | 文档加载 → 切块 → 嵌入 → 检索 → 接 Agent |

**练完 L1 你能回答**:
- "我有一个客服问题 → 查订单库 → 回信", 怎么写?
- "我想在调用 LLM 前先做敏感词过滤", 怎么写?
- "我想给 Agent 接私有知识库", 怎么写?

---

## 3. L2 — LangGraph 编排 (生产关键)

**目标**: 让 Agent 在真实生产环境**可靠地跑**。

| 模块 | 关键概念 | 学到什么 |
|------|---------|---------|
| `06_state_graph.py` | `StateGraph` / `MessagesState` / `add_node` / `add_edge` / `add_conditional_edges` | 把 Agent 拆成图,自定义 routing |
| `07_persistence.py` | `InMemorySaver` / `PostgresSaver` / `thread_id` / `store` | 长对话状态保存 + 跨进程恢复 |
| `08_interrupt_hitl.py` | `interrupt()` / `Command(resume=...)` | 危险操作前暂停,等人工审批 |
| `09_streaming.py` | `stream` / `astream_events` / `messages` mode / `updates` mode | token 级 / 节点级流式输出 |
| `10_durable_execution.py` | checkpoint + replay + time travel | 故障恢复 + 审计 + 重放 |

**练完 L2 你能回答**:
- "用户说了一半下次回来还要续上", 怎么存?
- "Agent 要执行退款,需要主管审批", 怎么等?
- "Agent 跑了一半进程挂了", 怎么不丢状态?
- "前端要流式打字机效果", 怎么输出?

---

## 4. L3 — LangSmith 平台

**目标**: 上线后**看得见** + **能量化**。

| 模块 | 关键能力 | 学到什么 |
|------|---------|---------|
| `11_langsmith_tracing.py` | `LANGSMITH_TRACING=true` / `@traceable` | 每一次 LLM 调用都有 trace,排查问题 |
| `12_langsmith_evaluation.py` | datasets / evaluators / experiments | 离线打分,A/B 测试 prompt 改动 |

**练完 L3 你能回答**:
- "上周一次失败的对话到底哪一步错了?"
- "换 prompt 后平均质量提升多少?"

---

## 5. L4 — Multi-Agent 编排

**目标**: 复杂任务需要多个 Agent 协作。

| 模块 | 模式 | 适用场景 |
|------|------|---------|
| `13_supervisor.py` | 中央调度器派发 | 任务清晰、节点稳定 |
| `14_handoff.py` | Agent 之间转交控制权 | 对话路由、专家转移 |
| `15_swarm.py` | 群智,Agent 动态互通 | 协作型 / 探索型任务 |

---

## 6. L5 — Deep Agents

**目标**: 长任务 + 复杂规划 + 文件系统 + 子 Agent。

- `create_deep_agent` 一行起手
- 自动 planning / TODO 管理
- subagent 委派
- 虚拟文件系统工具

---

## 7. L6 — OPC AI 产品端到端

**目标**: 把 L1-L5 串成一个**真实形态**的 OPC 产品。

场景: 一个"AI 售前顾问",能:
1. 接听用户问题 (L1 Tool + L4 Handoff)
2. 查订单 / 查产品 (L1 Tool)
3. 内部走退款流程前等主管审批 (L2 HITL)
4. 知识库回答技术问题 (L1 Retrieval)
5. 整个过程可追溯 (L3 Trace)
6. 多 Agent 协作 (L4 Supervisor)
7. 长对话恢复 (L2 Persistence)

---

## 8. 学完每层之后的"里程碑验收"

| 层 | 验收标准 |
|---|---------|
| L1 | 独立写一个查天气 + 查日历的 Agent |
| L2 | 写一个图:分析→查工具→人工审批→写入 DB |
| L3 | 在 LangSmith 上看到自己 Agent 的 trace |
| L4 | 写一个 supervisor 协调 3 个专家 Agent |
| L5 | 写一个 deep agent,完成 5 步复杂任务 |
| L6 | OPC demo 端到端跑通,有前端 |

---

## 9. 推荐阅读顺序

```text
读 readme.md (官方定位)
   ↓
读 ROADMAP.md (本文)
   ↓
L1 → L2 → L3 → L4 → L5 → L6
   ↓
每个模块顺序: README.md → 对应 .py → 跑起来
   ↓
做 OPC 集成 demo (L6)
```

---

## 10. 必备依赖 (requirements.txt)

```text
langchain>=1.0
langchain-openai>=1.0           # OpenAI 兼容协议 (含 MiniMax / Ollama / DeepSeek)
langchain-ollama>=1.0            # Ollama (可选,如果用本地模型)
langgraph>=1.0
langchain-text-splitters>=1.0
langsmith>=0.4
deepeval>=2.0                    # 离线评估 (L3)
pydantic>=2.0
python-dotenv>=1.0
```

---

## 11. 环境变量

```bash
# MiniMax M3 (默认)
export MINIMAX_API_KEY="..."
export MINIMAX_BASE_URL="https://api.minimaxi.com/v1"  # 实际 endpoint 替换

# LangSmith (L3 需要)
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY="..."
export LANGSMITH_PROJECT="0401-langchain-langgraph-v1"

# OpenAI 兼容备选
export OPENAI_API_KEY="..."
```
