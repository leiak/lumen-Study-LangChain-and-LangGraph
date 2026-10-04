"""04_middleware.py — Demo 4: @wrap_tool_call middleware patterns.

学完这个 demo 你能回答:
1.  @wrap_tool_call 怎么拦截工具执行? (handler(request) 真执行)
2.  logging_middleware 怎么记录 input + output + latency?
3.  PII strip middleware 怎么 mask 手机号 / 邮箱?
4.  Rate limit middleware 怎么限制每分钟调用次数?
5.  多个 middleware 怎么 chain? (顺序敏感)
6.  Handler 返 ToolMessage vs Command 的差别?

跑法:
    python 04_middleware.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import HumanMessage, ToolMessage

from _common import banner, get_sample_agent, step
from middleware import logging_middleware, pii_strip_middleware, rate_limit_middleware
from tools import calculator, get_weather, write_note

# ============================================================
# Demo
# ============================================================
banner("Demo 4: Tool Middleware Patterns")


# ============================================================
# Step 1: logging_middleware — 看所有 tool 调用
# ============================================================
def demo_logging() -> None:
    step(1, "logging_middleware — 记录 input/output/latency")

    agent = get_sample_agent(
        tools=[get_weather, calculator],
        middleware=[logging_middleware],
    )

    try:
        r = agent.invoke({"messages": [HumanMessage("北京天气? 再算 (1+2)*3")]})
        last_msg = r["messages"][-1]
        content = getattr(last_msg, "content", "")
        print(f"\n  最终回复: {content[:120]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# Step 2: pii_strip_middleware — 输出剥 PII
# ============================================================
def demo_pii_strip() -> None:
    step(2, "pii_strip_middleware — mask 手机号 / 邮箱")

    # 直接测 middleware: 模拟一个工具返回含 PII 的结果
    class FakeRequest:
        def __init__(self, name: str, args: dict, call_id: str):
            self.tool_call = {"name": name, "args": args, "id": call_id}

    def fake_handler(req):
        # 假装工具返回了含 PII 的内容
        return ToolMessage(
            content="用户 13800138000 的邮箱 alice@example.com 已注册",
            tool_call_id=req.tool_call["id"],
        )

    req = FakeRequest("fake_tool", {}, "c1")
    # AgentMiddleware 不直接 call, 通过 .wrap_tool_call(req, handler) 触发
    tm = pii_strip_middleware.wrap_tool_call(req, fake_handler)
    print(f"  PII strip 后: {tm.content}")
    # 期望: '用户 138****8000 的邮箱 a***@example.com 已注册'

    # 💡 实战 PII strip 注意事项:
    #    - 必须新建 ToolMessage, 不能 setattr (frozen / BaseMessage 不可变)
    #    - 只 strip 工具输出, 不动用户输入 (那是另一层 middleware 的活)
    #    - regex 不能太激进 — 别把日期 / ID 也 mask 掉


# ============================================================
# Step 3: rate_limit_middleware — 限制调用频率
# ============================================================
def demo_rate_limit() -> None:
    step(3, "rate_limit_middleware — 限制每分钟调用次数")

    agent = get_sample_agent(
        tools=[get_weather],
        middleware=[rate_limit_middleware],  # 默认 10/min
    )

    try:
        # 连续 invoke 5 次 — 不应该触发限流 (但 LLM 每次 invoke 调 N 个工具)
        for i in range(3):
            r = agent.invoke({"messages": [HumanMessage(f"第 {i+1} 次问: 北京天气?")]})
            last_msg = r["messages"][-1]
            content = getattr(last_msg, "content", "")
            print(f"  invoke #{i+1}: {content[:80]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# Step 4: Chain 多个 middleware — 顺序敏感
# ============================================================
def demo_chain_middleware() -> None:
    step(4, "chain 多个 middleware — 顺序: logging → rate_limit → pii_strip")

    # 顺序很重要: 先 logging 记所有调用, 再 rate_limit 阻止超限, 最后 pii_strip mask 输出
    # middleware 嵌套: 最先声明的最外层 (类似洋葱模型)
    agent = get_sample_agent(
        tools=[get_weather, calculator],
        middleware=[logging_middleware, rate_limit_middleware, pii_strip_middleware],
    )

    try:
        r = agent.invoke({"messages": [HumanMessage("北京天气?")]})
        last_msg = r["messages"][-1]
        content = getattr(last_msg, "content", "")
        print(f"\n  最终回复: {content[:120]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 middleware 顺序规则 (跟 04_langchain_basics demo 7 一致):
    #    - wrap_tool_call: 嵌套调用 — 最先声明的最外层
    #    - 例如 [A, B, C] → A(B(C(handler)))
    #    - 所以 logging 应该最先声明 (它要看到所有调用 + 输出)
    #    - pii_strip 应该最后 (它处理最终输出)


# ============================================================
# Step 5: agent 跑全套 middleware
# ============================================================
def demo_full_middleware_stack() -> None:
    step(5, "Full middleware stack — agent + logging + rate_limit + pii_strip")

    # 多工具 + 全套 middleware
    agent = get_sample_agent(
        tools=[get_weather, calculator, write_note],
        middleware=[
            logging_middleware,
            rate_limit_middleware,
            pii_strip_middleware,
        ],
    )

    try:
        r = agent.invoke(
            {"messages": [HumanMessage("北京天气? 帮我算 99*99. 再写一条笔记 'AI 学习'")]}
        )
        last_msg = r["messages"][-1]
        content = getattr(last_msg, "content", "")
        print(f"\n  最终回复: {content[:200]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# Step 6: 自定义 wrap_tool_call — 自定义 metric
# ============================================================
_call_count: dict[str, int] = {}


@wrap_tool_call
def metric_middleware(request, handler):
    """自定义 metric middleware — 累计每个工具调用次数."""
    tool_name = request.tool_call["name"]
    _call_count[tool_name] = _call_count.get(tool_name, 0) + 1
    print(f"  [METRIC] {tool_name} 累计调用: {_call_count[tool_name]}")
    return handler(request)


def demo_custom_metric() -> None:
    step(6, "自定义 metric_middleware — 累计调用次数")

    agent = get_sample_agent(
        tools=[get_weather, calculator],
        middleware=[metric_middleware],
    )

    try:
        # 跑 3 次 — 每次都统计
        for i in range(2):
            r = agent.invoke({"messages": [HumanMessage(f"第 {i+1} 次: 北京天气?")]})
            last_msg = r["messages"][-1]
            content = getattr(last_msg, "content", "")
            print(f"  invoke #{i+1}: {content[:80]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    print(f"\n  最终统计: {_call_count}")
    # 实战: 上报到 Prometheus / DataDog, 按工具分 latency histogram

    # 💡 metric middleware 实战:
    #    - 累计每次调用的 latency (P50 / P95 / P99)
    #    - 累计 error rate (按工具名)
    #    - 上报到 metrics 服务 (Prometheus pushgateway)
    #    - 给 SLO 看板供 SRE 监控


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    if not has_key:
        print("[!] 没 API key — 仅跑本地 middleware 演示 (跳过需要 LLM 的部分)")

    demos = [
        ("pii_strip", demo_pii_strip),  # ✅ no LLM
        ("logging", demo_logging),      # ⚠️ LLM
        ("rate_limit", demo_rate_limit),  # ⚠️ LLM
        ("chain_middleware", demo_chain_middleware),  # ⚠️ LLM
        ("full_middleware_stack", demo_full_middleware_stack),  # ⚠️ LLM
        ("custom_metric", demo_custom_metric),  # ⚠️ LLM
    ]
    for name, fn in demos:
        if name != "pii_strip" and not has_key:
            print(f"\n[跳过 {name}] 没 API key")
            continue
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 04_middleware.py 全部 demo 跑完。")