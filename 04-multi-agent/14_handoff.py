"""14_handoff.py — Handoff 模式.

Agent 自己决定"转交"给另一个 Agent, 控制权完全转移。
与 Supervisor 不同: Handoff 是 agent-driven, Supervisor 是中央调度。

学完这个模块你能回答:
 1.  Handoff 工具怎么定义 (每个 agent 都能调转交)?
 2.  Command(goto=...) 怎么让 agent 互相跳转?
 3.  Handoff 时怎么把上下文传过去?
 4.  create_agent + handoff tools 最省事的写法?
 5.  双向 handoff (a → b 和 b → a)?
 6.  Handoff 触发 HITL (主管审批转交)?
 7.  Handoff 到 subgraph (子图套娃)?
 8.  Handoff 路径审计 (state 里记跳了几次)?
 9.  Supervisor + Handoff 混合模式怎么搭?
10.  生产架构怎么落地?

跑法:
    python 14_handoff.py
"""
from __future__ import annotations

import os
import sys
from typing import Annotated, Literal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from _common import banner, get_llm

# ============================================================
# 0. Handoff 工具工厂
# ============================================================


def make_handoff_tool(target_agent: str, description: str):
    """工厂: 创建一个转交工具.

    target_agent: 转给谁 (字符串, 用 Command(goto=target) 跳转)
    description:   LLM 看到的工具描述
    """
    tool_name = f"transfer_to_{target_agent}"

    @tool(tool_name)
    def handoff(reason: str) -> str:
        f"""{description}."""
        # 实际内容不重要, 因为 Command(goto=...) 才是真的跳转
        # 这里返回的内容会作为 ToolMessage 加到 history, 给后续 agent 看到
        return f"[handoff -> {target_agent}] {reason}"

    handoff.name = tool_name
    return handoff


# 预定义 3 个 handoff 工具
TRANSFER_TO_TECH = make_handoff_tool(
    "tech",
    "转交给技术专家 (排查 API 报错、技术原理)。参数 reason 写明转交原因",
)
TRANSFER_TO_SALES = make_handoff_tool(
    "sales",
    "转交给售前专家 (产品功能、价格、推荐)。参数 reason 写明转交原因",
)
TRANSFER_TO_SUPPORT = make_handoff_tool(
    "support",
    "转交给售后专家 (订单查询、退款、物流)。参数 reason 写明转交原因",
)


# ============================================================
# 1. 基础 Handoff — 单 agent + handoff tools
# ============================================================
banner("1. 基础 Handoff — 单 agent + handoff tools")


def demo_basic_handoff() -> None:
    """Agent 自己决定要不要调 handoff 工具."""
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

    for q in ["API 返回 500 错误", "你们有什么产品?", "你好"]:
        r = agent.invoke({"messages": [HumanMessage(q)]})
        print(f">>> Q: {q}")
        for m in r["messages"]:
            if hasattr(m, "tool_calls") and m.tool_calls:
                for tc in m.tool_calls:
                    print(f"    [tool_call] {tc['name']}({tc.get('args', {})})")


# ============================================================
# 2. 完整 Handoff Graph — Command(goto=...) 跳转
# ============================================================
banner("2. 完整 Handoff Graph (Command 跳转)")


def build_handoff_graph():
    """每个 sub-agent 都是节点, 互相用 Command(goto=...) 跳转."""
    llm = get_llm()

    def make_agent_node(name: str, description: str, handoff_tools: list):
        """构造一个 agent 节点: 调 LLM → 看要不要 handoff."""
        agent_llm = llm.bind_tools(handoff_tools)
        tools_by_name = {t.name: t for t in handoff_tools}

        def agent_node(state: MessagesState) -> Command:
            system = SystemMessage(content=f"你是「{name}」。{description}")
            msgs = [system] + state["messages"]
            resp = agent_llm.invoke(msgs)

            # 检查 handoff
            if resp.tool_calls:
                tc = resp.tool_calls[0]
                if tc["name"].startswith("transfer_to_"):
                    target = tc["name"].replace("transfer_to_", "")
                    return Command(
                        goto=target,
                        update={"messages": [resp]},
                    )

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
        "技术", "回答 API、报错、架构问题。",
        [],  # 终点, 不再转
    )

    graph = StateGraph(MessagesState)
    graph.add_node("sales", sales_node)
    graph.add_node("support", support_node)
    graph.add_node("tech", tech_node)

    # 所有跳转都通过 Command(goto=...), 图里不用 add_conditional_edges
    graph.add_edge(START, "sales")  # 默认从 sales 入口

    return graph.compile()


