"""13_supervisor.py — Supervisor 模式.

中央 Supervisor 节点根据用户问题, 路由到不同的专家 Agent。

学完这个模块你能回答:
 1. Supervisor 路由用 free text 还是 structured output (Pydantic)?
 2. 怎么拼"单轮路由 vs 多轮路由"两种图?
 3. 怎么让 Supervisor 跟踪路由历史 (audit)?
 4. 怎么给 Supervisor 加 HITL 中断?
 5. 怎么用 create_agent 当 specialist (省事)?
 6. 怎么让 specialist 各自带自己的工具?
 7. 怎么搭"层级 Supervisor" (Supervisor of Supervisors)?
 8. Supervisor 流式输出时怎么看到路由决策?
 9. Supervisor 模式的优缺点 vs Handoff / Swarm?
10. 生产架构怎么落地 (middleware + observability)?

跑法:
    python 13_supervisor.py
"""
from __future__ import annotations

import os
import sys
from typing import Annotated, Literal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from _common import banner, get_llm

# ============================================================
# 0. 共享 — 工具 + 工厂
# ============================================================


@tool
def get_product_info(product: str) -> str:
    """查产品信息."""
    return f"{product}: 标准版 ¥99/月, 专业版 ¥299/月"


@tool
def get_order_status(order_id: str) -> str:
    """查订单状态."""
    return f"订单 {order_id}: 已发货, 预计明天到"


@tool
def check_api_status(api: str) -> str:
    """查 API 健康状态."""
    return f"{api}: 运行正常, 延迟 50ms"


# ============================================================
# 1. 基础 Supervisor — free text 路由
# ============================================================
banner("1. 基础 Supervisor — free text 路由")


SUPERVISOR_PROMPT = """你是 Supervisor, 根据用户最新问题决定交给哪个专家。

可选专家:
- sales: 售前 (产品功能、价格、推荐)
- support: 售后 (订单状态、退款、物流)
- tech: 技术 (API、报错、技术原理)

只返回专家名字 (sales / support / tech), 不要解释。

用户问题: {question}"""


def supervisor_router_free(state: MessagesState) -> Literal["sales", "support", "tech", "__end__"]:
    """根据最后一条 HumanMessage 路由."""
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage):
        return "__end__"

    llm = get_llm()
    decision = llm.invoke(SUPERVISOR_PROMPT.format(question=last.content)).content.strip().lower()

    if "sales" in decision:
        return "sales"
    if "tech" in decision:
        return "tech"
    return "support"


def make_specialist(name: str, description: str):
    """工厂: 创建专家节点函数 (LLM-only)."""
    llm = get_llm()

    def specialist(state: MessagesState) -> dict:
        system = SystemMessage(content=f"你是「{name}」。{description}\n回答不超过 80 字。")
        msgs = [system] + state["messages"]
        response = llm.invoke(msgs)
        return {"messages": [response]}

    return specialist


def demo_basic_supervisor() -> None:
    sales = make_specialist("售前", "回答产品功能、价格、推荐。")
    support = make_specialist("售后", "处理订单状态、退款申请、物流查询。")
    tech = make_specialist("技术", "排查 API 报错、技术原理、架构问题。")

    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", lambda s: s)  # supervisor 自身不更新 state
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
    app = graph.compile()

    for q in ["你们的产品多少钱?", "我的订单 #123 在哪?", "API 返回 500 错误"]:
        r = app.invoke({"messages": [HumanMessage(q)]})
        print(f">>> Q: {q}")
        print(f"    A: {r['messages'][-1].content[:100]}")
        print()


# ============================================================
# 2. Structured Output 路由 — Pydantic schema
# ============================================================
banner("2. Structured Output 路由 — Pydantic")


class RouteDecision(BaseModel):
    """Supervisor 的路由决策."""

    next_agent: Literal["sales", "support", "tech", "__end__"] = Field(
        description="下一个专家, 或 __end__ 结束"
    )
    reason: str = Field(description="为什么选这个专家, 1 句话")


