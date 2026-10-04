"""tools.py — 共享 sample tools (6 个).

教学 tool calling 工具集:
  - 简单工具 (get_weather, calculator): 单参数 / 表达式
  - 复杂工具 (web_search, db_query): 多参数 + nested schema
  - 危险工具 (write_note, refund): 需 HITL gate

💡 设计要点:
  - 用 @tool 装饰 + BaseModel args_schema (Pydantic 校验)
  - 每个工具有详细 docstring (LLM 靠 docstring 决定何时调)
  - 工具 return 是 dict (结构化) 或 string (简单)
  - calculator 用 AST 而非 eval (避免代码注入)
"""
import ast
import operator

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Literal


# ============================================================
# Simple tools (1 param)
# ============================================================
@tool
def get_weather(city: str) -> dict:
    """获取某城市天气. 输入城市名 (中文或英文), 返回 dict with temp_c + condition.

    Args:
        city: 城市名, e.g. "北京" / "Beijing"

    Returns:
        {"city": str, "temp_c": int, "condition": str}
    """
    # Mock data — 真实场景调 openweather / 和风 API
    return {"city": city, "temp_c": 22, "condition": "sunny"}


@tool
def calculator(expression: str) -> str:
    """安全计算数学表达式 (AST 解析, 不用 eval).

    Args:
        expression: e.g. "123 * 456" or "(1 + 2) * 3"

    Returns:
        计算结果字符串, e.g. "56088"
    """
    # AST 安全求值 — 不调 eval,避免任意代码执行
    bin_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }
    un_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in bin_ops:
            return bin_ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in un_ops:
            return un_ops[type(node.op)](_eval(node.operand))
        raise ValueError(f"unsupported node: {type(node).__name__}")

    tree = ast.parse(expression, mode="eval")
    return str(_eval(tree.body))


# ============================================================
# Complex tools (nested schema)
# ============================================================
class SearchQuery(BaseModel):
    """搜索参数."""

    query: str = Field(description="搜索关键词")
    max_results: int = Field(default=5, description="最多返回数, 1-20", ge=1, le=20)
    language: Literal["zh", "en"] = Field(default="en", description="结果语言")


class SearchResult(BaseModel):
    """单条搜索结果."""

    title: str
    snippet: str
    url: str


@tool("web_search", args_schema=SearchQuery)
def web_search(query: str, max_results: int = 5, language: str = "en") -> list[dict]:
    """Web 搜索 (mock). 输入 query + max_results + language, 返回搜索结果列表.

    Args:
        query: 搜索关键词
        max_results: 最多返回数 (1-20)
        language: "zh" 或 "en"

    Returns:
        list of {title, snippet, url}
    """
    # Mock: echo back
    return [
        {
            "title": f"Result {i + 1} for {query}",
            "snippet": f"Snippet about {query} in {language}",
            "url": f"https://example.com/{i + 1}",
        }
        for i in range(min(max_results, 20))
    ]


class DBQuery(BaseModel):
    """DB 查询参数."""

    table: Literal["users", "orders", "products"] = Field(description="目标表")
    where: dict | None = Field(default=None, description="WHERE 条件, e.g. {'id': 123}")
    limit: int = Field(default=100, ge=1, le=1000, description="行数限制 (1-1000)")


@tool("db_query", args_schema=DBQuery)
def db_query(table: str, where: dict | None = None, limit: int = 100) -> list[dict]:
    """查询 MySQL 表 (mock). 返回 rows.

    Args:
        table: users / orders / products
        where: 过滤条件 dict, e.g. {"id": 123}
        limit: 行数限制 (1-1000)

    Returns:
        list of row dicts
    """
    # Mock data — 真实场景调 SQLAlchemy / pymysql
    return [{"id": i, "name": f"row_{i}", "table": table} for i in range(min(limit, 5))]


# ============================================================
# Sensitive tools (HITL required)
# ============================================================
@tool
def write_note(content: str) -> str:
    """写一条笔记 (sensitive — 需 HITL approval).

    Args:
        content: 笔记内容

    Returns:
        "saved: <preview>" 或 "rejected by user"
    """
    # Demo 不真写, mock — 真实场景写 SQLite / 文件 / 笔记服务
    return f"saved: {content[:50]}"


class RefundRequest(BaseModel):
    """退款请求."""

    order_id: int = Field(description="订单 ID")
    amount_cents: int = Field(ge=1, le=100000, description="退款金额 (分, 1-100000)")
    reason: str = Field(description="退款原因")


@tool("refund", args_schema=RefundRequest)
def refund(order_id: int, amount_cents: int, reason: str) -> dict:
    """发起退款 (sensitive — 需 HITL approval).

    Args:
        order_id: 订单 ID
        amount_cents: 退款金额 (分, 1-100000)
        reason: 退款原因

    Returns:
        {"status": "approved" | "rejected", "order_id": int, "amount": int}
    """
    # Mock: 默认 approved — 实际配 HITL 时由人审批
    return {"status": "approved", "order_id": order_id, "amount": amount_cents}


__all__ = [
    "get_weather",
    "calculator",
    "web_search",
    "db_query",
    "write_note",
    "refund",
    "SearchQuery",
    "DBQuery",
    "RefundRequest",
]