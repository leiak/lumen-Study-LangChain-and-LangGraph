# L4-13 · Supervisor 模式:中央调度,客服分流最常用

> 单 Agent 什么都干不好——一个 prompt 塞"既会售前又会售后又会技术",LLM 上下文乱 / 工具互相干扰 / prompt 调一调全崩。多 Agent 模式就是各管各的:Supervisor(中央调度)/ Handoff(自主转交)/ Swarm(多向协作)。Supervisor 最简单清晰,生产 80% 场景都够用。这篇拆 10 个 demo,涵盖从 free text 路由到生产架构。

## 为什么学这个

生产里客服 AI 不能"一个 agent 打天下":

- 售前要 RAG 查知识库
- 售后要查订单系统
- 技术要查 API 文档
- 退款要主管审批

硬塞一个 agent 里,问题是:

| 问题 | 后果 |
|---|---|
| 工具太多 | LLM 选错工具率 ↑ |
| prompt 太长 | 互相干扰,调一处崩一片 |
| 没有隔离 | 高风险工具不能单独管控 |
| 难审计 | 不知道"这个问题为什么这么答" |

Supervisor 模式解决:**中央调度节点 + N 个专家 agent**,路由清晰 / 工具隔离 / 便于审计。

跟 Java 服务的分层架构一个思路——Controller / Service / Repository,只不过这里是 Supervisor / Specialist / Tool。

## 学完你能回答 10 个问题

1. Supervisor 路由用 free text 还是 structured output(Pydantic)?
2. 怎么拼"单轮路由 vs 多轮路由"两种图?
3. 怎么让 Supervisor 跟踪路由历史(audit)?
4. 怎么给 Supervisor 加 HITL 中断?
5. 怎么用 create_agent 当 specialist(省事)?
6. 怎么让 specialist 各自带自己的工具?
7. 怎么搭"层级 Supervisor"(Supervisor of Supervisors)?
8. Supervisor 流式输出时怎么看到路由决策?
9. Supervisor 模式的优缺点 vs Handoff / Swarm?
10. 生产架构怎么落地(middleware + observability)?

## 1. 基础 Supervisor — free text 路由

```python
SUPERVISOR_PROMPT = """你是 Supervisor, 根据用户最新问题决定交给哪个专家。

可选专家:
- sales: 售前 (产品功能、价格、推荐)
- support: 售后 (订单状态、退款、物流)
- tech: 技术 (API、报错、技术原理)

只返回专家名字 (sales / support / tech), 不要解释。

用户问题: {question}"""


def supervisor_router_free(state):
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage):
        return "__end__"

    llm = get_llm()
    decision = llm.invoke(SUPERVISOR_PROMPT.format(question=last.content)).content.strip().lower()

    if "sales" in decision: return "sales"
    if "tech" in decision: return "tech"
    return "support"  # 默认


def make_specialist(name, description):
    """工厂: 创建专家节点函数 (LLM-only, 不带工具)."""
    llm = get_llm()
    def specialist(state):
        system = SystemMessage(content=f"你是「{name}」。{description}\n回答不超过 80 字。")
        msgs = [system] + state["messages"]
        response = llm.invoke(msgs)
        return {"messages": [response]}
    return specialist


def build():
    sales = make_specialist("售前", "回答产品功能、价格、推荐。")
    support = make_specialist("售后", "处理订单状态、退款申请、物流查询。")
    tech = make_specialist("技术", "排查 API 报错、技术原理、架构问题。")

    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", lambda s: s)
    graph.add_node("sales", sales)
    graph.add_node("support", support)
    graph.add_node("tech", tech)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", supervisor_router_free,
        {"sales": "sales", "support": "support", "tech": "tech", "__end__": END},
    )
    graph.add_edge("sales", END)
    graph.add_edge("support", END)
    graph.add_edge("tech", END)
    return graph.compile()
```

实战:free text 简单但不稳,LLM 可能返回"我觉得应该是 tech"。

## 2. Structured Output 路由 — Pydantic schema

```python
class RouteDecision(BaseModel):
    """Supervisor 的路由决策."""
    next_agent: Literal["sales", "support", "tech", "__end__"] = Field(
        description="下一个专家, 或 __end__ 结束"
    )
    reason: str = Field(description="为什么选这个专家, 1 句话")


def supervisor_router_structured(state):
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage):
        return "__end__"

    llm = get_llm().with_structured_output(RouteDecision)
    decision: RouteDecision = llm.invoke(f"根据用户问题决定路由: {last.content}")
    print(f"    [supervisor 决策] {decision.next_agent} ({decision.reason})")
    return decision.next_agent
```

