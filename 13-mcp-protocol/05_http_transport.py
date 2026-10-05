"""05_http_transport.py — Demo 5: MCP Streamable HTTP Transport.

学完这个 demo 你能回答:
1.  MCP HTTP transport vs stdio 区别? (HTTP 跨网络, 进程隔离)
2.  FastMCP 怎么跑 HTTP server? (transport="streamable-http")
3.  客户端怎么连 HTTP server? (streamablehttp_client + URL)
4.  in-process 测试怎么做? (ASGITransport, 不开真端口)
5.  Bearer auth 怎么注入? (自定义 httpx client)
6.  实战: 部署到 docker / k8s, 多 client 连同一 server

跑法:
    python 05_http_transport.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager

from _common import banner, get_llm, run_async, step
from mcp_helpers import check_mcp_available

# ============================================================
# MCP Server (HTTP transport)
# ============================================================


def build_http_server():
    """构造 FastMCP server (HTTP transport)."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("http-mcp-server", host="127.0.0.1", port=8765)

    # ─── Tool 1: 远程计算 ───
    @mcp.tool()
    def calc(expression: str) -> str:
        """远程计算器 (HTTP transport).

        Args:
            expression: 数学表达式

        Returns:
            结果
        """
        import ast as _ast
        import operator

        bin_ops = {
            _ast.Add: operator.add, _ast.Sub: operator.sub,
            _ast.Mult: operator.mul, _ast.Div: operator.truediv,
        }

        def _eval(node):
            if isinstance(node, _ast.Expression):
                return _eval(node.body)
            if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, _ast.BinOp) and type(node.op) in bin_ops:
                return bin_ops[type(node.op)](_eval(node.left), _eval(node.right))
            raise ValueError("unsupported")

        return str(_eval(_ast.parse(expression, mode="eval").body))

    # ─── Tool 2: 远程 echo ───
    @mcp.tool()
    def ping(message: str) -> str:
        """回显 + 服务器时间.

        Args:
            message: 消息

        Returns:
            pong 消息
        """
        import datetime

        now = datetime.datetime.now().isoformat(timespec="seconds")
        return f"pong: {message} @ {now}"

    # ─── Resource: 服务端状态 ───
    @mcp.resource("status://server")
    def server_status() -> str:
        """服务器状态 (mock)."""
        return "OK | uptime: 100s | clients: 1"

    return mcp


# ============================================================
# Demo
# ============================================================
banner("Demo 5: MCP Streamable HTTP Transport")


# ============================================================
# Step 1: 概念 — HTTP transport vs stdio
# ============================================================
async def demo_http_vs_stdio() -> None:
    step(1, "HTTP transport vs stdio — 维度对比")

    print("""
  ┌──────────────────┬──────────────────┬──────────────────────────┐
  │ 维度              │ stdio            │ streamable-http          │
  ├──────────────────┼──────────────────┼──────────────────────────┤
  │ 启动              │ 子进程 (Popen)   │ 独立 HTTP 进程 / 容器     │
  │ 传输              │ stdin/stdout     │ HTTP + JSON-RPC          │
  │ 跨网络            │ ✗ (本机)         │ ✓ (任意网络)             │
  │ 多 client         │ 1 server : 1 client│ 1 server : N clients    │
  │ 部署              │ embedded         │ docker / k8s / 反代       │
  │ 鉴权              │ OS 权限          │ Bearer / OAuth / mTLS     │
  │ 调试              │ MCP Inspector   │ Inspector + curl         │
  │ 适用              │ 本地开发 / IDE   │ 生产 / 多客户端 / SaaS    │
  └──────────────────┴──────────────────┴──────────────────────────┘

  实战:
    - 本地: stdio (快, 零网络)
    - 生产: HTTP (鉴权, 监控, 横向扩展)
""")


# ============================================================
# Step 2: in-process ASGI 测试 (不开真端口)
# ============================================================
async def demo_in_process_asgi() -> None:
    step(2, "in-process ASGI 测试 — httpx.ASGITransport 不开真端口")

    info = check_mcp_available()
    if not info.get("langchain_mcp_adapters"):
        print("  [跳过] langchain-mcp-adapters 未安装")
        return

    print("""
  ⚠ FastMCP.streamable_http_app() 不支持 in-process ASGITransport:
    - FastMCP 的 streamable_http_manager 需要 task group 启动
    - ASGITransport 跳过 task group → RuntimeError
    - 必须真起 uvicorn (subprocess) 才能跑

  替代方案 1: uvicorn.Config + uvicorn.Server (无 socket)
    - 把 server 跑在 background task, 用真实 socket 绑端口 0 (随机)
    - 完测后 server_task.cancel()
    - 比 subprocess 快, 但仍要 OS socket

  替代方案 2: subprocess + uvicorn CLI (Step 3 用此)
    - `python -m uvicorn --app <asgi_app>` 起子进程
    - 完全标准, 适合 pytest 集成测试
    - 启动慢 (~1s) 但行为接近生产

  实战结论:
    - 单元测试 FastMCP server: 用 stdio transport (01-04 已覆盖)
    - 集成测试 HTTP server: 真起 uvicorn, 走 socket
    - ASGITransport 仅适合 stateless FastAPI app, FastMCP 不行
""")


