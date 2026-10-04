"""05_hitl_tools.py — Demo 5: HumanInTheLoopMiddleware — 危险工具前暂停等人批.

学完这个 demo 你能回答:
1.  HumanInTheLoopMiddleware 怎么给危险工具加审批?
2.  interrupt_on={tool: {"allowed_decisions": [...]}} 怎么配?
3.  agent 跑到危险工具时怎么自动暂停? (checkpointer 必须)
4.  Command(resume={"decisions": [...]}) 怎么传审批决策?
5.  approved / rejected / edit 三种决策分别什么意思?
6.  怎么程序化检测 "是否在暂停状态"? (state.next / state.tasks[0].interrupts)
7.  多决策怎么传 (一个 interrupt 触发多个工具审批)?

跑法:
    python 05_hitl_tools.py
"""
from __future__ import annotations

import os
import sys

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from _common import banner, get_llm, step
from tools import calculator, refund, write_note

# ============================================================
# Demo
# ============================================================
banner("Demo 5: Human-in-the-Loop for Sensitive Tools")


# ============================================================
# Step 1: 配 HITL middleware — interrupt_on 字典
# ============================================================
def demo_configure_hitl() -> None:
    step(1, "配 HumanInTheLoopMiddleware — interrupt_on={tool: {allowed_decisions}}")

    # HumanInTheLoopMiddleware 自动拦截指定工具, 暂停等 resume
    # allowed_decisions: ["approve", "edit", "reject"]
    #   approve = 通过
    #   edit    = 改参数后通过 (需传 edited_action)
    #   reject  = 拒绝 (LLM 会看到拒绝结果, 可以重试或放弃)
    middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "refund": {
                "allowed_decisions": ["approve", "edit", "reject"],
            },
            "write_note": {
                "allowed_decisions": ["approve", "reject"],  # 不允许 edit
            },
            # calculator 不在 interrupt_on 里 → 直接执行, 不暂停
        },
    )

    print("  配 interrupt_on:")
    print(f"    refund     : approve/edit/reject")
    print(f"    write_note : approve/reject")
    print(f"    calculator : (no interrupt → 直通)")
    print(f"  middleware type: {type(middleware).__name__}")

    # 💡 实战 allowed_decisions 选择:
    #    - 退款: 允许 edit (主管改金额) — 复杂决策
    #    - 写笔记: 只 approve/reject — 简单 yes/no
    #    - 删数据: 只 approve/reject — edit 太危险
    #    - 调付费 API: 只 approve/reject — 不能让 AI 改金额


# ============================================================
# Step 2: Safe tool (calculator) — 不在 interrupt_on 里 → 直通
# ============================================================
def demo_safe_tool_passes() -> None:
    step(2, "Safe tool (calculator) — 不在 interrupt_on → 直通")

    llm = get_llm()
    checkpointer = InMemorySaver()

    agent_with_hitl = (
        # 用 create_agent 重新创建 — 加 HITL middleware
        # 这里直接构造, 避免 import create_agent 在模块顶部
        __import__("langchain.agents", fromlist=["create_agent"]).create_agent(
            model=llm,
            tools=[calculator, refund, write_note],
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "refund": {"allowed_decisions": ["approve", "reject"]},
                        "write_note": {"allowed_decisions": ["approve", "reject"]},
                    },
                ),
            ],
            checkpointer=checkpointer,
        )
    )

    config = {"configurable": {"thread_id": "hitl-safe-1"}}

    # 触发 calculator — 应该直接返回, 不暂停
    print(">>> invoke 1: 触发 calculator (应该不暂停)")
    try:
        agent_with_hitl.invoke(
            {"messages": [HumanMessage("帮我算 (100+200)*3")]},
            config=config,
        )
    except Exception as e:
        print(f"  invoke 异常: {type(e).__name__}: {str(e)[:100]}")

    state = agent_with_hitl.get_state(config)
    if state.next:
        print(f"  ❌ 居然暂停了: {state.next}")
    else:
        print(f"  ✓ calculator 没触发 interrupt, agent 已结束")
        msgs = state.values.get("messages", [])
        if msgs:
            print(f"  最终回复: {msgs[-1].content[:120]}")