| 维度 | free text | structured (Pydantic) |
|---|---|---|
| 稳定性 | LLM 可能返回多余解释 | schema 强制约束 |
| 可观测性 | 解析后才知结果 | 直接拿到字段 |
| 实现复杂度 | 简单 | 需要 Pydantic model |
| 推荐度 | 学习用 | **生产用** |

## 3. 多轮 Supervisor — 用户跟不同专家来回聊

```python
# 关键: 专家结束后回 supervisor (而不是 END), 支持多轮
graph.add_edge("sales", "supervisor")
graph.add_edge("support", "supervisor")
graph.add_edge("tech", "supervisor")

# 第 1 轮: 售前
r1 = app.invoke({"messages": [HumanMessage("产品多少钱?")]})
# 第 2 轮: 换售后 (新问题触发 supervisor 重新路由)
r2 = app.invoke({"messages": [HumanMessage("好, 那我刚下的订单在哪?")]})
```

实战经验:

- 单轮(售前 → END):简单场景(用户问完就走)
- 多轮(售前 → supervisor → 售后):真实客服场景,用户来回问

## 4. 带工具的 Specialist — 每个专家有自己的工具集

```python
def make_tool_specialist(name, description, tools):
    llm = get_llm().bind_tools(tools)
    def specialist(state):
        system = SystemMessage(content=f"你是「{name}」。{description}")
        msgs = [system] + state["messages"]
        resp = llm.invoke(msgs)
        results = []
        if resp.tool_calls:
            tools_by_name = {t.name: t for t in tools}
            for tc in resp.tool_calls:
                fn = tools_by_name[tc["name"]]
                results.append(ToolMessage(content=str(fn.invoke(tc["args"])), tool_call_id=tc["id"]))
            final = llm.invoke([system] + state["messages"] + [resp] + results)
            return {"messages": [resp] + results + [final]}
        return {"messages": [resp]}
    return specialist


sales = make_tool_specialist("售前", "查产品信息", [get_product_info])
support = make_tool_specialist("售后", "查订单状态", [get_order_status])
tech = make_tool_specialist("技术", "查 API 状态", [check_api_status])
```

实战:每个 specialist 只能用自己的工具,工具选择错误率下降 50%+。

## 5. create_agent 当 specialist — 最省事

```python
from langchain.agents import create_agent

sales_agent = create_agent(
    model=get_llm(), tools=[get_product_info],
    system_prompt="你是售前, 回答产品功能、价格。",
)
support_agent = create_agent(
    model=get_llm(), tools=[get_order_status],
    system_prompt="你是售后, 处理订单查询。",
)
tech_agent = create_agent(
    model=get_llm(), tools=[check_api_status],
    system_prompt="你是技术, 查 API 健康状态。",
)

def sales_node(state):
    r = sales_agent.invoke({"messages": state["messages"]})
    return {"messages": r["messages"]}
```

实战:`create_agent` 自带 tool calling 循环,最省事。

## 6. 跟踪路由历史 — audit 用

```python
class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    routing_log: Annotated[list[str], lambda a, b: a + b]


def routing_logger(state):
    """把当前轮路由记到 state, 方便事后审计."""
    last = state["messages"][-1]
    decision = supervisor_router_free({"messages": state["messages"]})
    return {"routing_log": [f"[{type(last).__name__}] -> {decision}"]}
```

实战:routing_log 配合 LangSmith 上报,可视化"问题都路由去了哪"。

## 7. Supervisor + HITL — 关键路由先审批

```python
def supervisor_with_approval(state) -> Command:
    decision = supervisor_router_free(state)
    last = state["messages"][-1]
    if "大额" in (last.content if isinstance(last, HumanMessage) else ""):
        human_input = interrupt({
            "stage": "supervisor",
            "proposed_route": decision,
            "user_msg": last.content,
        })
        if human_input != "approve":
            return Command(goto=END, update={"messages": [AIMessage(content="已取消")]})
    return Command(goto=decision)


app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "sup-hitl-1"}}

# 触发 HITL
app.invoke({"messages": [HumanMessage("我要申请大额退款 5000 元")]}, config=config)
# 主管批准
r = app.invoke(Command(resume="approve"), config=config)
```

