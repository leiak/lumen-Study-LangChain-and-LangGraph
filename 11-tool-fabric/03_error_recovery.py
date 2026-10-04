"""03_error_recovery.py — Demo 3: 工具错误处理 + retry + fallback + default values.

学完这个 demo 你能回答:
1.  工具 raise ValueError, 框架怎么处理? (LangChain 1.x: ToolException 自动转 ToolMessage)
2.  工具 return error dict vs raise — 哪种更好?
3.  怎么用 middleware 做 retry? (handler + try/except loop)
4.  怎么实现 fallback tool? (try A, 失败 → try B)
5.  Optional 参数 + 默认值 + LLM 漏传参数会怎样?
6.  ToolException vs 普通 Exception 的区别? (业务错 vs 编程错)

跑法:
    python 03_error_recovery.py
"""
import asyncio
import os
import sys
import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from _common import banner, get_sample_agent, step
from tools import calculator

# ============================================================
# Demo
# ============================================================
banner("Demo 3: Tool Error Recovery")


# ============================================================
# Step 1: 工具 raise ValueError — 走 ToolException
# ============================================================
@tool
def flaky_search(query: str, fail_rate: float = 0.5) -> str:
    """(mock) 不稳定搜索 — 模拟间歇性失败.

    Args:
        query: 搜索关键词
        fail_rate: 失败概率 (0-1), 仅供测试

    Returns:
        搜索结果 (成功时)
    """
    # 模拟间歇性失败 — 真实场景是网络抖动 / DB 临时不可用
    import random
    if random.random() < fail_rate:
        raise ToolException(f"搜索 '{query}' 暂时不可用, 请稍后重试")
    return f"results for {query}"


def demo_raise_value_error() -> None:
    step(1, "工具 raise ValueError → ToolException")

    # 直接调用: ToolException 正常抛出
    try:
        flaky_search.invoke({"query": "test", "fail_rate": 1.0})  # 100% fail
        print("  ❌ 应该 raise")
    except ToolException as e:
        print(f"  ✓ ToolException: {e}")

    # 💡 在 create_agent 里, ToolException 会被框架捕获, 转成:
    #    ToolMessage(content=str(e), tool_call_id=...)
    #    LLM 看到后可以: ① 改参数 ② 换工具 ③ 告诉用户失败
    #    普通 Exception (非 ToolException) 会被框架报 graph error → 通常 abort


# ============================================================
# Step 2: 工具 return error dict — 不 raise
# ============================================================
@tool
def safe_search(query: str) -> dict:
    """(mock) 安全搜索 — 失败返回 error dict, 不 raise.

    Args:
        query: 搜索关键词

    Returns:
        {"ok": bool, "data": any, "error": str | None}
    """
    if not query:
        return {"ok": False, "data": None, "error": "query 不能为空"}
    if len(query) > 100:
        return {"ok": False, "data": None, "error": "query 太长 (max 100)"}
    return {"ok": True, "data": f"results for {query}", "error": None}


def demo_return_error_dict() -> None:
    step(2, "工具 return error dict (不 raise)")

    # 正常调用
    r = safe_search.invoke({"query": "LangChain"})
    print(f"  OK: {r}")

    # 边界调用 — 不 raise, 返回 error dict
    r = safe_search.invoke({"query": ""})
    print(f"  空 query: {r}")

    r = safe_search.invoke({"query": "x" * 200})
    print(f"  超长 query: {r}")

    # 💡 raise vs return dict 对比:
    #   raise ToolException:
    #     + 框架自动转 ToolMessage 给 LLM
    #     + 业务错语义明确
    #     - LLM 不知道有几种错误类型
    #   return error dict:
    #     + 调用方代码能区分多种错误 (ok/error)
    #     + LLM 看到 dict 能精细决策
    #     - 调用方都要处理 ok 判断
    #   实战: 内部用 raise (简洁), 对外 API 用 return dict (可控)


# ============================================================
# Step 3: Retry middleware — wrap_tool_call + try/except loop
# ============================================================
from langchain.agents.middleware import wrap_tool_call


@wrap_tool_call
def retry_middleware(request, handler):
    """retry middleware — 失败重试 3 次, 指数 backoff."""
    max_retries = 3
    delay = 0.1  # 100ms
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return handler(request)
        except (ToolException, ValueError) as e:
            last_err = e
            if attempt < max_retries:
                print(f"  [RETRY] attempt {attempt} 失败: {type(e).__name__}, {delay:.2f}s 后重试")
                time.sleep(delay)
                delay *= 2  # 指数 backoff
    # 重试 3 次仍失败 — 把最后一次错误包成 ToolMessage
    return ToolMessage(
        content=f"重试 {max_retries} 次后仍失败: {last_err}",
        tool_call_id=request.tool_call["id"],
    )


