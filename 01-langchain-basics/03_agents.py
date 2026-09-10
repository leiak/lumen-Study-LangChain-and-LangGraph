"""03_agents.py — create_agent: LangChain 1.0 统一 Agent 入口.

学完这个模块你能回答:
1.  create_agent 怎么用? (model + tools → 编译好的图)
2.  怎么配 system_prompt 控角色 / 行为?
3.  怎么让 Agent 输出结构化结果 (response_format)?
4.  怎么存多轮对话 (checkpointer + thread_id)?
5.  怎么扩展 state 字段 (state_schema + reducer)?
6.  怎么注入运行时上下文 (context_schema)?
7.  middleware 怎么拦截 pre/post-model? (before_model / after_model)
8.  怎么在工具调用前人工审批 (interrupt_before)?
9.  stream 有几种模式 (values / updates / messages)?
10. Agent 死循环了怎么办 (recursion_limit)?

跑法:
    python 03_agents.py
"""
from __future__ import annotations

import os
import sys
from operator import add as add_int

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain.agents import create_agent
from langchain.agents.middleware import AgentState
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from _common import banner, get_llm

# ============================================================
# 共享工具 (模块顶层定义, 所有 demo 复用)
# ============================================================


@tool
def get_weather(city: str) -> str:
    """查某城市天气 (mock)。"""
    return f"{city} 晴, 25°C"


@tool
def get_time(timezone: str = "Asia/Shanghai") -> str:
    """查某时区当前时间 (mock)。"""
    return f"{timezone} 当前时间: 14:30"


# ============================================================
# 1. 最基础的 Agent — model + tools 就能跑
# ============================================================
banner("1. create_agent — 最小可用")


def demo_minimal_agent() -> None:
    # create_agent 内部构建一个完整的 StateGraph:
    #   START → model → (有 tool_calls?) → tools → model → ... → END
    # 我们不用手动拼图,框架全包了
    llm = get_llm()
    agent = create_agent(model=llm, tools=[get_weather])

    # invoke 接受 {"messages": [...]} (LangGraph 约定: state 是 dict)
    result = agent.invoke({"messages": [HumanMessage("北京天气怎么样?")]})
    print("messages 长度:", len(result["messages"]))
    print(f"最后一条: {result['messages'][-1].content[:200]}")


# ============================================================
# 2. system_prompt — 控角色 / 行为约束
# ============================================================
banner("2. system_prompt 注入")


def demo_system_prompt() -> None:
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather],
        # system_prompt 会作为 SystemMessage 拼到 messages 最前面,每次 invoke 都生效
        system_prompt="你是一个简短的天气助手,回答不超过 20 字。",
    )

    result = agent.invoke({"messages": [HumanMessage("广州?")]})
    print("回复:", result["messages"][-1].content)

    # 💡 实战技巧: system_prompt 也可以是 callable (动态生成)
    #   system_prompt=lambda state: f"用户偏好: {state['preferences']}"
    # 每次 invoke 根据 state 动态生成,适合多租户场景


# ============================================================
# 3. response_format — 让 Agent 吐结构化 JSON
# ============================================================
banner("3. response_format — 结构化输出")


class WeatherReport(BaseModel):
    """天气报告结构."""

    city: str
    temperature: int = Field(description="摄氏度")
    condition: str = Field(description="晴/多云/雨 等")


def demo_structured_agent() -> None:
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather],
        response_format=WeatherReport,
        system_prompt=(
            "你必须调用 get_weather 工具拿到准确天气数据, "
            "然后用 WeatherReport 结构返回结果。只返回结构化数据,不要解释。"
        ),
    )

    result = agent.invoke({"messages": [HumanMessage("深圳天气?")]})
    sr = result.get("structured_response")
    if sr:
        print(f"结构化结果: city={sr.city}, temp={sr.temperature}, condition={sr.condition}")
        print(f"  → isinstance(sr, WeatherReport): {isinstance(sr, WeatherReport)}")
    else:
        # 退化: 部分模型不会自动吐结构化,要 prompt 强约束才稳
        last = result["messages"][-1]
        print(f"⚠️ Agent 没返回结构化, 最后一条: {last.content[:120]}")
        print(">>> 提示: response_format 需要 system prompt 强制要求才稳定触发")


