# L4-15 · Swarm 模式:多 Agent 动态协作,适合探索型任务

> Supervisor 是中央调度,Handoff 是 agent 自主转交——但都是"线性流转"。Swarm 是**多向协作**:没有中心调度,没有固定入口,任意 agent 可以联系任意 agent。最适合"研究 / 探索 / 多角色迭代"——研究员找资料、写作者起稿、审阅者改稿,循环迭代。这篇拆 10 个 demo,从研究 pipeline 到多 reviewer 投票。

## 为什么学这个

Supervisor 和 Handoff 都假设"路径大致确定":

- Supervisor:中央节点决定走哪
- Handoff:每个 agent 决定转给谁(但路径基本单向)

Swarm 不一样——**任意 agent 任意时刻跳到任意 agent**,适合:

| 场景 | 为什么 Swarm |
|---|---|
| 研究报告 | 研究员 → 写作者 → 审阅者 → 研究员(循环) |
| 多 LLM 投票 | 多个 reviewer 并行投票 |
| 探索型任务 | 不知道会跳哪,边走边定 |
| 工单处理 | intake → categorize → resolver → qa → closer(多角色) |

风险:**死循环 / 成本失控 / 调试难**。所以必须配 max_handoffs + timeout + 全量 trace。

跟真人团队的协作一个思路——研究员写完稿给编辑,编辑退回来改,改完再给审阅,审阅通过了才发。

## 学完你能回答 10 个问题

1. Swarm 和 Handoff 有什么区别(没有入口 / 多向跳转)?
2. 怎么用 handoff 工具让 agent 互相联系?
3. 怎么让任意 agent 都能作为入口?
4. 怎么防死循环(max_handoffs 限制)?
5. 怎么搭"研究员 → 写作者 → 审阅者"研究 pipeline?
6. 怎么搭多研究员并行 + 共享 scratchpad?
7. 怎么用 swarm 做"投票"(多个 reviewer 取共识)?
8. Swarm 实战案例:客服工单自动处理?
9. Swarm vs Supervisor / Handoff 选型?
10. 生产架构怎么落地?

## 1. Swarm 核心概念

```
Swarm 模式 = Handoff 的多向协作版本

核心特征:
  - 没有中心调度器 (vs Supervisor)
  - 任意 Agent 可以主动联系任意其他 Agent
  - 没有固定入口 (vs Handoff 单一入口)
  - Agent 共享 messages state (互相能看到上下文)
  - 适合: 研究 / 探索 / 多角色迭代

与 Supervisor / Handoff 对比:
  - Supervisor: 中央路由, 路径清晰, 适合业务分流
  - Handoff:    单一入口, agent-driven, 适合对话转接
  - Swarm:      多向跳转, 动态协作, 适合研究 / 探索

风险:
  - 死循环 (a→b→a→b→...)
  - 调试难 (路径不可预测)
  - 成本高 (LLM 调用多)
  → 实战必加 max_handoffs + timeout
```

## 2. Swarm 工具工厂

```python
def make_handoff_tool(target_agent, description):
    tool_name = f"handoff_to_{target_agent}"

    @tool(tool_name)
    def handoff(payload: str) -> str:
        f"""{description}."""
        return f"[handoff -> {target_agent}] {payload}"

    handoff.name = tool_name
    return handoff


HANDOFF_WRITER = make_handoff_tool(
    "writer", "把研究素材转给写作 Agent (附 brief 描述要写什么)"
)
HANDOFF_REVIEWER = make_handoff_tool(
    "reviewer", "把初稿转给审阅 Agent (附完整 draft)"
)
HANDOFF_RESEARCHER = make_handoff_tool(
    "researcher", "把修改意见转回研究员 (附修改要求)"
)
```

实战:Handoff payload 字段很重要,要把"为什么转交 / 附什么材料"写清楚。

## 3. 完整 Swarm — 研究 → 写作 → 审阅

