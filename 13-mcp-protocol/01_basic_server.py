"""01_basic_server.py — Demo 1: MCP Server 基础 (FastMCP stdio).

学完这个 demo 你能回答:
1.  MCP server 3 类 primitive 是什么? (Resource / Tool / Prompt)
2.  FastMCP 高层 API 怎么装饰? (@mcp.tool / @mcp.resource / @mcp.prompt)
3.  stdio transport 怎么跑? (subprocess + stdin/stdout JSON-RPC)
4.  Resource URI 怎么设计? (file:// / scheme://path)
5.  客户端怎么连 + list + invoke?

跑法:
    python 01_basic_server.py       # 自动测试 (不起真 server)
    python 01_basic_server.py serve # 真起 server (stdio, 等待 client)
"""
from __future__ import annotations

import asyncio
import os
import sys

from _common import banner, run_async, step
from mcp_helpers import check_mcp_available, stdio_session

# ============================================================
# MCP Server 实现 (FastMCP)
# ============================================================

# 关键设计: 这个 demo 既可以 import (被 client 当 server 用),
# 也可以直接运行 `python 01_basic_server.py serve` 起真 server.
#
# FastMCP 提供高层装饰器 — 比裸的 mcp.Server API 简洁 80%.
# 3 类装饰器:
#   @mcp.tool()        — 工具 (LLM 调用)
#   @mcp.resource()    — 资源 (客户端可读, e.g. file 内容)
#   @mcp.prompt()      — 提示模板 (预定义, 客户端填参数)


