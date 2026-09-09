"""15_swarm.py — Swarm 模式.

Agent 之间动态通信, 没有中心调度器。
适合探索型 / 协作型任务。

学完这个模块你能回答:
 1. Swarm 和 Handoff 有什么区别 (没有入口 / 多向跳转)?
 2. 怎么用 handoff 工具让 agent 互相联系?
 3. 怎么让任意 agent 都能作为入口?
 4. 怎么防死循环 (max_handoffs 限制)?
 5. 怎么搭"研究员 → 写作者 → 审阅者"研究 pipeline?
 6. 怎么搭多研究员并行 + 共享 scratchpad?
 7. 怎么用 swarm 做"投票" (多个 reviewer 取共识)?
 8. Swarm 实战案例: 客服工单自动处理?
 9. Swarm vs Supervisor / Handoff 选型?
10. 生产架构怎么落地?

跑法:
    python 15_swarm.py
"""
from __future__ import annotations

import os
import sys
from typing import Annotated

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command
from typing_extensions import TypedDict

from _common import banner, get_llm

# ============================================================
# 0. Swarm 共享 — handoff 工具工厂
# ============================================================


def make_handoff_tool(target_agent: str, description: str):
    """Swarm 里的 handoff 工具, agent 主动调它跳到另一个 agent."""
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
HANDOFF_FINALIZER = make_handoff_tool(
    "finalizer", "审阅通过, 把终稿转给 finalizer 出最终报告"
)


# ============================================================
# 1. Swarm 核心概念
# ============================================================
banner("1. Swarm 核心概念")


def demo_swarm_concept() -> None:
    print(
        """
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
    """
    )


# ============================================================
# 2. 完整 Swarm — 研究 → 写作 → 审阅
# ============================================================
banner("2. Swarm — 研究 → 写作 → 审阅")