```python
def build_research_swarm():
    llm = get_llm()

    def researcher(state) -> Command:
        resp = llm.bind_tools([HANDOFF_WRITER]).invoke(
            [SystemMessage("你是研究员。用户给主题后, 先列 3 个要点 (脑补), 然后调 handoff_to_writer 把素材转给写作者。")]
            + state["messages"]
        )
        if resp.tool_calls:
            return Command(goto="writer", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    def writer(state) -> Command:
        resp = llm.bind_tools([HANDOFF_REVIEWER]).invoke(
            [SystemMessage("你是写作者。基于研究员素材写 100 字内初稿, 调 handoff_to_reviewer 交给审阅。")]
            + state["messages"]
        )
        if resp.tool_calls:
            return Command(goto="reviewer", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    def reviewer(state) -> Command:
        resp = llm.bind_tools([HANDOFF_RESEARCHER]).invoke(
            [SystemMessage("你是审阅。看初稿, 需要修改就调 handoff_to_researcher (附意见); 通过就直接说'通过'。")]
            + state["messages"]
        )
        if resp.tool_calls:
            return Command(goto="researcher", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    graph = StateGraph(MessagesState)
    graph.add_node("researcher", researcher)
    graph.add_node("writer", writer)
    graph.add_node("reviewer", reviewer)
    graph.add_edge(START, "researcher")
    return graph.compile()
```

输出 messages 流程:
```
[0] HumanMessage         "写一段 AI 在医疗的应用的短文"
[1] AIMessage            研究员列 3 个要点 + tool_call(handoff_to_writer)
[2] AIMessage            写作者 100 字初稿 + tool_call(handoff_to_reviewer)
[3] AIMessage            审阅者 '需要修改: 加数据' + tool_call(handoff_to_researcher)
[4] AIMessage            研究员补充数据 + tool_call(handoff_to_writer)
...
```

实战:这就是真实团队协作的循环迭代。

## 4. 防死循环 — max_handoffs

```python
class SwarmState(TypedDict):
    messages: Annotated[list, add_messages]
    handoff_count: int


MAX_HANDOFFS = 5


def make_limited_node(name, system_prompt, next_targets):
    handoff_tools = [make_handoff_tool(t, f"转 {t}") for t in next_targets]

    def node(state) -> Command:
        if state.get("handoff_count", 0) >= MAX_HANDOFFS:
            return Command(
                goto=END,
                update={"messages": [AIMessage(content=f"[{name}] 已达转交上限, 停止")]},
            )

        resp = llm.bind_tools(handoff_tools).invoke([SystemMessage(system_prompt)] + state["messages"])
        if resp.tool_calls:
            target = resp.tool_calls[0]["name"].replace("handoff_to_", "")
            return Command(
                goto=target,
                update={
                    "messages": [resp],
                    "handoff_count": state.get("handoff_count", 0) + 1,
                },
            )
        return Command(goto=END, update={"messages": [resp]})

    return node
```

实战经验:

| 阈值 | 含义 |
|---|---|
| `MAX_HANDOFFS = 5` | 5 次还没结论就停 |
| `recursion_limit = 25` | LangGraph 节点执行上限 |
| `timeout = 60s` | 单次 LLM 调用超时 |

## 5. 多入口 Swarm

```python
def build_multi_entry_swarm():
    research = make_node("research", "研究员, 找完转 writer", ["writer"])
    writer = make_node("writer", "写手, 写完转 reviewer", ["reviewer"])
    reviewer = make_node("reviewer", "审阅, 通过转 final", ["final"])
    final = make_node("final", "终稿", [])
    
    graph = StateGraph(MessagesState)
    graph.add_node("research", research)
    graph.add_node("writer", writer)
    graph.add_node("reviewer", reviewer)
    graph.add_node("final", final)
    graph.add_edge(START, "research")  # 默认入口
    return graph.compile()
```

实战:多入口实际做法

- 不同入口用不同 thread_id
- 用 `update_state` 改"下一步"
- 用 entry_router 节点判断从哪里开始

## 6. 并行 Swarm — 多研究员 + 共享 scratchpad