def supervisor_router_structured(state: MessagesState) -> Literal["sales", "support", "tech", "__end__"]:
    """用 Pydantic schema 让 LLM 给结构化决策 (比 free text 更可靠)."""
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage):
        return "__end__"

    llm = get_llm().with_structured_output(RouteDecision)
    # type: ignore[assignment]  # with_structured_output 的返回类型不容易 narrow
    decision: RouteDecision = llm.invoke(  # type: ignore[assignment]
        f"根据用户问题决定路由: {last.content}"
    )
    print(f"    [supervisor 决策] {decision.next_agent} ({decision.reason})")
    return decision.next_agent


def demo_structured_routing() -> None:
    """用 Pydantic 让 LLM 必须输出规范 schema, 比 free text 更稳."""
    print(">>> 用 Pydantic schema 替代 free text:")
    sales = make_specialist("售前", "回答产品功能、价格。")
    support = make_specialist("售后", "处理订单。")
    tech = make_specialist("技术", "排查 API 报错。")

    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", lambda s: s)
    graph.add_node("sales", sales)
    graph.add_node("support", support)
    graph.add_node("tech", tech)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", supervisor_router_structured,
        {"sales": "sales", "support": "support", "tech": "tech", "__end__": END},
    )
    graph.add_edge("sales", END)
    graph.add_edge("support", END)
    graph.add_edge("tech", END)
    app = graph.compile()

    r = app.invoke({"messages": [HumanMessage("退款政策是?")]})
    print(f">>> 最终回复: {r['messages'][-1].content[:80]}")

    # 💡 free text vs structured:
    #   - free text:    LLM 自由输出, 简单但容易格式漂移 ("我想应该是 tech" 解析失败)
    #   - structured:   Pydantic schema 强制约束, 适合生产 (tool_calling 实现)


# ============================================================
# 3. 多轮 Supervisor — 专家聊完回到 supervisor 重新路由
# ============================================================
banner("3. 多轮 Supervisor — 用户可以跟不同专家来回聊")


def demo_multi_turn() -> None:
    sales = make_specialist("售前", "回答产品功能、价格。")
    support = make_specialist("售后", "处理订单。")
    tech = make_specialist("技术", "排查 API 报错。")

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
    # 关键: 专家结束后回 supervisor (而不是 END), 支持多轮
    graph.add_edge("sales", "supervisor")
    graph.add_edge("support", "supervisor")
    graph.add_edge("tech", "supervisor")

    app = graph.compile()

    print(">>> 多轮: 售前 -> 售后 (supervisor 重新路由)")
    # 第 1 轮: 售前
    r1 = app.invoke({"messages": [HumanMessage("产品多少钱?")]})
    print(f"    第 1 轮: {r1['messages'][-1].content[:80]}")
    # 第 2 轮: 换售后 (新问题触发重新路由)
    r2 = app.invoke({"messages": [HumanMessage("好, 那我刚下的订单在哪?")]})
    print(f"    第 2 轮: {r2['messages'][-1].content[:80]}")


# ============================================================
# 4. 带工具的 Specialist — 每个专家有自己的工具集
# ============================================================
banner("4. 带工具的 Specialist")


def make_tool_specialist(name: str, description: str, tools: list):
    """创建带工具的 specialist — LLM 自己决定调不调用工具."""
    llm = get_llm().bind_tools(tools)

    def specialist(state: MessagesState) -> dict:
        system = SystemMessage(content=f"你是「{name}」。{description}")
        msgs = [system] + state["messages"]
        resp = llm.invoke(msgs)
        # 如果 LLM 调了工具, 真跑工具
        results = []
        if resp.tool_calls:
            from langchain_core.messages import ToolMessage
            tools_by_name = {t.name: t for t in tools}
            for tc in resp.tool_calls:
                fn = tools_by_name[tc["name"]]
                results.append(ToolMessage(content=str(fn.invoke(tc["args"])), tool_call_id=tc["id"]))
            # 再调一次 LLM 整理工具结果
            final = llm.invoke([system] + state["messages"] + [resp] + results)
            return {"messages": [resp] + results + [final]}
        return {"messages": [resp]}

    return specialist