def build_research_swarm():
    """3 Agent 互相协作的 pipeline."""
    llm = get_llm()

    def researcher(state: MessagesState) -> Command:
        resp = llm.bind_tools([HANDOFF_WRITER]).invoke(
            [SystemMessage(
                "你是研究员。用户给主题后, 先列 3 个要点 (脑补), "
                "然后调 handoff_to_writer 把素材转给写作者。"
            )]
            + state["messages"]
        )
        if resp.tool_calls:
            return Command(goto="writer", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    def writer(state: MessagesState) -> Command:
        resp = llm.bind_tools([HANDOFF_REVIEWER]).invoke(
            [SystemMessage(
                "你是写作者。基于研究员素材写 100 字内初稿, "
                "调 handoff_to_reviewer 交给审阅。"
            )]
            + state["messages"]
        )
        if resp.tool_calls:
            return Command(goto="reviewer", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    def reviewer(state: MessagesState) -> Command:
        resp = llm.bind_tools([HANDOFF_RESEARCHER]).invoke(
            [SystemMessage(
                "你是审阅。看初稿, 需要修改就调 handoff_to_researcher (附意见); "
                "通过就直接说'通过'。"
            )]
            + state["messages"]
        )
        if resp.tool_calls:
            return Command(goto="researcher", update={"messages": [resp]})
        return Command(goto=END, update={"messages": [resp]})

    graph = StateGraph(MessagesState)
    graph.add_node("researcher", researcher)
    graph.add_node("writer", writer)
    graph.add_node("reviewer", reviewer)
    graph.add_edge(START, "researcher")  # 默认入口
    return graph.compile()


def demo_research_swarm() -> None:
    app = build_research_swarm()
    print(">>> 主题: AI 在医疗的应用")
    r = app.invoke(
        {"messages": [HumanMessage("写一段关于'AI 在医疗的应用'的短文, 100 字以内")]}
    )
    print(f">>> Swarm 协作完成, 共 {len(r['messages'])} 条消息")
    for i, m in enumerate(r["messages"]):
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                print(f"    [{i}] -> {tc['name']}")
        elif hasattr(m, "content") and m.content:
            print(f"    [{i}] [{type(m).__name__}] {m.content[:80]}")


# ============================================================
# 3. 防死循环 — max_handoffs 限制
# ============================================================
banner("3. 防死循环 — max_handoffs")


class SwarmState(TypedDict):
    messages: Annotated[list, add_messages]
    handoff_count: int


MAX_HANDOFFS = 5  # 超过就强制 END


def build_swarm_with_limit():
    llm = get_llm()

    def make_limited_node(name, system_prompt, next_targets):
        """每个 node 都检查 handoff_count, 超限就 END."""
        handoff_tools = [make_handoff_tool(t, f"转 {t}") for t in next_targets]

        def node(state: SwarmState) -> Command:
            if state.get("handoff_count", 0) >= MAX_HANDOFFS:
                return Command(
                    goto=END,
                    update={"messages": [AIMessage(content=f"[{name}] 已达转交上限, 停止")]},
                )

            resp = llm.bind_tools(handoff_tools).invoke(
                [SystemMessage(system_prompt)] + state["messages"]
            )
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

    a = make_limited_node(
        "a", "你是 a。可以转 b 或 c。", ["b", "c"]
    )
    b = make_limited_node(
        "b", "你是 b。可以转 c 或 a。", ["c", "a"]
    )
    c = make_limited_node(
        "c", "你是 c。可以转 a 或 b。", ["a", "b"]
    )

    graph = StateGraph(SwarmState)
    graph.add_node("a", a)
    graph.add_node("b", b)
    graph.add_node("c", c)
    graph.add_edge(START, "a")
    return graph.compile()


def demo_deadlock_protection() -> None:
    app = build_swarm_with_limit()
    r = app.invoke(
        {
            "messages": [HumanMessage("开始")],
            "handoff_count": 0,
        }
    )
    print(f">>> 转交次数: {r['handoff_count']}")
    print(f">>> 最后一条: {r['messages'][-1].content[:80]}")
    print(f">>> 死循环防护: 超过 {MAX_HANDOFFS} 次强制 END")


# ============================================================
# 4. 多入口 Swarm — 任意 agent 都能作为入口
# ============================================================
banner("4. 多入口 Swarm")


def build_multi_entry_swarm():
    """每个 agent 都能作为入口, 通过 thread_id 或初始 message 判断."""
    llm = get_llm()

    def make_node(name, system_prompt, handoffs):
        tools = [make_handoff_tool(t, f"转 {t}") for t in handoffs]
        def node(state: MessagesState) -> Command:
            resp = llm.bind_tools(tools).invoke([SystemMessage(system_prompt)] + state["messages"])
            if resp.tool_calls:
                target = resp.tool_calls[0]["name"].replace("handoff_to_", "")
                return Command(goto=target, update={"messages": [resp]})
            return Command(goto=END, update={"messages": [resp]})
        return node

    research = make_node("research", "研究员, 找完转 writer", ["writer"])
    writer = make_node("writer", "写手, 写完转 reviewer", ["reviewer"])
    reviewer = make_node("reviewer", "审阅, 通过转 final", ["final"])
    final = make_node("final", "终稿", [])

    graph = StateGraph(MessagesState)
    graph.add_node("research", research)
    graph.add_node("writer", writer)
    graph.add_node("reviewer", reviewer)
    graph.add_node("final", final)
    # 关键: 不固定入口 — START 是个特殊位置, 后续可以用 update_state
    #       或从任意 agent 启动 (但 LangGraph 必须有 START 边, 所以这里先到 research)
    graph.add_edge(START, "research")
    return graph.compile()


def demo_multi_entry() -> None:
    print(
        """
    多入口 Swarm 实战:
      1. 不同入口用不同 thread_id
      2. 或者用 update_state 改"下一步"
      3. 也可以让一个 entry_router 节点先判断从哪里开始

    实战意义: 不同用户 / 不同任务类型, 起点不同
    """
    )


# ============================================================
# 5. 并行 Swarm — 多个 Researcher 同时找资料
# ============================================================
banner("5. 并行 Swarm — 多研究员 + 共享 scratchpad")


class ParallelState(TypedDict):
    messages: Annotated[list, add_messages]
    research_notes: Annotated[list[str], lambda a, b: a + b]


def build_parallel_swarm():
    """3 个研究员并行调研, 然后 writer 整合."""
    llm = get_llm()

    def research_tech(state: ParallelState) -> dict:
        resp = llm.invoke(
            f"从技术角度研究: {state['messages'][-1].content}, 列出 3 个要点, 50 字内。"
        )
        return {"research_notes": [f"[技术] {resp.content}"]}

    def research_market(state: ParallelState) -> dict:
        resp = llm.invoke(
            f"从市场角度研究: {state['messages'][-1].content}, 列出 3 个要点, 50 字内。"
        )
        return {"research_notes": [f"[市场] {resp.content}"]}

    def research_user(state: ParallelState) -> dict:
        resp = llm.invoke(
            f"从用户角度研究: {state['messages'][-1].content}, 列出 3 个要点, 50 字内。"
        )
        return {"research_notes": [f"[用户] {resp.content}"]}

    def writer(state: ParallelState) -> Command:
        notes = "\n".join(state["research_notes"])
        resp = llm.invoke(f"基于研究笔记写一段 100 字总结:\n{notes}")
        return Command(goto=END, update={"messages": [resp]})

    graph = StateGraph(ParallelState)
    graph.add_node("research_tech", research_tech)
    graph.add_node("research_market", research_market)
    graph.add_node("research_user", research_user)
    graph.add_node("writer", writer)
    # 3 个并行入口
    graph.add_edge(START, "research_tech")
    graph.add_edge(START, "research_market")
    graph.add_edge(START, "research_user")
    # 都汇合到 writer
    graph.add_edge("research_tech", "writer")
    graph.add_edge("research_market", "writer")
    graph.add_edge("research_user", "writer")
    return graph.compile()


def demo_parallel_research() -> None:
    app = build_parallel_swarm()
    r = app.invoke(
        {
            "messages": [HumanMessage("AI Agent 商业化前景")],
            "research_notes": [],
        }
    )
    print(f">>> 收集了 {len(r['research_notes'])} 条研究笔记:")
    for note in r["research_notes"]:
        print(f"  - {note[:80]}")
    print(f">>> 最终总结: {r['messages'][-1].content[:100]}")


# ============================================================
# 6. 投票 Swarm — 多 reviewer 取共识
# ============================================================
banner("6. 投票 Swarm — 多 reviewer 取共识")


class VotingState(TypedDict):
    messages: Annotated[list, add_messages]
    votes: Annotated[list[str], lambda a, b: a + b]


def build_voting_swarm():
    """3 个 reviewer 各自给评分, 取多数决."""
    llm = get_llm()

    def reviewer_a(state: VotingState) -> dict:
        resp = llm.invoke(
            f"作为严格审阅人, 评价这段内容 (pass/fail + 1 句话原因):\n{state['messages'][-1].content}"
        )
        return {"votes": [f"[严格] {resp.content}"]}

    def reviewer_b(state: VotingState) -> dict:
        resp = llm.invoke(
            f"作为宽松审阅人, 评价这段内容 (pass/fail + 1 句话原因):\n{state['messages'][-1].content}"
        )
        return {"votes": [f"[宽松] {resp.content}"]}

    def reviewer_c(state: VotingState) -> dict:
        resp = llm.invoke(
            f"作为专业审阅人, 评价这段内容 (pass/fail + 1 句话原因):\n{state['messages'][-1].content}"
        )
        return {"votes": [f"[专业] {resp.content}"]}

    def tally(state: VotingState) -> Command:
        votes = state["votes"]
        pass_count = sum(1 for v in votes if "pass" in v.lower())
        decision = "通过" if pass_count >= 2 else "打回"
        return Command(
            goto=END,
            update={"messages": [AIMessage(content=f"[投票结果] {pass_count}/{len(votes)} pass, {decision}")]},
        )

    graph = StateGraph(VotingState)
    graph.add_node("reviewer_a", reviewer_a)
    graph.add_node("reviewer_b", reviewer_b)
    graph.add_node("reviewer_c", reviewer_c)
    graph.add_node("tally", tally)
    graph.add_edge(START, "reviewer_a")
    graph.add_edge(START, "reviewer_b")
    graph.add_edge(START, "reviewer_c")
    graph.add_edge("reviewer_a", "tally")
    graph.add_edge("reviewer_b", "tally")
    graph.add_edge("reviewer_c", "tally")
    return graph.compile()


def demo_voting() -> None:
    app = build_voting_swarm()
    r = app.invoke(
        {
            "messages": [HumanMessage("这是一段待审内容: LangGraph 是构建有状态 Agent 的框架。")],
            "votes": [],
        }
    )
    print(">>> 3 个 reviewer 投票:")
    for v in r["votes"]:
        print(f"  - {v[:80]}")
    print(f">>> 最终: {r['messages'][-1].content}")

    # 💡 实战:
    #   - 多 LLM 投票 (ensemble) 降低单模型偏差
    #   - 不同 prompt / 不同 model 投票
    #   - 类似 self-consistency / MoA (Mixture of Agents)


# ============================================================
# 7. 实战案例 — 客服工单自动处理 Swarm
# ============================================================
banner("7. 实战案例 — 客服工单 Swarm")


def demo_customer_service_swarm() -> None:
    """模拟客服工单自动处理: 分类 → 处理 → 复核 → 关闭."""
    print(
        """
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
    """
    )


# ============================================================
# 8. Swarm 模式选型 — 什么时候用
# ============================================================
banner("8. Swarm 模式选型")


def demo_swarm_selection() -> None:
    print(
        """
    ┌────────────────────┬──────────────┬──────────┬──────────┬──────────────┐
    │ 场景               │ Supervisor    │ Handoff  │ Swarm    │ 推荐         │
    ├────────────────────┼──────────────┼──────────┼──────────┼──────────────┤
    │ 客服分流 (3-5 专家)│ ✓ 最合适     │ 可       │ 过度设计 │ Supervisor   │
    │ 客服对话 (转接)    │ 一般         │ ✓ 最合适 │ 可       │ Handoff      │
    │ 研究报告 (协作)    │ 单点瓶颈     │ 路径受限 │ ✓ 最合适 │ Swarm        │
    │ 多 LLM 投票        │ 中央调度     │ 多次跳转 │ ✓ 最合适 │ Swarm (并行) │
    │ 探索型 agent       │ 路由死板     │ 单入口   │ ✓ 最合适 │ Swarm        │
    │ 业务流程 (固定流)  │ OK           │ OK       │ 过度灵活 │ 单图 / pipe  │
    └────────────────────┴──────────────┴──────────┴──────────┴──────────────┘

    决策原则:
      - 业务稳定 + 路径明确 → 单图 / Supervisor
      - 灵活对话 + 单一入口 → Handoff
      - 多角色协作 + 探索型 → Swarm
    """
    )


# ============================================================
# 9. Swarm 的坑 — 实战经验
# ============================================================
banner("9. Swarm 的坑 — 实战经验")


def demo_swarm_pitfalls() -> None:
    print(
        """
    Swarm 模式的 4 大坑:

    1. 死循环
       - a→b→a→b→... 无限循环
       - 防: max_handoffs + timeout + visited 集合

    2. 成本失控
       - 多个 agent + 多次 handoff = LLM 调用 N 倍
       - 防: 加 budget 限制, 监控单次对话成本

    3. 调试难
       - 路径不可预测, 失败难复现
       - 防: 全量 LangSmith trace + 强制 routing_log

    4. 状态污染
       - 所有 agent 共享 messages, 容易混上下文
       - 防: 给每个 agent 用独立的 prompt 段, 用 metadata 标记
    """
    )


# ============================================================
# 10. 生产架构 — Swarm 落地
# ============================================================
banner("10. 生产架构 — Swarm 落地")


def demo_production_snippet() -> None:
    snippet = """
    # 生产 Swarm 标准接法:

    # 1. handoff_count 强制上限 (防死循环)
    MAX_HANDOFFS = 5
    if state.get("handoff_count", 0) >= MAX_HANDOFFS:
        return Command(goto=END, update={"messages": [AIMessage("已达上限")]})

    # 2. timeout 强制上限 (防 LLM 卡死)
    #    LangGraph 用 recursion_limit=25 (节点执行次数)
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
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    for name, fn in [
        ("demo_swarm_concept", demo_swarm_concept),
        ("demo_research_swarm", demo_research_swarm),
        ("demo_deadlock_protection", demo_deadlock_protection),
        ("demo_multi_entry", demo_multi_entry),
        ("demo_parallel_research", demo_parallel_research),
        ("demo_voting", demo_voting),
        ("demo_customer_service_swarm", demo_customer_service_swarm),
        ("demo_swarm_selection", demo_swarm_selection),
        ("demo_swarm_pitfalls", demo_swarm_pitfalls),
        ("demo_production_snippet", demo_production_snippet),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 15_swarm.py 全部 demo 跑完。")
