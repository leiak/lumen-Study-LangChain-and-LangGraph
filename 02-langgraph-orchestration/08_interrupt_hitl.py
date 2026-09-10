"""08_interrupt_hitl.py — Interrupt & Human-in-the-Loop.

学完这个模块你能回答:
1.  interrupt() 怎么在节点中暂停?
2.  怎么用 Command(resume=...) 恢复 Agent?
3.  怎么拦截工具参数 (e.g. 金额 > 100 才审批)?
4.  怎么支持 edit 决策 (主管改参数后批准)?
5.  怎么在 interrupt 后给 LLM 反馈让它重试?
6.  多轮审批怎么串 (主管 → 用户 → 执行)?
7.  怎么把 HITL 集成到 LangGraph Studio / 前端?

跑法:
    python 08_interrupt_hitl.py
"""
from __future__ import annotations

import os
import sys
from typing import Annotated, Literal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from _common import banner, get_llm

# ============================================================
# 0. 准备工具
# ============================================================


@tool
def refund_order(order_id: str, amount: float) -> str:
    """给订单退款。生产环境这是危险操作, 需要人工审批。"""
    return f"订单 {order_id} 已退款 {amount} 元"


@tool
def get_weather(city: str) -> str:
    """查天气."""
    return f"{city} 晴 25°C"


# ============================================================
# 1. interrupt() — 在节点中暂停
# ============================================================
banner("1. interrupt() — 在节点中暂停")


def demo_basic_interrupt() -> None:
    def human_review_node(state: MessagesState) -> dict:
        # interrupt 暂停图执行, 等外部 Command(resume=...) 恢复
        # 这里给人类一个"问卷", 人类的回答通过 resume= 传回来
        decision = interrupt({
            "question": "请审批 Agent 当前操作:",
            "messages_preview": [m.content[:60] for m in state["messages"][-3:]],
        })
        return {"messages": [HumanMessage(content=f"[人类审批]: {decision}")]}

    llm = get_llm().bind_tools([refund_order])

    def call_llm(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def call_tools(state: MessagesState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            if tc["name"] == "refund_order":
                results.append(
                    ToolMessage(
                        content=str(refund_order.invoke(tc["args"])),
                        tool_call_id=tc["id"],
                    )
                )
        return {"messages": results}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return "human_review"

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", call_tools)
    graph.add_node("human_review", human_review_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", "human_review"])
    graph.add_edge("tools", "agent")
    graph.add_edge("human_review", END)

    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "hitl-1"}}

    print(">>> 第 1 次 invoke (触发工具 → human_review 暂停):")
    app.invoke({"messages": [HumanMessage("帮订单 #123 退款 100 元")]}, config=config)
    state = app.get_state(config)
    if state.next:
        print(f"  暂停在: {state.next}")
        if state.tasks and state.tasks[0].interrupts:
            print(f"  待审批: {state.tasks[0].interrupts[0].value}")

        print(">>> 第 2 次 invoke (主管批准 → 恢复):")
        result = app.invoke(Command(resume="approved"), config=config)
        print(f"  最终 messages 数: {len(result['messages'])}")
    else:
        print("  Agent 没暂停 (小模型可能不调工具)")


# ============================================================
# 2. 工具调用前 interrupt — 拦截参数 (按规则)
# ============================================================
banner("2. 工具前 interrupt — 按参数阈值拦截")


def demo_tool_interrupt() -> None:
    llm = get_llm().bind_tools([refund_order])

    def call_llm(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def call_tools_with_check(state: MessagesState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            if tc["name"] == "refund_order":
                amount = tc["args"].get("amount", 0)
                if amount > 100:
                    # 超过 100 必须审批
                    decision = interrupt({
                        "tool_call": tc,
                        "reason": f"退款金额 {amount} > 100, 需要审批",
                    })
                    if decision != "approve":
                        results.append(ToolMessage(
                            content=f"退款被拒绝: {decision}",
                            tool_call_id=tc["id"],
                        ))
                        continue
                results.append(ToolMessage(
                    content=str(refund_order.invoke(tc["args"])),
                    tool_call_id=tc["id"],
                ))
        return {"messages": results}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", call_tools_with_check)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")

    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "hitl-tool-1"}}

    # 测试 1: 金额 50 → 不暂停
    print(">>> 测试 1: 退款 50 元 (无需审批):")
    app.invoke({"messages": [HumanMessage("帮订单 #123 退款 50 元")]}, config=config)
    state = app.get_state(config)
    print(f"  暂停点: {state.next} (空 tuple / None = 已 END)")

    # 测试 2: 金额 200 → 暂停
    print("\n>>> 测试 2: 退款 200 元 (需要审批):")
    config2 = {"configurable": {"thread_id": "hitl-tool-2"}}
    app.invoke({"messages": [HumanMessage("帮订单 #456 退款 200 元")]}, config=config2)
    state = app.get_state(config2)
    if state.next:
        print(f"  暂停在: {state.next}")
        # 批准
        result = app.invoke(Command(resume="approve"), config=config2)
        print(f"  批准后, messages 数: {len(result['messages'])}")

    # 💡 实战模式: 把"金额阈值" / "黑名单用户" / "高风险操作" 都按规则拦
    # 跟 Java 拦截器 / Gin middleware 思路一样


