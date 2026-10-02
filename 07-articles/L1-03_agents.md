# L1-03 · create_agent 一统天下:LangChain 1.0 的 Agent 入口

> LangChain 1.x 把 Agent 入口收敛成一个函数 `create_agent(model, tools, ...)`。内部构建完整 StateGraph,业务代码只需要"传 model + tools"就能跑。这篇拆 10 个 demo,从最简到生产架构全覆盖。

## 为什么学这个

如果你 2026 年要写一个 AI Agent,99% 的场景用 `create_agent` 就够了。LangChain 团队把「model + tools + memory + 审批 + 流式」封装成一个函数,内部是完整的 LangGraph 图:

```
START → model → (有 tool_calls?) → tools → model → ... → END
```

业务代码不用关心图怎么连,只需要 10 个参数。

但只看 `create_agent(model, tools)` 只能跑 demo,生产里要管:

- 多轮对话(checkpointer)
- 结构化输出(response_format)
- 自定义 state(state_schema)
- 运行时上下文(context_schema)
- 横切关注点(middleware)
- 人工审批(interrupt_before)
- 流式输出(stream_mode)
- 死循环兜底(recursion_limit)

## 学完你能回答 10 个问题

1. `create_agent` 内部构建的图长什么样?
2. `system_prompt` 怎么传?(字符串 vs callable)
3. 怎么让 Agent 输出结构化 Pydantic 结果?
4. 多轮对话怎么存?(checkpointer + thread_id)
5. 怎么扩展 state 字段?(state_schema + reducer)
6. 怎么注入运行时上下文?(context_schema)
7. middleware 怎么拦截 pre/post-model?
8. 怎么在工具调用前人工审批?(interrupt_before)
9. stream 有几种模式?(values / updates / messages)
10. 死循环怎么兜底?(recursion_limit)

## 1. 最简 Agent

```python
from langchain.agents import create_agent
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """查某城市天气 (mock)。"""
    return f"{city} 晴, 25°C"

agent = create_agent(model=llm, tools=[get_weather])

result = agent.invoke({"messages": [HumanMessage("北京天气?")]})
print(result["messages"][-1].content)
```

返回值是 state(dict),`messages` 字段是完整的对话历史(含 HumanMessage / AIMessage / ToolMessage)。

> 跟 Spring Bean 装配 / Gin route 注册一样——声明式 + 图化。

## 2. system_prompt 注入

```python
agent = create_agent(
    model=llm,
    tools=[get_weather],
    system_prompt="你是简短的天气助手, 回答不超过 20 字。",
)
```

`system_prompt` 也支持 callable,根据 state 动态生成:

```python
system_prompt=lambda state: f"用户偏好: {state.get('preferences', {})}"
```

适用多租户 / 动态角色场景。

## 3. 结构化输出 `response_format`

```python
from pydantic import BaseModel, Field

class WeatherReport(BaseModel):
    city: str
    temperature: int = Field(description="摄氏度")
    condition: str = Field(description="晴/多云/雨 等")

agent = create_agent(
    model=llm,
    tools=[get_weather],
    response_format=WeatherReport,
    system_prompt="必须调用 get_weather, 然后用 WeatherReport 结构返回。",
)

result = agent.invoke({"messages": [HumanMessage("深圳?")]})
sr = result.get("structured_response")
print(sr.city, sr.temperature, sr.condition)
```

`result["structured_response"]` 自动是 `WeatherReport` 实例,不用解析。

> ⚠️ 推理模型(M3 / DeepSeek-R1)结构化输出不稳,prompt 必须强约束"只返回结构化数据"才稳。

## 4. 多轮对话:checkpointer

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

config = {"configurable": {"thread_id": "user-001"}}

