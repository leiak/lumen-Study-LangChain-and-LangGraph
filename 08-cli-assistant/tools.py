"""tools.py — 6 个 mock 工具,4 个 specialist 各自挂一批.

工具清单:
  weather    : get_weather
  calc       : calc  (AST 安全求值,禁止 __import__)
  notes      : read_note, write_note  (write_note 触发 HITL)
  orders     : get_order, refund_order (refund_order 触发 HITL)
  mysql      : list_tables, describe_table, run_sql (run_sql 触发 HITL)

安全:
  - calc 用 ast.parse + 白名单节点,禁止 Name/Call/Attribute (避免 __import__/open)
  - read_note/write_note 的 name 限制 [a-z0-9_]+,防路径穿越
  - refund_order 金额 > 10000 拒绝 (业务规则)
  - run_sql 用 sqlparse + 白名单 statement type (SELECT/SHOW/...) + 自动 LIMIT 1000

Notes 持久化 (JSONL):
  - 数据文件: 08-cli-assistant/data/notes.jsonl (相对 tools.py)
  - 格式: 每行 {"name": ..., "content": ..., "updated_at": ISO 时间戳}
  - 启动加载: 模块 import 时 _load_notes() 读所有行, 同名取最后一条 (按文件顺序)
  - 写入: write_note approve 后 append 一行 (失败不抛错, 内存已生效, 仅本条不持久化)
  - 损坏行: JSON 解析失败 / KeyError 跳过该行, 不影响其它记录加载
"""
from __future__ import annotations

import ast
import concurrent.futures
import json
import operator
import re
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

# ============================================================
# 数据目录 — 跟 tools.py 同级的 data/ (运行时数据, .gitignore 排除)
# ============================================================
_DATA_DIR = Path(__file__).parent / "data"
_NOTES_FILE = _DATA_DIR / "notes.jsonl"