def demo_with_tools() -> None:
    sales = make_tool_specialist("售前", "查产品信息", [get_product_info])
    support = make_tool_specialist("售后", "查订单状态", [get_order_status])
    tech = make_tool_specialist("技术", "查 API 状态", [check_api_status])

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
    app = graph.compile()

    queries = ["标准版多少钱?", "订单 #123 到哪了?", "/api/users 健康吗?"]
    for q in queries:
        r = app.invoke({"messages": [HumanMessage(q)]})
        print(f">>> Q: {q}")
        print(f"    A: {r['messages'][-1].content[:100]}")
        print()


# ============================================================
# 5. create_agent 当 specialist — 更省事
# ============================================================
banner("5. create_agent 当 specialist")


def demo_create_agent_specialists() -> None:
    """create_agent 自带 tool calling 循环, 当 specialist 最省事."""
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

    def support_node(state):
        r = support_agent.invoke({"messages": state["messages"]})
        return {"messages": r["messages"]}

    def tech_node(state):
        r = tech_agent.invoke({"messages": state["messages"]})
        return {"messages": r["messages"]}

    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", lambda s: s)
    graph.add_node("sales", sales_node)
    graph.add_node("support", support_node)
    graph.add_node("tech", tech_node)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", supervisor_router_free,
        {"sales": "sales", "support": "support", "tech": "tech", "__end__": END},
    )
    graph.add_edge("sales", END)
    graph.add_edge("support", END)
    graph.add_edge("tech", END)
    app = graph.compile()

    r = app.invoke({"messages": [HumanMessage("订单 #999 在哪?")]})
    print(f">>> 用 create_agent 当 specialist: {r['messages'][-1].content[:100]}")


# ============================================================
# 6. 跟踪路由历史 — 在 state 里记 supervisor 的决策
# ============================================================
banner("6. 跟踪路由历史 — audit 用")


class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    routing_log: Annotated[list[str], lambda a, b: a + b]  # reducer 累加


def routing_logger(state: SupervisorState) -> dict:
    """把当前轮路由记到 state, 方便事后审计."""
    last = state["messages"][-1]
    decision = supervisor_router_free({"messages": state["messages"]})
    return {"routing_log": [f"[{type(last).__name__}] -> {decision}"]}


def demo_routing_log() -> None:
    sales = make_specialist("售前", "回答产品功能。")
    support = make_specialist("售后", "处理订单。")
    tech = make_specialist("技术", "排查 API 报错。")

    graph = StateGraph(SupervisorState)
    graph.add_node("supervisor", routing_logger)  # supervisor 现在真更新 state
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
    app = graph.compile()

    for q in ["产品功能?", "订单 #123 在哪?"]:
        r = app.invoke({"messages": [HumanMessage(q)], "routing_log": []})
        print(f">>> Q: {q}")
        print(f"    routing_log: {r['routing_log']}")
        print(f"    最终回复: {r['messages'][-1].content[:80]}")

    # 💡 实战: routing_log 配合 LangSmith 上报, 可视化"问题都路由去了哪"


# ============================================================
# 7. Supervisor + HITL — 关键决策先让人审
# ============================================================
banner("7. Supervisor + HITL — 关键路由先审批")


def demo_supervisor_hitl() -> None:
    """大额退款 / 重要操作时, supervisor 路由前先让人审批."""
    def supervisor_with_approval(state: MessagesState) -> Command:
        decision = supervisor_router_free(state)
        # 关键: 大额相关都让人审
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

    sales = make_specialist("售前", "回答产品功能。")
    support = make_specialist("售后", "处理订单。")

    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", supervisor_with_approval)
    graph.add_node("sales", sales)
    graph.add_node("support", support)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", lambda s: s,
        {"sales": "sales", "support": "support", "__end__": END},
    )
    graph.add_edge("sales", END)
    graph.add_edge("support", END)

    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "sup-hitl-1"}}

    # 模拟大额退款场景
    app.invoke({"messages": [HumanMessage("我要申请大额退款 5000 元")]}, config=config)
    state = app.get_state(config)
    print(f">>> 触发 HITL, 暂停在: {state.next}")
    if state.tasks and state.tasks[0].interrupts:
        print(f"    待审批: {state.tasks[0].interrupts[0].value}")

    # 主管批准
    r = app.invoke(Command(resume="approve"), config=config)
    print(f">>> 主管批准后, 最终: {r['messages'][-1].content[:80]}")