# 第 1 轮
agent.invoke({"messages": [HumanMessage("我叫王明")]}, config=config)
# 第 2 轮:同 thread_id,LLM 看到历史
r = agent.invoke({"messages": [HumanMessage("我叫什么?")]}, config=config)
```

`thread_id` 是会话唯一标识:

| 设计 | 适用 |
| --- | --- |
| `"user-001"` | 单用户单会话 |
| `"user-001-conv-A"` | 单用户多会话 |
| `"team-123-thread-456"` | 团队协作 |

不同 `thread_id` 互不干扰。

生产用 `PostgresSaver`,进程重启 / 多副本共享(L2-07 详讲)。

## 5. 扩展 state:state_schema + reducer

业务要在 state 里加自定义字段:

```python
from langchain.agents.middleware import AgentState
from typing_extensions import Annotated
from operator import add as add_int

class CustomState(AgentState):
    user_id: str = "anonymous"
    turn_count: Annotated[int, add_int] = 0  # reducer, 自动累加

agent = create_agent(
    model=llm,
    tools=[get_weather],
    state_schema=CustomState,
)
```

`Annotated[int, add_int]` 是 reducer,每次 invoke 自动累加:

| 字段 | reducer | 行为 |
| --- | --- | --- |
| 无 | 默认 | 整体覆盖 |
| `Annotated[..., add_int]` | 累加 | 数值 / list 自动合并 |
| `Annotated[..., add_messages]` | 智能 | message 自动去重 |

## 6. 运行时上下文:`context_schema`

跟 state 区别:context 是**不可变配置**(user_id / locale / feature_flags),每次 invoke 注入,LLM 看不到但工具能拿到。

```python
from pydantic import BaseModel

class AppContext(BaseModel):
    user_id: str = "anonymous"
    locale: str = "zh-CN"

agent = create_agent(
    model=llm,
    tools=[get_personalized_greeting],
    context_schema=AppContext,
)

result = agent.invoke(
    {"messages": [HumanMessage("杭州?")]},
    context=AppContext(user_id="U-Alice", locale="zh-CN"),
)
```

context 注入到工具的方式:配合 `InjectedToolArg`(`user_id: Annotated[str, InjectedToolArg]`)。

| 类型 | 用途 | 谁改 |
| --- | --- | --- |
| `state` | 业务数据(messages / turn_count / 业务字段) | reducer / 节点 |
| `context` | 配置(user_id / locale / feature_flags) | 每次 invoke 注入 |

## 7. middleware:横切关注点

```python
from langchain.agents.middleware import before_model, after_model

@before_model
def log_before(state: AgentState, runtime):
    """调 LLM 前跑。可以返回 dict 改 state,返回 None 不改."""
    print(f"准备调 LLM, 最新消息: {type(state['messages'][-1]).__name__}")
    return None

@after_model
def log_after(state: AgentState, runtime):
    """LLM 返回后、跑工具前."""
    print(f"LLM 返回: {type(state['messages'][-1]).__name__}")
    return None

agent = create_agent(
    model=llm,
    tools=[get_weather],
    middleware=[log_before, log_after],
)
```

middleware 实战用途:

| 用途 | 哪个 hook |
| --- | --- |
| 审计日志 | `before_model` |
| PII 脱敏 | `wrap_model_call` |
| token 计数 | `after_model` |
| 安全护栏 | `after_model` raise |

更 powerful 的 hook(`wrap_model_call` / `wrap_tool_call`)在 L1-04 middleware 详讲。

## 8. 工具调用前人工审批:`interrupt_before`

```python
from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver

agent = create_agent(
    model=llm,
    tools=[get_weather],
    interrupt_before=["tools"],  # 在所有 "tools" 节点前暂停
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "approval-demo"}}

# 第 1 次 invoke:Agent 决定调工具 → 在 tools 节点前暂停
agent.invoke(
    {"messages": [HumanMessage("北京天气? 你必须调工具。")]},
    config=config,
)

# 检查 state 看是否真的暂停
state = agent.get_state(config)
if state.tasks and any(t.interrupts for t in state.tasks):
    # 主管审批 → 恢复
    result = agent.invoke(Command(resume=None), config=config)
```

HITL 适用:

- 删数据 / 改配置 / 调付费 API——必须人工点头
- 医疗 / 金融合规场景
- LLM 决策有风险的场景

> ⚠️ 小模型(M3 / DeepSeek-V3)经常不调工具直接答,interrupt 根本不触发。检查方式:`state.tasks`,没 interrupt 就别 `resume`,会挂死。

## 9. stream 三种模式

```python
# mode="values": 每步返回完整 state 快照
for chunk in agent.stream(input, stream_mode="values"):
    print(chunk["messages"][-1].content)

