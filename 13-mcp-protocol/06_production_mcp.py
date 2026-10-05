"""06_production_mcp.py — Demo 6: 生产级 MCP (pool / retry / auth / observability).

学完这个 demo 你能回答:
1.  高并发怎么复用 MCP session? (session pool)
2.  transient error 怎么 retry? (tenacity + 退避)
3.  Bearer auth 怎么注入? (create_session + headers)
4.  observability 怎么做? (logging + tool_call duration)
5.  graceful shutdown 怎么做? (close session + drain)
6.  实战: 把 MCP 接进 FastAPI / 生产监控

跑法:
    python 06_production_mcp.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from _common import banner, get_llm, run_async, step
from mcp_helpers import check_mcp_available

# ============================================================
# Mock MCP server (跑本 demo 时用)
# ============================================================


def build_production_server():
    """构造 FastMCP server (slow + flaky tool 模拟生产场景)."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("production-mcp-server")

    @mcp.tool()
    def slow_lookup(query: str, delay_ms: int = 100) -> str:
        """慢查询 (模拟 IO).

        Args:
            query: 查询
            delay_ms: 延迟毫秒

        Returns:
            结果
        """
        import time as _t

        _t.sleep(delay_ms / 1000)
        return f"result for '{query}' (after {delay_ms}ms)"

    @mcp.tool()
    def maybe_fail(should_fail: bool = False) -> str:
        """可控失败 (测 retry).

        Args:
            should_fail: 是否失败

        Returns:
            OK 字符串
        """
        if should_fail:
            raise RuntimeError("simulated transient failure")
        return "OK"

    @mcp.tool()
    def echo_value(value: str) -> str:
        """回显.

        Args:
            value: 任意值

        Returns:
            原值
        """
        return value

    return mcp


# ============================================================
# Demo
# ============================================================
banner("Demo 6: Production MCP (pool + retry + auth + observability)")


# ============================================================
# Step 1: 概念 — 生产 MCP 4 大支柱
# ============================================================
async def demo_concept() -> None:
    step(1, "生产 MCP 4 大支柱")

    print("""
  ┌────────────────────┬─────────────────────────────────────────┐
  │ 维度                │ 实战                                    │
  ├────────────────────┼─────────────────────────────────────────┤
  │ 高并发              │ Session Pool (N session + 队列复用)      │
  │ 容错                │ Retry + 退避 (tenacity) + 错误分类      │
  │ 鉴权                │ Bearer token / OAuth / mTLS             │
  │ 可观测              │ Logging + tool_call duration + 指标      │
  └────────────────────┴─────────────────────────────────────────┘

  实战栈:
    - httpx + 连接池 (HTTP keep-alive)
    - tenacity (retry library)
    - structlog / loguru (JSON structured log)
    - prometheus_client (metrics)
""")


# ============================================================
# Step 2: Session Pool — N session + 队列复用
# ============================================================
@dataclass
class PooledSession:
    """单个 pooled session."""

    session_id: int
    # 实际使用时 session 是 ClientSession 对象
    last_used: float = 0.0
    in_use: bool = False


class MCPSessionPool:
    """MCP session 池 — 复用 session 避免每次新建成本.

    实战:
      - 生产常见 50-200 并发 client
      - 每个 client 维持 1 session (or 按需 acquire)
      - session 复用减少 handshake 开销 (~100ms/次)
      - pool size 配合 backpressure 防止过载
    """

    def __init__(self, server_url: str, pool_size: int = 5) -> None:
        self.server_url = server_url
        self.pool_size = pool_size
        self.queue: asyncio.Queue[PooledSession] = asyncio.Queue()
        self.all_sessions: list[PooledSession] = []

    async def start(self) -> None:
        for i in range(self.pool_size):
            ps = PooledSession(session_id=i)
            self.queue.put_nowait(ps)
            self.all_sessions.append(ps)

    @asynccontextmanager
    async def acquire(self):
        ps = await self.queue.get()
        ps.in_use = True
        ps.last_used = time.time()
        try:
            yield ps
        finally:
            ps.in_use = False
            await self.queue.put(ps)

    def stats(self) -> dict:
        in_use = sum(1 for ps in self.all_sessions if ps.in_use)
        return {
            "total": self.pool_size,
            "in_use": in_use,
            "available": self.pool_size - in_use,
        }


