# L4-14 · Handoff 模式:Agent 自己决定转交给谁

> Supervisor 是"中央调度",所有决策权在 Supervisor 手里。Handoff 反过来:**每个 Agent 自己决定要不要转交,转给谁**。客服"我帮你转技术"就是典型 Handoff。这篇拆 10 个 demo,涵盖从单 agent + handoff tool 到 Supervisor + Handoff 混合模式。

## 为什么学这个

Supervisor 模式的局限:

- 所有路由都要绕一道中央节点(增加延迟)
- 专家之间的协作不够灵活(A 想让 B 帮忙,必须回 Supervisor)
- 中央 Supervisor 是单点故障 / 单点瓶颈

Handoff 模式:

- 每个 agent 自己调"转交工具",控制权直接转移
- 灵活的对话式转接("我帮你转技术")
- 路径由 agent 自己决定,更自然

实战对比:

| 场景 | Supervisor | Handoff |
|---|---|---|
| 客服分流 | ✓ | 可 |
| 客服对话转接 | 一般 | ✓ |
| 内部跨部门协作 | 单点瓶颈 | ✓ |

## 学完你能回答 10 个问题

1. Handoff 工具怎么定义(每个 agent 都能调转交)?
2. `Command(goto=...)` 怎么让 agent 互相跳转?
3. Handoff 时怎么把上下文传过去?
4. `create_agent` + handoff tools 最省事的写法?
5. 双向 handoff(a → b 和 b → a)?
6. Handoff 触发 HITL(主管审批转交)?
7. Handoff 到 subgraph(子图套娃)?
8. Handoff 路径审计(state 里记跳了几次)?
9. Supervisor + Handoff 混合模式怎么搭?
10. 生产架构怎么落地?

## 1. Handoff 工具工厂

```python
def make_handoff_tool(target_agent, description):
    """工厂: 创建一个转交工具."""
    tool_name = f"transfer_to_{target_agent}"

    @tool(tool_name)
    def handoff(reason: str) -> str:
        f"""{description}."""
        return f"[handoff -> {target_agent}] {reason}"

    handoff.name = tool_name
    return handoff


TRANSFER_TO_TECH = make_handoff_tool(
    "tech", "转交给技术专家 (排查 API 报错、技术原理)。参数 reason 写明转交原因"
)
TRANSFER_TO_SALES = make_handoff_tool(
    "sales", "转交给售前专家 (产品功能、价格、推荐)。参数 reason 写明转交原因"
)
TRANSFER_TO_SUPPORT = make_handoff_tool(
    "support", "转交给售后专家 (订单查询、退款、物流)。参数 reason 写明转交原因"
)
```

实战:工具描述是 LLM 是否正确选择的关键,写清楚**什么时候用、参数是什么**。

## 2. 单 Agent + Handoff Tools

```python
from langchain.agents import create_agent

agent = create_agent(
    model=get_llm(),
    tools=[TRANSFER_TO_TECH, TRANSFER_TO_SALES],
    system_prompt=(
        "你是前台客服。判断用户问题类型: "
        "涉及 API 报错 → 调 transfer_to_tech; "
        "涉及产品功能/价格 → 调 transfer_to_sales; "
        "否则直接回答。"
    ),
)

r = agent.invoke({"messages": [HumanMessage("API 返回 500 错误")]})
# 输出 tool_call: transfer_to_tech(reason="...")
```

实战:create_agent 不会真跳转——只触发 tool_call。要跳转需配合 LangGraph。

## 3. 完整 Handoff Graph — `Command` 跳转

