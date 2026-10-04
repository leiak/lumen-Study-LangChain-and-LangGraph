"""10_streaming_codegen.py — Demo 10: LLM token streaming code gen.

教学 streaming UX:
  - astream yield tokens 增量 (用户看代码逐字浮现)
  - 累积 buffer 到完整 → 写盘 (半截 code 不能 parse, 不能写)
  - TTFT (time-to-first-token) 是 UX 关键指标
  - astream_events 提供更细粒度事件 (on_llm_new_token)

学完这个 demo 你能回答:
1.  为什么 codegen 需要 streaming? (用户感知延迟 vs 真实延迟)
2.  LangChain 1.x streaming API 有哪两个? (astream / astream_events)
3.  TTFT 怎么测? (time.perf_counter() 第一个 chunk 时记录)
4.  为什么不能每 token 解析/写盘? (半截 code 不能 parse)
5.  callback 模式怎么 hookup 到 UI? (on_token 闭包)
6.  astream vs astream_events 的区别? (token-level vs event-level)
7.  生产 codegen UX 怎么实现? (Cursor / Copilot 风格逐字浮现)

跑法:
    python 10_streaming_codegen.py

💡 设计要点:
  - streaming.py 抽出来, 复用 astream 逻辑
  - 5 个 demo steps: 3 个 streaming 机制演示 + 2 个集成验证
  - callback `on_token` 给 UI hookup (e.g. print char-by-char)
  - 写盘只在累积完成时 (不要半截)
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Windows GBK 编码保护 — LLM 返回的 emoji 可能崩 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _common import banner, get_llm, output_dir, step
from codegen_pipeline import (
    file_to_code,
    plan_to_code,
    plan_to_code_streaming,
    safe_plan_to_code,
)
from plan_schema import FileSpec, Plan, spec_to_plan
from streaming import (
    StreamResult,
    iter_llm_tokens,
    stream_file_code,
    stream_llm_content,
)


# ============================================================
# Demo helpers
# ============================================================
def _format_size(n: int) -> str:
    """Format byte count for human reading."""
    if n < 1024:
        return f"{n}B"
    return f"{n/1024:.1f}KB"


# ============================================================
# Step 1: Basic astream — 看 token 增量
# ============================================================
async def step_1_basic_astream() -> None:
    """Step 1: astream basic — 看 token 增量."""
    step(1, "basic astream — 看 token 增量 (no codegen, 验证 streaming 行为)")
    llm = get_llm(temperature=0.0)

    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [
        SystemMessage(content="你是助手, 用一句话回答."),
        HumanMessage(content="Python 是什么?"),
    ]

    print("  streaming tokens (实时打印):")
    print("  ", end="")
    result = await stream_llm_content(llm, messages, on_token=lambda t: print(t, end="", flush=True))
    print()  # newline
    print()
    print(f"  ✓ 完成:")
    print(f"    TTFT       : {result.ttft_seconds:.3f}s (用户感知的'响应延迟')")
    print(f"    total      : {result.total_seconds:.3f}s (完整生成时间)")
    print(f"    token chunks: {result.token_count} (每 chunk 1-3 个 token)")
    print(f"    content    : {len(result.content)} 字符")
    print(f"  💡 对比 non-streaming: 用户要等 {result.total_seconds:.1f}s 才看到第一个字")


# ============================================================
# Step 2: Streaming 单文件 — 看 code char-by-char
# ============================================================
async def step_2_streaming_file() -> None:
    """Step 2: streaming 生成单个 file — 看 code char-by-char (用 dot 表示进度)."""
    step(2, "streaming 单文件 — 看 code char-by-char (用 dot 表示进度)")
    llm = get_llm(temperature=0.0)

    fs = FileSpec(
        path="streaming_demo.py",
        purpose="计算斐波那契数列",
        functions=[],
    )

    # callback: 每 20 token 打印一个 dot (避免 terminal 乱, 同时给"在跑" 反馈)
    char_count = 0
    def on_token(t):
        nonlocal char_count
        char_count += 1
        if char_count % 20 == 0:
            print(".", end="", flush=True)

    print("  streaming code (每 20 token 一个 dot):")
    print("  ", end="")
    result = await stream_file_code(llm, fs, on_token=on_token)
    print()
    print()
    print(f"  ✓ 完成: {len(result.content)} 字符, TTFT {result.ttft_seconds:.2f}s, total {result.total_seconds:.2f}s")
    print(f"  头 6 行预览:")
    for line in result.content.split("\n")[:6]:
        print(f"    {line}")
    print(f"  💡 教学: 半截 code 不能 parse, 所以累积完整才处理 (extract / write)")


# ============================================================
# Step 3: TTFT 对比 — streaming vs non-streaming
# ============================================================
async def step_3_ttft_comparison() -> None:
    """Step 3: 对比 streaming vs non-streaming 的 first-byte 时间."""
    step(3, "TTFT 对比: streaming vs non-streaming (same prompt)")
    llm = get_llm(temperature=0.0)

    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [
        SystemMessage(content="你是助手."),
        HumanMessage(content="用 50 字介绍 Python."),
    ]

    # Non-streaming: invoke, 等全部完成
    start = time.perf_counter()
    response = llm.invoke(messages)
    non_stream_total = time.perf_counter() - start
    # non-streaming 没有 streaming, "first byte" = 全响应时间 (用户感知到的延迟)
    non_stream_first_byte = non_stream_total

    # Streaming: astream, 第一个 chunk 就是"first byte"
    result = await stream_llm_content(llm, messages)

    # speedup = 用户感知延迟的比值 (越大越好)
    speedup = non_stream_total / result.ttft_seconds if result.ttft_seconds > 0 else float('inf')

    print(f"  non-streaming (invoke):")
    print(f"    first byte = total : {non_stream_first_byte:.3f}s (用户等这么久才看到响应)")
    print(f"    完整响应长度       : {len(response.content)} 字符")
    print()
    print(f"  streaming (astream):")
    print(f"    TTFT               : {result.ttft_seconds:.3f}s (用户看到这个延迟)")
    print(f"    total              : {result.total_seconds:.3f}s (完整生成)")
    print()
    print(f"  ✓ 感知延迟 speedup: {speedup:.1f}x (non-streaming / streaming TTFT)")
    print(f"  💡 这就是 Cursor / Copilot 的 UX 魔法: 用户看不到等待, 看到的是进度")
    if speedup < 1:
        print(f"  ⚠️ 注意: speedup < 1 意味着 streaming 反而更慢 — 可能 TTFT 含额外连接/握手时间")


# ============================================================
# Step 4: 多文件 streaming — 文件 1 写完才生成文件 2
# ============================================================
async def step_4_multi_file_streaming() -> None:
    """Step 4: 多文件 streaming — 每文件独立计时 + safety gate."""
    step(4, "多文件 streaming — plan_to_code_streaming 端到端")
    llm = get_llm(temperature=0.0)

    spec = """生成一个 Python 模块:
