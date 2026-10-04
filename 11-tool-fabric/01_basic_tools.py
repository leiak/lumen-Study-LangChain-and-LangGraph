"""01_basic_tools.py — Demo 1: @tool + Pydantic validation + 复杂 schema.

学完这个 demo 你能回答:
1.  @tool 装饰器最简形态? (无 args_schema, 自动从签名推断)
2.  @tool + args_schema=BaseModel 怎么严格校验? (ge / le / Literal)
3.  LLM 怎么 "看到" 工具 schema? (从 docstring + 类型注解)
4.  工具 invoke 永远接受 dict, 不是位置参数 — 为什么?
5.  复杂 schema: Optional / Literal / Field(default) 怎么组合?
6.  工具 return 是 dict 还是 string? 哪个对 LLM 更友好?

跑法:
    python 01_basic_tools.py
"""
from __future__ import annotations

import os
import sys

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError

from _common import banner, get_sample_agent, step
from tools import (
    DBQuery,
    RefundRequest,
    SearchQuery,
    calculator,
    db_query,
    get_weather,
    refund,
    web_search,
)

# ============================================================
# Step 1: @tool 简单形态 — 无 schema, 自动推断
# ============================================================
banner("Demo 1: Basic Tools")


def demo_simple_tool() -> None:
    step(1, "@tool 简单形态 (无 schema) — get_weather")
    # @tool 把普通函数包成 BaseTool, 自动从签名 + docstring 推断 schema
    print(f"  工具名: {get_weather.name}")
    print(f"  描述:   {get_weather.description[:80]}...")
    print(f"  参数:   {list(get_weather.args.keys())}")

    # invoke 永远接受 dict — LLM 调工具时也是传 dict (不是位置参数)
    result = get_weather.invoke({"city": "北京"})
    print(f"  invoke({{'city': '北京'}}) → {result}")
    # 实际 print 输出: {'city': '北京', 'temp_c': 22, 'condition': 'sunny'}

    # 💡 invoke dict 而非位置参数的原因:
    #    LLM 的 tool_call 永远产出 {"name": ..., "args": {...}}, 框架 dispatch 时
    #    用 .invoke(tc["args"]) 就能直接调用, 不需要解包. 统一 dict 接口便于通用化.


# ============================================================
# Step 2: @tool + args_schema — Pydantic 严格校验
# ============================================================
def demo_schema_tool() -> None:
    step(2, "@tool + args_schema (Pydantic 校验) — web_search")

    # 正常调用
    result = web_search.invoke({"query": "RAG", "max_results": 3, "language": "en"})
    print(f"  正常调用: {len(result)} 条结果")

    # 越界调用 — max_results=999 > le=20 → Pydantic ValidationError
    print("\n  越界调用 max_results=999 (le=20):")
    try:
        web_search.invoke({"query": "test", "max_results": 999, "language": "en"})
        print("  ❌ 居然没报错?")
    except ValidationError as e:
        # ValidationError 被 LangChain 转成 ToolException, 自动回给 LLM
        err = e.errors()[0]
        print(f"  ✓ Pydantic 拦截: {err['loc']} - {err['msg'][:60]}")

    # 💡 在 create_agent 里, Pydantic 校验失败会被 LangChain 自动转成
    #    ToolMessage(content=错误信息) 回给 LLM — LLM 看到错就会改参数重试
    #    不需要写额外 try/except


# ============================================================
# Step 3: Agent invocation with tools
# ============================================================
def demo_agent_invocation() -> None:
    step(3, "create_agent 装 1 个工具 + invoke")

    # 用 _common 的工厂 — 传 tools 列表
    agent = get_sample_agent(tools=[get_weather])

    # 小模型 (M3) 工具能力不稳, 失败不阻塞
    try:
        r = agent.invoke({"messages": [HumanMessage("北京天气怎么样?")]})
        last_msg = r["messages"][-1]
        content = getattr(last_msg, "content", "")
        print(f"  最终回复: {content[:120]}")
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# Step 4: 复杂 schema — Literal + Field 约束 + Optional
# ============================================================
def demo_complex_schema() -> None:
    step(4, "复杂 schema: Literal + Field + Optional")

    # SearchQuery / DBQuery / RefundRequest 三种 Pydantic schema
    # Literal: 枚举值, LLM 只能选其一
    # Field(ge=1, le=20): 数值约束
    # Field(default=...): 可选参数
    # dict | None: Optional

    print("  SearchQuery (Literal[zh/en] + ge/le):")
    print(f"    字段: {list(SearchQuery.model_fields.keys())}")
    print(f"    max_results: ge={SearchQuery.model_fields['max_results'].metadata}")
    print(f"    language: Literal={SearchQuery.model_fields['language'].metadata}")

    print("\n  DBQuery (Literal[users/orders/products] + Optional where):")
    print(f"    table: Literal={DBQuery.model_fields['table'].metadata}")

    print("\n  RefundRequest (ge=1 + le=100000):")
    print(f"    amount_cents 约束: ge=1, le=100000")

    # 验证 Literal 约束: table 不在白名单 → Pydantic 拒绝
    print("\n  DBQuery 越界测试 (table='unknown'):")
    try:
        DBQuery(table="unknown", limit=10)
        print("  ❌ 居然没报错?")
    except ValidationError as e:
        err = e.errors()[0]
        print(f"  ✓ Pydantic 拦截: {err['msg'][:80]}")

    # db_query 工具调用: where + limit 一起传
    rows = db_query.invoke({"table": "users", "where": {"id": 1}, "limit": 3})
    print(f"\n  db_query(table='users', where={{'id': 1}}, limit=3) → {len(rows)} 行")


# ============================================================
# Step 5: Tool 返回 dict vs string — 哪种对 LLM 更友好?
# ============================================================
def demo_return_types() -> None:
    step(5, "Tool 返回 dict vs string")

    # get_weather 返回 dict — LLM 可读 JSON, 也能精确取字段
    print("  get_weather (dict):")
    result = get_weather.invoke({"city": "Shanghai"})
    print(f"    return: {result}")
    print(f"    type: {type(result).__name__}")

    # calculator 返回 string — 简单数值
    print("\n  calculator (string):")
    result = calculator.invoke({"expression": "(1 + 2) * 3"})
    print(f"    return: '{result}'")
    print(f"    type: {type(result).__name__}")

    # refund 返回 dict — 包含 status + order_id + amount
    print("\n  refund (dict with status):")
    result = refund.invoke({"order_id": 12345, "amount_cents": 5000, "reason": "test"})
    print(f"    return: {result}")

    # 💡 实战:
    #    - 工具返回 dict 时, LangChain 自动 str() 序列化给 LLM
    #    - dict 比 string 让 LLM 更结构化地理解 (尤其多个字段)
    #    - 但: 返回 dict 时 ToolMessage.content 是 str(dict), 不是真 dict
    #    - 想让下游代码拿到结构化数据 → 用 artifact (见 L1 02_tools.py demo 7)


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    # 这些 demo 大部分不调 LLM (smoke test), 仅 demo_agent_invocation 需要
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("[!] 没设 API key — 仅跑本地 demo (跳过 agent invocation)")

    demos = [
        ("simple_tool", demo_simple_tool),
        ("schema_tool", demo_schema_tool),
        ("agent_invocation", demo_agent_invocation),
        ("complex_schema", demo_complex_schema),
        ("return_types", demo_return_types),
    ]
    for name, fn in demos:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 01_basic_tools.py 全部 demo 跑完。")