# ============================================================
# 8. 流式 Supervisor — 看每步路由
# ============================================================
banner("8. 流式 Supervisor — 看每步路由")


def demo_streaming() -> None:
    sales = make_specialist("售前", "回答产品功能。")
    support = make_specialist("售后", "处理订单。")
    tech = make_specialist("技术", "排查 API 报错。")

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
    app = graph.compile()

    print(">>> 流式输出 (updates mode) — 看 routing 步骤:")
    for chunk in app.stream(
        {"messages": [HumanMessage("API 出错了")]},
        stream_mode="updates",
    ):
        for node, delta in chunk.items():
            if "messages" in delta:
                print(f"  [step] node={node}, new_msgs={len(delta['messages'])}")


# ============================================================
# 9. Supervisor vs Handoff vs Swarm — 对比
# ============================================================
banner("9. Supervisor vs Handoff vs Swarm — 模式对比")


def demo_comparison() -> None:
    print(
        """
    ┌────────────┬──────────────────┬──────────────────┬──────────────────┐
    │            │ Supervisor       │ Handoff          │ Swarm            │
    ├────────────┼──────────────────┼──────────────────┼──────────────────┤
    │ 调度中心   │ 有 (中央)        │ 无 (agent 自决)  │ 无 (动态)        │
    │ 谁决定     │ Supervisor       │ Agent 自己       │ 任意 Agent       │
    │ 路由逻辑   │ LLM 1 次决策     │ LLM 每次自决     │ LLM 每次自决     │
    │ 实现复杂度 │ 低 (1 个 router) │ 中 (每个 agent   │ 高 (任意跳转)    │
    │            │                  │   都有 handoff)  │                  │
    │ 适用场景   │ 客服分流         │ 客服对话转接     │ 研究协作         │
    │            │ 售前/售后/技术    │ "我帮你转技术"   │ 多角色循环迭代   │
    │ 优点       │ 简单清晰, 易审计 │ 灵活, agent 自主 │ 探索型强, 适合   │
    │            │                  │                  │ 多角色协作       │
    │ 缺点       │ 单点故障风险     │ 不易审计, 路径   │ 可能死循环,      │
    │            │                  │ 不可控           │ 调试难           │
    └────────────┴──────────────────┴──────────────────┴──────────────────┘

    选型建议:
      - 业务稳定、专家少 (≤5): Supervisor
      - 业务灵活、agent 多 (5-10): Handoff
      - 研究 / 探索型、多角色迭代: Swarm
    """
    )


# ============================================================
# 10. 生产架构 — Supervisor 落地
# ============================================================
banner("10. 生产架构 — Supervisor 落地")


def demo_production_snippet() -> None:
    snippet = """
    # 生产 Supervisor 标准接法:

    # 1. 用 structured output (Pydantic) 路由 — 比 free text 可靠
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

    # 3. 持久化 (PostgresSaver) — 多轮对话恢复
    app = graph.compile(checkpointer=PostgresSaver(...), store=PostgresStore(...))

    # 4. LangSmith 上报 — 看每个问题的路由决策
    config = {"configurable": {"thread_id": "user-001"}, "metadata": {"user_tier": "vip"}}

    # 5. HITL — 高风险操作 (大额 / 黑名单用户) 强制人工审批
    graph.compile(interrupt_before=["refund_executor"], checkpointer=...)
    """
    print(snippet)

    # 💡 关键实践:
    #   - 用 Pydantic 路由 (free text 不稳)
    #   - 加中间件 (限流 / 日志 / 风控)
    #   - 高风险路由加 interrupt
    #   - LangSmith metadata 标记用户层级 / 业务线


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    for name, fn in [
        ("demo_basic_supervisor", demo_basic_supervisor),
        ("demo_structured_routing", demo_structured_routing),
        ("demo_multi_turn", demo_multi_turn),
        ("demo_with_tools", demo_with_tools),
        ("demo_create_agent_specialists", demo_create_agent_specialists),
        ("demo_routing_log", demo_routing_log),
        ("demo_supervisor_hitl", demo_supervisor_hitl),
        ("demo_streaming", demo_streaming),
        ("demo_comparison", demo_comparison),
        ("demo_production_snippet", demo_production_snippet),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 13_supervisor.py 全部 demo 跑完。")