# ============================================================
# 3. Edit 决策 — 主管改参数后批准
# ============================================================
banner("3. Edit 决策 — 改参数后批准")


def demo_edit_decision() -> None:
    """主管可以修改工具参数再批准 (e.g. 200 改成 80)."""
    llm = get_llm().bind_tools([refund_order])

    def call_llm(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def call_tools_with_edit(state: MessagesState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            if tc["name"] == "refund_order":
                amount = tc["args"].get("amount", 0)
                if amount > 100:
                    # decision 是个 dict: {type: 'approve'|'edit'|'reject', args?: ...}
                    decision = interrupt({
                        "tool_call": tc,
                        "options": ["approve", "edit", "reject"],
                    })
                    if isinstance(decision, dict):
                        dtype = decision.get("type")
                        if dtype == "reject":
                            results.append(ToolMessage(
                                content=f"退款被拒绝",
                                tool_call_id=tc["id"],
                            ))
                            continue
                        elif dtype == "edit":
                            # 主管改了参数, 用新参数调
                            new_args = decision.get("args", tc["args"])
                            results.append(ToolMessage(
                                content=str(refund_order.invoke(new_args)),
                                tool_call_id=tc["id"],
                            ))
                            continue
                    # 默认 approve
                results.append(ToolMessage(
                    content=str(refund_order.invoke(tc["args"])),
                    tool_call_id=tc["id"],
                ))
        return {"messages": results}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", call_tools_with_edit)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")

    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "hitl-edit-1"}}

    app.invoke({"messages": [HumanMessage("帮订单 #789 退款 200 元")]}, config=config)
    print(">>> 触发 200 元退款, 等审批:")

    # 模拟主管 edit: 改成 80 元
    edited = {"type": "edit", "args": {"order_id": "#789", "amount": 80.0}}
    result = app.invoke(Command(resume=edited), config=config)
    print(">>> 主管改成 80 元后批准:")
    for m in result["messages"][-3:]:
        print(f"  [{type(m).__name__}] {m.content[:100]}")

    # 💡 HumanInTheLoopMiddleware (04_middleware.py 演示) 也是这个模式
    # 自定义 interrupt 更灵活, 内置 middleware 更省事


# ============================================================
# 4. Reject + 反馈 — 让 LLM 看到拒绝后重试
# ============================================================
banner("4. Reject + 反馈 — 让 LLM 重试")


def demo_reject_feedback() -> None:
    """拒绝退款时, 把原因当 ToolMessage 喂给 LLM, 让它重答."""
    llm = get_llm().bind_tools([refund_order])

    def call_llm(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def call_tools_with_feedback(state: MessagesState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            if tc["name"] == "refund_order":
                decision = interrupt({"tool_call": tc, "reason": "需要审批"})
                if decision == "approve":
                    results.append(ToolMessage(
                        content=str(refund_order.invoke(tc["args"])),
                        tool_call_id=tc["id"],
                    ))
                else:
                    # 把拒绝原因当 ToolMessage 返回, LLM 看到后会重新回答
                    results.append(ToolMessage(
                        content=f"操作被拒绝 (原因: {decision})。请告诉用户无法执行此操作。",
                        tool_call_id=tc["id"],
                    ))
        return {"messages": results}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", call_tools_with_feedback)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")

    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "hitl-reject-1"}}

    app.invoke({"messages": [HumanMessage("帮订单 #999 退款 1000 元")]}, config=config)
    print(">>> 触发 1000 元退款:")

    result = app.invoke(Command(resume="reject: 金额异常, 怀疑欺诈"), config=config)
    print(">>> 拒绝原因: '金额异常, 怀疑欺诈':")
    print(f"  最终 LLM 回复: {result['messages'][-1].content[:150]}")

    # 💡 关键: 把拒绝原因当 ToolMessage 回传
    # LLM 会读 tool result → 重新生成"告诉用户被拒"的回答


# ============================================================
# 5. 多轮审批 — 主管 → 用户 → 执行
# ============================================================
banner("5. 多轮审批 — 主管 → 用户 → 执行")


