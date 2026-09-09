"""04_middleware.py — Middleware: 在 Agent 上插横切逻辑.

学完这个模块你能回答:
1.  @dynamic_prompt 怎么根据请求动态生成 system prompt?
2.  @wrap_model_call 怎么拦截模型调用? (打日志 / 改 prompt / 重试)
3.  @before_model / @after_model 比 wrap_model_call 简单在哪?
4.  @wrap_tool_call 怎么拦截工具执行? (鉴权 / 重试 / metric)
5.  HumanInTheLoopMiddleware 怎么给危险工具加审批?
6.  SummarizationMiddleware 怎么自动压缩长对话?
7.  多个 middleware 的执行顺序是怎样的?
8.  怎么写自定义 middleware 做 PII 脱敏?

跑法:
    python 04_middleware.py
"""
from __future__ import annotations

import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    SummarizationMiddleware,
    after_model,
    before_model,
    dynamic_prompt,
    wrap_model_call,
    wrap_tool_call,
)
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from _common import banner, get_llm

# ============================================================
# 0. 准备工具 — 退款 (危险操作) + 普通工具
# ============================================================


@tool
def refund_order(order_id: str, amount: float) -> str:
    """(mock) 给订单退款。生产环境这是危险操作!"""
    return f"订单 {order_id} 已退款 {amount} 元"


@tool
def get_weather(city: str) -> str:
    """(mock) 查天气."""
    return f"{city} 晴, 25°C"


@tool
def slow_lookup(query: str) -> str:
    """(mock) 故意慢的工具 — 演示 wrap_tool_call 做超时控制."""
    import time

    time.sleep(2)
    return f"results for {query}"


# ============================================================
# 1. @dynamic_prompt — 动态生成 system prompt
# ============================================================
banner("1. @dynamic_prompt — 动态 prompt")


@dynamic_prompt
def tone_prompt(request) -> str:
    """根据请求动态选择语气. request 含 .messages / .model / .tools."""
    user_msg = ""
    for m in request.messages:
        if isinstance(m, HumanMessage):
            user_msg = m.content
            break

    if "正式" in user_msg:
        return "你用正式语气回答,使用'您'。"
    if "轻松" in user_msg:
        return "你用轻松幽默的语气回答,可以用 emoji。"
    return "你正常回答。"


def demo_dynamic_prompt() -> None:
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[tone_prompt],
    )

    print(">>> 正式语气:")
    r = agent.invoke({"messages": [HumanMessage("正式介绍一下 LangChain")]})
    print(f"  {r['messages'][-1].content[:120]}")

    print("\n>>> 轻松语气:")
    r = agent.invoke({"messages": [HumanMessage("轻松介绍一下 LangChain")]})
    print(f"  {r['messages'][-1].content[:120]}")

    # 💡 实战: dynamic_prompt 也常用于多租户场景
    #   @dynamic_prompt
    #   def tenant_prompt(request):
    #       tenant = request.runtime.context.tenant_id
    #       return f"你是 {tenant} 的客服,回答要符合品牌指南..."
    # 也可以读 state (history) 决定语气


# ============================================================
# 2. @wrap_model_call — 完全控制模型调用 (前后插桩)
# ============================================================
banner("2. @wrap_model_call — 模型调用前后插桩")


@wrap_model_call
def log_and_rewrite(request, handler):
    """打日志 + 强制中文回复. 这是最 powerful 的 middleware,可改 request/response."""
    print(f"  [log_and_rewrite] → 调 LLM, {len(request.messages)} 条消息")

    # 在调用前可以改 request: 加 system message / 改 user msg / 切模型
    if not any(isinstance(m, SystemMessage) for m in request.messages):
        request.messages.insert(0, SystemMessage(content="你必须用中文回答。"))

    # 调真正的模型 — 这一行必须存在,否则 agent 不工作
    response = handler(request)

    # 调用后处理: 改 response / 重试 / 缓存
    last = response.result[0] if response.result else None
    content_len = len(last.content) if last and last.content else 0
    print(f"  [log_and_rewrite] ← LLM 回复, {content_len} 字符")
    return response


def demo_wrap_model_call() -> None:
    llm = get_llm()
    agent = create_agent(model=llm, tools=[], middleware=[log_and_rewrite])

    agent.invoke({"messages": [HumanMessage("Hi")]})
    agent.invoke({"messages": [HumanMessage("Hello")]})

    # 💡 wrap_model_call 适用场景:
    # - token 用量统计 / 计费 (response.usage)
    # - fallback: 第一次失败 → 换模型 / 降级 prompt 重试
    # - 输出过滤: response.result 里扫敏感词 → raise
    # - A/B 实验: 不同用户走不同模型