# ============================================================
# Step 3: 真起 HTTP server + 客户端连 (短时跑, 测完即关)
# ============================================================
async def demo_real_http_server() -> None:
    step(3, "真起 HTTP server + 客户端连 (127.0.0.1:8765)")

    info = check_mcp_available()
    if not info.get("langchain_mcp_adapters"):
        print("  [跳过] langchain-mcp-adapters 未安装")
        return

    from langchain_mcp_adapters.sessions import create_session
    from langchain_mcp_adapters.tools import load_mcp_tools

    # 后台跑 server (用 uvicorn 启动 FastMCP app)
    server = build_http_server()
    app = server.streamable_http_app()

    import uvicorn

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=8765,
        log_level="warning",
        lifespan="on",
    )
    uv_server = uvicorn.Server(config)

    # 在后台 task 起 server
    server_task = asyncio.create_task(uv_server.serve())

    # 等 server ready
    for _ in range(20):
        await asyncio.sleep(0.2)
        if uv_server.started:
            break
    if not uv_server.started:
        print("  [跳过] server 启动超时")
        uv_server.should_exit = True
        await server_task
        return

    try:
        async with create_session({
            "transport": "http",
            "url": "http://127.0.0.1:8765/mcp",
        }) as session:
            await session.initialize()

            tools = await load_mcp_tools(session)
            print(f"  远程 HTTP 加载 {len(tools)} 个 tool")
            print(f"  server URL: http://127.0.0.1:8765/mcp")

            # 测 ping — 用便捷方法 call_tool (MCP SDK 1.x)
            result = await session.call_tool("ping", {"message": "hello"})
            for content in result.content:
                print(f"  ping → {getattr(content, 'text', content)}")

            # 测 resource — 用便捷方法 read_resource
            from pydantic import AnyUrl

            result = await session.read_resource(AnyUrl("status://server"))
            for content in result.contents:
                print(f"  status://server → {getattr(content, 'text', content)}")
    finally:
        uv_server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            uv_server.force_exit = True

    # 💡 实战:
    #    - 端口 8765 是 MCP 默认 endpoint /mcp
    #    - uvicorn.Config lifespan="on" 是 FastMCP 启动必需
    #    - 生产: uvicorn --workers 4 = 并发 4 client
    #    - 生产: 反代 nginx + CORS + rate limit


# ============================================================
# Step 4: HTTP transport + LangChain agent
# ============================================================
async def demo_http_with_agent() -> None:
    step(4, "HTTP transport + LangChain agent")

    info = check_mcp_available()
    if not info.get("langchain_mcp_adapters"):
        print("  [跳过] langchain-mcp-adapters 未安装")
        return

    if not any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    ):
        print("  [跳过] 无 API key, 跳过 agent 部分")
        return

    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_mcp_adapters.sessions import create_session
    from langchain_mcp_adapters.tools import load_mcp_tools

    server = build_http_server()
    app = server.streamable_http_app()

    import uvicorn

    config = uvicorn.Config(
        app=app, host="127.0.0.1", port=8766,
        log_level="warning", lifespan="on",
    )
    uv_server = uvicorn.Server(config)
    server_task = asyncio.create_task(uv_server.serve())

    for _ in range(20):
        await asyncio.sleep(0.2)
        if uv_server.started:
            break
    if not uv_server.started:
        print("  [跳过] server 启动超时")
        uv_server.should_exit = True
        await server_task
        return

    try:
        async with create_session({
            "transport": "http",
            "url": "http://127.0.0.1:8766/mcp",
        }) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)

            agent = create_agent(model=get_llm(), tools=tools)

            try:
                r = await agent.ainvoke({
                    "messages": [HumanMessage("帮我算 (50 + 70) * 2, 然后 ping 一下 'done'")],
                })
                last = r["messages"][-1]
                print(f"  Agent 最终回复: {getattr(last, 'content', '')[:150]}")
            except Exception as e:
                print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")
    finally:
        uv_server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            uv_server.force_exit = True

    # 💡 HTTP transport 实战:
    #    - server 在另一进程 / 另一容器
    #    - LangChain 端只看到 BaseTool list
    #    - 替换 stdio → HTTP 不需要改 agent 代码