```python
def build_handoff_graph():
    llm = get_llm()

    def make_agent_node(name, description, handoff_tools):
        agent_llm = llm.bind_tools(handoff_tools)
        tools_by_name = {t.name: t for t in handoff_tools}

        def agent_node(state) -> Command:
            system = SystemMessage(content=f"你是「{name}」。{description}")
            msgs = [system] + state["messages"]
            resp = agent_llm.invoke(msgs)

            if resp.tool_calls:
                tc = resp.tool_calls[0]
                if tc["name"].startswith("transfer_to_"):
                    target = tc["name"].replace("transfer_to_", "")
                    return Command(goto=target, update={"messages": [resp]})

            return Command(goto=END, update={"messages": [resp]})

        return agent_node

    sales_node = make_agent_node(
        "售前", "回答产品功能、价格、推荐。",
        [TRANSFER_TO_SUPPORT, TRANSFER_TO_TECH],
    )
    support_node = make_agent_node(
        "售后", "处理订单和退款, 涉及技术问题转技术。",
        [TRANSFER_TO_TECH],
    )
    tech_node = make_agent_node(
        "技术", "回答 API、报错、架构问题。", []
    )

    graph = StateGraph(MessagesState)
    graph.add_node("sales", sales_node)
    graph.add_node("support", support_node)
    graph.add_node("tech", tech_node)
    graph.add_edge(START, "sales")

    return graph.compile()
```

实战:`Command(goto=...)` 是真跳转,所有跳转都通过它,图里不用 `add_conditional_edges`。

## 4. Handoff 时传上下文

```python
class HandoffState(TypedDict):
    messages: Annotated[list, add_messages]
    handoff_count: int
    handoff_path: Annotated[list[str], lambda a, b: a + b]


def sales_node(state) -> Command:
    resp = llm.invoke([SystemMessage("...")] + state["messages"])
    if resp.tool_calls:
        tc = resp.tool_calls[0]
        reason = tc["args"].get("reason", "")
        return Command(
            goto="support",
            update={
                "messages": [resp],
                "handoff_count": state.get("handoff_count", 0) + 1,
                "handoff_path": [f"sales -> support: {reason}"],
            },
        )
    return Command(goto=END, update={"messages": [resp]})
```

实战:Handoff 时把"原因 + 元数据"塞 state,下个 agent 能看到完整上下文。

## 5. create_agent + Handoff Tools — 最简但有坑

```python
agent = create_agent(
    model=get_llm(),
    tools=[TRANSFER_TO_TECH, TRANSFER_TO_SALES],
    system_prompt="你是前台。涉及 API 报错 → transfer_to_tech。",
)
```

⚠️ **坑**:单纯 create_agent 只触发 tool,不会真跳转。要跳转必须:
- 包成 LangGraph 节点
- 在节点里 `Command(goto=...)`

## 6. 双向 Handoff (a ↔ b)

```python
def a_node(state) -> Command:
    resp = llm.invoke(...)
    if resp.tool_calls:
        tc = resp.tool_calls[0]
        if tc["name"] == "transfer_to_support":
            return Command(goto="support", update={"messages": [resp]})
    return Command(goto=END, update={"messages": [resp]})


# 实战: a 答产品, b 答订单, 互转
```

实战经验:

- 双向 Handoff 容易死循环
- 必须加 `handoff_count` 限制
- LangGraph recursion_limit 设 25

## 7. Handoff + HITL — 敏感转交先审

```python
def sales_node(state) -> Command:
    resp = llm.invoke([SystemMessage("...")] + state["messages"])
    if resp.tool_calls:
        tc = resp.tool_calls[0]
        if tc["name"] == "transfer_to_support":
            reason = tc["args"].get("reason", "")
            # 涉及敏感关键词 → 审批
            if any(kw in reason for kw in ["大额", "隐私", "投诉"]):
                human = interrupt({
                    "stage": "handoff_approval",
                    "from": "sales",
                    "to": "support",
                    "reason": reason,
                })
                if human != "approve":
                    return Command(goto=END, update={"messages": [AIMessage("已取消")]})
            return Command(goto="support", update={"messages": [resp]})
    return Command(goto=END, update={"messages": [resp]})


app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "handoff-hitl-1"}}

app.invoke(
    {"messages": [HumanMessage("我要申请大额退款, 涉及隐私数据")]},
    config=config,
)
r = app.invoke(Command(resume="approve"), config=config)
```

实战:涉及金额 / 隐私 / 投诉的转交,主管审批后才真跳转。

## 8. Handoff 到 Subgraph — 子图套娃

