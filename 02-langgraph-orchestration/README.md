# L2 — LangGraph 编排

> 5 个模块覆盖 LangGraph 1.x 的核心能力。
> 这一层决定你的 Agent 能不能**在生产环境可靠地跑**。

## 模块清单

| # | 文件 | 关键概念 | 一句话目标 |
|---|------|---------|----------|
| 06 | `06_state_graph.py` | `StateGraph` / `MessagesState` / `add_node` / `add_edge` / `add_conditional_edges` | 把 Agent 拆成图,自定义 routing |
| 07 | `07_persistence.py` | `InMemorySaver` / `PostgresSaver` / `thread_id` / `store` | 长对话状态保存 + 跨进程恢复 |
| 08 | `08_interrupt_hitl.py` | `interrupt()` / `Command(resume=...)` | 危险操作前暂停,等人工审批 |
| 09 | `09_streaming.py` | `stream` / `astream_events` / `messages` mode | token 级 / 节点级流式输出 |
| 10 | `10_durable_execution.py` | checkpoint + replay + time travel | 故障恢复 + 审计 + 重放 |

## 为什么需要 LangGraph?

`create_agent` 适合**简单场景**: 一个 LLM 循环调 tool,直到没 tool 可调就停。

但生产场景你需要:
- **多步 pipeline**: 检索 → 重写 → 调用 LLM → 验证 → 返回
- **人工介入**: 退款前暂停等主管批
- **状态持久化**: 进程挂了状态不丢
- **时间旅行**: 跑错的对话能回退到某一步重新跑
- **流式**: 前端要打字机效果,或节点级进度条

这些就是 LangGraph 提供的。

## 跑起来

```bash
pip install -r ../../requirements.txt
python 06_state_graph.py
python 07_persistence.py
python 08_interrupt_hitl.py
python 09_streaming.py
python 10_durable_execution.py
```

## 学完 L2 你能

1. 用 StateGraph 拼一个多节点的 Agent pipeline
2. 用 checkpointer 存长对话,跨进程恢复
3. 用 interrupt 暂停 Agent 等人工批
4. 用 streaming 给前端输出 token 级流
5. 用 time travel 回退到任意一步重跑

## 关键心智模型

```
StateGraph
   │
   ├── Nodes (节点): 接收 state,返回 state 更新
   ├── Edges (边): 普通连接
   ├── Conditional Edges (条件边): 根据 state 决定下一个节点
   └── Checkpointer (检查点): 每一步都打 snapshot
```