# ============================================================
# Step 3: Sensitive tool (refund) — 应该触发 interrupt
# ============================================================
def demo_refund_triggers_interrupt() -> None:
    step(3, "Sensitive tool (refund) — 触发 interrupt, 暂停")

    llm = get_llm()
    checkpointer = InMemorySaver()

    agent_with_hitl = (
        __import__("langchain.agents", fromlist=["create_agent"]).create_agent(
            model=llm,
            tools=[refund],
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "refund": {"allowed_decisions": ["approve", "edit", "reject"]},
                    },
                ),
            ],
            checkpointer=checkpointer,
        )
    )

    config = {"configurable": {"thread_id": "hitl-refund-1"}}

    print(">>> invoke 1: 触发 refund (应该暂停)")
    try:
        agent_with_hitl.invoke(
            {"messages": [HumanMessage("帮订单 12345 退款 5000 分, 原因是客户投诉")]},
            config=config,
        )
    except Exception as e:
        print(f"  invoke 异常: {type(e).__name__}: {str(e)[:100]}")

    # 检查 state
    state = agent_with_hitl.get_state(config)
    if state.next:
        print(f"  ✓ 已暂停, next: {state.next}")
        # 看 interrupt 的内容 (待审批的 tool_call)
        if state.tasks and state.tasks[0].interrupts:
            for intr in state.tasks[0].interrupts:
                print(f"  待审批: {intr.value}")
    else:
        print(f"  [i] Agent 没暂停 (小模型如 M3 工具调用不稳)")
        print(f"       Claude / GPT 上会真触发 — 试 mininax 或 deepseek")


