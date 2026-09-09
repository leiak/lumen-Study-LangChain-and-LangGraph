LangChain **2026 年 9 月的官方文档**。([Docs by LangChain][1])

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