```python
class ParallelState(TypedDict):
    messages: Annotated[list, add_messages]
    research_notes: Annotated[list[str], lambda a, b: a + b]


def build_parallel_swarm():
    def research_tech(state):
        resp = llm.invoke(f"从技术角度研究: {state['messages'][-1].content}, 列出 3 个要点, 50 字内。")
        return {"research_notes": [f"[技术] {resp.content}"]}

    def research_market(state):
        resp = llm.invoke(f"从市场角度研究: {state['messages'][-1].content}, 列出 3 个要点, 50 字内。")
        return {"research_notes": [f"[市场] {resp.content}"]}

    def research_user(state):
        resp = llm.invoke(f"从用户角度研究: {state['messages'][-1].content}, 列出 3 个要点, 50 字内。")
        return {"research_notes": [f"[用户] {resp.content}"]}

    def writer(state) -> Command:
        notes = "\n".join(state["research_notes"])
        resp = llm.invoke(f"基于研究笔记写一段 100 字总结:\n{notes}")
        return Command(goto=END, update={"messages": [resp]})

    graph = StateGraph(ParallelState)
    graph.add_node("research_tech", research_tech)
    graph.add_node("research_market", research_market)
    graph.add_node("research_user", research_user)
    graph.add_node("writer", writer)
    # 3 个并行入口 (LangGraph 自动并行)
    graph.add_edge(START, "research_tech")
    graph.add_edge(START, "research_market")
    graph.add_edge(START, "research_user")
    # 都汇合到 writer
    graph.add_edge("research_tech", "writer")
    graph.add_edge("research_market", "writer")
    graph.add_edge("research_user", "writer")
    return graph.compile()
```

实战:用 `research_notes: Annotated[list, lambda a, b: a + b]` 做共享 scratchpad,3 个研究员同时写、最后 writer 整合。

## 7. 投票 Swarm — 多 reviewer 取共识

```python
class VotingState(TypedDict):
    messages: Annotated[list, add_messages]
    votes: Annotated[list[str], lambda a, b: a + b]


def build_voting_swarm():
    def reviewer_a(state):
        resp = llm.invoke(f"作为严格审阅人, 评价 (pass/fail):\n{state['messages'][-1].content}")
        return {"votes": [f"[严格] {resp.content}"]}

    def reviewer_b(state):
        resp = llm.invoke(f"作为宽松审阅人, 评价 (pass/fail):\n{state['messages'][-1].content}")
        return {"votes": [f"[宽松] {resp.content}"]}

    def reviewer_c(state):
        resp = llm.invoke(f"作为专业审阅人, 评价 (pass/fail):\n{state['messages'][-1].content}")
        return {"votes": [f"[专业] {resp.content}"]}

    def tally(state) -> Command:
        votes = state["votes"]
        pass_count = sum(1 for v in votes if "pass" in v.lower())
        decision = "通过" if pass_count >= 2 else "打回"
        return Command(
            goto=END,
            update={"messages": [AIMessage(content=f"[投票结果] {pass_count}/{len(votes)} pass, {decision}")]},
        )
```

实战:

- 多 LLM 投票(ensemble)降低单模型偏差
- 不同 prompt / 不同 model 投票
- 类似 self-consistency / MoA(Mixture of Agents)

## 8. 实战案例 — 客服工单自动处理

```
客服工单 Swarm:

1. intake    - 接收工单, 提取关键信息
2. categorize - 分类 (退款 / 物流 / 投诉 / 其他)
3. resolver  - 处理 (调对应系统 / 查订单 / 发邮件)
4. qa        - 质量检查 (LLM 评估处理质量)
5. closer    - 关闭工单 / 升级人工

跳转逻辑:
  - intake → categorize
  - categorize → resolver (按类型路由)
  - resolver → qa (处理完送审)
  - qa → closer (qa 通过) / resolver (qa 不通过, 退回重做)
  - closer → END

实战加分项:
  - max_handoffs 防死循环 (qa 反复退 resolver)
  - LangSmith 上报每步
  - 工单 state 实时同步到工单系统
```

## 9. Swarm 模式选型

