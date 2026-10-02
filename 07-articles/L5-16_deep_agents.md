# L5-16 · Deep Agents:长任务 Agent Harness

> 客服 Agent 通常 5-10 步就结束,但"深度研究"类任务常常跑几十分钟甚至几小时——中途要规划(TODO)、要落中间结果(FS)、要并行子任务(subagent)、还要自动压缩历史(context summary)。`create_agent` 不够用。Deep Agents 是 LangChain 团队在 LangGraph 之上封装的 harness,把这些能力全部内置。这篇拆 10 个 demo,从 TODO 管理到虚拟文件系统到 subagent 委派。

## 为什么学这个

`create_agent` 适合"短任务":

- 客服对话(5-10 步)
- 简单工具调用
- 单次任务

但"长任务"需要更多:

| 长任务需求 | create_agent | Deep Agents |
|---|---|---|
| 规划(TODO) | 自己写 prompt | ✓ 内置 `write_todos` |
| 中间结果存档 | 写到 messages 里撑爆 | ✓ 虚拟文件系统 |
| 子任务委派 | 自己实现 | ✓ `task(subagent_type)` |
| Context 压缩 | SummarizationMW | ✓ 内置 token 压缩 |
| 失败重试 | 自己实现 | harness 自带 |
| 任务持久化 | checkpointer | ✓ 推荐 PostgresSaver |

实战 Deep Agents 适用场景:

- "调研 AI Agent 发展史,写份报告"——研究类
- "分析这个 codebase 找 5 个 bug"——代码分析类
- "从 100 份合同里提取关键条款"——长任务批处理

## 学完你能回答 10 个问题

1. Deep Agents vs create_agent 区别在哪(为什么需要 deep agents)?
2. Deep Agent 内置的 TODO 工具怎么用?
3. 虚拟文件系统怎么读写(state.files)?
4. 怎么定义 subagents 委派子任务?
5. Deep Agent 怎么接 HITL?
6. Deep Agent 怎么接 middleware?
7. Deep Agent 怎么流式输出?
8. 怎么用 Deep Agent 做"长任务"(数小时研究)?
9. Deep Agent 失败 / 重试怎么处理?
10. 生产里 Deep Agent 怎么落地?

## 0. 安装

```bash
pip install deepagents
```

deepagents 是 LangChain 团队官方包,装不上时本文 demo 自动 fallback 到 `create_agent` + LangGraph StateGraph 演示等价功能。

## 1. 最简 Deep Agent

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=get_llm(),
    system_prompt="你是一个深度研究助手, 回答要全面、有条理。",
)

result = agent.invoke(
    {"messages": [HumanMessage("LangChain 1.0 的 3 大核心改进是什么?")]}
)
print(result["messages"][-1].content)
```

Deep Agent 关键能力(create_agent 没有的):

- ✓ 自动 TODO 规划:`write_todos` / `read_todos`
- ✓ 虚拟文件系统:`write_file` / `read_file` / `ls`
- ✓ Subagent 委派:`task(description, subagent_type)`
- ✓ Context 摘要:token 超限自动压缩历史

## 2. Deep Agent + 自定义工具

```python
@tool
def search_web(query: str) -> str:
    """(mock) 网络搜索."""
    return f"搜索结果: 关于 {query} 的 3 篇文档..."


@tool
def write_file(filename: str, content: str) -> str:
    """(mock) 写入文件."""
    return f"已写入 {filename}, {len(content)} 字"


agent = create_deep_agent(
    model=get_llm(),
    tools=[search_web, write_file],
    system_prompt="研究一个主题, 搜资料, 写成报告文件。",
)

result = agent.invoke(
    {"messages": [HumanMessage("研究 AI Agent 的发展史, 写份 500 字报告到 report.md")]}
)
# state.files 里能看到 report.md
```

实战:Deep Agent 适合"研究 + 写报告"这种**多步 + 中间产物**的任务。

## 3. Subagents — 委派子任务

```python
research_agent = {
    "name": "research-agent",
    "description": "负责搜索资料, 适合需要事实查询的任务",
    "system_prompt": "你是研究员, 简明扼要地给关键事实, 不超过 100 字。",
}
writer_agent = {
    "name": "writer-agent",
    "description": "负责把素材写成通顺文字",
    "system_prompt": "你是写作者, 把给的素材整理成 50 字短文。",
}

