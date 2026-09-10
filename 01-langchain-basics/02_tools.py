"""02_tools.py — Tools: 把 Python 函数 / 类 / API 暴露给 LLM.

学完这个模块你能回答:
1.  @tool 装饰器怎么用? (最简形态)
2.  怎么用 args_schema 严格定义参数? (Pydantic 校验)
3.  怎么用 BaseTool 子类封装有状态 / 复杂工具?
4.  怎么写异步工具? (调 HTTP / 数据库时必备)
5.  工具报错怎么处理? (ToolException 让 LLM 看到错误)
6.  怎么程序化构造工具? (StructuredTool.from_function)
7.  怎么返回 artifact? (content 给 LLM, artifact 给程序)
8.  怎么注入运行时上下文? (InjectedToolArg, 如 user_id)
9.  完整 tool calling 流程是什么? (bind → dispatch → ToolMessage 回填)
10. 模型一次返回多个工具调用怎么处理? (并行 dispatch)

跑法:
    python 02_tools.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Annotated, Any

# Windows cmd 默认 GBK,LLM 返回 emoji / 特殊符号会崩。强制 UTF-8 + 错误替换
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import (
    BaseTool,
    InjectedToolArg,
    StructuredTool,
    ToolException,
    tool,
)
from pydantic import BaseModel, Field

from _common import banner, get_llm

# ============================================================
# 1. @tool 装饰器 — 最简形态
# ============================================================
banner("1. @tool 装饰器 (最简)")


@tool
def add(a: int, b: int) -> int:
    """把两个数相加。"""
    return a + b


def demo_simple_tool() -> None:
    # @tool 把普通函数包成 BaseTool 实例,自动从签名和 docstring 推断 schema
    print("工具名:        ", add.name)            # → "add"
    print("工具描述 (来自 docstring):", add.description)
    print("参数 schema:    ", add.args)            # → {"a": int, "b": int}
    print("直接调用 (LLM 不参与):", add.invoke({"a": 1, "b": 2}))  # → 3
    # 注意: invoke 永远接受 dict,不是位置参数。LLM 调工具时也是传 dict。


# ============================================================
# 2. @tool + args_schema — 严格参数校验
# ============================================================
banner("2. @tool + args_schema (Pydantic 校验)")


class SearchInput(BaseModel):
    """搜索输入."""

    query: str = Field(description="搜索关键词")
    # ge=1, le=20 → LangChain 把这些约束发给 LLM,LLM 通常会避免越界
    top_k: int = Field(default=3, description="返回前 N 条", ge=1, le=20)


@tool("web_search", args_schema=SearchInput)
def web_search(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """(mock) 在网上搜索关键词."""
    # 真实场景:调 Bing / Google API,这里假装返回
    return [
        {"title": f"结果 {i} for {query}", "url": f"https://example.com/{i}"}
        for i in range(top_k)
    ]


def demo_schema_tool() -> None:
    # 正常调用 → 返回 list[dict]
    print("OK:", web_search.invoke({"query": "LangChain 1.0", "top_k": 2}))

    # 越界调用 → Pydantic ValidationError, LangChain 会自动转给 LLM
    try:
        web_search.invoke({"query": "test", "top_k": 999})  # 超过 le=20
        # web_search.ainvoke()
    except Exception as e:
        print(f"校验失败 (预期): {type(e).__name__}")


# ============================================================
# 3. BaseTool 子类 — 封装有状态 / 复杂的工具
# ============================================================
banner("3. BaseTool 子类 (有状态工具)")


class _CalculatorInput(BaseModel):
    expression: str = Field(description="数学表达式,例如 1+2*3")


class CalculatorTool(BaseTool):
    """支持 + - * / 与括号的简单计算器."""

    name: str = "calculator"
    description: str = "计算数学表达式,支持四则运算和括号。"
    args_schema: type[BaseModel] = _CalculatorInput
    # 工具执行失败时,框架自动重试的最大次数 (在 create_agent 里才有意义)
    max_retries: int = 1

    def _run(self, expression: str) -> str:
        # ⚠️ eval 在生产环境危险, 这里仅做演示
        try:
            return str(eval(expression, {"__builtins__": {}}, {}))
        except Exception as exc:
            # 业务错误 → ToolException, 会自动转成 ToolMessage 回给 LLM
            raise ToolException(f"无法计算 '{expression}': {exc}")

    async def _arun(self, expression: str) -> str:
        # 真实异步 IO (调 HTTP / DB) 这里用 await
        return self._run(expression)


def demo_basetool() -> None:
    calc = CalculatorTool()
    print("1+2*3   =", calc.invoke({"expression": "1+2*3"}))
    print("(1+2)*3 =", calc.invoke({"expression": "(1+2)*3"}))

    # BaseTool 子类的最大优势: 可以带状态 (self.xxx)
    #   class SqlTool(BaseTool):
    #       conn: Connection       ← 数据库连接
    #       cache: dict = {}       ← 缓存
    #       def _run(self, sql):   ← 主逻辑
    #           return self.conn.execute(sql)
    # 跟 Spring 的 @Service / Gin 的 struct method 是一回事,只是 LLM 能直接调用它


# ============================================================
# 4. 异步工具 — 调 HTTP / 数据库时必备
# ============================================================
banner("4. 异步工具 (asyncio)")


@tool
async def fetch_url(url: str) -> str:
    """(mock) 异步抓取 URL 内容。"""
    await asyncio.sleep(0.1)  # 模拟 IO 等待
    return f"<html>{url} 的内容...</html>"


async def demo_async_tool() -> None:
    # 异步工具必须 await,或在 async chain 里用 .ainvoke
    result = await fetch_url.ainvoke({"url": "https://example.com"})
    print("异步结果:", result[:60])

    # 💡 实际场景里,多个独立 IO 必须并发 — asyncio.gather
    # 顺序跑 3 个要 0.3s, 并发只 0.1s
    t0 = asyncio.get_event_loop().time()
    results = await asyncio.gather(
        fetch_url.ainvoke({"url": "https://a.com"}),
        fetch_url.ainvoke({"url": "https://b.com"}),
        fetch_url.ainvoke({"url": "https://c.com"}),
    )
    elapsed = asyncio.get_event_loop().time() - t0
    print(f"并发抓取 {len(results)} 个 URL, 耗时 {elapsed:.2f}s (而非 0.3s)")


# ============================================================
# 5. 工具错误处理 — ToolException 让 LLM 看到错误并决定是否重试
# ============================================================
banner("5. 工具错误处理 (ToolException)")


@tool
def safe_divide(a: float, b: float) -> float:
    """除法, b 不能为 0。"""
    if b == 0:
        # ToolException 而非普通 Exception → 框架知道这是"业务错",会回给 LLM
        raise ToolException("b 不能为 0, 请告诉用户换一个非零除数")
    return a / b


def demo_tool_error() -> None:
    # 直接调用: ToolException 正常抛出
    try:
        safe_divide.invoke({"a": 10, "b": 0})
    except ToolException as e:
        print(f"ToolException (预期): {e}")

    # 在 create_agent / bind_tools 流程里:
    #   ToolException 会被框架自动捕获 → 转成 ToolMessage(content=str(e)) → 回给 LLM
    #   LLM 看到错误后可以: ① 改参数重试 ② 换工具 ③ 直接告诉用户
    # 不需要任何额外配置 — LangChain 1.x 的默认行为
    print(">>> 在 Agent 里, ToolException 自动转 ToolMessage, LLM 决定下一步")


# ============================================================
# 6. StructuredTool.from_function — 程序化构造工具
# ============================================================
banner("6. StructuredTool.from_function (程序化构造)")


# 当函数是外部库 / 动态生成的, 不能直接 @tool 时,用 from_function 包一层
def _lookup_employee_raw(emp_id: str) -> dict[str, Any]:
    """(mock) 查员工信息."""
    employees = {
        "E001": {"name": "张三", "dept": "工程", "level": "P7"},
        "E002": {"name": "李四", "dept": "产品", "level": "P6"},
    }
    return employees.get(emp_id, {"error": "not found"})


# 动态构造工具: 没有 @tool 装饰, 但同样有完整的 schema + invoke
lookup_employee = StructuredTool.from_function(
    func=_lookup_employee_raw,
    name="lookup_employee",
    description="按员工 ID 查员工信息, 返回 {name, dept, level}",
)


def demo_constructed_tool() -> None:
    print("工具:", lookup_employee.name)
    print("调用:", lookup_employee.invoke({"emp_id": "E001"}))

    # 💡 适用场景:
    # - 工具函数是动态生成的 (例如从配置文件 / 注册中心加载)
    # - 同一个底层函数想包成多个不同名字的工具 (如 get_user / find_user 共用实现)
    # - 工具来自第三方库, 不能改它的签名


# ============================================================
# 7. 返回 artifact — content 给 LLM 看, artifact 给程序用
# ============================================================
banner("7. 返回 (content, artifact) — 大数据场景")


@tool
def query_database(sql: str) -> tuple[str, list[dict[str, Any]]]:
    """(mock) 跑 SQL, 返回 (LLM 看的摘要, 完整结果集)."""
    rows = [
        {"id": i, "value": f"row-{i}", "data": "x" * 50}
        for i in range(5)
    ]
    # (content, artifact) tuple: content 进 LLM 的上下文, artifact 留给程序
    summary = f"查询返回 {len(rows)} 行, 前 3 行预览: {rows[:3]}"
    return (summary, rows)


def demo_artifact_tool() -> None:
    # invoke 返回的就是 (content, artifact)
    content, rows = query_database.invoke({"sql": "SELECT * FROM t"})
    print(f"content (给 LLM): {content[:60]}...")
    print(f"artifact (给程序): {len(rows)} 行完整数据")

    # 💡 适用场景: 工具返回大量数据,但只想让 LLM 看摘要
    # - 全文搜索:  摘要 = top 3 + 计数,   artifact = 完整结果列表
    # - 数据库查询: 摘要 = 总数 + 前几行,   artifact = 完整 DataFrame
    # - 文件读取:   摘要 = "文件 1000 行", artifact = 完整文本
    # 跟 Java 里把 DTO 拆成 SummaryVO + DetailVO 思路一样


# ============================================================
# 8. InjectedToolArg — 注入运行时上下文 (user_id, session_id)
# ============================================================
banner("8. InjectedToolArg — 注入运行时上下文")


# 场景: 多用户系统里, 工具需要知道 "当前是谁在调", 不能让 LLM 自己填
# Annotated[..., InjectedToolArg] 告诉 LangChain: 这个参数 LLM 不传,运行时注入
# (InjectedToolArg 在 1.x 是 marker class, 不接受任何参数)
@tool
def get_my_orders(
    user_id: Annotated[str, InjectedToolArg],  # ← 无 ()
    status: str = "all",
) -> str:
    """查当前用户的订单。user_id 由系统注入, LLM 不需要传。"""
    return f"[用户 {user_id}] {status} 订单: 3 个 (mock)"


def demo_injected_tool() -> None:
    # LLM 看到的 schema 中, user_id 被标记为 injected → LLM 不能填这个参数
    schema_params = list(get_my_orders.args.keys())
    print(f"LLM 看到的参数: {schema_params}")  # → 只有 'status', user_id 被隐藏

    # 直接调用时, user_id 必须由调用方 (Agent 框架 / 我们的代码) 注入
    # 这里手动模拟 framework 的注入行为
    config: RunnableConfig = {"configurable": {"user_id": "U-Alice"}}
    user_id = config["configurable"]["user_id"]
    result = get_my_orders.invoke({"user_id": user_id, "status": "pending"})
    print("结果:", result)


# ============================================================
# 9. 完整 tool calling 流程 — bind → dispatch → 回填 ToolMessage
# ============================================================
banner("9. 完整 tool calling 流程 (bind → dispatch → 回填)")


@tool
def get_weather(city: str) -> str:
    """(mock) 查天气."""
    return f"{city} 晴, 25°C"


@tool
def get_time(timezone: str) -> str:
    """(mock) 查时间."""
    return f"{timezone} 当前时间: 14:30"


def _dispatch_tool_calls(resp, tools: list) -> list[ToolMessage]:
    """手动 dispatch: 把 AIMessage.tool_calls 路由回 Python 函数, 包成 ToolMessage.

    LangChain 内部的 create_agent 就是在做这个 — 我们这里手动展开,看清每一步。
    """
    tool_map = {t.name: t for t in tools}
    tool_messages: list[ToolMessage] = []

    for tc in resp.tool_calls:
        fn = tool_map.get(tc["name"])
        if fn is None:
            content = f"未知工具: {tc['name']}"
        else:
            try:
                content = str(fn.invoke(tc["args"]))
            except ToolException as e:
                # 业务错: 把错误内容当 ToolMessage 回给 LLM
                content = f"工具错误: {e}"
            except Exception as e:
                # 意外错: 不暴露内部细节给 LLM
                content = f"工具执行失败: {type(e).__name__}"

        # ToolMessage 必须带 tool_call_id, 用来对应回 AIMessage 里的 tool_call
        tool_messages.append(ToolMessage(content=content, tool_call_id=tc["id"]))

    return tool_messages


def demo_full_tool_calling() -> None:
    # 这是 LangChain tool calling 的"心脏" — 后面所有 Agent 都基于这套机制
    llm = get_llm()
    tools = [get_weather, get_time]

    # Step 1: bind_tools 把工具的 schema 告诉 LLM
    llm_with_tools = llm.bind_tools(tools)

    user_msg = "北京天气怎么样? 现在几点了?"
    messages = [HumanMessage(content=user_msg)]

    # Step 2: 调用 LLM, 它可能返回 tool_calls 列表
    resp = llm_with_tools.invoke(messages)
    print(f"text: {resp.content or '(空, 模型决定调用工具)'}")
    print(f"tool_calls: {[tc['name'] for tc in resp.tool_calls]}")

    if not resp.tool_calls:
        print("[!] 模型没有调用工具,可能是 MiniMax-M3 工具能力不稳定。换个模型 (Claude / GPT) 试试。")
        return

    # Step 3: dispatch — 手动把 tool_calls 路由回 Python 函数
    tool_messages = _dispatch_tool_calls(resp, tools)
    for tm in tool_messages:
        print(f"  ToolMessage({tm.tool_call_id[:8]}...): {tm.content}")

    # Step 4: 把 AIMessage + ToolMessage 一起喂回 LLM, 让它生成最终回复
    final = llm_with_tools.invoke([*messages, resp, *tool_messages])
    print(f"\n最终回复: {final.content}")


# ============================================================
# 10. 并行 tool calls — 一次返回多个工具调用
# ============================================================
banner("10. 并行 tool calls (一次返回多个调用)")


@tool
def search_books(keyword: str) -> str:
    """(mock) 搜书."""
    return f"《{keyword}》相关书籍 3 本"


@tool
def search_movies(keyword: str) -> str:
    """(mock) 搜电影."""
    return f"《{keyword}》相关电影 2 部"


def demo_parallel_tool_calls() -> None:
    llm = get_llm()
    tools = [search_books, search_movies]

    # parallel_tool_calls 参数 (OpenAI 兼容):
    #   = True  (默认) → 模型可以一次吐多个 tool_calls
    #   = False        → 强制模型一次只调一个 (旧模型兼容)
    llm_with_tools = llm.bind_tools(tools)

    resp = llm_with_tools.invoke("推荐几本 Python 学习的书, 再推荐几部科幻电影")
    print(f"text: {resp.content or '(空)'}")
    print(f"一次返回 {len(resp.tool_calls)} 个 tool_call:")
    for tc in resp.tool_calls:
        print(f"  - {tc['name']}({tc['args']})")

    if not resp.tool_calls:
        print("[!] 模型没返回 tool_call,跳过 dispatch")
        return

    # 并行 dispatch — 独立 IO 必须并发
    async def _run_parallel() -> list[tuple[str, str]]:
        async def one(tc):
            fn_map = {"search_books": search_books, "search_movies": search_movies}
            fn = fn_map.get(tc["name"])
            if fn is None:
                return (tc["id"], f"未知工具 {tc['name']}")
            # 同步函数包成异步 (实际工具是 async 时不用包)
            result = await asyncio.to_thread(fn.invoke, tc["args"])
            return (tc["id"], str(result))

        return await asyncio.gather(*(one(tc) for tc in resp.tool_calls))

    results = asyncio.run(_run_parallel())
    print(f"并行执行 {len(results)} 个工具:")
    for tc_id, content in results:
        print(f"  - {tc_id[:8]}... → {content}")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    # Section 1-8 不需要 LLM, 纯本地工具演示
    demo_simple_tool()
    demo_schema_tool()
    demo_basetool()
    asyncio.run(demo_async_tool())
    demo_tool_error()
    demo_constructed_tool()
    demo_artifact_tool()
    demo_injected_tool()

    # Section 9-10 需要 LLM, MiniMax-M3 工具能力可能不稳,失败不阻塞
    for name, fn in [
        ("demo_full_tool_calling", demo_full_tool_calling),
        ("demo_parallel_tool_calls", demo_parallel_tool_calls),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 02_tools.py 全部 demo 跑完。")