# ============================================================
# 3. @before_model / @after_model — 简化版 (只看一眼/改 state)
# ============================================================
banner("3. @before_model / @after_model — 简化版")


@before_model
def log_before(state, runtime):
    """在调 LLM 前打日志. 不改 state."""
    print(state)
    print(f"  [log_before] 准备调 LLM, 消息数: {len(state['messages'])}")
    return None  # 不改 state


@after_model
def log_after(state, runtime):
    """在 LLM 返回后打日志. 不改 state."""
    last = state["messages"][-1]
    content_preview = (last.content or "")[:60] if hasattr(last, "content") else "<no content>"
    print(f"  [log_after] LLM 返回: {content_preview}...")
    return None


def demo_before_after() -> None:
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather],
        middleware=[log_before, log_after],
    )

    print(">>> before/after 演示 (只打日志,不改 state):")
    r = agent.invoke({"messages": [HumanMessage("深圳?")]})
    print(f"  最终回复: {r['messages'][-1].content[:120]}")

    # 💡 before_model vs wrap_model_call:
    #   before/after: 简单, 只看 state, 适合"加日志/计数/header"等只读场景
    #   wrap_model_call: 完全控制,可改 request / 重试 / fallback 模型
    # 大多数横切需求用 before/after 就够
    #
    # 实战: 想"在 messages 里加东西" → 用 system_prompt 动态版, 别在 before_model 加
    # 想"统计 token" → 用 after_model + response_metadata


# ============================================================
# 4. @wrap_tool_call — 拦截工具执行 (鉴权 / 超时 / 重试 / metric)
# ============================================================
banner("4. @wrap_tool_call — 拦截工具执行")


@wrap_tool_call
def tool_call_logger(request, handler):
    """打日志 + 模拟超时控制 (实际场景用 tenacity/asyncio.wait_for)."""
    tool_name = request.tool_call["name"]
    tool_args = request.tool_call["args"]
    print(f"  [tool_logger] → 调工具: {tool_name}({tool_args})")

    try:
        # handler(request) 真的执行工具, 直接返回 ToolMessage / Command
        response = handler(request)
        # ToolMessage 有 .content 字段, 不是 .result
        content = getattr(response, "content", str(response))
        print(f"  [tool_logger] ← 工具返回: {str(content)[:80]}")
        return response
    except Exception as e:
        print(f"  [tool_logger] ✗ 工具失败: {type(e).__name__}: {e}")
        raise


def demo_wrap_tool_call() -> None:
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather],
        middleware=[tool_call_logger],
    )

    print(">>> wrap_tool_call 自动打印工具调用日志:")
    r = agent.invoke({"messages": [HumanMessage("北京天气?")]})
    print(f"  最终: {r['messages'][-1].content[:80]}")

    # 💡 wrap_tool_call 实战场景:
    # - 权限检查: 拒绝某些 user_id 调特定 tool (RBAC)
    # - 超时控制: slow_lookup 这种工具强制 1s 超时
    # - 重试: 网络错自动重试 3 次 (用 tenacity 库)
    # - metric: 上报每次工具调用的 latency / success rate 到 Prometheus


# ============================================================
# 5. HumanInTheLoopMiddleware — 危险工具前暂停等人批
# ============================================================
banner("5. HumanInTheLoopMiddleware — 人工审批")


def demo_human_in_the_loop() -> None:
    from pydantic import BaseModel as _BM

    class Ctx(_BM):
        user_id: str = "anonymous"

    llm = get_llm()
    checkpointer = InMemorySaver()

    agent = create_agent(
        model=llm,
        tools=[refund_order],
        context_schema=Ctx,
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "refund_order": {
                        "allowed_decisions": ["approve", "edit", "reject"],
                    },
                },
            ),
        ],
        checkpointer=checkpointer,
    )

    config = {"configurable": {"thread_id": "hitl-demo"}}

    # 第 1 步: 触发 refund → Agent 在工具前暂停
    print(">>> 第 1 次 invoke — 触发 refund,会暂停:")
    try:
        agent.invoke(
            {"messages": [HumanMessage("帮订单 #12345 退款 100 元")]},
            config=config,
        )
    except Exception as e:
        print(f"  invoke 异常: {type(e).__name__}: {str(e)[:100]}")

    # 检查 state 看是否真的 pause
    state = agent.get_state(config)
    if state.next:
        print(f"  >>> 暂停在节点: {state.next}")

        # 模拟主管审批: approve
        print(">>> 主管审批: approve")
        result = agent.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )
        print(f"  最终回复: {result['messages'][-1].content[:120]}")
    else:
        print("  >>> 模型没调 refund 工具,跳过 resume demo")
        print("  >>> (小模型如 M3 工具调用不稳,Claude / GPT 上会真触发暂停)")

    # 💡 HITL 适用:
    # - 退款 / 删数据 / 改配置 — 必须人工点头
    # - 调付费 API — 每次要确认
    # - 合规敏感场景 (医疗 / 金融)
    # approve = 通过 / edit = 改参数 / reject = 拒绝