- `greeter.py`: 定义 `class Greeter`, 接受 name, 含 greet() 返回 'Hello, {name}!'
- `main.py`: 导入 Greeter, 实例化, 调 greet() 打印结果

要求: 类型注解 + docstring."""

    plan = spec_to_plan(llm, spec)
    print(f"  plan files: {[f.path for f in plan.files]}")

    out = output_dir() / "demo10"
    out.mkdir(parents=True, exist_ok=True)
    print(f"  output_dir: {out}")

    # 全局 callback: 每个文件共用 (UI hookup)
    chunk_total = [0]
    file_idx = [0]
    def on_token(t):
        chunk_total[0] += 1

    print("\n  开始 streaming (5 个文件 = 5 次 astream, 每文件累积完整才写):")
    written, results = await plan_to_code_streaming(llm, plan, output_dir=out, on_token=on_token)
    print()
    print(f"  ✓ 写入 {len(written)} 个文件:")
    for path, res in zip(written, results):
        print(f"    {path.name:25} {len(res.content):>5} 字符, "
              f"TTFT {res.ttft_seconds:.2f}s, total {res.total_seconds:.2f}s, "
              f"~{res.token_count} chunks")

    # 计算总 TTFT (sum) — UX 上"等多久才看到第一个 token"
    total_ttft = sum(r.ttft_seconds for r in results)
    total_time = sum(r.total_seconds for r in results)
    print(f"\n  累计 TTFT: {total_ttft:.2f}s | 累计 total: {total_time:.2f}s")
    print(f"  全局 chunk 总数: {chunk_total[0]} (含 safety 拦截的文件前 token)")
    print(f"  💡 教学: 文件顺序生成是 trade-off — demo 9 的 dep-aware 不在此 demo 演示")


# ============================================================
# Step 5: astream_events — 细粒度事件流
# ============================================================
async def step_5_astream_events() -> None:
    """Step 5: astream_events — on_llm_new_token 细粒度事件."""
    step(5, "astream_events — 细粒度事件流 (on_llm_new_token)")
    llm = get_llm(temperature=0.0)

    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [
        SystemMessage(content="你是助手."),
        HumanMessage(content="一句话: 你好世界"),
    ]

    event_count = 0
    token_event_count = 0
    start_event_count = 0
    end_event_count = 0
    first_token_at: float | None = None

    print("  监听事件流 (start / new_token / end):")
    start = time.perf_counter()
    async for event in llm.astream_events(messages, version="v2"):
        event_count += 1
        ev_type = event["event"]
        if ev_type == "on_llm_new_token":
            token_event_count += 1
            if first_token_at is None:
                first_token_at = time.perf_counter() - start
                # 第一个 token event 时打印
                print(f"    ✦ 第一个 on_llm_new_token @ {first_token_at:.3f}s")
        elif ev_type == "on_chat_model_start":
            start_event_count += 1
        elif ev_type == "on_chat_model_end":
            end_event_count += 1
            elapsed = time.perf_counter() - start
            print(f"    ✓ on_chat_model_end @ {elapsed:.3f}s")
    total_elapsed = time.perf_counter() - start

    print(f"\n  事件统计:")
    print(f"    总事件数      : {event_count}")
    print(f"    on_*_start    : {start_event_count}")
    print(f"    on_llm_new_token: {token_event_count} (每 token 一个 event)")
    print(f"    on_*_end      : {end_event_count}")
    print(f"    TTFT (first token): {first_token_at:.3f}s" if first_token_at else "    TTFT: N/A")
    print(f"    total: {total_elapsed:.3f}s")
    print(f"  💡 astream_events 比 astream 更细: 可监听 chain / tool / retriever 等节点")
    print(f"     production UI 用 events (e.g. LangSmith / OpenLLMetry / 自家 trace)")
    print(f"     simple streaming 用 astream (够用)")


# ============================================================
# Bonus: iter_llm_tokens async iterator demo (没有 call 但 import 了, 加个 quick smoke)
# ============================================================
async def step_bonus_iter_tokens() -> None:
    """Bonus step: async iterator 模式 — 让 caller 用 `async for` 拉 token."""
    step("B", "iter_llm_tokens — async generator 模式 (SSE / WebSocket 友好)")
    llm = get_llm(temperature=0.0)

    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [
        SystemMessage(content="你是助手."),
        HumanMessage(content="一句话"),
    ]

    print("  pull model: async for token, elapsed in iter_llm_tokens():")
    print("  ", end="")
    chunks = 0
    async for token, elapsed in iter_llm_tokens(llm, messages):
        chunks += 1
        if chunks <= 5:
            # 前 5 个 token 打 elapsed, 后面省略避免刷屏
            print(f"[{elapsed:.2f}s:{token!r}]", end=" ", flush=True)
        elif chunks == 6:
            print("...", end="", flush=True)
    print()
    print(f"  ✓ 收到 {chunks} 个 chunks (async iterator 模式 — UI / SSE / WebSocket 可直接用)")


# ============================================================
# Main
# ============================================================
async def main() -> None:
    banner("Demo 10: Streaming Code Generation")

    await step_1_basic_astream()
    await step_2_streaming_file()
    await step_3_ttft_comparison()
    await step_4_multi_file_streaming()
    await step_5_astream_events()
    await step_bonus_iter_tokens()

    print()
    print("=" * 60)
    print("Demo 10 总结:")
    print("  ✅ astream(messages) yield AIMessageChunk, .content 是 string 增量")
    print("  ✅ buffer 用 list + join (避免 str += 反复分配)")
    print("  ✅ 累积完整后再 extract / write (半截 code 不能 parse)")
    print("  ✅ TTFT = time.perf_counter() 第一个 chunk 时记录")
    print("  ✅ callback `on_token(token)` 给 UI hookup (闭包 / 装饰器都行)")
    print("  ✅ astream_events version='v2' 提供更细事件 (chain / tool / retriever)")
    print("  ✅ async iterator 模式 (iter_llm_tokens) — SSE / WebSocket 友好")
    print("  💡 生产 codegen UX: Cursor / Copilot 风格的逐字浮现 = streaming codegen")


if __name__ == "__main__":
    asyncio.run(main())