# ============================================================
# 4. 多轮对话 — checkpointer + thread_id
# ============================================================
banner("4. 多轮对话 (checkpointer)")


def demo_multiturn() -> None:
    llm = get_llm()
    # InMemorySaver → 进程内存;生产用 PostgresSaver / SqliteSaver
    checkpointer = InMemorySaver()

    agent = create_agent(
        model=llm,
        tools=[get_weather],
        checkpointer=checkpointer,
    )

    # thread_id 是会话的唯一标识 — 同一 thread 共享历史,不同 thread 隔离
    config = {"configurable": {"thread_id": "user-001"}}

    # 第一轮: LLM 不知道你叫什么
    agent.invoke({"messages": [HumanMessage("我叫王明, 住在北京")]}, config=config)
    # 第二轮: LLM 通过 thread_id 找到历史,记得你叫王明
    r2 = agent.invoke({"messages": [HumanMessage("我叫什么? 住哪?")]}, config=config)
    print("第二轮回复:", r2["messages"][-1].content)

    # 拿到完整历史 (LangGraph state inspection)
    state = agent.get_state(config)
    print(f"\n历史消息数: {len(state.values['messages'])}")
    print(f"thread_id 隔离: 换个 thread_id 是全新会话")
    other = agent.invoke(
        {"messages": [HumanMessage("我叫什么?")]},
        config={"configurable": {"thread_id": "user-002"}},
    )
    print(f"  user-002 回复: {other['messages'][-1].content[:80]}")


# ============================================================
# 5. state_schema — 自定义 state 字段 + reducer
# ============================================================
banner("5. state_schema — 自定义状态字段")


def demo_state_schema() -> None:
    # AgentState 是 LangChain 1.x 默认 state (含 messages)
    # 我们继承它,加自定义字段
    class CustomState(AgentState):
        """扩展 state: 加 user_id 和 turn_count."""

        user_id: str = "anonymous"
        # Annotated[..., add_int] → reducer, 每次 invoke 自动累加
        turn_count: Annotated[int, add_int] = 0

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather],
        state_schema=CustomState,
    )

    config = {"configurable": {"thread_id": "state-demo"}}

    r1 = agent.invoke(
        {
            "messages": [HumanMessage("北京天气?")],
            "user_id": "user-001",
            # turn_count 不传 → 走 default (0) + reducer → 实际是 0+1
        },
        config=config,
    )
    print(f"第 1 轮 turn_count: {r1.get('turn_count')}, user_id: {r1.get('user_id')}")

    r2 = agent.invoke(
        {
            "messages": [HumanMessage("上海?")],
            "user_id": "user-001",
        },
        config=config,
    )
    # 同 thread → reducer 累加: 0 → 1 → 2
    print(f"第 2 轮 turn_count: {r2.get('turn_count')}")

    # 💡 reducer 模式跟 LangGraph 的 Operator.add / add_messages 是一回事
    # 适用: 计数 / 累积日志 / append-only 列表


# ============================================================
# 6. context_schema — 注入运行时上下文 (不可变配置)
# ============================================================
banner("6. context_schema — 运行时上下文")