def demo_retry_middleware() -> None:
    step(3, "retry middleware — 失败重试 3 次")

    # 直接测 middleware 行为 — 用一个总是失败的工具
    @tool
    def always_fail_tool(x: int) -> str:
        """故意失败的工具."""
        raise ToolException(f"故意失败 x={x}")

    # 模拟 request 对象
    class FakeRequest:
        def __init__(self, name: str, args: dict, call_id: str):
            self.tool_call = {"name": name, "args": args, "id": call_id}

    captured: list[ToolMessage] = []

    def fake_handler(req):
        # 实际调用工具 (总是失败)
        fn_map = {"always_fail_tool": always_fail_tool}
        result = fn_map[req.tool_call["name"]].invoke(req.tool_call["args"])
        return ToolMessage(content=str(result), tool_call_id=req.tool_call["id"])

    req = FakeRequest("always_fail_tool", {"x": 42}, "call_xyz")
    # AgentMiddleware 不直接 call, 而是通过 .wrap_tool_call(request, handler) 触发
    tm = retry_middleware.wrap_tool_call(req, fake_handler)
    captured.append(tm)
    print(f"  最终 ToolMessage: {tm.content}")

    # 💡 实战 retry middleware:
    #    - 只对 transient 错误重试 (网络 / DB timeout / 5xx)
    #    - 永久错误 (4xx / 参数错) 不重试
    #    - max_retries 通常 3-5, delay 100ms 起步, 指数 backoff
    #    - 生产: 用 tenacity 库 — 更 robust 的策略 (jitter / max_delay)


# ============================================================
# Step 4: Fallback tool — try primary, fail → try secondary
# ============================================================
@tool
def primary_search(query: str) -> str:
    """主搜索引擎 — 假设稳定."""
    # 主搜索
    return f"[PRIMARY] results for {query}"


@tool
def fallback_search(query: str) -> str:
    """备用搜索引擎 — 主搜索失败时用."""
    return f"[FALLBACK] results for {query}"


def demo_fallback_tool() -> None:
    step(4, "fallback tool — 主工具失败, 走备工具")

    # 模拟: primary 故意失败, 走 fallback
    @tool
    def fail_broker(query: str) -> str:
        """故意失败的 broker — 触发 fallback."""
        raise ToolException("primary broker down")

    # fallback 策略: 包装在 middleware 里
    @wrap_tool_call
    def fallback_middleware(request, handler):
        """失败时用同名 fallback 工具."""
        # 这里简化: 假设失败时调用 fallback_search
        try:
            return handler(request)
        except (ToolException, ValueError) as e:
            print(f"  [FALLBACK] primary 失败: {e}, 切 fallback_search")
            fb_result = fallback_search.invoke(request.tool_call["args"])
            return ToolMessage(
                content=str(fb_result),
                tool_call_id=request.tool_call["id"],
            )

    # mock 直接调用 — 验证 fallback 流程
    class FakeRequest:
        def __init__(self):
            self.tool_call = {"name": "fail_broker", "args": {"query": "test"}, "id": "c1"}

    def fake_handler(req):
        raise ToolException("primary broker down (mock)")

    req = FakeRequest()
    # 调用 fail_broker (会失败) — 用 try/except 抓 ToolException
    try:
        fail_broker.invoke(req.tool_call["args"])
        print("  fail_broker 直接调用: 未失败?")
    except ToolException as e:
        print(f"  fail_broker 直接调用 → ToolException: {e}")

    # 用 fallback_middleware 跑 (会捕获异常, 走 fallback)
    # 注意: AgentMiddleware 不直接 call, 通过 .wrap_tool_call(req, handler) 触发
    tm = fallback_middleware.wrap_tool_call(req, fake_handler)
    print(f"  经 fallback_middleware: {tm.content}")

    # 💡 实战 fallback 模式:
    #    - 不同 provider 备灾 (OpenAI → Anthropic → 本地模型)
    #    - 不同 DB 副本 (主库 → 备库 → 只读副本)
    #    - 不同 region (us-east-1 → us-west-2 → eu-west-1)
    #    监控 fallback 触发率 — 高于 5% 就是事故


# ============================================================
# Step 5: Default values for missing args
# ============================================================
class SearchWithDefaults(BaseModel):
    """带默认值 + 可选字段的搜索."""

    query: str = Field(description="搜索关键词 (必填)")
    max_results: int = Field(default=10, description="最多返回数, 默认 10")
    language: str | None = Field(default=None, description="语言, 默认不限")
    sort: Literal["relevance", "date"] = Field(default="relevance", description="排序方式")


@tool("flexible_search", args_schema=SearchWithDefaults)
def flexible_search(
    query: str,
    max_results: int = 10,
    language: str | None = None,
    sort: str = "relevance",
) -> dict:
    """灵活搜索 — 大多数参数可选, 有默认值.

    Args:
        query: 搜索关键词 (必填)
        max_results: 最多返回数, 默认 10
        language: 语言, 默认不限
        sort: 排序方式, 默认 relevance

    Returns:
        {"query": str, "params": {...}, "count": int}
    """
    return {
        "query": query,
        "params": {"max_results": max_results, "language": language, "sort": sort},
        "count": max_results,
    }


def demo_default_values() -> None:
    step(5, "Default values — LLM 漏传参数也不会崩")

    # 最小调用: 只传必填 query
    r = flexible_search.invoke({"query": "test"})
    print(f"  最小调用: {r}")

    # 完整调用: 所有参数
    r = flexible_search.invoke(
        {"query": "test", "max_results": 5, "language": "en", "sort": "date"}
    )
    print(f"  完整调用: {r}")

    # 💡 LLM 经常漏传可选参数 — Pydantic default 兜底, 工具始终能跑
    #    反例: 必填参数没 default → LLM 必须填, 不填就崩
    #    实战: 能 optional 的都 optional + 给合理 default


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    # 这些 demo 全部不调 LLM — 纯工具 + middleware 行为
    demos = [
        ("raise_value_error", demo_raise_value_error),
        ("return_error_dict", demo_return_error_dict),
        ("retry_middleware", demo_retry_middleware),
        ("fallback_tool", demo_fallback_tool),
        ("default_values", demo_default_values),
    ]
    for name, fn in demos:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 03_error_recovery.py 全部 demo 跑完。")