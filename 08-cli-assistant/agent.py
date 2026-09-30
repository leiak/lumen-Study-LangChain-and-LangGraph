"""agent.py — 装配 supervisor + 4 specialists.

架构:
  supervisor (create_supervisor)
    ├── WeatherAgent  (create_agent, tools=[get_weather])
    ├── CalcAgent     (create_agent, tools=[calc])
    ├── NotesAgent    (create_agent, tools=[read_note, write_note])
    └── OrdersAgent   (create_agent, tools=[get_order, refund_order])

HITL 挂 supervisor.compile() 上, 危险工具 (refund_order / write_note) 在
HumanInTheLoopMiddleware 里登记, 触发时整个 supervisor graph 暂停.

middleware (PII + dynamic_prompt) 挂 supervisor.compile() 上, supervisor
调 LLM 前生效.

复用:
  - 13_supervisor.py: langgraph_supervisor.create_supervisor
  - 04_middleware.py demo 5: HumanInTheLoopMiddleware
  - 04_middleware.py demo 1/8: dynamic_prompt / wrap_model_call
"""
from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph_supervisor import create_supervisor

from middleware import redact_pii, tone_prompt
from tools import (
    calc,
    get_order,
    get_weather,
    read_note,
    refund_order,
    write_note,
)

# ============================================================
# Specialist 工厂
# ============================================================
def _make_weather_agent(model):
    return create_agent(
        model=model,
        tools=[get_weather],
        system_prompt=(
            "你是 WeatherAgent. 用户问天气时, 调 get_weather 工具, "
            "用中文简洁回答 (不超过 30 字)."
        ),
        name="WeatherAgent",
    )


def _make_calc_agent(model):
    return create_agent(
        model=model,
        tools=[calc],
        system_prompt=(
            "你是 CalcAgent. 用户问数学时, 调 calc 工具, "
            "把结果用一句话告诉用户."
        ),
        name="CalcAgent",
    )


def _make_notes_agent(model):
    return create_agent(
        model=model,
        tools=[read_note, write_note],
        system_prompt=(
            "你是 NotesAgent. 读/写笔记. 调工具后用中文简短回复."
        ),
        name="NotesAgent",
    )


def _make_orders_agent(model):
    return create_agent(
        model=model,
        tools=[get_order, refund_order],
        system_prompt=(
            "你是 OrdersAgent. 查订单 / 退款. 调工具后用中文简短回复. "
            "退款是危险操作, 必须经 HumanInTheLoopMiddleware 审批."
        ),
        name="OrdersAgent",
    )


# ============================================================
# Supervisor 装配
# ============================================================
SUPERVISOR_PROMPT = """你是智能个人助手 supervisor. 根据用户问题, 把任务派给:
  - WeatherAgent: 天气相关
  - CalcAgent:    数学计算
  - NotesAgent:   笔记读写
  - OrdersAgent:  订单/退款

不要直接调工具. 一次只派一个 specialist. 用中文回复用户."""


def build_graph(model, *, checkpointer=None, store=None):
    """Build supervisor graph with middleware + checkpointer + store.

    checkpointer / store 默认 None — 由 caller 注入 (cli.py 负责创建).
    """
    weather_agent = _make_weather_agent(model)
    calc_agent = _make_calc_agent(model)
    notes_agent = _make_notes_agent(model)
    orders_agent = _make_orders_agent(model)

    hitl = HumanInTheLoopMiddleware(
        interrupt_on={
            # write_note / refund_order 触发 HITL
            "write_note": {"allowed_decisions": ["approve", "edit", "reject"]},
            "refund_order": {"allowed_decisions": ["approve", "edit", "reject"]},
        },
    )

    supervisor = create_supervisor(
        agents=[weather_agent, calc_agent, notes_agent, orders_agent],
        model=model,
        prompt=SUPERVISOR_PROMPT,
        output_mode="last_message",  # 只回 supervisor 看到的 final message
    )

    return supervisor.compile(
        checkpointer=checkpointer,
        store=store,
        middleware=[redact_pii, tone_prompt, hitl],
    )


__all__ = ["build_graph"]