# ============================================================
# Mock 数据 — Notes 启动加载 JSONL, 其它内存 dict 够 demo 用
# ============================================================
def _load_notes() -> dict[str, str]:
    """模块加载时从 JSONL 读所有笔记.

    JSONL 格式: 每行 {"name": ..., "content": ..., "updated_at": ...}.
    同名多条取最后一条 (按文件顺序, 即最新的覆盖 — 跟 git diff 类比,
    "最后写入者赢").
    单行 JSON 坏就跳过 — 一个坏行不 kill 整个加载 (REPL 还能起).

    Returns:
        dict[name, content]. 文件不存在 → 返回默认 seed.
    """
    if not _NOTES_FILE.exists():
        return {"todo": "买牛奶, 取快递, 交水电费"}

    notes: dict[str, str] = {}
    try:
        with open(_NOTES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # KeyError 也跳 (record 缺字段, 跳过)
                    notes[rec["name"]] = rec["content"]
                except (json.JSONDecodeError, KeyError):
                    # 损坏行 / 缺字段: 不让一个坏记录 kill 整个加载
                    continue
    except OSError:
        # 文件读不到: 退到默认 seed
        return {"todo": "买牛奶, 取快递, 交水电费"}
    return notes


_NOTES: dict[str, str] = _load_notes()


def _save_note(name: str, content: str) -> None:
    """追加一条记录到 notes.jsonl. 写入失败不抛错 (defensive).

    ⚠️ 故意不 raise: 用户已经 HITL approve 了, 写盘失败不应该让 user 觉得
    操作失败. _NOTES 内存 dict 已更新 (UI 立刻生效), 磁盘持久化失败最多
    下次重启丢这条. UX 优先于一致性.
    """
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        rec = {
            "name": name,
            "content": content,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(_NOTES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        # 写盘失败: 静默吞掉 (defensive). 用户无感, 下次重启仅丢这条.
        pass
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
    """(mock) 写笔记. name 必须是 [a-z0-9_]+. ⚠️ 触发 HITL 审批.

    持久化: approve 后写入 08-cli-assistant/data/notes.jsonl, REPL 重启后仍可读.
    同名重复允许 — JSONL 多条都保留, 加载时取最后一条 (自然 history 效果).
    """
    if not _NAME_RE.match(name):
        return f"name 非法: {name!r}"
    _NOTES[name] = content  # 内存立即生效 (UI 可见)
    _save_note(name, content)  # 持久化 (失败不抛错, 见 _save_note docstring)
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


# ============================================================
# MySQL — run_sql 触发 HITL
# ============================================================
# I4: 真正 lazy import — mysql_db 在 .env 没配 MySQL 时也能 import tools.py
# (mysql_db 顶层 import 都 OK, 但 build_engine() 在缺 env 时 raise RuntimeError).
# 把 from mysql_db import ... 挪进函数, 让 tools.py 即使 mysql_db 有任何
# import-time 错误也能干净加载.


@tool
def list_tables() -> str:
    """(mysql) 列出数据库所有表名.

    复用 mysql_db.get_schema_summary (SHOW TABLES + 60s 模块级缓存), 避免直接查
    information_schema.tables.table_rows — 那个 column 在某些 MySQL 版本 / 配置 /
    列权限下不返回, 会 NoSuchColumnError. SHOW TABLES 跨版本都稳.

    返回格式: '数据库表:\n  - users\n  - orders'
    """
    from mysql_db import build_engine, get_schema_summary  # 真正 lazy
    try:
        engine = build_engine()
        tables, _ = get_schema_summary(engine)
    except RuntimeError as e:
        return f"(MySQL 未配置: {e})"
    if not tables:
        return "(数据库没有表, 或者连接失败 — 检查 .env)"
    return "数据库表:\n" + "\n".join(f"  - {t}" for t in tables)


@tool
def describe_table(table_name: str) -> str:
    """(mysql) describe 表结构: 列名 + 类型 + 注释. 写 SQL 前先 describe 一下看字段.

    table_name 不带引号 (e.g. 'users', 不是 '`users`').
    返回格式: 'users 表结构:\\n  id: int NOT NULL PRI ...'
    """
    from mysql_db import build_engine, get_schema_summary  # 真正 lazy
    try:
        engine = build_engine()
        _, describe = get_schema_summary(engine)
    except RuntimeError as e:
        return f"(MySQL 未配置: {e})"
    if table_name not in describe:
        available = list(describe.keys())
        return f"表 {table_name!r} 不存在. 可用表: {available}"
    return describe[table_name]


@tool
def run_sql(query: str) -> str:
    """(mysql) 执行 SELECT/SHOW/DESCRIBE/EXPLAIN/WITH 查询, 返回格式化 markdown 表格.

    ⚠️ 触发 HITL 审批 — execute 前会先弹窗让用户确认.

    安全审计 (mysql_db._audit_sql):
      - 只允许 SELECT/SHOW/DESCRIBE/EXPLAIN/WITH (statement type 白名单)
      - 拒绝 INSERT/UPDATE/DELETE/DROP/TRUNCATE/GRANT 等写操作 (含 WITH+INSERT 绕过)
      - 拒绝多语句 (; 后面有内容)
      - 拒绝 INTO OUTFILE / LOAD DATA / LOAD_FILE / INFORMATION_SCHEMA
      - 拒绝注释注入 (-- / # / /* */) — 先 strip 再审计
      - 自动 LIMIT 1000 (防 OOM)
      - 10s 查询超时 (ThreadPoolExecutor client-side kill)

    Transient retry (mysql_db._TRANSIENT_MYSQL_CODES):
      - 自动重试 3 次 (initial + 2 retries), backoff 1s/2s (max 3s 等待)
      - 仅对 lock / 连接类 errno 重试:
        1205 Lock wait timeout · 1213 Deadlock ·
        2003 Can't connect host · 2006 Server gone away · 2013 Lost connection ·
        1040 Too many connections
      - 永久 SQL 错 (1146/1054/1052/1064/1364) 不重试 — 失败是确定的
      - audit 拒绝 (ValueError) 不重试 — 永久
      - 查询超时 (ThreadPoolExecutor TimeoutError) 不重试 — 下次大概率还慢
      - 3 次仍失败: raise 给 _enrich_error 兜底 (LLM 拿到 enriched 错误)

    错误处理:
      - MySQL 未配置: 友好提示 (RuntimeError)
      - audit 拒绝: 转 [安全审计拒绝] 给 LLM (ValueError)
      - SQL 执行错: 走 mysql_db._enrich_error 加 hint (表/列模糊匹配),
        LLM 拿到 enriched 错误能 self-correct, 不用 user 介入

    返回: markdown 表格 (前 50 行 + 行数统计) 或 [安全审计拒绝] / [SQL 执行失败] 错误.
    """
    from mysql_db import build_engine, execute_safe_select, _enrich_error  # 真正 lazy
    try:
        engine = build_engine()
        result_text, _ = execute_safe_select(engine, query)
    except RuntimeError as e:
        return f"(MySQL 未配置: {e})"
    except ValueError as e:
        # _audit_sql 拒绝: 转成 ToolMessage 给 LLM 看 (LLM 会改 SQL 重试)
        return f"[安全审计拒绝] {e}"
    except Exception as e:
        # SQL 语法错 / 表不存在 / 连接断: enrich 一下让 LLM 能 self-correct
        try:
            enriched = _enrich_error(engine, e)
            return f"[SQL 执行失败] {enriched}"
        except Exception:
            # enrich 自己失败 (defensive — _enrich_error 设计上不 raise, 但兜底):
            # 透传原始错误
            return f"[SQL 执行失败] {type(e).__name__}: {e}"
    return result_text