# ============================================================
# Step 5: 自定义 httpx client — Bearer auth / headers
# ============================================================
async def demo_bearer_auth() -> None:
    step(5, "Bearer auth — 自定义 httpx client 注入 header")

    print("""
  MCP HTTP 默认无 auth — 生产必须加 Bearer / OAuth:

      from langchain_mcp_adapters.sessions import create_session

      headers = {"Authorization": "Bearer sk-xxx"}

      async with create_session({
          "transport": "http",
          "url": "https://mcp.example.com/mcp",
          "headers": headers,
      }) as session:
          await session.initialize()
          ...

  Server 端 (FastMCP):
    - middleware 校验 Authorization header
    - 401 拒绝 + WWW-Authenticate header
    - /token 端点发 Bearer (OAuth2 flow)

  实战 (3-tier auth):
    1. public tool — 任何 client 可调
    2. user tool — 校验 Bearer token (user scope)
    3. admin tool — 校验 admin token (RBAC)

  工具:
    - mcp.shared._httpx_utils.create_mcp_http_client 自定义 client
    - httpx.Auth 子类 (Bearer / OAuth2 / mTLS)
    - 反代层 (nginx / cloudflare) 加 IP 白名单
""")
    # 没真起带 auth 的 server, 仅展示模式
    print("  (模式演示, 没真起 auth server)")


# ============================================================
# Step 6: 多 client 并发连同一 HTTP server
# ============================================================
async def demo_multi_client() -> None:
    step(6, "多 client 并发连同一 HTTP server")

    info = check_mcp_available()
    if not info.get("langchain_mcp_adapters"):
        print("  [跳过] langchain-mcp-adapters 未安装")
        return

    from langchain_mcp_adapters.sessions import create_session
    from langchain_mcp_adapters.tools import load_mcp_tools

    server = build_http_server()
    app = server.streamable_http_app()

    import uvicorn

    config = uvicorn.Config(
        app=app, host="127.0.0.1", port=8767,
        log_level="warning", lifespan="on",
    )
    uv_server = uvicorn.Server(config)
    server_task = asyncio.create_task(uv_server.serve())

    for _ in range(20):
        await asyncio.sleep(0.2)
        if uv_server.started:
            break
    if not uv_server.started:
        print("  [跳过] server 启动超时")
        uv_server.should_exit = True
        await server_task
        return

    async def one_client(client_id: int) -> list[str]:
        async with create_session({
            "transport": "http",
            "url": "http://127.0.0.1:8767/mcp",
        }) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)

            result = await session.call_tool("ping", {"message": f"from-{client_id}"})
            texts = [getattr(c, "text", str(c)) for c in result.content]
            return texts

    try:
        # 3 个 client 并发
        results = await asyncio.gather(
            one_client(1), one_client(2), one_client(3),
        )
        for i, texts in enumerate(results, 1):
            print(f"  client-{i}: {texts[0] if texts else '<empty>'}")
        print(f"  ✓ 3 client 并发完成, server 横向扩展能力验证")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")
    finally:
        uv_server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            uv_server.force_exit = True

    # 💡 HTTP transport 实战优势:
    #    - N 个 client 连同一 server (stdio 做不到)
    #    - 横向扩展: uvicorn --workers N
    #    - 监控: Prometheus middleware + OpenTelemetry
    #    - 反代: nginx path /mcp → upstream


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    # Step 1 (概念) + Step 2 (in-process 限制) + Step 5 (auth 模式) 不需要 server
    run_async(demo_http_vs_stdio())
    run_async(demo_in_process_asgi())
    run_async(demo_bearer_auth())

    # Step 3/4/6 需要 langchain-mcp-adapters + uvicorn
    # ⚠ uvicorn.Server 绑 anyio event loop — 必须同一 asyncio.run 跑完, 不然跨 loop 崩
    info = check_mcp_available()
    if info.get("langchain_mcp_adapters"):

        async def all_http_demos() -> None:
            await demo_real_http_server()
            await demo_multi_client()
            if has_key:
                await demo_http_with_agent()
            else:
                print("\n[i]   Step 4 跳过 (无 API key)")

        run_async(all_http_demos())
    else:
        print("\n[跳过] Step 3/4/6 需 langchain-mcp-adapters")

    print("\n[OK] 05_http_transport.py 全部 demo 跑完。")