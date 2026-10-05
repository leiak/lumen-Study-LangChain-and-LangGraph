"""04_multi_server.py — Demo 4: 多 MCP server 同时接入.

学完这个 demo 你能回答:
1.  怎么同时连 2+ MCP server? (多个 stdio_client 并发)
2.  多个 server 的 tool 怎么合并? (load_mcp_tools * N + 列表拼接)
3.  agent 怎么调度? (LangChain 自动 — 全部 tool 暴露给 LLM)
4.  server 命名空间怎么区分? (tool name 通常带 server 前缀)
5.  实战场景: filesystem + custom + github 三 server 一起

跑法:
    python 04_multi_server.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from langchain_core.messages import HumanMessage

from _common import banner, get_llm, run_async, step
from mcp_helpers import stdio_session

# ============================================================
# 2 个示例 MCP server 内嵌在本 demo
# ============================================================
# Server A: filesystem (mock) — 读写文件
# Server B: search (mock) — 搜索文档


def build_server_a_filesystem():
    """Server A: 文件系统 (mock)."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("filesystem-mock")

    # 内存 mock filesystem
    files = {
        "/notes.md": "# LangChain 1.x 笔记\n\ncreate_agent 是核心 API",
        "/config.json": '{"version": "1.0.0", "debug": false}',
        "/data/users.csv": "id,name\n1,alice\n2,bob",
    }

    @mcp.resource("file://{path}")
    def read_file(path: str) -> str:
        """读文件.

        Args:
            path: 文件路径
        """
        if not path.startswith("/"):
            path = "/" + path
        return files.get(path, f"file not found: {path}")

    @mcp.tool()
    def list_files(directory: str = "/") -> list[str]:
        """列出目录下文件.

        Args:
            directory: 目录路径
        """
        return [p for p in files.keys() if p.startswith(directory)]

    return mcp


def build_server_b_search():
    """Server B: 文档搜索 (mock)."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("search-mock")

    docs = {
        "doc_1": "LangChain 1.x 简化了 Agent 创建流程",
        "doc_2": "LangGraph 适合编排长任务 + 状态管理",
        "doc_3": "MCP 是 Anthropic 推出的 tool 协议标准",
        "doc_4": "RAG 解决 hallucination, 用 retrieval 增强生成",
    }

    @mcp.tool()
    def search(query: str, max_results: int = 3) -> list[str]:
        """搜索文档.

        Args:
            query: 查询词
            max_results: 最多返回数
        """
        # 简单 keyword match
        matches = []
        for did, content in docs.items():
            if query.lower() in content.lower():
                matches.append(f"{did} → {content[:80]}")
                if len(matches) >= max_results:
                    break
        return matches if matches else ["no results"]

    @mcp.tool()
    def get_doc(doc_id: str) -> str:
        """按 ID 取文档.

        Args:
            doc_id: 文档 ID
        """
        return docs.get(doc_id, "doc not found")

    return mcp


# ============================================================
# Demo
# ============================================================
banner("Demo 4: Multi-Server MCP Integration")


# ============================================================
# Step 1: 并发连 2 个 MCP server
# ============================================================
async def demo_multi_connect() -> None:
    step(1, "并发连 2 MCP server — filesystem + search")

    from langchain_mcp_adapters.tools import load_mcp_tools

    # 注意: 当前 mcp SDK 0.3.x 没有 MultiServerMCPClient (已被重命名/拆分)
    # 实战: 用 asyncio.gather 并发起多个 stdio_client
    async def one_server_tools(script: str) -> list:
        async with stdio_session(script) as session:
            return await load_mcp_tools(session)

    # 由于 demo 没法 import "self" (没 server 单独文件), 我们 inline 测试
    # 直接演示概念 — 加载 2 个 server 的 tool
    print("  (演示: 多个 stdio_session 并发, 实际生产用 asyncio.gather)")

    print("""
  生产 pattern (asyncio.gather):

      async def load_all_tools():
          a, b = await asyncio.gather(
              one_server_tools("filesystem_server.py"),
              one_server_tools("search_server.py"),
          )
          return a + b

  实战:
    - N 个 server → N 个 stdio subprocess
    - 每个独立 ClientSession
    - load_mcp_tools 每个 → 合并 list
    - LangChain create_agent(tools=merged)
