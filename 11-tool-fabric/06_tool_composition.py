"""06_tool_composition.py — Demo 6: Tool 组合 — 工具调工具.

学完这个 demo 你能回答:
1.  工具内部能调用其他工具吗? (能, tool A 里 invoke tool B)
2.  tool composition 跟 Agent 调度有什么区别? (一个 LLM 决策, 一个工具自己决策)
3.  怎么写 "聚合工具" — 调多个子工具汇总结果?
4.  工具内 invoke 异步工具 (.ainvoke) vs 同步 (.invoke)?
5.  composition 怎么避免循环依赖? (A 调 B, B 不能调 A)
6.  实战场景: search + db + summarize 怎么合成一个 answer_question 工具?

跑法:
    python 06_tool_composition.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from _common import banner, get_llm, get_sample_agent, step
from tools import calculator, db_query, get_weather, web_search

# ============================================================
# Demo
# ============================================================
banner("Demo 6: Tool Composition — 工具调工具")


# ============================================================
# Step 1: Tool A 调 Tool B (内部 invoke)
# ============================================================
@tool
def weather_then_calc(city: str) -> str:
    """先查天气, 再根据温度算 '如果升温 10 度是多少'.

    Args:
        city: 城市名

    Returns:
        完整叙述: "city 当前 X 度, 升温 10 度后是 X+10"
    """
    # 工具内部调另一个工具 — tool composition 基础
    weather = get_weather.invoke({"city": city})
    temp_c = weather["temp_c"]
    # 用 calculator 算 temp_c + 10
    new_temp = calculator.invoke({"expression": f"{temp_c} + 10"})
    return f"{city} 当前 {temp_c}°C, 升温 10 度后是 {new_temp}°C"


def demo_basic_composition() -> None:
    step(1, "Tool A 调 Tool B (基本组合)")

    # 直接 invoke 组合工具
    r = weather_then_calc.invoke({"city": "北京"})
    print(f"  weather_then_calc(北京) → {r}")

    # 💡 工具内 invoke 子工具: 简单直接, 但失去了 Agent 编排的灵活性
    #    vs Agent 编排: LLM 决定何时调哪个工具, 更灵活但更贵
    #    实战: 固定流程 → composition; 灵活决策 → Agent


# ============================================================
# Step 2: Agent 只看 tool A — 但 A 内部用 B
# ============================================================
def demo_agent_only_sees_composed() -> None:
    step(2, "Agent 只看到组合工具 (看不到子工具)")

    # agent 只能调 weather_then_calc — 它看不到 get_weather / calculator
    agent = get_sample_agent(tools=[weather_then_calc])

    try:
        r = agent.invoke({"messages": [HumanMessage("北京天气怎么样? 升温 10 度呢?")]})
        last_msg = r["messages"][-1]
        content = getattr(last_msg, "content", "")
        print(f"  Agent 最终回复: {content[:150]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 实战场景:
    #    - 子工具不该被 LLM 看到 (e.g. SQL executor) → 包成高级工具
    #    - 子工具要被 LLM 看到 (灵活) → 都暴露给 Agent
    #    composition 是 "抽象" — 跟 OOP 把细节藏在 public method 后面一样


# ============================================================
# Step 3: 嵌套组合 (A → B → C)
# ============================================================
@tool
def deep_weather_summary(city: str, query: str) -> str:
    """深度天气摘要: 调 A → A 调 B → B 调 C.

    Args:
        city: 城市
        query: 额外搜索关键词 (给 web_search 用)

    Returns:
        完整摘要: "city 天气 X 度, 升温 10 度后 Y 度, 搜索 query 结果 N 条"
    """
    # A: weather_then_calc → 它会调 get_weather + calculator
    weather_part = weather_then_calc.invoke({"city": city})

    # B: web_search (同级工具, 不嵌套)
    search_part = web_search.invoke({"query": query, "max_results": 2, "language": "en"})

    return f"{weather_part} | 搜索 '{query}' 共 {len(search_part)} 条结果"


def demo_nested_composition() -> None:
    step(3, "嵌套组合 A → B → C")

    r = deep_weather_summary.invoke({"city": "北京", "query": "北京天气"})
    print(f"  deep_weather_summary → {r}")

    # 💡 嵌套深度限制:
    #    - 实际项目里 2-3 层足够, 再深调试难 + 性能差
    #    - 每层 invoke 都是同步调用 (除非用 .ainvoke + asyncio.gather)
    #    - 工具之间不要循环依赖 (A 调 B, B 调 A → 死循环)


# ============================================================
# Step 4: 聚合工具 — 调多个子工具汇总
# ============================================================
@tool
def research_assistant(topic: str) -> dict:
    """研究助手: web_search + db_query 并行 (mock 同步), 汇总成 dict.

    Args:
        topic: 研究主题

    Returns:
        {"search": [...], "db": [...], "summary": str}
    """
    # 1. web 搜索
    search_results = web_search.invoke(
        {"query": topic, "max_results": 3, "language": "en"}
    )

    # 2. db 查询 (假设 topic 是产品名, 查 products 表)
    db_results = db_query.invoke({"table": "products", "limit": 3})

    # 3. 汇总
    return {
        "search": search_results,
        "db": db_results,
        "summary": f"主题 '{topic}': web {len(search_results)} 条, db {len(db_results)} 条",
    }


def demo_aggregation_tool() -> None:
    step(4, "聚合工具 — 多工具 → 1 个 dict")

    r = research_assistant.invoke({"topic": "LangChain"})
    print(f"  返回类型: {type(r).__name__}")
    print(f"  summary: {r['summary']}")
    print(f"  search 前 1 条: {r['search'][0]['title']}")
    print(f"  db 前 1 条: {r['db'][0]}")

    # 💡 实战聚合工具:
    #    - search + db + calculator + summarize 组合成一个 "research" 工具
    #    - Agent 调一次 research 就拿到完整 context
    #    - 优势: 减少 LLM 决策次数 (省 token + latency)
    #    - 劣势: 灵活性低 (固定流程)


# ============================================================
# Step 5: 异步 composition (ainvoke + gather)
# ============================================================
@tool
async def fast_research(topic: str) -> dict:
    """异步研究助手 — web + db 并发.

    Args:
        topic: 研究主题

    Returns:
        {"search": [...], "db": [...], "elapsed_s": float}
    """
    import time

    t0 = time.perf_counter()

    # 子工具 async 用 ainvoke — 然后 gather 并发
    search_results, db_results = await asyncio.gather(
        web_search.ainvoke({"query": topic, "max_results": 3, "language": "en"}),
        db_query.ainvoke({"table": "products", "limit": 3}),
    )

    elapsed = time.perf_counter() - t0
    return {
        "search": search_results,
        "db": db_results,
        "elapsed_s": round(elapsed, 3),
    }


async def run_fast_research() -> None:
    step(5, "异步 composition (ainvoke + gather) — 并发快 2x")

    r = await fast_research.ainvoke({"topic": "LangChain"})
    print(f"  web {len(r['search'])} 条, db {len(r['db'])} 条")
    print(f"  耗时 {r['elapsed_s']}s (并发; 串行会更慢)")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    if not has_key:
        print("[!] 没 API key — agent demo 跳过, 本地 composition 仍跑")

    demos = [
        ("basic_composition", demo_basic_composition),       # ✅ no LLM
        ("agent_only_sees_composed", demo_agent_only_sees_composed),  # ⚠️ LLM
        ("nested_composition", demo_nested_composition),     # ✅ no LLM
        ("aggregation_tool", demo_aggregation_tool),         # ✅ no LLM
    ]
    for name, fn in demos:
        if name == "agent_only_sees_composed" and not has_key:
            print(f"\n[跳过 {name}] 没 API key")
            continue
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    # 异步 demo
    try:
        asyncio.run(run_fast_research())
    except Exception as e:
        print(f"[fast_research] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 06_tool_composition.py 全部 demo 跑完。")