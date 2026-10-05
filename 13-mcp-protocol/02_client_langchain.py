"""02_client_langchain.py — Demo 2: MCP Client + LangChain 集成.

学完这个 demo 你能回答:
1.  load_mcp_tools 把 MCP server 转 LangChain BaseTool 怎么用?
2.  create_agent + MCP tools 实测?
4.  跟 11 本地 @tool 区别? (远程 vs 本地, 进程 vs 启动)
5.  MCP tool 跟 LLM tool schema 怎么对齐? (Pydantic 自动)
6.  实战: agent 看不到 MCP 协议细节, 只看到 tool

跑法:
    python 02_client_langchain.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from langchain_core.messages import HumanMessage

from _common import banner, get_llm, run_async, step
from mcp_helpers import stdio_session

# ============================================================
# Demo
# ============================================================
# 关键: banner 必须在 if __name__ 内, 否则被 import 时会污染 stdout (JSON-RPC)
if __name__ == "__main__":
    banner("Demo 2: MCP Client + LangChain Integration")


# ============================================================
# Step 1: 连 MCP server + load tools
# ============================================================
async def demo_load_mcp_tools() -> None:
    step(1, "load_mcp_tools — MCP server → LangChain BaseTool")

    from langchain_mcp_adapters.tools import load_mcp_tools

    # 连 01_basic_server.py 的 MCP server (本地 stdio subprocess)
    async with stdio_session("01_basic_server.py") as session:
        tools = await load_mcp_tools(session)

        print(f"  加载 {len(tools)} 个 tool:")
        for t in tools:
            print(f"    - {t.name}")
            print(f"      描述: {(t.description or '')[:70]}")
            # 检查类型 — MCP tool 转 LangChain BaseTool
            print(f"      类型: {type(t).__name__}")

    # 💡 load_mcp_tools 关键点:
    #    - 输入 ClientSession (已 initialize)
    #    - 返回 list[BaseTool] — 跟 11 本地 @tool 完全一样的接口
    #    - agent 看不出这是 MCP, 跟本地 tool 没区别


# ============================================================
# Step 2: create_agent + MCP tools
# ============================================================
async def demo_agent_with_mcp() -> None:
    step(2, "create_agent + MCP tools — LLM 看不出 MCP 协议")

    from langchain.agents import create_agent
    from langchain_mcp_adapters.tools import load_mcp_tools

    async with stdio_session("01_basic_server.py") as session:
        tools = await load_mcp_tools(session)

        agent = create_agent(
            model=get_llm(),
            tools=tools,
        )

        # 实战: agent 调 MCP server 提供的 calculator
        try:
            r = await agent.ainvoke({
                "messages": [HumanMessage("(1 + 2) * 3 等于多少?")],
            })
            last = r["messages"][-1]
            content = getattr(last, "content", "")
            print(f"  最终回复: {content[:150]}")
        except Exception as e:
            print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 关键观察:
    #    - agent 看到的 tool schema 是 calculator + echo (MCP server 提供)
    #    - 不知道 tool 来自 subprocess / 远程 / 本地
    #    - 跟 11 本地 @tool 同样 invoke 流程
    #    - 实战: 远程 MCP 替换不需要改 agent 代码


# ============================================================
# Step 3: 对比 11 本地 vs 13 远程
# ============================================================
async def demo_compare_11_vs_13() -> None:
    step(3, "11 本地 @tool vs 13 MCP 远程 — 对比")

    from langchain.agents import create_agent
    from langchain_mcp_adapters.tools import load_mcp_tools

    # ─── 11 本地 @tool ───
    from langchain_core.tools import tool

    @tool
    def local_calculator(expression: str) -> str:
        """本地计算器 (11 风格).

        Args:
            expression: 数学表达式

        Returns:
            计算结果
        """
        import ast as _ast
        import operator

        bin_ops = {
            _ast.Add: operator.add, _ast.Sub: operator.sub, _ast.Mult: operator.mul,
            _ast.Div: operator.truediv, _ast.Pow: operator.pow,
        }

        def _eval(node):
            if isinstance(node, _ast.Expression):
                return _eval(node.body)
            if isinstance(node, _ast.Constant):
                return node.value
            if isinstance(node, _ast.BinOp):
                return bin_ops[type(node.op)](_eval(node.left), _eval(node.right))
            raise ValueError("unsupported")

        return str(_eval(_ast.parse(expression, mode="eval").body))

    # ─── 13 MCP 远程 ───
    async with stdio_session("01_basic_server.py") as session:
        mcp_tools = await load_mcp_tools(session)

    # 两个 agent
    local_agent = create_agent(model=get_llm(), tools=[local_calculator])
    remote_agent = create_agent(model=get_llm(), tools=mcp_tools)

    # (跳过打印 agent internals — create_agent 返回 CompiledStateGraph, 不暴露 tool list)
    print("  本地 agent 暴露 1 个 tool (local_calculator)")
    print("  远程 agent 暴露 MCP server 的 tool list")
    print("  本地: tool 函数在进程内, 直接 call")
    print("  远程: tool 是 MCP subprocess, JSON-RPC 跨进程")

    # 实战:
    print("""
  ┌────────────────┬──────────────────────┬─────────────────────────┐
  │ 维度            │ 11 本地 @tool         │ 13 MCP 远程              │
  ├────────────────┼──────────────────────┼─────────────────────────┤
  │ 进程            │ 同进程 (Python 函数)  │ 子进程 / HTTP 远程       │
  │ 性能            │ 直接 call (纳秒)      │ JSON-RPC 序列化 (~ms)    │
  │ 重启            │ 改代码重启 Python    │ 单独重启 MCP server     │
  │ 跨语言          │ 仅 Python           │ 任意语言 (Go / Rust / JS)│
  │ 协议            │ 函数签名             │ MCP (标准化)             │
  │ 适用            │ 快速 demo / 单体     │ 微服务 / 跨团队 / 跨语言 │
  └────────────────┴──────────────────────┴─────────────────────────┘