实战场景:大额退款 / 隐私数据 / 高风险用户,关键路由前先让人审。

## 8. 流式 Supervisor — 看每步路由

```python
for chunk in app.stream(
    {"messages": [HumanMessage("API 出错了")]},
    stream_mode="updates",
):
    for node, delta in chunk.items():
        if "messages" in delta:
            print(f"  [step] node={node}, new_msgs={len(delta['messages'])}")
```

输出:
```
[step] node=supervisor, new_msgs=0
[step] node=tech, new_msgs=2  ← 路由到 tech, tech 调工具 + 答
```

实战:前端能实时显示"AI 正在咨询技术专家"。

## 9. Supervisor vs Handoff vs Swarm

| 维度 | Supervisor | Handoff | Swarm |
|---|---|---|---|
| 调度中心 | 有(中央) | 无(agent 自决) | 无(动态) |
| 谁决定 | Supervisor | Agent 自己 | 任意 Agent |
| 路由逻辑 | LLM 1 次决策 | LLM 每次自决 | LLM 每次自决 |
| 实现复杂度 | 低 | 中 | 高 |
| 适用场景 | 客服分流 | 客服对话转接 | 研究协作 |
| 优点 | 简单清晰,易审计 | 灵活,agent 自主 | 探索型强 |
| 缺点 | 单点故障风险 | 不易审计 | 可能死循环 |

选型建议:
- 业务稳定、专家少(≤5):Supervisor
- 业务灵活、agent 多(5-10):Handoff
- 研究 / 探索型、多角色迭代:Swarm

## 10. 生产架构

```python
# 1. 用 structured output (Pydantic) 路由
class RouteDecision(BaseModel):
    next_agent: Literal["sales", "support", "tech", "__end__"]
    confidence: float = Field(ge=0, le=1)
    reason: str

# 2. Supervisor 本身做中间件 (限流 / 监控)
@wrap_model_call
async def rate_limit_supervisor(request, handler):
    if over_rate_limit():
        return Command(goto=END, update={"messages": [AIMessage("限流中")]})
    return await handler(request)

# 3. 持久化 (PostgresSaver)
app = graph.compile(checkpointer=PostgresSaver(...), store=PostgresStore(...))

# 4. LangSmith 上报 — 看每个问题的路由决策
config = {"configurable": {"thread_id": "user-001"}, "metadata": {"user_tier": "vip"}}

# 5. HITL — 高风险操作强制人工审批
graph.compile(interrupt_before=["refund_executor"], checkpointer=...)
```

关键实践:

- 用 Pydantic 路由(free text 不稳)
- 加中间件(限流 / 日志 / 风控)
- 高风险路由加 interrupt
- LangSmith metadata 标记用户层级 / 业务线

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| 路由错误率高 | free text 解析失败 | 用 `with_structured_output` |
| 单点故障 | Supervisor 自己挂了 | 加 retry + 多副本 + 熔断 |
| 专家间上下文串扰 | 共享 messages | metadata 分段隔离 |
| 高风险操作没拦住 | Supervisor 不带工具检查 | 关键工具前加 interrupt |
| 路由决策看不见 | 没存 routing_log | state 加 `routing_log` reducer |
| 多轮路由状态混乱 | supervisor 没 state | TypedDict 加 `routing_log` 字段 |

## 小结

- Supervisor 模式 = 中央调度 + N 个专家
- Free text 简单但不稳,**Pydantic structured 是生产推荐**
- 单轮 vs 多轮路由:单轮专家 → END,多轮专家 → supervisor
- `create_agent` 当 specialist 最省事,自带 tool calling 循环
- 路由历史 + LangSmith metadata 让一切可观测
- 高风险路由加 interrupt,主管审批
- Supervisor vs Handoff vs Swarm 按业务复杂度选

Supervisor 让 Agent 团队"分工明确"。下一步让 Agent **自己决定转交给谁**——L4-14 Handoff 见。

## 延伸阅读

- [LangGraph Multi-Agent 官方文档](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- 上一篇:[L3-12 LangSmith Evaluation](./L3-12_langsmith_evaluation.md)
- 下一篇:[L4-14 Handoff 模式](./L4-14_handoff.md)
- 源码:`04-multi-agent/13_supervisor.py`