async def demo_session_pool() -> None:
    step(2, "Session Pool — 复用 session 降低 handshake 开销")

    # Mock pool (不真连 server — 测 pool 逻辑)
    pool = MCPSessionPool(server_url="stdio://01_basic_server.py", pool_size=3)
    await pool.start()
    print(f"  初始 pool: {pool.stats()}")

    # 模拟 5 个并发请求复用 3 个 session
    async def worker(worker_id: int) -> None:
        async with pool.acquire() as ps:
            await asyncio.sleep(0.05)  # 模拟 work
            print(f"  worker-{worker_id} 拿到 session {ps.session_id}")

    await asyncio.gather(*[worker(i) for i in range(5)])
    print(f"  完成后 pool: {pool.stats()}")
    print("  ✓ 5 个 worker 复用 3 个 session, 没阻塞")

    # 💡 实战:
    #    - pool size = 期望并发数 / session 创建时间(s) × 安全系数
    #    - session 本身有时限 (HTTP keep-alive, server restart)
    #    - 实战加 session_health_check + auto_recreate
    #    - 用 asyncio.Semaphore 也行, 但 pool 能统计 in_use 更精细


# ============================================================
# Step 3: Retry with 退避
# ============================================================
async def demo_retry() -> None:
    step(3, "Retry — transient 错误自动重试 + 退避")

    print("""
  实战 retry 模式:

    import tenacity

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=0.1, max=1.0),
        retry=tenacity.retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    async def call_with_retry(session, tool_name, args):
        return await session.call_tool(tool_name, args)

  错误分类:
    - transient (retry): ConnectionError, TimeoutError, 502/503/504
    - permanent (no retry): ValueError, 401/403/400
    - rate limit (retry + 长退避): 429

  实战陷阱:
    - 重试过多 → 雪崩 (上游恢复慢)
    - 没分类 → 永久错误也被重试 (浪费)
    - 退避太短 → 持续打挂 server
""")