""")


# ============================================================
# Step 4: Agent 全程 — 多个 MCP tools 调度
# ============================================================
async def demo_agent_multi_tools() -> None:
    step(4, "Agent 全程 — calculator + echo 联合调度")

    from langchain.agents import create_agent
    from langchain_mcp_adapters.tools import load_mcp_tools

    async with stdio_session("01_basic_server.py") as session:
        tools = await load_mcp_tools(session)

        # tools 包括 calculator + echo
        tool_names = [t.name for t in tools]
        print(f"  MCP server 暴露 tools: {tool_names}")

        agent = create_agent(model=get_llm(), tools=tools)

        # 让 LLM 决定调哪个 tool
        try:
            r = await agent.ainvoke({
                "messages": [HumanMessage("帮我算 100*200, 然后 echo 'done' 3 次")],
            })
            # 看 message 序列 — 确认 LLM 调了 tool
            msgs = r["messages"]
            tool_calls = sum(1 for m in msgs if hasattr(m, "tool_calls") and m.tool_calls)
            tool_results = sum(1 for m in msgs if m.type == "tool")
            print(f"  LLM 调了 {tool_calls} 次 tool, 收到 {tool_results} 个 ToolMessage")
            print(f"  最终消息数: {len(msgs)}")
            last = msgs[-1]
            print(f"  最终回复: {getattr(last, 'content', '')[:150]}")
        except Exception as e:
            print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# Step 5: 错误隔离 — MCP server 挂了怎么办?
# ============================================================
async def demo_error_handling() -> None:
    step(5, "错误隔离 — MCP server 不存在 / 挂掉")

    # 实战中常见 3 类错误:
    print("""
  MCP client 错误处理 (3 类):

  1. Server 启动失败 (path 错 / Python 解释器错)
     → stdio_client 立即抛 ConnectionError
     → 实战: try/except + 退避重试

  2. Server 运行中崩溃 (subprocess 退出)
     → 后续 tool call 抛 BrokenPipeError / EOF
     → 实战: 监控 process, 自动重启 + Prometheus alert

  3. Tool 调用超时 (e.g. 网络)
     → MCP 协议默认无 timeout
     → 实战: 包 asyncio.wait_for(timeout=30)
            + 失败 fallback 到 default response

  LangChain 端:
    - 工具错误自动转 ToolMessage (跟 11 一致)
    - LLM 看到错误可以重试或放弃
    - 实战: retry middleware (11 demo 3) 同样适用 MCP
""")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    banner("Demo 2: MCP Client + LangChain Integration")
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    # Step 1/3/5 不需要 LLM
    run_async(demo_load_mcp_tools())
    run_async(demo_compare_11_vs_13())
    run_async(demo_error_handling())

    if has_key:
        run_async(demo_agent_with_mcp())
        run_async(demo_agent_multi_tools())
        print("\n[OK] 02_client_langchain.py 全部 demo 跑完。")
    else:
        print("\n[OK] 02_client_langchain.py — Step 2/4 跳过 (需 API key)。")
        print("[i]   跑 Step 2: 设 ANTHROPIC_API_KEY 等之一")