main_agent = create_deep_agent(
    model=get_llm(),
    subagents=[research_agent, writer_agent],
    system_prompt="你是主编。需要研究时调 research-agent, 需要写作时调 writer-agent。",
)
```

Subagent 实战优势:

- **上下文隔离**:subagent 看不到主 agent 的全 history(防止撑爆)
- **角色分工**:不同 subagent 不同的 system_prompt / tools
- **并行**:deepagents 自动并行多个 task 调用
- **节省 token**:简单子任务不污染主上下文

## 4. 虚拟文件系统

```python
agent = create_deep_agent(
    model=get_llm(),
    system_prompt="先 write_todos 列计划, 然后逐项执行, 最后写到 final.md",
)

result = agent.invoke({"messages": [HumanMessage("研究 LangGraph 1.0 的 5 个核心特性")]})

files = result.get("files", {})
for name, content in files.items():
    print(f"  - {name}: {len(content)} chars")
```

虚拟 FS vs 真实 FS:

| 维度 | 虚拟 FS(Deep Agent) | 真实 FS |
|---|---|---|
| 存储位置 | state 里 | 磁盘 |
| 跨 checkpoint | ✓ 自动保留 | 落盘永久 |
| 跨进程 | 跟 checkpointer 走 | 直接共享 |
| 大文件 / 二进制 | ✗ 不适合 | ✓ 适合 |
| 中间结果 / 配置 | ✓ 适合 | OK |

实战:中间结果用虚拟 FS,大文件 / 报告输出用真实 FS。

## 5. TODO 管理 — 规划能力

```python
agent = create_deep_agent(
    model=get_llm(),
    system_prompt="先 write_todos 列计划, 再逐项执行",
)

result = agent.invoke({"messages": [HumanMessage("3 步搞定市场调研报告")]})

todos = result.get("todos", [])
for t in todos:
    print(f"  - [{t.get('status', '?')}] {t.get('content', '')[:60]}")
```

TODO 实战价值:

- **长任务**:让 agent 自己拆解步骤,不会半路跑偏
- **用户可见**:把 todos 显示在 UI 上("AI 正在做 3/8")
- **失败恢复**:某个 todo 失败,可以重跑该 todo(不重头开始)

## 6. Deep Agent + HITL — 关键操作人工审批

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt

@tool
def dangerous_op(payload: str) -> str:
    """(mock) 高风险操作, 需要人工审批."""
    decision = interrupt({"op": "dangerous", "payload": payload})
    if decision != "approve":
        return f"已取消: {decision}"
    return f"已执行: {payload}"


# Deep Agent 的 HITL 思路:
# 1. 在自定义工具里调 interrupt(...)
# 2. agent 编译时带 checkpointer=InMemorySaver / PostgresSaver
# 3. invoke 触发 interrupt 后, 用 app.get_state(config) 看暂停点
# 4. 主管审批 → app.invoke(Command(resume="approve"), config)
```

实战:Deep Agent 的高风险操作(发邮件 / 改数据库 / 调付费 API)一律走 interrupt。

## 7. Deep Agent + Middleware

```python
from langchain.agents.middleware import wrap_model_call

@wrap_model_call
def logging_middleware(request, handler):
    """日志中间件: 打印每次 LLM 调用的消息数."""
    n = len(request.messages)
    print(f"  [middleware] LLM 调用, {n} 条消息")
    return handler(request)


agent = create_deep_agent(
    model=get_llm(),
    tools=[],
    system_prompt="你是助手",
    middleware=[logging_middleware],
)
```

支持的 middleware 类型:

| 类型 | 用途 |
|---|---|
| `wrap_model_call` | 包 LLM 调用(PII 脱敏 / 限流) |
| `wrap_tool_call` | 包工具调用(权限校验) |
| `before_model` | 调 LLM 前(动态 prompt) |
| `after_model` | 调 LLM 后(摘要 / 校验) |

实战:PII 脱敏、token 计数、日志、限流、风控——Deep Agent 全支持。

## 8. Deep Agent 流式输出

```python
agent = create_deep_agent(
    model=get_llm(),
    system_prompt="你要研究主题, 先 TODO 规划, 然后用工具搜集",
)

for chunk in agent.stream(
    {"messages": [HumanMessage("研究 RAG 的 3 个核心组件")]},
    stream_mode="updates",
):
    for node, delta in chunk.items():
        if "messages" in delta:
            print(f"  [step] {node}: {len(delta['messages'])} new msg(s)")
```