# ============================================================
# 6. SummarizationMiddleware — 长对话自动压缩
# ============================================================
banner("6. SummarizationMiddleware — 长对话自动压缩")


def demo_summarization() -> None:
    # ⚠️ SummarizationMiddleware 会调 LLM 生成摘要,小模型 (M3) 比较慢,
    # 这里只演示配置,不真跑长对话 — 实战用 Claude/GPT
    from langchain.agents.middleware import SummarizationMiddleware
    # ummarizationMiddleware 类是一个用于 LangChain / LangGraph 智能体的中间件，其核心作用是自动压缩对话历史，防止上下文窗口溢出。
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[
            SummarizationMiddleware(
                model=llm,
                # 总 token 数超过这个阈值 → 触发摘要
                max_tokens_before_summary=4000,
                # 摘要后保留最近 N 条消息 (其余压成 SystemMessage)
                messages_to_keep=4,
                summary_prompt=""
            ),
        ],
    )
    print(">>> SummarizationMiddleware 配置示例 (max_tokens_before_summary=4000, keep=4)")
    print("    实战: 灌入超过 4000 token 的对话,框架自动调 LLM 摘要旧消息")
    print("    阈值根据 context window 选: GPT-4o (128k) → 80000, Claude (200k) → 120000")

    # 💡 摘要 vs 截断的对比:
    #   截断 (truncate): 简单粗暴,丢历史,长对话 LLM 不知道你之前说过啥
    #   摘要 (summarize): 调一次 LLM 压缩,LLM 之后能从 SystemMessage 看到历史要点
    # 配合 checkpointer 用: 摘要本身也存到 checkpointer,resume 时不丢
    # 配合 response_format 用: 让 LLM 吐结构化的"用户偏好摘要",更可控


# ============================================================
# 7. Middleware 顺序 — 中间件按列表顺序串联执行
# ============================================================
banner("7. Middleware 执行顺序")


@before_model
def mw_a(state, runtime):
    print("    [mw_a] before_model")
    return None


@before_model
def mw_b(state, runtime):
    print("    [mw_b] before_model")
    return None


@after_model
def mw_c(state, runtime):
    print("    [mw_c] after_model")
    return None


@after_model
def mw_d(state, runtime):
    print("    [mw_d] after_model")
    return None


def demo_middleware_order() -> None:
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[mw_a, mw_b, mw_c, mw_d],
    )

    print(">>> 4 个 middleware,执行顺序应该是 a → b → LLM → c → d:")
    agent.invoke({"messages": [HumanMessage("hi")]})

    # 💡 顺序规则:
    # - before_model: 按 middleware 列表顺序执行 (a → b → ... → LLM)
    # - after_model:  按 middleware 列表顺序执行 (LLM → c → d → ...)
    # - wrap_model_call: 嵌套调用 — 最先声明的最外层
    # - middleware 之间顺序敏感,改顺序 = 改行为


# ============================================================
# 8. 自定义 middleware — PII 脱敏 (经典实战)
# ============================================================
banner("8. 自定义 middleware — PII 脱敏")


@wrap_model_call
def redact_phone_numbers(request, handler):
    """把用户消息里的手机号脱敏再发给 LLM."""
    phone_re = re.compile(r"1[3-9]\d{9}")
    for m in request.messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            m.content = phone_re.sub("1XX-XXXX-XXXX", m.content)
    return handler(request)


def demo_pii_redaction() -> None:
    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[redact_phone_numbers],
    )

    print(">>> 用户消息含手机号,被脱敏成 1XX-XXXX-XXXX 再发给 LLM:")
    result = agent.invoke(
        {"messages": [HumanMessage("我的手机号是 13800138000,请帮我记一下")]}
    )
    print(f"  最终回复: {result['messages'][-1].content[:200]}")


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

    demos = [
        ("demo_before_after", demo_before_after)
        # ("demo_dynamic_prompt", demo_dynamic_prompt),
        # ("demo_wrap_model_call", demo_wrap_model_call),
        # ("demo_before_after", demo_before_after),
        # ("demo_wrap_tool_call", demo_wrap_tool_call),
        # ("demo_human_in_the_loop", demo_human_in_the_loop),
        # ("demo_summarization", demo_summarization),
        # ("demo_middleware_order", demo_middleware_order),
        # ("demo_pii_redaction", demo_pii_redaction),
    ]

    for name, fn in demos:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 04_middleware.py 全部 demo 跑完。")