def demo_context_schema() -> None:
    from pydantic import BaseModel as _BM

    class AppContext(_BM):
        """运行时上下文: 不可变, 每次 invoke 注入, LLM 看不到但工具能拿到."""

        user_id: str = "anonymous"
        locale: str = "zh-CN"

    @tool
    def get_personalized_greeting(city: str) -> str:
        """基于用户上下文生成问候。"""
        # context 通过 InjectedToolArg 或 config 注入 (见 02_tools.py 演示)
        return f"您好,为您查询 {city} 的天气"

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_personalized_greeting, get_weather],
        context_schema=AppContext,
        system_prompt="个性化助手, 用用户的 locale 回答。",
    )

    # invoke 时通过 context= 传,框架自动注入到工具 (via InjectedToolArg)
    result = agent.invoke(
        {"messages": [HumanMessage("杭州?")]},
        context=AppContext(user_id="U-Alice", locale="zh-CN"),
    )
    print("回复:", result["messages"][-1].content[:200])

    # 💡 context vs state 的区别:
    #   context: 不可变配置 (user_id / api_key / feature_flags),每次 invoke 注入
    #   state:   可变状态 (messages / turn_count / 自定义字段),reducer 合并
    # 一个是"配置",一个是"状态"


# ============================================================
# 7. middleware — 拦截 pre/post-model
# ============================================================
banner("7. middleware (before_model / after_model)")


def demo_middleware_basic() -> None:
    from langchain.agents.middleware import (
        after_model,
        before_model,
    )

    @before_model
    def log_before(state: AgentState, runtime) -> dict | None:
        """在调 LLM 前跑。可以返回 dict 修改 state,返回 None 不修改."""
        last = state["messages"][-1] if state["messages"] else None
        if last:
            print(f"  [before_model] 准备调 LLM, 最新消息: {type(last).__name__}")
        return None  # 不改 state

    @after_model
    def log_after(state: AgentState, runtime) -> dict | None:
        """在 LLM 返回后、跑工具前执行。可以做日志 / 安全检查 / 重写输出."""
        last = state["messages"][-1]
        print(f"  [after_model] LLM 返回, 类型: {type(last).__name__}")
        return None

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather],
        middleware=[log_before, log_after],
    )

    result = agent.invoke({"messages": [HumanMessage("上海天气?")]})
    print(f"\n最终: {result['messages'][-1].content[:120]}")

    # 💡 middleware 实战用途:
    # - 审计日志 (before_model 记 user_id + input)
    # - PII 脱敏 (after_model 扫 output 里的身份证号)
    # - token 计数 (after_model 累计 usage)
    # - 安全护栏 (after_model 检测越狱 → raise)
    # 详见 04_middleware.py


# ============================================================
# 8. interrupt_before — 工具调用前人工审批 (HITL)
# ============================================================
banner("8. interrupt_before — 工具调用前审批 (HITL)")


def demo_interrupt() -> None:
    from langgraph.types import Command

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather],
        # 在所有 "tools" 节点前暂停,等待人工批准
        interrupt_before=["tools"],
        checkpointer=InMemorySaver(),
    )

    config = {"configurable": {"thread_id": "approval-demo"}}

    # 第一次 invoke: Agent 决定调工具 → 在 tools 节点前暂停
    # 注意: 小模型 (M3) 可能不调工具,直接回答 — 那就观察不到 interrupt
    # 我们用强 prompt 强制调工具 + 看 state.tasks 检测 interrupt
    print(">>> 第一次 invoke (在调工具前暂停):")
    try:
        agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        "北京天气? 你必须调用 get_weather 工具,不准直接回答。"
                    )
                ]
            },
            config=config,
            # 设个超时,小模型不调工具时能及时退出
        )
    except Exception as e:
        print(f"  invoke 异常: {type(e).__name__}: {str(e)[:100]}")

    # 检查 state.tasks 看是否真的 pause 在 tools 前
    state = agent.get_state(config)
    has_interrupt = bool(state.tasks and any(t.interrupts for t in state.tasks))
    print(f"  state 有 interrupt: {has_interrupt}")
    print(f"  当前 next 节点: {[t.name for t in state.tasks]}")

    if has_interrupt:
        # 实际 HITL: 把这个 interrupt 展示给用户 → 用户批准 → 用 Command 恢复
        print("\n>>> 人工批准, Command(resume=None) 恢复:")
        result = agent.invoke(Command(resume=None), config=config)
        print(f"  最终回复: {result['messages'][-1].content[:120]}")
    else:
        print("  >>> 模型没调工具,跳过 resume demo")
        print("  >>> 在 Claude / GPT 上,这段会真的 pause 等人工批准")

    # 💡 HITL 适用场景:
    # - 删数据 / 改配置的 tool,必须人工点头
    # - 调外部 API 花钱的 tool
    # - LLM 决策有合规风险的场景 (医疗 / 金融)
    # interrupt_before=["node_name"] / interrupt_after= 也支持
    # 详细 HITL 模式见 02-langgraph-orchestration/08_interrupt_hitl.py