```python
def build_subgraph():
    def analyze(state): return {"messages": [AIMessage(content="[analyze] 问题已拆解")]}
    def lookup(state): return {"messages": [AIMessage(content="[lookup] 已查文档")]}
    def solve(state): return {"messages": [AIMessage(content="[solve] 方案: 重启服务")]}

    g = StateGraph(MessagesState)
    g.add_node("analyze", analyze)
    g.add_node("lookup", lookup)
    g.add_node("solve", solve)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "lookup")
    g.add_edge("lookup", "solve")
    g.add_edge("solve", END)
    return g.compile()


tech_subgraph = build_subgraph()
graph.add_node("tech_subgraph", tech_subgraph)
# sales 转过来直接到 subgraph, 子图内部自己走
```

实战:Handoff 目标可以是另一个 graph(子图),适合复杂流程编排。

## 9. Handoff 路径审计

```python
class AuditedState(TypedDict):
    messages: Annotated[list, add_messages]
    handoff_log: Annotated[list[str], lambda a, b: a + b]


def sales(state) -> Command:
    resp = llm.invoke(...)
    if resp.tool_calls:
        return Command(
            goto="support",
            update={"messages": [resp], "handoff_log": ["sales → support"]},
        )
    return Command(goto=END, update={"messages": [resp]})


# 输出:
# >>> 完整路径: sales → support
# >>> 最终 messages: 4 条
```

实战用途:

- 客服复盘:"这个用户都跟谁聊过?"
- SLA 监控:多次 handoff = 转多了 = 服务差
- 合规审计:谁 → 谁,理由是什么

## 10. Supervisor + Handoff 混合 + 生产架构

混合架构(实战最常见):

```
        用户问题
           ↓
        Supervisor (中央路由)
           ↓ 路由到
        Sales Agent ←─→ Handoff to Tech
           ↓               ↓
          END            Support Agent
                          ↓
                         END
```

适合:顶层用 Supervisor 分流,细分问题 Agent 内自治。

生产 snippet:

```python
# 1. 用 factory 函数生成 handoff tool
def make_handoff_tool(target, description):
    @tool(f"transfer_to_{target}")
    def handoff(reason: str):
        f"{description}"
    return handoff

# 2. Command(goto=...) + Command(update={...}) 同时给消息 + state
return Command(
    goto="tech",
    update={"messages": [resp], "handoff_log": [f"sales → tech: {reason}"]},
)

# 3. 持久化 + LangSmith
app = graph.compile(checkpointer=PostgresSaver(...))

# 4. 死循环防护 — max_handoffs
if state.get("handoff_count", 0) > 5:
    return Command(goto=END, update={"messages": [AIMessage("已超转上限")]})

# 5. 异步化 — astream_events 看每个跳转
async for event in app.astream_events(input, version="v2"):
    if event["event"] == "on_chain_end":
        print(f"  [{event['name']}] 完成")
```

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| create_agent 不跳转 | 只触发 tool,没 Command | 包成 LangGraph 节点 |
| 双向 Handoff 死循环 | a→b→a→b | 加 `handoff_count` 限制 |
| 上下文丢失 | state 没传 | `update={...}` 塞字段 |
| 路径不可审计 | 没记 handoff_log | state 加 `handoff_log` reducer |
| 敏感转交没人审 | 没加 interrupt | 关键转交前 `interrupt(...)` |
| 子图 Handoff 报错 | subgraph 状态不兼容 | subgraph state 与主图匹配 |

## 小结

- Handoff 工具 = `transfer_to_<agent>` 工厂函数
- `Command(goto=...)` 是真跳转,所有跳转都通过它
- create_agent + handoff tools 不会真跳转,需 LangGraph 节点包一层
- Handoff 时 state 传上下文(reducer 累加)
- 双向 Handoff 加 `handoff_count` 防死循环
- 敏感 Handoff 前 interrupt 让人审批
- Handoff 到 subgraph 实现复杂流程编排
- 实战最常见:Supervisor(顶层)+ Handoff(细分)的混合

Handoff 让 Agent "自主转交"。下一步让多个 Agent **多向协作**——L4-15 Swarm 见。

## 延伸阅读

- [LangGraph Multi-Agent 官方文档](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- 上一篇:[L4-13 Supervisor 模式](./L4-13_supervisor.md)
- 下一篇:[L4-15 Swarm 多向协作](./L4-15_swarm.md)
- 源码:`04-multi-agent/14_handoff.py`