def demo_full_handoff() -> None:
    app = build_handoff_graph()

    print(">>> Q: 我想退款 (sales → support)")
    r = app.invoke({"messages": [HumanMessage("我想退款")]})
    print(f"    最终 messages 数: {len(r['messages'])}")
    for m in r["messages"]:
        marker = (m.content or "")[:60] if hasattr(m, "content") else ""
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                print(f"    [{type(m).__name__} + tool] -> {tc['name']}")
        else:
            print(f"    [{type(m).__name__}] {marker}")


# ============================================================
# 3. Handoff 时传上下文 — state 里塞附加信息
# ============================================================
banner("3. Handoff 时传上下文")


class HandoffState(TypedDict):
    messages: Annotated[list, add_messages]
    handoff_count: int
    handoff_path: Annotated[list[str], lambda a, b: a + b]


def build_handoff_graph_with_context():
    """Handoff 时把"转交原因"塞到 state 里, 下个 agent 能看到."""
    llm = get_llm()

    def sales_node(state: HandoffState) -> Command:
        resp = llm.invoke(
            [SystemMessage("你是售前, 用户要退款就转 support, 调 transfer_to_support 工具。")]
            + state["messages"]
        )
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

    def support_node(state: HandoffState) -> Command:
        # 这里能看到上一次的转交原因
        path = state.get("handoff_path", [])
        context_msg = f"转交流水: {path}" if path else "首次进入"
        resp = llm.invoke(
            [SystemMessage(f"你是售后。{context_msg}。用户问订单就回答。")]
            + state["messages"]
        )
        return Command(
            goto=END,
            update={
                "messages": [resp],
                "handoff_path": [f"support -> END"],
            },
        )

    graph = StateGraph(HandoffState)
    graph.add_node("sales", sales_node)
    graph.add_node("support", support_node)
    graph.add_edge(START, "sales")
    return graph.compile()


def demo_handoff_with_context() -> None:
    app = build_handoff_graph_with_context()
    r = app.invoke(
        {
            "messages": [HumanMessage("我要退款")],
            "handoff_count": 0,
            "handoff_path": [],
        }
    )
    print(f">>> 转交路径: {r['handoff_path']}")
    print(f">>> 转交次数: {r['handoff_count']}")
    print(f">>> 最终回复: {r['messages'][-1].content[:80]}")


# ============================================================
# 4. create_agent + handoff tools — 最省事写法
# ============================================================
banner("4. create_agent + handoff tools (最简)")


def demo_create_agent_handoff() -> None:
    """create_agent 自动处理 tool calling 循环, 加 handoff tool 就完事.

    但单纯 create_agent 不会真跳转 — 它只是调了 tool, 返回结果就结束。
    要真跳转, 还是需要包成 LangGraph 节点。
    """
    from langchain.agents import create_agent

    agent = create_agent(
        model=get_llm(),
        tools=[TRANSFER_TO_TECH, TRANSFER_TO_SALES],
        system_prompt=(
            "你是前台。涉及 API 报错 → transfer_to_tech; "
            "涉及产品功能 → transfer_to_sales。"
        ),
    )

    r = agent.invoke({"messages": [HumanMessage("API 出错了")]})
    print(">>> create_agent 看到 handoff tool 调用:")
    for m in r["messages"]:
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                print(f"    {tc['name']}({tc['args']})")

    # 💡 提示:
    #   - 单纯 create_agent: 只触发 tool, 不跳转
    #   - 想要真跳转: 包成 LangGraph 节点, 在节点里用 Command(goto=...)
    #   - 或者用 LangGraph 内置的 create_react_agent + handoff 配合


# ============================================================
# 5. 双向 Handoff — a → b, b → a
# ============================================================
banner("5. 双向 Handoff (a ↔ b)")