实战:长任务时,前端能看到"AI 正在查资料 / 正在写报告 / 正在审稿"的进度。

## 9. Deep Agent vs create_agent — 选型

| 维度 | create_agent | create_deep_agent |
|---|---|---|
| 用法 | LangChain 1.x 内置 | deepagents 包(LangGraph 之上封装) |
| 内置 TODO | ✗ 需自己写 prompt | ✓ 自动 write_todos |
| 内置 FS | ✗ 需自己写工具 | ✓ write_file / read |
| Subagent | ✗ 需自己实现 | ✓ task 委派 |
| Context 摘要 | ✗ 需 SummarizationMW | ✓ 内置 token 压缩 |
| 适用 | 单步 / 多步工具调用 / 简单 chatbot | 长任务(小时级)/ 深度研究 / 编程 |
| 依赖 | langchain 1.x | + deepagents |
| 上手 | 简单 | 中等(要学新 API) |

选型:

- 客服 / 简单 chatbot → `create_agent`
- 长任务(研究 / 编程) → `create_deep_agent`
- 已有 LangGraph pipeline → 继续用 LangGraph(不强制 deepagents)

## 10. 生产架构 — Deep Agent 落地

```python
# 1. 必须 checkpointer (因为 Deep Agent 是长任务)
from langgraph.checkpoint.postgres import PostgresSaver
DB = "postgresql://..."
with PostgresSaver.from_conn_string(DB) as cp:
    agent = create_deep_agent(
        model=llm,
        tools=[...],
        subagents=[...],
        checkpointer=cp,  # 关键
    )

# 2. thread_id 设计
config = {"configurable": {"thread_id": "research-task-001"}}

# 3. token / 步数限制 (防 LLM 失控)
config = {
    "configurable": {"thread_id": "..."},
    "recursion_limit": 50,  # 节点最多执行 50 次
}

# 4. 异步化 (长任务不要同步等)
result = await agent.ainvoke(input, config=config)

# 5. 流式给前端 (用户能看到进度)
async for chunk in agent.astream(input, stream_mode="updates"):
    yield f"data: {json.dumps(chunk)}\n\n"

# 6. 中间结果存 DB (任务跨进程可恢复)
#    PostgresSaver 自动做这件事

# 7. 监控: LangSmith 自动 trace + 自己的 dashboard
#    - TODO 完成率
#    - 平均任务时长
#    - 失败率
```

关键实践:

- 必须持久化(PostgresSaver),不能 InMemory
- 任务可恢复(interrupt + resume)
- 用户能看到进度(stream TODO 状态)
- 失败重试(单 TODO 失败 vs 整个 agent 失败)

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| 状态没保留 | 没用 checkpointer | 必须 PostgresSaver |
| TODO 没拆解 | LLM 不主动调 write_todos | system_prompt 强约束 |
| 虚拟 FS 撑爆 | 大文件塞 state | 大文件写真实 FS |
| Subagent 上下文不全 | 隔离设计 | 主 agent 显式传 payload |
| Cost 失控 | LLM 多次调用 + 长 context | budget 限制 + 摘要 |
| 死循环 | subagent 互相调用 | max_handoffs + recursion_limit |

## 小结

- Deep Agents = LangGraph 之上的长任务 harness
- 内置 TODO 管理 + 虚拟文件系统 + subagent + context 摘要
- 适用场景:研究 / 编程 / 长任务(小时级)
- 必须配 checkpointer(PostgresSaver)
- Subagent 上下文隔离,节省 token
- 选型:短任务用 create_agent,长任务用 create_deep_agent
- 生产落地:PostgresSaver + LangSmith trace + 流式进度

Deep Agents 让长任务"规划 + 落地 + 恢复"全有。下一步用 **真实业务场景** 把 L1-L5 全串起来——L6-17 OPC 端到端 demo 见。

## 延伸阅读

- [Deep Agents GitHub](https://github.com/langchain-ai/deepagents)
- [LangGraph Durable Execution](https://langchain-ai.github.io/langgraph/concepts/durable_execution/)
- 上一篇:[L4-15 Swarm 多向协作](./L4-15_swarm.md)
- 下一篇:[L6-17 OPC 端到端 demo](./L6-17_opc_product.md)
- 源码:`05-deep-agents/16_deep_agents.py`