def demo_multi_interrupt() -> None:
    """多轮串行审批."""
    llm = get_llm()

    class State(TypedDict):
        messages: Annotated[list, add_messages]
        approved: bool
        confirmed: bool

    def step1_propose(state: State) -> dict:
        return {"messages": [HumanMessage(content="[系统] 我准备执行: 退款 200 元")]}

    def step2_manager_review(state: State) -> dict:
        decision = interrupt({"stage": "manager", "msg": "主管审批?"})
        return {"approved": decision == "approve"}

    def step3_user_confirm(state: State) -> dict:
        decision = interrupt({"stage": "user", "msg": "用户确认?"})
        return {"confirmed": decision == "confirm"}

    def step4_execute(state: State) -> dict:
        return {"messages": [HumanMessage(content="已退款 200 元")]}

    def route_after_step2(state: State) -> str:
        return "step3" if state.get("approved") else END

    def route_after_step3(state: State) -> str:
        return "step4" if state.get("confirmed") else END

    graph = StateGraph(State)
    graph.add_node("step1", step1_propose)
    graph.add_node("step2", step2_manager_review)
    graph.add_node("step3", step3_user_confirm)
    graph.add_node("step4", step4_execute)
    graph.add_edge(START, "step1")
    graph.add_edge("step1", "step2")
    graph.add_conditional_edges("step2", route_after_step2, ["step3", END])
    graph.add_conditional_edges("step3", route_after_step3, ["step4", END])
    graph.add_edge("step4", END)

    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "multi-hitl-1"}}

    print(">>> 第 1 次 invoke (停在 step2 等主管):")
    app.invoke({"messages": [], "approved": False, "confirmed": False}, config=config)
    state = app.get_state(config)
    print(f"  暂停点: {state.next}")

    print("\n>>> 主管批准 (resume='approve'):")
    app.invoke(Command(resume="approve"), config=config)
    state = app.get_state(config)
    print(f"  现在停在: {state.next}")

    print("\n>>> 用户确认 (resume='confirm'):")
    r = app.invoke(Command(resume="confirm"), config=config)
    print(f"  最终 messages: {[m.content for m in r['messages']]}")

    # 💡 多轮审批实战:
    #   - 内部审批流: 提交 → 主管 → 总监 → CEO
    #   - 跨系统: 我方 → 对方 API → 我方确认
    #   - 任何"流水线式"人工环节


# ============================================================
# 6. Pydantic schema 的 interrupt — 让前端更好渲染
# ============================================================
banner("6. Pydantic schema 的 interrupt")


def demo_structured_interrupt() -> None:
    """interrupt 用 Pydantic schema 描述问卷, 前端可以自动生成表单."""
    class ApprovalRequest(BaseModel):
        """前端表单: 主管审批问卷."""

        action: Literal["approve", "reject"] = Field(description="审批决定")
        reason: str = Field(default="", description="备注, 拒绝时必填")
        new_amount: float | None = Field(default=None, description="如改金额, 填这里")

    llm = get_llm().bind_tools([refund_order])

    def call_llm(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def call_tools(state: MessagesState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            if tc["name"] == "refund_order":
                # 用 schema 描述 interrupt 的输入, 前端拿到可以自动渲染表单
                decision: ApprovalRequest = interrupt(ApprovalRequest(
                    # action / reason / new_amount 都是前端填
                ).model_dump())
                # 接 decision.new_amount 决定要不要改参数
                if decision["action"] == "reject":
                    results.append(ToolMessage(
                        content=f"被拒: {decision['reason']}",
                        tool_call_id=tc["id"],
                    ))
                else:
                    args = dict(tc["args"])
                    if decision.get("new_amount"):
                        args["amount"] = decision["new_amount"]
                    results.append(ToolMessage(
                        content=str(refund_order.invoke(args)),
                        tool_call_id=tc["id"],
                    ))
        return {"messages": results}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", call_tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")

    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "hitl-schema-1"}}

    app.invoke({"messages": [HumanMessage("帮订单 #A1 退款 300 元")]}, config=config)
    state = app.get_state(config)
    print(">>> 触发 300 元退款, 等审批问卷:")
    if state.tasks and state.tasks[0].interrupts:
        print(f"  问卷 schema: {state.tasks[0].interrupts[0].value}")

    # 主管 approve 并改成 100
    decision = {"action": "approve", "reason": "金额过大, 砍到 100", "new_amount": 100}
    result = app.invoke(Command(resume=decision), config=config)
    print(f">>> 主管改成 100 后批准:")
    for m in result["messages"][-3:]:
        print(f"  [{type(m).__name__}] {m.content[:100]}")

    # 💡 实战: LangGraph Studio / 自己的前端可以用 schema 自动渲染表单
    #   - FastAPI 后端返回 interrupt value (含 schema)
    #   - 前端用 schema 生成 React 表单
    #   - 用户填完 → POST 到 /resume 端点


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
        ("demo_basic_interrupt", demo_basic_interrupt),
        ("demo_tool_interrupt", demo_tool_interrupt),
        ("demo_edit_decision", demo_edit_decision),
        ("demo_reject_feedback", demo_reject_feedback),
        ("demo_multi_interrupt", demo_multi_interrupt),
        ("demo_structured_interrupt", demo_structured_interrupt),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 08_interrupt_hitl.py 全部 demo 跑完。")