# mode="updates": 每步返回 state delta {node_name: delta}
for chunk in agent.stream(input, stream_mode="updates"):
    for node, delta in chunk.items():
        print(f"[{node}] {len(delta.get('messages', []))} new msg")

# mode="messages": LLM token 级流(像 ChatGPT 打字机)
for token_msg, metadata in agent.stream(input, stream_mode="messages"):
    if hasattr(token_msg, "content") and token_msg.content:
        print(token_msg.content, end="", flush=True)
```

| 模式 | 用途 |
| --- | --- |
| `values` | 调试、看完整 state |
| `updates` | 前端 patch 风格 |
| `messages` | 打字机流式(SSE 推前端) |

## 10. 死循环兜底:`recursion_limit`

```python
@tool
def infinite_lookup(query: str) -> str:
    """(故意) 永远让 Agent 再查一次。"""
    return "没找到, 请再查一次"

agent = create_agent(model=llm, tools=[infinite_lookup])

try:
    agent.invoke(
        {"messages": [HumanMessage("找一个不存在的东西")]},
        config={"recursion_limit": 5},
    )
except GraphRecursionError as e:
    print(f"兜底成功: {e}")
```

`recursion_limit` 限制图的递归步数,超限抛 `GraphRecursionError`。

实战建议:

| Agent 类型 | recursion_limit |
| --- | --- |
| 简单 chatbot | 默认 25 |
| 复杂 RAG(多次检索) | 50+ |
| 调外部 API 多的 | 调低(省钱 + 快速失败) |

## 实战踩坑

| 坑 | 原因 | 解法 |
| --- | --- | --- |
| `result["__interrupt__"]` 不存在 | LangChain 1.x 改了 API | 用 `state.tasks[0].interrupts` |
| M3 / DeepSeek-R1 不调工具 | 小模型工具能力弱 | prompt 强约束 "必须调 XX 工具" |
| `Command(resume=None)` 挂死 | 没有真 interrupt 也调 resume | 先 `check state.tasks` 再决定 |
| `structured_response` 为 None | 推理模型没强约束 | 加 system_prompt 强制要求 |
| 多轮对话历史太长爆 token | 没收口 | 加 `SummarizationMiddleware` |
| `create_agent` import 不到 | langchain 版本不对 | `pip install langchain==1.0.2` |

## 生产架构

```python
# 生产标配
agent = create_agent(
    model=llm,
    tools=business_tools,
    system_prompt=PROD_PROMPT,
    response_format=BusinessSchema,  # 结构化输出
    state_schema=CustomState,        # 业务字段
    context_schema=AppContext,        # 运行时配置
    middleware=[pii_mw, audit_mw],   # 横切
    checkpointer=PostgresSaver(...), # 跨进程持久
    interrupt_before=["dangerous_tool"],  # 高危审批
)

# 调用
config = {"configurable": {"thread_id": user_id}}
result = agent.invoke(input, config=config, context=AppContext(...))
```

## 小结

- `create_agent(model, tools)` 是 LangChain 1.x 统一入口,内部是完整图
- `response_format=Pydantic` 让结果结构化
- `checkpointer + thread_id` 支持多轮 + 持久化
- `state_schema + context_schema` 区分可变 state / 不可变 context
- `middleware` 切横切关注点
- `interrupt_before` 在危险工具前暂停等审批
- `stream_mode="messages"` 给前端打字机效果
- `recursion_limit` 兜底死循环

`create_agent` 搞定了"调用层"。接下来要解决"生产里的横切问题"——下一篇 Middleware 展开讲 PII / 日志 / 风控。

## 延伸阅读

- [LangChain create_agent 文档](https://python.langchain.com/docs/concepts/agents/)
- 上一篇:[L1-02 Tools 工具系统](./L1-02_tools.md)
- 下一篇:[L1-04 Middleware 横切关注点](./L1-04_middleware.md)
- 源码:`01-langchain-basics/03_agents.py`