def build_server():
    """构造 FastMCP server (含 1 resource template + 2 tools)."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("basic-mcp-server")

    # ─── Resource template: 文件内容 ───
    # 用 config:// 协议避免 Pydantic AnyUrl 自动加 trailing slash
    # (file://{path} 配合 AnyUrl 会变成 file://config.yaml/ → template 不匹配)
    @mcp.resource("config://{name}")
    def read_file(name: str) -> str:
        """读取指定文件内容 (mock, 不真读文件).

        Args:
            name: 文件名 (e.g. "config.yaml")

        Returns:
            文件内容 (mock)
        """
        # Mock data — 真实场景用 pathlib.Path + 权限校验
        mock_files = {
            "config.yaml": "version: 1\nname: my-app\ndebug: false",
            "README.md": "# Basic MCP Server\n\n提供 calculator + echo 两个 primitive.",
            "data.json": '{"count": 42, "items": ["a", "b", "c"]}',
        }
        return mock_files.get(name, f"<file '{name}' not found>")

    # ─── Tool 1: calculator ───
    @mcp.tool()
    def calculator(expression: str) -> str:
        """安全计算数学表达式 (AST 解析, 不用 eval).

        Args:
            expression: 数学表达式 (e.g. "123 * 456")

        Returns:
            计算结果
        """
        import ast as _ast
        import operator

        bin_ops = {
            _ast.Add: operator.add,
            _ast.Sub: operator.sub,
            _ast.Mult: operator.mul,
            _ast.Div: operator.truediv,
            _ast.Pow: operator.pow,
            _ast.Mod: operator.mod,
        }

        def _eval(node):
            if isinstance(node, _ast.Expression):
                return _eval(node.body)
            if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, _ast.BinOp) and type(node.op) in bin_ops:
                return bin_ops[type(node.op)](_eval(node.left), _eval(node.right))
            raise ValueError(f"unsupported: {type(node).__name__}")

        return str(_eval(_ast.parse(expression, mode="eval").body))

    # ─── Tool 2: echo (演示 typed arg) ───
    @mcp.tool()
    def echo(message: str, repeat: int = 1) -> str:
        """回显消息 N 次.

        Args:
            message: 消息内容
            repeat: 重复次数 (1-5)

        Returns:
            重复 N 次拼接的字符串
        """
        repeat = max(1, min(repeat, 5))
        return " ".join([message] * repeat)

    return mcp


# ============================================================
# Demo 测试 (不起真 server, 用 stdio_session 测)
# ============================================================
# 关键: banner 必须在 if __name__ 内, 否则被 import 当 server 时会污染 stdout (JSON-RPC)
if __name__ == "__main__":
    banner("Demo 1: Basic MCP Server (FastMCP stdio)")


async def demo_check_mcp() -> None:
    step(1, "检查 MCP SDK 版本")
    info = check_mcp_available()
    for k, v in info.items():
        print(f"  {k}: {v}")

    # 💡 实战: 跑 demo 前先 check 版本 — 不同 langchain-mcp-adapters 版本 API 不一样
    #    0.3.x: stdio_client + create_session + load_mcp_tools
    #    0.2.x: MultiServerMCPClient (deprecated, 已重命名)


async def demo_list_tools() -> None:
    step(2, "client 连 server + list tools")

    async with stdio_session(__file__) as session:
        # MCP SDK 1.x 提供便捷方法 list_tools (不用 send_request + result_type)
        resp = await session.list_tools()
        for tool in resp.tools:
            print(f"  Tool: {tool.name}")
            desc = (tool.description or "")[:80]
            print(f"    描述: {desc}...")


async def demo_list_resources() -> None:
    step(3, "list resources + read")

    async with stdio_session(__file__) as session:
        # 列出所有 resources
        resp = await session.list_resources()
        for r in resp.resources:
            print(f"  Resource URI: {r.uri}")

        # 读 config.yaml
        from pydantic import AnyUrl

        result = await session.read_resource(AnyUrl("config://config.yaml"))
        print(f"\n  读 config://config.yaml:")
        for content in result.contents:
            text = getattr(content, "text", str(content))
            print(f"    {text}")


async def demo_call_tool() -> None:
    step(4, "调 tool — calculator + echo")

    async with stdio_session(__file__) as session:
        # calculator
        result = await session.call_tool("calculator", {"expression": "(1 + 2) * 3"})
        print(f"  calculator((1+2)*3) →")
        for content in result.content:
            print(f"    {getattr(content, 'text', content)}")

        # echo
        result = await session.call_tool("echo", {"message": "hi", "repeat": 3})
        print(f"\n  echo('hi', 3) →")
        for content in result.content:
            print(f"    {getattr(content, 'text', content)}")


async def demo_with_langchain_adapter() -> None:
    step(5, "用 langchain-mcp-adapters 转 LangChain tool")

    from langchain_mcp_adapters.tools import load_mcp_tools

    async with stdio_session(__file__) as session:
        tools = await load_mcp_tools(session)
        print(f"  加载 {len(tools)} 个 LangChain tool:")
        for t in tools:
            print(f"    - {t.name}: {t.description[:60]}")

        # 直接调 (跟 11 本地 @tool 一样)
        calc = next(t for t in tools if t.name == "calculator")
        result = await calc.ainvoke({"expression": "10 * 20"})
        print(f"\n  calc.ainvoke({{'expression': '10 * 20'}}) → {result}")

    # 💡 实战:
    #    - load_mcp_tools 把 MCP server 转 LangChain BaseTool
    #    - 跟 11 本地 @tool 同样用法 (create_agent + tools)
    #    - 区别: 11 本地 (在进程内), 13 远程 (subprocess / HTTP)


# ============================================================
# 真起 server (命令行 `python 01_basic_server.py serve`)
# ============================================================
def main_serve() -> None:
    """真起 stdio server — 等待 client 连."""
    print("[server] starting basic MCP server (Ctrl-C to quit)...", file=sys.stderr)
    server = build_server()
    server.run(transport="stdio")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    # 检测是否被 stdio client 当 subprocess 调 (stdin 是 pipe, 不是 tty)
    is_subprocess = not sys.stdin.isatty()

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        # 显式 serve 命令 — 起 server
        main_serve()
    elif is_subprocess:
        # 被 client 当 MCP server 起 — 自动跑 server (不打印, 不跑 demo)
        main_serve()
    else:
        # 直接命令行跑 — 测试 demo
        banner("Demo 1: Basic MCP Server (FastMCP stdio)")
        run_async(demo_check_mcp())
        run_async(demo_list_tools())
        run_async(demo_list_resources())
        run_async(demo_call_tool())
        run_async(demo_with_langchain_adapter())
        print("\n[OK] 01_basic_server.py 全部 demo 跑完。")
        print("[i]   真起 server: python 01_basic_server.py serve")
        print("[i]   测 MCP Inspector: npx @modelcontextprotocol/inspector python 01_basic_server.py")