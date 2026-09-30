"""agent.py — 装配 supervisor + 4 specialists.

架构:
  supervisor (create_supervisor)
    ├── WeatherAgent  (create_agent, tools=[get_weather], middleware=[redact_pii, tone_prompt])
    ├── CalcAgent     (create_agent, tools=[calc],          middleware=[redact_pii, tone_prompt])
    ├── NotesAgent    (create_agent, tools=[read_note, write_note],
    │                                       middleware=[redact_pii, tone_prompt, hitl])
    └── OrdersAgent   (create_agent, tools=[get_order, refund_order],
                                          middleware=[redact_pii, tone_prompt, hitl])

重要坑 (spec review R3, fix commit):
  - `supervisor.compile()` 是 `StateGraph.compile()`, 不接受 `middleware=`
    kwarg — middleware 是 langchain.agents.create_agent 的特性, 不是
    langgraph StateGraph 的特性.
  - 解法: middleware 全部下沉到 4 个 specialist 的 `create_agent(middleware=[...])`.
    装饰器 marker 自带去重, LLM 只看到最终状态.
  - hitl 只挂 NotesAgent + OrdersAgent (其它 specialist 没有危险工具,
    HumanInTheLoopMiddleware 挂上去不触发 = 浪费节点).

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
# HITL 配置 — 在有危险工具的 specialist 上挂
# ============================================================
# write_note / refund_order 都登记上, 触发时整个 subgraph 暂停等待
# 人工审批 (cli.py 用 Command(resume=...) 恢复).
_HITL_INTERRUPT_ON = {
    "write_note": {"allowed_decisions": ["approve", "edit", "reject"]},
    "refund_order": {"allowed_decisions": ["approve", "edit", "reject"]},
}


def _hitl():
    """每次 build_graph 调一次, 避免多个 agent 共享同一个 middleware
    实例导致 state schema 冲突 (middleware 会注入额外 state keys)."""
    return HumanInTheLoopMiddleware(interrupt_on=_HITL_INTERRUPT_ON)


# ============================================================
# Specialist 工厂
# ============================================================
# 注意: 每个 specialist 都挂 [redact_pii, tone_prompt].
#   - redact_pii: 在 LLM 看到 user message 之前脱敏 PII
#   - tone_prompt: 根据历史动态切 system prompt (正式/轻松)
# redact_pii 是幂等的, tone_prompt 对相同输入返回相同 prompt — 多个 specialist
# 挂同一 middleware 实例不会改变最终行为. (decorator marker 不去重, 只是这两个
# 函数的语义天然 idempotent.)
def _make_weather_agent(model):
    return create_agent(
        model=model,
        tools=[get_weather],
        system_prompt=(
            "你是 WeatherAgent. 用户问天气时, 调 get_weather 工具, "
            "用中文简洁回答 (不超过 30 字)."
        ),
        name="WeatherAgent",
        middleware=[redact_pii, tone_prompt],
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
        middleware=[redact_pii, tone_prompt],
    )


def _make_notes_agent(model):
    # write_note 是危险工具 → HITL
    return create_agent(
        model=model,
        tools=[read_note, write_note],
        system_prompt=(
            "你是 NotesAgent. 读/写笔记. 调工具后用中文简短回复. "
            "写笔记是敏感操作, 必须经人工审批."
        ),
        name="NotesAgent",
        middleware=[redact_pii, tone_prompt, _hitl()],
    )


def _make_orders_agent(model):
    # refund_order 是危险工具 → HITL
    return create_agent(
        model=model,
        tools=[get_order, refund_order],
        system_prompt=(
            "你是 OrdersAgent. 查订单 / 退款. 调工具后用中文简短回复. "
            "退款是危险操作, 必须经人工审批."
        ),
        name="OrdersAgent",
        middleware=[redact_pii, tone_prompt, _hitl()],
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

    checkpointer / store 默认 None — 由 caller 注入 (T7 cli.py 会传进来).

    middleware 装配说明:
      - supervisor.compile() 是 StateGraph.compile(), 不支持 middleware=
        kwarg (那是 langchain.agents.create_agent 的特性).
      - 所以 redact_pii / tone_prompt / hitl 都下沉到各 specialist 的
        create_agent(middleware=[...]) 里.
      - hitl 只在 NotesAgent / OrdersAgent 上挂 (其它 specialist 没有
        危险工具, HITL 不会触发).
    """
    weather_agent = _make_weather_agent(model)
    calc_agent = _make_calc_agent(model)
    notes_agent = _make_notes_agent(model)
    orders_agent = _make_orders_agent(model)

    supervisor = create_supervisor(
        agents=[weather_agent, calc_agent, notes_agent, orders_agent],
        model=model,
        prompt=SUPERVISOR_PROMPT,
        output_mode="last_message",  # 只回最后一个 specialist 的 final message (supervisor 内部 routing 不进 messages)
    )

    return supervisor.compile(checkpointer=checkpointer, store=store)


__all__ = ["build_graph"]