def build_bidirectional_handoff():
    """两个 agent 可以互转."""
    llm = get_llm()
    a_to_b = TRANSFER_TO_SUPPORT  # a 转 b
    b_to_a = TRANSFER_TO_SALES    # b 转 a

    def a_node(state: MessagesState) -> Command:
        resp = llm.invoke(
            [SystemMessage("你是 agent A。要查订单就 transfer_to_support, 否则答。")]
            + state["messages"]
        )
        if resp.tool_calls:
            tc = resp.tool_calls[0]
            if tc["name"] == "transfer_to_support":
                return Command(goto="support", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    def b_node(state: MessagesState) -> Command:
        resp = llm.invoke(
            [SystemMessage("你是 agent B (售后)。要查产品就 transfer_to_sales, 否则答。")]
            + state["messages"]
        )
        if resp.tool_calls:
            tc = resp.tool_calls[0]
            if tc["name"] == "transfer_to_sales":
                return Command(goto="sales", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    graph = StateGraph(MessagesState)
    graph.add_node("sales", a_node)
    graph.add_node("support", b_node)
    graph.add_edge(START, "sales")
    return graph.compile()


def demo_bidirectional() -> None:
    app = build_bidirectional_handoff()
    print(">>> Q: 问产品 (sales 答), 再问订单 (sales → support), 又问产品 (support → sales)")
    # 第 1 轮: sales 答
    r1 = app.invoke({"messages": [HumanMessage("你们有什么产品?")]})
    print(f"    [1] {r1['messages'][-1].content[:60]}")
    # 第 2 轮: 新问题 sales → support
    r2 = app.invoke({"messages": [HumanMessage("订单 #123 在哪?")]})
    print(f"    [2] {r2['messages'][-1].content[:60]}")
    # 第 3 轮: support → sales
    r3 = app.invoke({"messages": [HumanMessage("那产品多少钱?")]})
    print(f"    [3] {r3['messages'][-1].content[:60]}")


# ============================================================
# 6. Handoff + HITL — 转交先审批
# ============================================================
banner("6. Handoff + HITL (敏感转交先让人审)")


def build_handoff_with_hitl():
    """涉及"金额 / 隐私"的转交, 先让人审批."""
    llm = get_llm()

    def sales_node(state: MessagesState) -> Command:
        resp = llm.invoke(
            [SystemMessage("你是售前。要查订单就 transfer_to_support, 转交时写明 reason。")]
            + state["messages"]
        )
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

    def support_node(state: MessagesState) -> Command:
        resp = llm.invoke([SystemMessage("你是售后, 回答订单问题。")] + state["messages"])
        return Command(goto=END, update={"messages": [resp]})

    graph = StateGraph(MessagesState)
    graph.add_node("sales", sales_node)
    graph.add_node("support", support_node)
    graph.add_edge(START, "sales")
    return graph.compile(checkpointer=InMemorySaver())


def demo_handoff_hitl() -> None:
    app = build_handoff_with_hitl()
    config = {"configurable": {"thread_id": "handoff-hitl-1"}}

    # 触发敏感转交
    app.invoke(
        {"messages": [HumanMessage("我要申请大额退款, 涉及隐私数据")]},
        config=config,
    )
    state = app.get_state(config)
    print(f">>> 触发 HITL, 暂停在: {state.next}")
    if state.tasks and state.tasks[0].interrupts:
        print(f"    待审批: {state.tasks[0].interrupts[0].value}")

    # 主管批准
    r = app.invoke(Command(resume="approve"), config=config)
    print(f">>> 批准后最终回复: {r['messages'][-1].content[:80]}")


# ============================================================
# 7. Handoff 到 subgraph — 子图套娃
# ============================================================
banner("7. Handoff 到 subgraph")


def build_subgraph():
    """技术 agent 本身是个 subgraph (分析 → 查文档 → 给方案)."""
    def analyze(state):
        return {"messages": [AIMessage(content="[analyze] 问题已拆解")]}

    def lookup(state):
        return {"messages": [AIMessage(content="[lookup] 已查文档")]}

    def solve(state):
        return {"messages": [AIMessage(content="[solve] 方案: 重启服务")]}

    g = StateGraph(MessagesState)
    g.add_node("analyze", analyze)
    g.add_node("lookup", lookup)
    g.add_node("solve", solve)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "lookup")
    g.add_edge("lookup", "solve")
    g.add_edge("solve", END)
    return g.compile()


def demo_handoff_to_subgraph() -> None:
    """Handoff 目标可以是另一个 graph (子图)."""
    tech_subgraph = build_subgraph()

    llm = get_llm()

    def sales_node(state: MessagesState) -> Command:
        resp = llm.invoke(
            [SystemMessage("你是售前, 技术问题调 transfer_to_tech。")]
            + state["messages"]
        )
        if resp.tool_calls:
            return Command(goto="tech_subgraph", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    graph = StateGraph(MessagesState)
    graph.add_node("sales", sales_node)
    # 子图作为节点嵌入
    graph.add_node("tech_subgraph", tech_subgraph)
    graph.add_edge(START, "sales")
    # 关键: 子图也有 END, 直接跳
    graph.add_edge("tech_subgraph", END)
    return graph.compile()


def demo_subgraph_handoff() -> None:
    app = demo_handoff_to_subgraph()
    r = app.invoke({"messages": [HumanMessage("API 出错了, 帮我查一下")]})
    print(">>> Handoff 到 subgraph 的 messages:")
    for m in r["messages"]:
        if hasattr(m, "content") and m.content:
            print(f"    [{type(m).__name__}] {m.content[:60]}")


# ============================================================
# 8. Handoff 路径审计 — state 记录跳了几次
# ============================================================
banner("8. Handoff 路径审计")


class AuditedState(TypedDict):
    messages: Annotated[list, add_messages]
    handoff_log: Annotated[list[str], lambda a, b: a + b]


def build_audited_handoff():
    llm = get_llm()

    def sales(state: AuditedState) -> Command:
        resp = llm.invoke([SystemMessage("售前, 退款 transfer_to_support")] + state["messages"])
        if resp.tool_calls:
            return Command(
                goto="support",
                update={"messages": [resp], "handoff_log": ["sales → support"]},
            )
        return Command(goto=END, update={"messages": [resp]})

    def support(state: AuditedState) -> Command:
        resp = llm.invoke([SystemMessage("售后, 回答")] + state["messages"])
        return Command(goto=END, update={"messages": [resp], "handoff_log": ["support → END"]})

    graph = StateGraph(AuditedState)
    graph.add_node("sales", sales)
    graph.add_node("support", support)
    graph.add_edge(START, "sales")
    return graph.compile()


def demo_audit() -> None:
    app = build_audited_handoff()
    r = app.invoke(
        {
            "messages": [HumanMessage("我要退款")],
            "handoff_log": [],
        }
    )
    print(f">>> 完整路径: {' → '.join(r['handoff_log'])}")
    print(f">>> 最终 messages: {len(r['messages'])} 条")

    # 💡 实战:
    #   - 客服复盘: "这个用户都跟谁聊过?"
    #   - SLA 监控: 多次 handoff = 转多了 = 服务差
    #   - 合规审计: 谁 → 谁, 理由是什么


# ============================================================
# 9. Supervisor + Handoff 混合
# ============================================================
banner("9. Supervisor + Handoff 混合模式")


def demo_hybrid_pattern() -> None:
    """Supervisor 入口 → 各 Agent 内部还能继续 Handoff.

    适合: 顶层用 Supervisor 分流, 细分问题 Agent 内自治.
    """
    print(
        """
    架构:

        用户问题
           ↓
        Supervisor (中央路由)
           ↓ 路由到
        Sales Agent ←─→ Handoff to Tech
           ↓               ↓
        END            Support Agent
                          ↓
                         END

    实战里这种混合最常见:
      - 顶层: Supervisor (3-5 个大方向, 简单清晰)
      - 细分: 每个 Agent 内部还能 Handoff (应对复杂场景)
    """
    )


# ============================================================
# 10. 生产架构 — Handoff 落地
# ============================================================
banner("10. 生产架构 — Handoff 落地")


def demo_production_snippet() -> None:
    snippet = """
    # 生产 Handoff 标准接法:

    # 1. 用 factory 函数生成 handoff tool (避免重复代码)
    def make_handoff_tool(target, description):
        @tool(f"transfer_to_{target}")
        def handoff(reason: str):
            f"{description}"
        return handoff

    # 2. Command(goto=...) + Command(update={...}) 同时给消息 + state
    return Command(
        goto="tech",
        update={
            "messages": [resp],
            "handoff_log": [f"sales → tech: {reason}"],
        },
    )

    # 3. 持久化 + LangSmith — 每次跳转都能复盘
    app = graph.compile(checkpointer=PostgresSaver(...))

    # 4. 死循环防护 — 加 max_handoffs 限制
    if state.get("handoff_count", 0) > 5:
        return Command(goto=END, update={"messages": [AIMessage("已超转上限")]})

    # 5. 异步化 — astream_events 看每个跳转
    async for event in app.astream_events(input, version="v2"):
        if event["event"] == "on_chain_end":
            print(f"  [{event['name']}] 完成")
    """
    print(snippet)


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
        ("demo_basic_handoff", demo_basic_handoff),
        ("demo_full_handoff", demo_full_handoff),
        ("demo_handoff_with_context", demo_handoff_with_context),
        ("demo_create_agent_handoff", demo_create_agent_handoff),
        ("demo_bidirectional", demo_bidirectional),
        ("demo_handoff_hitl", demo_handoff_hitl),
        ("demo_subgraph_handoff", demo_subgraph_handoff),
        ("demo_audit", demo_audit),
        ("demo_hybrid_pattern", demo_hybrid_pattern),
        ("demo_production_snippet", demo_production_snippet),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 14_handoff.py 全部 demo 跑完。")
