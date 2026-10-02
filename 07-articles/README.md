# 0401-langchain-langgraph-v1 — 通勤阅读系列

> 把 LangChain 1.x + LangGraph 1.x 实战教程浓缩成 17 篇技术文章,一篇一篇地铁上看。

## 适合谁

- 有 Python 基础,想入门 AI Agent 工程化
- Java/Go 后端转 AI Agent 的工程师
- 在通勤路上用手机刷技术,晚上回家敲代码验证

## 怎么读

每篇文章 = 一个 `.py` 文件的全方位解读。结构固定:

1. **为什么要学这个**(痛点 / 业务场景)
2. **学完你能回答 N 个问题**(知识图谱)
3. **10 个 demo 拆解**(从最简到生产)
4. **实战踩坑**(版本坑 / 性能坑 / 架构坑)
5. **生产架构**(怎么从 demo 到上线)
6. **延伸阅读**(相关链接 / 下一步)

## 目录

### L1 — LangChain 基础(5 篇)

| 序号 | 文章 | 对应代码 |
| --- | --- | --- |
| L1-01 | [接入任何 LLM,5 分钟跑通第一个 Agent](./L1-01_models.md) | `01_models.py` |
| L1-02 | [工具系统:把 Python 函数变成 LLM 能调的东西](./L1-02_tools.md) | `02_tools.py` |
| L1-03 | [create_agent 一统天下:LangChain 1.0 的 Agent 入口](./L1-03_agents.md) | `03_agents.py` |
| L1-04 | [Middleware 横切:AOP 思想在 Agent 上的实现](./L1-04_middleware.md) | `04_middleware.py` |
| L1-05 | [RAG 入门:给 Agent 接私有知识库](./L1-05_retrieval.md) | `05_retrieval.py` |

### L2 — LangGraph 编排(5 篇)

| 序号 | 文章 | 对应代码 |
| --- | --- | --- |
| L2-06 | [StateGraph:把 Agent 拆成可编排的图](./L2-06_state_graph.md) | `06_state_graph.py` |
| L2-07 | [持久化与 Checkpointer:多轮对话的"记忆"](./L2-07_persistence.md) | `07_persistence.py` |
| L2-08 | [HITL 人工介入:让 Agent 在关键决策前暂停](./L2-08_interrupt_hitl.md) | `08_interrupt_hitl.py` |
| L2-09 | [流式输出:前端打字机效果怎么实现](./L2-09_streaming.md) | `09_streaming.py` |
| L2-10 | [Durable Execution:进程挂了状态不丢](./L2-10_durable_execution.md) | `10_durable_execution.py` |

### L3 — LangSmith 可观测(2 篇)

| 序号 | 文章 | 对应代码 |
| --- | --- | --- |
| L3-11 | [LangSmith Tracing:让每一步 Agent 调用都看得见](./L3-11_langsmith_tracing.md) | `11_langsmith_tracing.py` |
| L3-12 | [LangSmith Evaluation:给 Agent 装考试系统](./L3-12_langsmith_evaluation.md) | `12_langsmith_evaluation.py` |

### L4 — 多智能体(3 篇)

| 序号 | 文章 | 对应代码 |
| --- | --- | --- |
| L4-13 | [Supervisor 模式:中央路由调度专家 Agent](./L4-13_supervisor.md) | `13_supervisor.py` |
| L4-14 | [Handoff 模式:Agent 主动转交给同伴](./L4-14_handoff.md) | `14_handoff.py` |
| L4-15 | [Swarm 模式:多 Agent 动态协作](./L4-15_swarm.md) | `15_swarm.py` |

### L5 — Deep Agents(1 篇)

| 序号 | 文章 | 对应代码 |
| --- | --- | --- |
| L5-16 | [Deep Agents:长任务 Agent 的高级 Harness](./L5-16_deep_agents.md) | `16_deep_agents.py` |

### L6 — 端到端产品 demo(1 篇)

| 序号 | 文章 | 对应代码 |
| --- | --- | --- |
| L6-17 | [OPC AI 客服中心:把 L1-L5 串成产品](./L6-17_opc_product.md) | `17_opc_product.py` |

## 阅读建议

- **入门路径**(一周刷完):L1 全部 + L2 前 3 篇
- **进阶路径**(两周):L1 + L2 全部 + L4
- **生产路径**(三周):全部 17 篇 + 跑通 `17_opc_product.py`

## 关于本教程

- 全部基于 LangChain 1.0.2 + LangGraph 1.0 系列
- LLM 默认用 OpenAI 兼容协议,可切 Anthropic / DeepSeek / MiniMax
- 代码可以直接 `python XX.py` 跑,失败也有友好提示
- 配套教程仓库: <https://github.com/your/repo>(待补)