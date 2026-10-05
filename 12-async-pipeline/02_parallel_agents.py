"""02_parallel_agents.py — Demo 2: asyncio.gather 多 agent 并发.

学完这个 demo 你能回答:
1.  多个独立查询为什么要并发? (latency 节省 = sum / n)
2.  asyncio.gather 默认行为? (one 抛其它全 cancelled — 不能用)
3.  return_exceptions=True 为什么必加? (失败隔离)
4.  agent.ainvoke 是真异步吗? (LLM 客户端是同步的, 但 API call 不阻塞 event loop)
5.  多 agent 并发时 thread_id 怎么管? (每个独立 config)
6.  实测并发加速比? (实测数据)

跑法:
    python 02_parallel_agents.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from langchain_core.messages import HumanMessage

from _common import banner, get_llm, run_async, step
from async_pipeline import gather_safe, measure_latency

# ============================================================
# Demo
# ============================================================
banner("Demo 2: Parallel Agents — gather_safe")


# =========================================================
# Step 1: 串行 vs 并发 — 实测加速比
# =========================================================
async def demo_serial_vs_parallel() -> None:
    step(1, "串行 vs 并发 — 实测加速比")

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    queries = [
        "什么是 RAG?",
        "什么是 BM25?",
        "什么是 FAISS?",
    ]

    # --- 串行 (一个一个跑) ---
    print(">>> 串行 3 个查询:")
    t0 = time.perf_counter()
    serial_results = []
    for q in queries:
        r = await agent.ainvoke({"messages": [HumanMessage(q)]})
        serial_results.append(r)
    serial_elapsed = time.perf_counter() - t0

    print(f"  串行耗时: {serial_elapsed:.2f}s ({len(queries)} queries)")
    for r in serial_results:
        last = r["messages"][-1]
        print(f"    - {getattr(last, 'content', '')[:60]}")

    # --- 并发 (gather_safe 一起跑) ---
    print("\n>>> 并发 3 个查询 (gather_safe):")
    t0 = time.perf_counter()
    results = await gather_safe(
        *(agent.ainvoke({"messages": [HumanMessage(q)]}) for q in queries),
    )
    parallel_elapsed = time.perf_counter() - t0

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    print(f"  并发耗时: {parallel_elapsed:.2f}s ({success_count}/{len(queries)} 成功)")
    speedup = serial_elapsed / max(parallel_elapsed, 0.001)
    print(f"  加速比: {speedup:.2f}x")

    # 💡 加速比原理:
    #    - 串行 = n1 + n2 + n3
    #    - 并发 ≈ max(n1, n2, n3) (LLM 并发请求不阻塞)
    #    - 实战: 3 query ~ 3x 加速; 10 query ~ 5-8x (网络限速)
    #    - 注意: LLM provider 有 rate limit, 并发太多会触发 429


# =========================================================
# Step 2: return_exceptions — 失败隔离
# =========================================================
async def demo_return_exceptions() -> None:
    step(2, "return_exceptions=True — 失败隔离 (一个抛不影响其它)")

    async def might_fail(name: str, fail: bool = False) -> str:
        await asyncio.sleep(0.05)
        if fail:
            raise ValueError(f"{name} 故意失败")
        return f"{name} ok"

    print(">>> 并发 4 task, 第 2 个故意失败:")
    results = await gather_safe(
        might_fail("a"),
        might_fail("b", fail=True),
        might_fail("c"),
        might_fail("d", fail=True),
    )

    for i, r in enumerate(results, 1):
        if isinstance(r, BaseException):
            print(f"  [task#{i}] ✗ {type(r).__name__}: {r}")
        else:
            print(f"  [task#{i}] ✓ {r}")

    # 💡 默认 gather 一个抛其它全 cancelled (asyncio.CancelledError)
    #    gather_safe 强制 return_exceptions=True, 实战永远用这个
    #    等价于: results = await asyncio.gather(*coros, return_exceptions=True)


# =========================================================
# Step 3: 多 agent 不同 config — 各自 thread
# =========================================================
async def demo_multi_agent_threads() -> None:
    step(3, "多 agent 不同 thread_id — 并发隔离状态")

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    queries = [
        ("user-1", "用一句话介绍 LangChain"),
        ("user-2", "用一句话介绍 LangGraph"),
        ("user-3", "用一句话介绍 MCP"),
    ]

    print(">>> 3 个独立 user 同时问:")
    t0 = time.perf_counter()

    async def ask(user_id: str, q: str) -> str:
        config = {"configurable": {"thread_id": user_id}}
        r = await agent.ainvoke(
            {"messages": [HumanMessage(q)]},
            config=config,
        )
        last = r["messages"][-1]
        return f"[{user_id}] {getattr(last, 'content', '')[:60]}"

    results = await gather_safe(*(ask(uid, q) for uid, q in queries))
    elapsed = time.perf_counter() - t0

    for r in results:
        if isinstance(r, BaseException):
            print(f"  ✗ {r}")
        else:
            print(f"  {r}")
    print(f"  并发耗时: {elapsed:.2f}s")

    # 💡 实战场景:
    #    - Web 服务每个用户独立 thread_id (HTTP session)
    #    - 后台批量: 100 个 query 不同 user_id 并发跑
    #    - 监控: 每个 thread 独立 metrics


# =========================================================
# Step 4: 实测 — 5 query 并发 vs 串行
# =========================================================
async def demo_throughput_benchmark() -> None:
    step(4, "Throughput 基准 — 5 query 并发 vs 串行")

    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(model=llm, tools=[])

    queries = [f"列出数字 {i} 的 3 个用途" for i in range(1, 6)]

    # 串行
    t0 = time.perf_counter()
    for q in queries:
        await agent.ainvoke({"messages": [HumanMessage(q)]})
    serial = time.perf_counter() - t0

    # 并发 5
    t0 = time.perf_counter()
    results = await gather_safe(
        *(agent.ainvoke({"messages": [HumanMessage(q)]}) for q in queries),
    )
    parallel = time.perf_counter() - t0

    success = sum(1 for r in results if not isinstance(r, BaseException))
    print(f"  串行: {serial:.2f}s")
    print(f"  并发 5: {parallel:.2f}s ({success}/{len(queries)} 成功)")
    print(f"  加速比: {serial / max(parallel, 0.001):.2f}x")
    print(f"  per-query latency (并行): {parallel * 1000 / len(queries):.0f}ms")

    # 💡 实战:
    #    - 串行 5 query = 5 * 单 query latency
    #    - 并发 5 query ≈ 单 query latency (LLM provider 并发处理)
    #    - per-query latency 串行 = 100% / 并发 ~ 20% (5x 加速)
    #    - 实战数字选 API 限速和 budget 决定 (openai tier 1 限制并发 60)


# =========================================================
# Step 5: measure_latency — async 上下文管理器
# =========================================================
async def demo_measure_latency() -> None:
    step(5, "measure_latency — async 上下文管理器")

    async def fake_work(name: str, duration: float) -> str:
        await asyncio.sleep(duration)
        return f"{name} done in {duration}s"

    # 串行测总耗时
    async with measure_latency() as t:
        await fake_work("a", 0.1)
        await fake_work("b", 0.1)
    print(f"  串行 2 task 总耗时: {t.elapsed_ms:.0f}ms")

    # 并发测总耗时
    async with measure_latency() as t:
        await gather_safe(fake_work("a", 0.1), fake_work("b", 0.1))
    print(f"  并发 2 task 总耗时: {t.elapsed_ms:.0f}ms")

    # 💡 measure_latency 用法:
    #    - async with 测 block 耗时
    #    - 实战: 包 LLM.ainvoke 拿 latency → 上报 metrics
    #    - 比 time.perf_counter() 手动配对更优雅


# =========================================================
# entry point
# =========================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    if not has_key:
        print("[!] 没 API key — Step 2/5 跑 (不需 LLM), Step 1/3/4 跳过")
        run_async(demo_return_exceptions())
        run_async(demo_measure_latency())
        print("\n[OK] 02_parallel_agents.py — 不需 LLM 的 demo 跑完。")
        sys.exit(0)

    # 顺序跑 — 不并发是因为 latency 测不准
    run_async(demo_serial_vs_parallel())
    run_async(demo_return_exceptions())
    run_async(demo_multi_agent_threads())
    run_async(demo_throughput_benchmark())
    run_async(demo_measure_latency())

    print("\n[OK] 02_parallel_agents.py 全部 demo 跑完。")
    print("[i]   实测加速比通常 3-5x (受 LLM provider rate limit 影响).")