# ============================================================
# Step 4: write_note — 触发 interrupt 后用 Command 传 approve
# ============================================================
def demo_write_note_approve() -> None:
    step(4, "write_note — interrupt 后用 Command(resume=approve) 恢复")

    llm = get_llm()
    checkpointer = InMemorySaver()

    agent_with_hitl = (
        __import__("langchain.agents", fromlist=["create_agent"]).create_agent(
            model=llm,
            tools=[write_note],
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "write_note": {"allowed_decisions": ["approve", "reject"]},
                    },
                ),
            ],
            checkpointer=checkpointer,
        )
    )

    config = {"configurable": {"thread_id": "hitl-note-1"}}

    # 第一次 invoke: 触发 write_note → interrupt
    print(">>> invoke 1: 触发 write_note (应该暂停)")
    try:
        agent_with_hitl.invoke(
            {"messages": [HumanMessage("帮我写一条笔记: 明天开会讨论 RAG 升级")]},
            config=config,
        )
    except Exception as e:
        print(f"  invoke 异常: {type(e).__name__}: {str(e)[:100]}")

    state = agent_with_hitl.get_state(config)
    if not state.next:
        print(f"  [i] Agent 没暂停 (跳过 resume demo)")
        return

    print(f"  ✓ 已暂停: {state.next}")

    # 第二次 invoke: Command(resume=...) 传审批决策
    # 格式: {"decisions": [{"type": "approve"}]}
    print(">>> invoke 2: 主管批准 (approve)")
    try:
        result = agent_with_hitl.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )
        msgs = result["messages"]
        print(f"  最终消息数: {len(msgs)}")
        print(f"  最终回复: {msgs[-1].content[:150]}")
    except Exception as e:
        print(f"  resume 异常: {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# Step 5: write_note — reject 决策
# ============================================================
def demo_write_note_reject() -> None:
    step(5, "write_note — reject 决策 (LLM 收到 rejected 反馈)")

    llm = get_llm()
    checkpointer = InMemorySaver()

    agent_with_hitl = (
        __import__("langchain.agents", fromlist=["create_agent"]).create_agent(
            model=llm,
            tools=[write_note],
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "write_note": {"allowed_decisions": ["approve", "reject"]},
                    },
                ),
            ],
            checkpointer=checkpointer,
        )
    )

    config = {"configurable": {"thread_id": "hitl-reject-1"}}

    print(">>> invoke 1: 触发 write_note")
    try:
        agent_with_hitl.invoke(
            {"messages": [HumanMessage("写笔记: 用户手机号 13800138000")]} ,
            config=config,
        )
    except Exception as e:
        print(f"  invoke 异常: {type(e).__name__}: {str(e)[:100]}")

    state = agent_with_hitl.get_state(config)
    if not state.next:
        print(f"  [i] Agent 没暂停 (跳过 reject demo)")
        return

    # 拒绝
    print(">>> invoke 2: 主管拒绝 (reject) — 因为含 PII")
    try:
        result = agent_with_hitl.invoke(
            Command(resume={"decisions": [{"type": "reject"}]}),
            config=config,
        )
        msgs = result["messages"]
        print(f"  最终消息数: {len(msgs)}")
        print(f"  最终回复: {msgs[-1].content[:200]}")
    except Exception as e:
        print(f"  resume 异常: {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# Step 6: edit 决策 — 改参数后批准
# ============================================================
def demo_refund_edit() -> None:
    step(6, "refund — edit 决策 (主管改金额后批准)")

    llm = get_llm()
    checkpointer = InMemorySaver()

    agent_with_hitl = (
        __import__("langchain.agents", fromlist=["create_agent"]).create_agent(
            model=llm,
            tools=[refund],
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "refund": {"allowed_decisions": ["approve", "edit", "reject"]},
                    },
                ),
            ],
            checkpointer=checkpointer,
        )
    )

    config = {"configurable": {"thread_id": "hitl-edit-1"}}

    print(">>> invoke 1: 触发 refund (amount=10000)")
    try:
        agent_with_hitl.invoke(
            {"messages": [HumanMessage("订单 999 退款 10000 分")]} ,
            config=config,
        )
    except Exception as e:
        print(f"  invoke 异常: {type(e).__name__}: {str(e)[:100]}")

    state = agent_with_hitl.get_state(config)
    if not state.next:
        print(f"  [i] Agent 没暂停 (跳过 edit demo)")
        return

    print(f"  ✓ 已暂停: {state.next}")

    # edit 决策: 改 amount_cents 从 10000 → 5000
    # 格式: {"type": "edit", "edited_action": {"name": "refund", "args": {...}}}
    print(">>> invoke 2: 主管 edit (amount 10000 → 5000)")
    try:
        result = agent_with_hitl.invoke(
            Command(
                resume={
                    "decisions": [
                        {
                            "type": "edit",
                            "edited_action": {
                                "name": "refund",
                                "args": {
                                    "order_id": 999,
                                    "amount_cents": 5000,  # 改小了
                                    "reason": "客户投诉 (主管审核后调整)",
                                },
                            },
                        }
                    ]
                }
            ),
            config=config,
        )
        msgs = result["messages"]
        print(f"  最终消息数: {len(msgs)}")
        print(f"  最终回复: {msgs[-1].content[:200]}")
    except Exception as e:
        print(f"  resume 异常: {type(e).__name__}: {str(e)[:100]}")

    # 💡 edit 决策实战:
    #    - 金额 / 数量 / 期限 类参数 — 主管常常想改
    #    - LangChain 1.x edit 格式: {"type": "edit", "edited_action": {"name": str, "args": dict}}
    #    - 必须保留 tool 名 + 所有必填参数 (否则 Pydantic 校验失败)


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    if not has_key:
        print("[!] 没 API key — HITL demo 全跳过 (需要 LLM 触发工具)")
        sys.exit(0)

    demos = [
        ("configure_hitl", demo_configure_hitl),
        ("safe_tool_passes", demo_safe_tool_passes),
        ("refund_triggers_interrupt", demo_refund_triggers_interrupt),
        ("write_note_approve", demo_write_note_approve),
        ("write_note_reject", demo_write_note_reject),
        ("refund_edit", demo_refund_edit),
    ]
    for name, fn in demos:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 05_hitl_tools.py 全部 demo 跑完。")
    print("[i] 小模型 (M3) 工具调用不稳, HITL 可能不会触发. 试 Claude/GPT/DeepSeek.")