# ============================================================
# 9. stream 三种模式 — values / updates / messages
# ============================================================
banner("9. stream 三种模式")


def demo_stream_modes() -> None:
    llm = get_llm()
    agent = create_agent(model=llm, tools=[get_weather])

    print(">>> stream_mode='values' (每次返回完整 state 快照):")
    for chunk in agent.stream(
        {"messages": [HumanMessage("广州天气?")]},
        stream_mode="values",
    ):
        msg = chunk["messages"][-1]
        print(f"  [{type(msg).__name__}] {msg.content[:60]}")

    print("\n>>> stream_mode='updates' (只返回本步 delta):")
    for chunk in agent.stream(
        {"messages": [HumanMessage("深圳天气?")]},
        stream_mode="updates",
    ):
        # chunk 格式: {"node_name": {state_delta}}
        for node, delta in chunk.items():
            if "messages" in delta:
                print(f"  [{node}] {type(delta['messages'][-1]).__name__}")

    print("\n>>> stream_mode='messages' (LLM token 级流式):")
    for token_msg, metadata in agent.stream(
        {"messages": [HumanMessage("杭州?")]},
        stream_mode="messages",
    ):
        # 只打印 AIMessage 的 content token,ToolMessage / HumanMessage 跳过
        if hasattr(token_msg, "content") and token_msg.content:
            print(f"  [token] {token_msg.content}", end="", flush=True)
    print()


# ============================================================
# 10. recursion_limit — Agent 死循环兜底
# ============================================================
banner("10. recursion_limit — 死循环兜底")


def demo_recursion_limit() -> None:
    # 故意造一个会无限循环的 agent: 工具永远返回"再查一次"
    @tool
    def infinite_lookup(query: str) -> str:
        """(故意) 永远让 Agent 再查一次 — 演示 recursion_limit."""
        return "没找到, 请再查一次"

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[infinite_lookup],
        # recursion_limit 限制图的递归步数, 超限抛 GraphRecursionError
        # 注意: recursion_limit 通过 invoke(stream) 的 config 传, 不在 create_agent 里
    )

    try:
        agent.invoke(
            {"messages": [HumanMessage("找一个不存在的东西")]},
            config={"recursion_limit": 5},
        )
    except Exception as e:
        # LangGraph 在超限时会抛 GraphRecursionError
        print(f"✓ 兜底成功: {type(e).__name__}")
        print(f"  消息: {str(e)[:150]}")

    # 💡 实战建议:
    #   - 默认 recursion_limit=25, 调 LLM 多的 Agent (复杂 RAG) 要调高
    #   - 调外部 API 多的 Agent 反而要调低, 省钱 + 快速失败
    #   - 配合 max_iterations / max_execution_time 一起用


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

    demos = [
        ("demo_recursion_limit", demo_recursion_limit)
        # ("demo_minimal_agent", demo_minimal_agent),
        # ("demo_system_prompt", demo_system_prompt),
        # ("demo_structured_agent", demo_structured_agent),
        # ("demo_multiturn", demo_multiturn),
        # ("demo_state_schema", demo_state_schema),
        # ("demo_context_schema", demo_context_schema),
        # ("demo_middleware_basic", demo_middleware_basic),
        # ("demo_interrupt", demo_interrupt),
        # ("demo_stream_modes", demo_stream_modes),
        # ("demo_recursion_limit", demo_recursion_limit),
    ]

    # 每个 demo 独立 try/except — 单个失败不影响其它
    for name, fn in demos:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 03_agents.py 全部 demo 跑完。")