| 场景 | Supervisor | Handoff | Swarm | 推荐 |
|---|---|---|---|---|
| 客服分流(3-5 专家) | ✓ 最合适 | 可 | 过度设计 | Supervisor |
| 客服对话(转接) | 一般 | ✓ 最合适 | 可 | Handoff |
| 研究报告(协作) | 单点瓶颈 | 路径受限 | ✓ 最合适 | Swarm |
| 多 LLM 投票 | 中央调度 | 多次跳转 | ✓ 最合适 | Swarm(并行) |
| 探索型 agent | 路由死板 | 单入口 | ✓ 最合适 | Swarm |
| 业务流程(固定流) | OK | OK | 过度灵活 | 单图 / pipe |

决策原则:

- 业务稳定 + 路径明确 → 单图 / Supervisor
- 灵活对话 + 单一入口 → Handoff
- 多角色协作 + 探索型 → Swarm

## 10. Swarm 的坑 + 生产架构

### 4 大坑

| 坑 | 后果 | 防 |
|---|---|---|
| 死循环 | a→b→a→b 无限循环 | max_handoffs + timeout + visited 集合 |
| 成本失控 | 多次 handoff = LLM 调用 N 倍 | 加 budget 限制,监控单次对话成本 |
| 调试难 | 路径不可预测,失败难复现 | 全量 LangSmith trace + 强制 routing_log |
| 状态污染 | 所有 agent 共享 messages | 给每个 agent 独立 prompt 段,metadata 标记 |

### 生产 snippet

```python
# 1. handoff_count 强制上限 (防死循环)
MAX_HANDOFFS = 5
if state.get("handoff_count", 0) >= MAX_HANDOFFS:
    return Command(goto=END, update={"messages": [AIMessage("已达上限")]})

# 2. timeout 强制上限 (防 LLM 卡死)
app = graph.compile()
app.invoke(input, config={"recursion_limit": 25})

# 3. routing_log 上报 (LangSmith 自动 trace + 自己的 log)
update = {
    "messages": [resp],
    "handoff_log": [f"{prev_node} → {next_node}"],
}

# 4. 监控 dashboard
#    - 平均 handoff_count (高 = 路径混乱)
#    - 死循环触发率 (MAX_HANDOFFS 命中次数)
#    - 单对话 LLM 成本

# 5. fallback
#    - LLM 调失败 → 默认走 fallback_agent
#    - 超时 → END + 提示用户转人工
```

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| 死循环 | 多向跳转无约束 | `MAX_HANDOFFS` + `recursion_limit` |
| 成本失控 | 多 agent 多次 handoff | budget 限制 + cost 监控 |
| 调试难 | 路径不可预测 | LangSmith 全量 trace + routing_log |
| 状态污染 | 共享 messages 上下文混 | metadata 分段 + 独立 system prompt |
| 并行 swarm state 冲突 | reducer 没配 | `Annotated[list, lambda a, b: a + b]` |
| LLM 选错跳转目标 | 工具描述不清 | 工具 description 写"何时用、参数是什么" |

## 小结

- Swarm = 多向 Handoff,任意 agent 跳任意 agent
- 共享 messages state + handoff_count 计数
- 防死循环:max_handoffs + recursion_limit + timeout
- 并行 Swarm 共享 scratchpad:`Annotated[list, lambda a, b: a + b]`
- 多 reviewer 投票 = 多 LLM ensemble,降低单模型偏差
- 选型:业务稳定用 Supervisor,对话转接用 Handoff,研究/探索用 Swarm
- 生产必备:trace + routing_log + cost 监控 + fallback

Swarm 是"探索型协作"模式。下一步把这一切都打包给"深度 agent"——L5-16 Deep Agents 见。

## 延伸阅读

- [LangGraph Multi-Agent 官方文档](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [OpenAI Swarm 框架参考](https://github.com/openai/swarm)
- 上一篇:[L4-14 Handoff 模式](./L4-14_handoff.md)
- 下一篇:[L5-16 Deep Agents](./L5-16_deep_agents.md)
- 源码:`04-multi-agent/15_swarm.py`
