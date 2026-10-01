"""tools.py — 6 个 mock 工具,4 个 specialist 各自挂一批.

工具清单:
  weather    : get_weather
  calc       : calc  (AST 安全求值,禁止 __import__)
  notes      : read_note, write_note  (write_note 触发 HITL)
  orders     : get_order, refund_order (refund_order 触发 HITL)

安全:
  - calc 用 ast.parse + 白名单节点,禁止 Name/Call/Attribute (避免 __import__/open)
  - read_note/write_note 的 name 限制 [a-z0-9_]+,防路径穿越
  - refund_order 金额 > 10000 拒绝 (业务规则)
"""
from __future__ import annotations

import ast
import concurrent.futures
import operator
import re
from langchain_core.tools import tool

# ============================================================
# Mock 数据 — 内存 dict,够 demo 用
# ============================================================
_NOTES: dict[str, str] = {
    "todo": "买牛奶, 取快递, 交水电费",
}
_ORDERS: dict[str, dict] = {
    "#123": {"item": "LangChain 课程", "amount": 199.0, "status": "已付款"},
    "#456": {"item": "LangGraph 课程", "amount": 299.0, "status": "已发货"},
}


def _norm_order_id(order_id: str) -> str:
    """订单号兼容: '123' / '#123' 都规范化成 '#123'.

    LLM 经常把 '#123' 解析成 '123' (丢了 #), 让 demo 用起来更友好.
    """
    s = order_id.strip()
    return s if s.startswith("#") else f"#{s}"


# ============================================================
# Weather — 无 HITL
# ============================================================
@tool
def get_weather(city: str) -> str:
    """(mock) 查天气. city 是城市名."""
    return f"{city} 晴 25°C, 微风"


# ============================================================
# Calc — AST 安全求值
# ============================================================
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_EXP = 10_000  # 幂运算指数上限, 防 9**9**9 这种 DoS


@tool
def calc(expr: str) -> str:
    """(mock) 计算数学表达式, 仅支持 +-*/%** 和数字/括号.

    e.g. calc("2 + 3 * 4") -> "14"
    1s 超时保护 (防 9**9**9 这种 DoS).
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"语法错误: {e}"
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_eval_node, tree.body)
            try:
                result = future.result(timeout=1.0)
            except concurrent.futures.TimeoutError:
                return "计算超时: 表达式过于复杂 (>1s), 已中止"
    except _UnsafeNode as e:
        return f"非法表达式: {e}"
    except Exception as e:
        return f"计算错误: {e}"
    return str(result)


def _eval_node(node: ast.AST) -> float | int:
    """递归求值, 只允许 Constant/BinOp/UnaryOp/Expression."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _UnsafeNode(f"常量类型 {type(value).__name__} 不允许")
        return value
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise _UnsafeNode(f"运算符 {type(node.op).__name__} 不允许")
        right = _eval_node(node.right)
        # 幂运算指数上限, 在算 left**right 之前先检查 right
        # (left**right 是 C-level 紧循环, GIL 不释放, ThreadPoolExecutor timeout 也救不了)
        if op is operator.pow and isinstance(right, int) and abs(right) > _MAX_EXP:
            raise _UnsafeNode(f"幂运算指数过大: {right} (>{_MAX_EXP})")
        left = _eval_node(node.left)
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise _UnsafeNode(f"一元运算符 {type(node.op).__name__} 不允许")
        return op(_eval_node(node.operand))
    raise _UnsafeNode(f"节点 {type(node).__name__} 不允许 (禁止 Name/Call/Attribute)")


class _UnsafeNode(Exception):
    """AST 求值时遇到不允许的节点."""


# ============================================================
# Notes — write 触发 HITL
# ============================================================
_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


@tool
def read_note(name: str) -> str:
    """(mock) 读笔记. name 必须是 [a-z0-9_]+."""
    if not _NAME_RE.match(name):
        return f"name 非法: {name!r}, 只允许小写字母数字下划线"
    return _NOTES.get(name, f"(笔记 {name!r} 不存在)")


@tool
def write_note(name: str, content: str) -> str:
    """(mock) 写笔记. name 必须是 [a-z0-9_]+. ⚠️ 触发 HITL 审批."""
    if not _NAME_RE.match(name):
        return f"name 非法: {name!r}"
    _NOTES[name] = content
    return f"笔记 {name!r} 已写入 ({len(content)} 字符)"


# ============================================================
# Orders — refund 触发 HITL
# ============================================================
@tool
def get_order(order_id: str) -> str:
    """(mock) 查订单详情. 订单号 '123' / '#123' 都接受."""
    oid = _norm_order_id(order_id)
    info = _ORDERS.get(oid)
    if info is None:
        return f"订单 {order_id} 不存在 (demo 内置 #123 / #456)"
    return f"订单 {oid}: {info['item']}, 金额 {info['amount']} 元, 状态 {info['status']}"


@tool
def refund_order(order_id: str, amount: float) -> str:
    """(mock) 给订单退款. ⚠️ 触发 HITL 审批. 金额 > 10000 业务拒绝."""
    if amount > 10000:
        return f"退款失败: 金额 {amount} 超过业务上限 10000"
    oid = _norm_order_id(order_id)
    info = _ORDERS.get(oid)
    if info is None:
        return f"订单 {order_id} 不存在 (demo 内置 #123 / #456)"
    return f"订单 {oid} 已退款 {amount} 元 (原金额 {info['amount']} 元)"
