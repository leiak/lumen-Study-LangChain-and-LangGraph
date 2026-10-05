"""mcp_helpers.py — 13 共享 MCP 工具 helpers.

实战 MCP 模式:
  - run_stdio_server: 起 stdio MCP server (subprocess)
  - run_http_server: 起 HTTP MCP server (asyncio task)
  - test_session: stdio_client + create_session + initialize 一站式
  - list_tools / call_tool: 简化 ClientSession 包装

💡 设计要点:
  - 不依赖 LangChain (可独立测试)
  - 教学 demo 用 — 生产应直接用 mcp SDK
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# ============================================================
# 1. Stdio server helper — 启动 MCP server subprocess
# ============================================================
async def run_stdio_server(server_script: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """起 stdio MCP server subprocess.

    实战:
        - `command` 是 MCP server 入口 (e.g. "python 01_basic_server.py")
        - stdin/stdout 是 JSON-RPC 通信通道
        - LangChain 0.3.x 用 `stdio_client(server_params)` 包这个

    Args:
        server_script: MCP server 脚本路径 (e.g. "01_basic_server.py")

    Returns:
        (reader, writer) — 给 stdio_client 用
    """
    return await asyncio.subprocess.create_subprocess_exec(
        sys.executable, server_script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


# ============================================================
# 2. test_session — 一站式 stdio client + initialize
# ============================================================
@asynccontextmanager
async def stdio_session(server_script: str) -> AsyncIterator[Any]:
    """stdio MCP session context manager.

    实战用法:
        async with stdio_session("01_basic_server.py") as session:
            tools = await load_mcp_tools(session)
            # ... 调 tool / list resource ...

    Args:
        server_script: MCP server 脚本路径

    Yields:
        已 initialize 的 ClientSession
    """
    # langchain-mcp-adapters 0.3.x 统一 API: create_session + transport config
    from langchain_mcp_adapters.sessions import create_session
    from langchain_mcp_adapters.tools import load_mcp_tools

    async with create_session({
        "transport": "stdio",
        "command": sys.executable,
        "args": [server_script],
    }) as session:
        await session.initialize()
        yield session


# ============================================================
# 3. list_tools_simple — 简化工具列表
# ============================================================
async def list_tools_simple(session: Any) -> list[str]:
    """返回 session 暴露的工具名列表 (调试用)."""
    resp = await session.list_tools()
    return [t.name for t in resp.tools]


# ============================================================
# 4. print_mcp_message — 调试打印 JSON-RPC 消息
# ============================================================
def print_mcp_message(msg: Any) -> None:
    """简化打印 MCP 消息 (debug 用)."""
    if hasattr(msg, "root"):
        # pydantic RootModel 包装
        msg = msg.root
    print(f"  [MCP] {type(msg).__name__}: {str(msg)[:200]}")


# ============================================================
# 5. check_mcp_available — 探测 MCP SDK 版本
# ============================================================
def check_mcp_available() -> dict:
    """返回 MCP SDK / adapter 版本信息 (调试 + 教学).

    实战:
        - 跑 demo 前先 check 版本, 防止 API 差异
        - LangChain 0.3.x 之前用 MultiServerMCPClient
        - 0.3.x+ 改用 stdio_client + create_session + load_mcp_tools
    """
    info = {}
    try:
        import mcp
        info["mcp"] = getattr(mcp, "__version__", "?")
    except ImportError:
        info["mcp"] = "NOT INSTALLED"

    try:
        from langchain_mcp_adapters.tools import load_mcp_tools
        import langchain_mcp_adapters
        info["langchain_mcp_adapters"] = getattr(langchain_mcp_adapters, "__version__", "?")
    except ImportError:
        info["langchain_mcp_adapters"] = "NOT INSTALLED"

    return info


__all__ = [
    "run_stdio_server",
    "stdio_session",
    "list_tools_simple",
    "print_mcp_message",
    "check_mcp_available",
]