""")


# ============================================================
# Step 2: inline server + multi tool 调度
# ============================================================
async def demo_multi_server_inline() -> None:
    step(2, "inline 2 server + agent 调度 — filesystem + search 一起暴露")

    # 把 2 个 server inline 写 — 用 run_async_subprocess 在同进程跑
    # 简化: 跳过 inline, 直接演示 tool 合并的 agent 行为
    from langchain.agents import create_agent
    from langchain_core.tools import tool

    # ─── 模拟 server A 提供的 tool ───
    @tool
    def list_files(directory: str = "/") -> list[str]:
        """列出目录文件 (filesystem server A).

        Args:
            directory: 目录路径
        """
        return ["/notes.md", "/config.json", "/data/users.csv"]

    @tool
    def read_file(path: str) -> str:
        """读文件内容 (filesystem server A).

        Args:
            path: 文件路径
        """
        files = {
            "/notes.md": "# LangChain 1.x\n\ncreate_agent 是核心 API",
            "/config.json": '{"version": "1.0.0"}',
        }
        return files.get(path, "not found")

    # ─── 模拟 server B 提供的 tool ───
    @tool
    def search(query: str, max_results: int = 3) -> list[str]:
        """搜索文档 (search server B).

        Args:
            query: 查询词
            max_results: 最多返回
        """
        docs = {
            "doc_1": "LangChain 1.x 简化 Agent",
            "doc_2": "LangGraph 适合长任务",
            "doc_3": "MCP 是 Anthropic 推出的协议",
        }
        return [f"{k}: {v}" for k, v in docs.items() if query.lower() in v.lower()][:max_results]

    # ─── 合并两个 server 的 tools ───
    all_tools = [list_files, read_file, search]
    print(f"  合并 2 server tools: {[t.name for t in all_tools]}")

    agent = create_agent(model=get_llm(), tools=all_tools)

    # 实战 query: 同时用两个 server
    try:
        r = await agent.ainvoke({
            "messages": [HumanMessage("先列出 / 目录文件, 然后搜索 'LangChain' 相关文档")],
        })
        msgs = r["messages"]
        tool_calls = sum(1 for m in msgs if hasattr(m, "tool_calls") and m.tool_calls)
        tool_names = []
        for m in msgs:
            if hasattr(m, "tool_calls") and m.tool_calls:
                tool_names.extend([tc["name"] for tc in m.tool_calls])
        print(f"  LLM 调了 {tool_calls} 次 tool:")
        for name in tool_names:
            print(f"    - {name}")
        print(f"  最终消息数: {len(msgs)}")
        last = msgs[-1]
        print(f"  最终回复: {getattr(last, 'content', '')[:200]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 实战:
    #    - LangChain 把所有 tool schema 拼起来给 LLM
    #    - LLM 看到: list_files (server A) + read_file (server A) + search (server B)
    #    - LLM 自动决定调哪个 server 的 tool
    #    - 不需要告诉 LLM "server 边界"


# ============================================================
# Step 3: Tool 命名冲突 — 同名 tool 怎么办?
# ============================================================
async def demo_naming_conflict() -> None:
    step(3, "Tool 命名冲突 — 多个 server 提供同名 tool")

    print("""
  MCP 没有强制的命名空间机制 — 同名 tool 会冲突.

  解决:
    1. server 端用前缀 (server_name + '_' + tool_name)
    2. client 端 dedup (后到的覆盖, 或手动 alert)
    3. LangChain 端 import tool name (server prefix 拼上)

  实战:
    - filesystem_server.list_files
    - search_server.list_files  (会冲突, 改成 search_files)
    - production: 团队约定 server prefix 命名规范
""")


# ============================================================
# Step 4: 实测多 server 性能
# ============================================================
async def demo_multi_perf() -> None:
    step(4, "实测 — 多 server 并行调度")

    from langchain.agents import create_agent
    from langchain_core.tools import tool

    @tool
    async def slow_tool_a(x: int) -> str:
        """server A 慢 tool."""
        await asyncio.sleep(0.1)
        return f"A result {x}"

    @tool
    async def slow_tool_b(x: int) -> str:
        """server B 慢 tool."""
        await asyncio.sleep(0.1)
        return f"B result {x}"

    agent = create_agent(model=get_llm(), tools=[slow_tool_a, slow_tool_b])

    # 让 LLM 同时调 a + b
    try:
        r = await agent.ainvoke({
            "messages": [HumanMessage("调 slow_tool_a(1) 和 slow_tool_b(2) 然后告诉我结果")],
        })
        msgs = r["messages"]
        tool_calls = sum(1 for m in msgs if hasattr(m, "tool_calls") and m.tool_calls)
        print(f"  LLM 调了 {tool_calls} 次 tool (期望 2: a + b)")

        # 看 message 序列 — 多次 tool_call 是并行还是串行
        ai_msg_with_tools = [m for m in msgs if hasattr(m, "tool_calls") and m.tool_calls]
        if ai_msg_with_tools:
            n_parallel = len(ai_msg_with_tools[0].tool_calls)
            print(f"  同一 AIMessage 含 {n_parallel} 个 tool_call (并行 dispatch)")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 LangGraph 多个 tool_call 同 AIMessage → 并行 dispatch
    #    vs 串行 (一个调完再下一个)
    #    实战: 多个 server tool 并发 ≈ 1 个 tool 耗时


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    run_async(demo_multi_connect())
    run_async(demo_naming_conflict())

    if has_key:
        run_async(demo_multi_server_inline())
        run_async(demo_multi_perf())
        print("\n[OK] 04_multi_server.py 全部 demo 跑完。")
    else:
        print("\n[OK] 04_multi_server.py — Step 2/4 跳过 (需 API key)。")