# ============================================================
# Step 4: Bearer Auth (HTTP transport)
# ============================================================
async def demo_bearer_auth_real() -> None:
    step(4, "Bearer auth 实测 — HTTP transport + 自定义 header")

    info = check_mcp_available()
    if not info.get("langchain_mcp_adapters"):
        print("  [跳过] langchain-mcp-adapters 未安装")
        return

    from langchain_mcp_adapters.sessions import create_session

    # 模拟: 带 Bearer token 连 server (server 端校验)
    server = build_production_server()
    app = server.streamable_http_app()

    import uvicorn

    config = uvicorn.Config(
        app=app, host="127.0.0.1", port=8770,
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
        # 带 auth header
        async with create_session({
            "transport": "http",
            "url": "http://127.0.0.1:8770/mcp",
            "headers": {"Authorization": "Bearer demo-token-xyz"},
        }) as session:
            await session.initialize()
            result = await session.call_tool("echo_value", {"value": "with-auth"})
            for c in result.content:
                print(f"  auth client → {getattr(c, 'text', c)}")

        # 不带 auth (server 默认不校验 — 看 401 实战要 server middleware)
        async with create_session({
            "transport": "http",
            "url": "http://127.0.0.1:8770/mcp",
        }) as session:
            await session.initialize()
            result = await session.call_tool("echo_value", {"value": "no-auth"})
            for c in result.content:
                print(f"  no-auth client → {getattr(c, 'text', c)}")
    finally:
        uv_server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            uv_server.force_exit = True

    # 💡 实战:
    #    - client 端: headers={"Authorization": "Bearer ..."}
    #    - server 端: FastMCP middleware 校验 header (production 必须)
    #    - 失败返 401 + WWW-Authenticate: Bearer realm="mcp"
    #    - OAuth2: /token 端点发 Bearer, refresh_token 续期


# ============================================================
# Step 5: Observability — tool_call duration + logging
# ============================================================
@dataclass
class ToolCallStat:
    tool_name: str
    duration_ms: float
    success: bool
    error: str | None = None


async def demo_observability() -> None:
    step(5, "Observability — tool_call 监控 + 结构化日志")

    info = check_mcp_available()
    if not info.get("langchain_mcp_adapters"):
        print("  [跳过] langchain-mcp-adapters 未安装")
        return

    from langchain_mcp_adapters.sessions import create_session

    server = build_production_server()
    app = server.streamable_http_app()

    import uvicorn

    config = uvicorn.Config(
        app=app, host="127.0.0.1", port=8771,
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

    stats: list[ToolCallStat] = []

    try:
        async with create_session({
            "transport": "http",
            "url": "http://127.0.0.1:8771/mcp",
        }) as session:
            await session.initialize()

            # 测 N 次 call, 记录每次耗时
            for i in range(5):
                start = time.time()
                try:
                    r = await session.call_tool(
                        "slow_lookup",
                        {"query": f"q-{i}", "delay_ms": 50 + i * 10},
                    )
                    dur = (time.time() - start) * 1000
                    stats.append(ToolCallStat(
                        tool_name="slow_lookup",
                        duration_ms=dur,
                        success=True,
                    ))
                except Exception as e:
                    dur = (time.time() - start) * 1000
                    stats.append(ToolCallStat(
                        tool_name="slow_lookup",
                        duration_ms=dur,
                        success=False,
                        error=str(e)[:50],
                    ))

            # 失败一次测错误记录
            try:
                start = time.time()
                await session.call_tool("maybe_fail", {"should_fail": True})
            except Exception as e:
                dur = (time.time() - start) * 1000
                stats.append(ToolCallStat(
                    tool_name="maybe_fail",
                    duration_ms=dur,
                    success=False,
                    error=str(e)[:80],
                ))

        # 输出统计
        print(f"\n  tool_call stats ({len(stats)} calls):")
        for s in stats:
            err = f" err={s.error}" if not s.success else ""
            print(f"    - {s.tool_name}: {s.duration_ms:.1f}ms{(' ✓' if s.success else ' ✗')}{err}")

        # 平均耗时
        success_stats = [s for s in stats if s.success]
        if success_stats:
            avg = sum(s.duration_ms for s in success_stats) / len(success_stats)
            print(f"\n  平均耗时 (success): {avg:.1f}ms")
            print(f"  成功率: {len(success_stats)}/{len(stats)} = {len(success_stats)/len(stats)*100:.0f}%")
    finally:
        uv_server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            uv_server.force_exit = True

    # 💡 实战:
    #    - Prometheus: Counter("mcp_tool_calls_total", ["tool", "status"])
    #    - Histogram: mcp_tool_duration_seconds (P50/P95/P99)
    #    - structlog: log JSON 到 stdout → Loki / ELK
    #    - OpenTelemetry: trace 跨 client + server + LLM


# ============================================================
# Step 6: Graceful shutdown
# ============================================================
async def demo_graceful_shutdown() -> None:
    step(6, "Graceful shutdown — drain in-flight + close session")

    print("""
  实战 shutdown 流程 (FastAPI / k8s pod terminate):

    1. SIGTERM 收到 → stop accepting new requests (HTTP 503)
    2. 等 in-flight 完成 (timeout 30s)
    3. close 所有 MCP session (terminate)
    4. close server (uvicorn.Server.should_exit = True)
    5. flush metrics + log "shutdown complete"

  代码模式 (FastAPI lifespan):

      @asynccontextmanager
      async def lifespan(app):
          # startup
          await mcp_pool.start()
          yield
          # shutdown
          await mcp_pool.close_all()
          await asyncio.sleep(0.5)  # drain

  K8s:
    - terminationGracePeriodSeconds: 30
    - preStop hook: 等 readiness probe 失败 (让 LB 摘除)
    - SIGTERM → app 走 shutdown 流程
""")


# ============================================================
# Step 7: 端到端 FastAPI + MCP
# ============================================================
async def demo_fastapi_integration() -> None:
    step(7, "FastAPI + MCP 集成 — 生产 pattern")

    print("""
  实战代码 (FastAPI lifespan + MCP pool):

      from contextlib import asynccontextmanager
      from fastapi import FastAPI, Request
      from langchain_mcp_adapters.sessions import create_session
      from langchain.agents import create_agent

      MCP_URL = "http://mcp.internal:8080/mcp"
      pool = MCPSessionPool(MCP_URL, pool_size=20)

      @asynccontextmanager
      async def lifespan(app: FastAPI):
          await pool.start()
          yield
          await pool.close_all()

      app = FastAPI(lifespan=lifespan)

      @app.post("/chat")
      async def chat(req: Request, body: ChatReq):
          async with pool.acquire() as ps:
              tools = await load_mcp_tools(ps.session)
              agent = create_agent(model=get_llm(), tools=tools)
              r = await agent.ainvoke({"messages": [HumanMessage(body.q)]})
              return {"answer": r["messages"][-1].content}

      # 反代:
      #   - nginx path /chat → app:8000/chat
      #   - nginx path /mcp → upstream mcp.internal:8080/mcp
      #   - 监控 Prometheus exporter :9090/metrics
""")
    # (没真起 FastAPI — 模式演示)


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    # 概念 + pool/retry/shutdown/integration 模式不需 server
    run_async(demo_concept())
    run_async(demo_session_pool())
    run_async(demo_retry())
    run_async(demo_graceful_shutdown())
    run_async(demo_fastapi_integration())

    # auth + observability 需要真 server (uvicorn 绑事件循环)
    info = check_mcp_available()
    if info.get("langchain_mcp_adapters"):

        async def all_prod_demos() -> None:
            await demo_bearer_auth_real()
            await demo_observability()

        run_async(all_prod_demos())
    else:
        print("\n[跳过] Step 4/5 需 langchain-mcp-adapters")

    print("\n[OK] 06_production_mcp.py 全部 demo 跑完。")