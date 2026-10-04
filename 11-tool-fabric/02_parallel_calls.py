"""02_parallel_calls.py — Demo 2: 并行 tool calls (asyncio.gather).

学完这个 demo 你能回答:
1.  LLM 一次能返回多个 tool_call 吗? (能, AIMessage.tool_calls 是 list)
2.  多个独立 IO 为什么要并行? (asyncio.gather, latency 节省)
3.  串行 dispatch vs 并行 dispatch 性能差几倍?
4.  并行失败如何隔离? (return_exceptions=True)
5.  LangChain create_agent 内部是怎么 dispatch 的? (异步顺序 vs 真并行)
6.  怎么手动写一个并行 dispatch loop? (asyncio.gather + tool_call_id 配对)

跑法:
    python 02_parallel_calls.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from langchain_core.messages import HumanMessage, ToolMessage

from _common import banner, get_llm, get_sample_agent, step
from tools import db_query, get_weather, web_search

# ============================================================
# Demo
# ============================================================
banner("Demo 2: Parallel Tool Calls")


def demo_parallel_native() -> None:
    """Step 1: 同步 tool, 用 asyncio.to_thread + gather 并行."""
    step(1, "同步 tool + asyncio.to_thread 并行 dispatch")

    # 3 个 tool 假装是同步 DB 查询, 每个 0.2s
    async def fake_io(name: str, duration: float) -> str:
        await asyncio.sleep(duration)
        return f"{name} done"

    async def run_parallel() -> list[str]:
        t0 = time.perf_counter()
        results = await asyncio.gather(
            fake_io("weather", 0.2),
            fake_io("search", 0.2),
            fake_io("db", 0.2),
        )
        elapsed = time.perf_counter() - t0
        return results, elapsed

    results, elapsed = asyncio.run(run_parallel())
    print(f"  并行 3 个 task, 总耗时 {elapsed:.3f}s (而非 0.6s)")
    print(f"  结果: {results}")

    # 串行对比
    async def run_serial() -> tuple[list[str], float]:
        t0 = time.perf_counter()
        results = []
        for name in ["weather", "search", "db"]:
            r = await fake_io(name, 0.2)
            results.append(r)
        elapsed = time.perf_counter() - t0
        return results, elapsed

    _, serial_elapsed = asyncio.run(run_serial())
    print(f"  串行 3 个 task, 总耗时 {serial_elapsed:.3f}s")
    print(f"  加速比: {serial_elapsed / elapsed:.1f}x")


def demo_inspect_tool_calls() -> None:
    """Step 2: 看 LLM 返回的 AIMessage.tool_calls 是 list."""
    step(2, "AIMessage.tool_calls — 一次返回多个调用")

    llm = get_llm()
    llm_with_tools = llm.bind_tools([get_weather, web_search, db_query])

    resp = llm_with_tools.invoke(
        "北京和上海今天天气怎么样? 同时帮我搜 RAG 论文, 查 orders 表前 5 行"
    )

    print(f"  text: {resp.content or '(空)'}")
    print(f"  tool_calls 数量: {len(resp.tool_calls)}")
    for i, tc in enumerate(resp.tool_calls, 1):
        print(f"    [{i}] {tc['name']}({list(tc['args'].keys())})")

    if not resp.tool_calls:
        print("  [i] 小模型没调工具, 演示跳过")


def demo_manual_parallel_dispatch() -> None:
    """Step 3: 手写并行 dispatch — 真并行执行多个 tool_call."""
    step(3, "手动并行 dispatch (asyncio.gather + tool_call_id 配对)")

    async def one(tc: dict, tool_map: dict) -> tuple[str, str]:
        """执行单个 tool_call, 返回 (tool_call_id, content)."""
        fn = tool_map.get(tc["name"])
        if fn is None:
            return (tc["id"], f"未知工具: {tc['name']}")
        # 同步函数包成异步 (实际工具是 async 时不用 to_thread)
        try:
            result = await asyncio.to_thread(fn.invoke, tc["args"])
            return (tc["id"], str(result))
        except Exception as e:
            return (tc["id"], f"工具错误: {type(e).__name__}: {str(e)[:80]}")

    async def dispatch_parallel(tool_calls: list, tools: list) -> list[ToolMessage]:
        tool_map = {t.name: t for t in tools}
        # asyncio.gather — 全部完成才返回
        results = await asyncio.gather(*(one(tc, tool_map) for tc in tool_calls))
        return [
            ToolMessage(content=content, tool_call_id=tc_id)
            for tc_id, content in results
        ]

    # 模拟 3 个并行 tool_call
    fake_tool_calls = [
        {"id": "call_1", "name": "get_weather", "args": {"city": "北京"}},
        {"id": "call_2", "name": "web_search", "args": {"query": "RAG", "max_results": 2, "language": "en"}},
        {"id": "call_3", "name": "db_query", "args": {"table": "users", "limit": 2}},
    ]

    t0 = time.perf_counter()
    tool_messages = asyncio.run(
        dispatch_parallel(fake_tool_calls, [get_weather, web_search, db_query])
    )
    elapsed = time.perf_counter() - t0

    print(f"  并行 3 个 tool, 耗时 {elapsed:.3f}s")
    for tm in tool_messages:
        preview = str(tm.content)[:60]
        print(f"    [{tm.tool_call_id}] {preview}")

    # 💡 tool_call_id 必须对应回 AIMessage.tool_calls[i].id
    #    框架靠这个 id 知道 "这条 ToolMessage 是哪条 tool_call 的结果"


def demo_parallel_with_failures() -> None:
    """Step 4: 并行 + 部分失败 — return_exceptions=True 隔离."""
    step(4, "并行 + 部分失败隔离 (return_exceptions=True)")

    async def might_fail(name: str, fail: bool) -> str:
        await asyncio.sleep(0.05)
        if fail:
            raise ValueError(f"{name} failed")
        return f"{name} ok"

    async def run() -> list:
        # return_exceptions=True → 失败 task 返回异常对象, 不污染其它 task
        results = await asyncio.gather(
            might_fail("a", fail=False),
            might_fail("b", fail=True),
            might_fail("c", fail=False),
            return_exceptions=True,
        )
        return results

    results = asyncio.run(run())
    for r in results:
        if isinstance(r, Exception):
            print(f"  ✗ 失败: {type(r).__name__}: {r}")
        else:
            print(f"  ✓ 成功: {r}")

    # 💡 默认 gather 一个抛其它全 cancelled — 实战永远用 return_exceptions=True
    #    或 asyncio.wait_for(timeout=...) 防 hang


def demo_agent_parallel() -> None:
    """Step 5: end-to-end agent — 让 LLM 决定调多个 tool, 内部 dispatch."""
    step(5, "end-to-end agent (LLM 决定调多工具)")

    agent = get_sample_agent(tools=[get_weather, web_search, db_query])

    try:
        r = agent.invoke(
            {"messages": [HumanMessage("同时告诉我北京天气, 搜 LangChain 论文, 查 users 表前 3 行")]}
        )
        last_msg = r["messages"][-1]
        content = getattr(last_msg, "content", "")
        print(f"  最终回复: {content[:150]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    # Step 1/3/4 不需要 LLM; Step 2/5 需要
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    demos = [
        ("parallel_native", demo_parallel_native),       # ✅ no LLM
        ("inspect_tool_calls", demo_inspect_tool_calls),  # ⚠️ LLM
        ("manual_parallel_dispatch", demo_manual_parallel_dispatch),  # ✅ no LLM
        ("parallel_with_failures", demo_parallel_with_failures),     # ✅ no LLM
        ("agent_parallel", demo_agent_parallel),         # ⚠️ LLM
    ]
    for name, fn in demos:
        if name in ("inspect_tool_calls", "agent_parallel") and not has_key:
            print(f"\n[跳过 {name}] 没 API key")
            continue
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 02_parallel_calls.py 全部 demo 跑完。")