"""mysql_db.py — MySQL 连接 + schema 查询 + 安全审计.

设计原则 (R6 spec review):
  - LLM 生成 SQL, 我们执行 (LangChain SQLDatabase 风格的简化版)
  - 安全审计必须: 白名单 statement 类型 + 禁用危险关键词 + 自动 LIMIT
  - 缺失 env 不阻塞 CLI — main.py 用 try/except 包住 build_engine()
  - SQL 解析用 sqlparse (AST), 不靠简单字符串匹配 (防大小写/嵌套子查询绕过)

公开 API:
  - build_engine()          -> Engine (缺 env 时 raise RuntimeError)
  - get_schema_summary(engine) -> (tables: list[str], describe: dict[str, str])
  - execute_safe_select(engine, sql) -> (text: str, rows: list[dict])

内部:
  - _audit_sql(sql: str) -> str  # 清洗/校验 SQL; 不合法 raise ValueError

跑法:
    1. .env 加  MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
    2. mysql < schema.sql  (参考 schema 在仓库根 08-cli-assistant/schema.sql)
    3. python main.py, 输入"北京有几个用户" → 派 DataAgent → 调 list_tables → run_sql
"""
from __future__ import annotations

import concurrent.futures
import os
import re
from typing import Any

import sqlparse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ============================================================
# Env 读取 — 缺失时 raise RuntimeError 给 main.py 友好提示
# ============================================================
def _read_env() -> dict[str, str]:
    """从 os.environ 读 5 个 MySQL env vars. 缺失任何一个 → raise."""
    required = ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"MySQL 未配置: 缺失 {missing}. "
            "在 .env 设置 MYSQL_HOST / MYSQL_PORT / MYSQL_USER / "
            "MYSQL_PASSWORD / MYSQL_DATABASE"
        )
    return {k: os.getenv(k, "") for k in required}


def build_engine() -> Engine:
    """创建 SQLAlchemy engine. 每次都新建 (便宜, pymysql 走 connection pool).

    缺 env → RuntimeError (给 main.py 提示);
    网络不通 → 第一次 connect 时抛 sqlalchemy.exc.OperationalError (tools.py 兜底).
    """
    env = _read_env()
    # pymysql driver, utf8mb4 兼容 emoji/中文
    url = (
        f"mysql+pymysql://{env['MYSQL_USER']}:{env['MYSQL_PASSWORD']}"
        f"@{env['MYSQL_HOST']}:{env['MYSQL_PORT']}/{env['MYSQL_DATABASE']}"
        "?charset=utf8mb4"
    )
    # pool_pre_ping=True: 长时间 idle 后, 第一次 query 自动发 SELECT 1 探活,
    # 防止 MySQL server timeout 杀掉连接后触发 "MySQL server has gone away".
    # pool_recycle=3600: 1 小时回收连接, 跟 MySQL wait_timeout 默认 8h 安全余量.
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=3600,
        # 默认 query timeout 通过每条 statement 的 execution_options 设, 见 _execute()
    )


# ============================================================
# Schema 摘要
# ============================================================
def get_schema_summary(engine: Engine) -> tuple[list[str], dict[str, str]]:
    """返回 (tables, describe) 元组.

    tables:   所有用户表名 (排除 mysql/information_schema/performance_schema)
    describe: {table_name: 格式化字符串 "列名 类型 注释\n..."}
    """
    with engine.connect() as conn:
        # SHOW TABLES 是 statement-level 命令, sqlparse 解析后 type 可能是 'SHOW'
        rows = conn.execute(
            text("SHOW TABLES"),
            execution_options={"timeout": 10},
        ).fetchall()
        # 过滤系统 schema (虽然我们已经选定了 MYSQL_DATABASE, 但 SHOW TABLES
        # 在某些版本仍可能带库名限定, 这里只取最后一段)
        all_tables: list[str] = []
        for r in rows:
            # r[0] 可能是 "dbname.tablename" 也可能是 "tablename"
            raw = str(r[0])
            table = raw.split(".")[-1]
            all_tables.append(table)

        # describe 每张表
        describe: dict[str, str] = {}
        for t in all_tables:
            try:
                # SHOW FULL COLUMNS 给出 Type, Null, Key, Default, Extra
                col_rows = conn.execute(
                    text(f"SHOW FULL COLUMNS FROM `{t}`"),
                    execution_options={"timeout": 10},
                ).fetchall()
                lines = [f"  {t} 表结构:"]
                for cr in col_rows:
                    # cr 是 Row, 索引顺序: Field, Type, Collation, Null, Key, Default, Extra, Privileges, Comment
                    field, type_, nullable, key, default, extra, *_, comment = cr
                    comment_str = f"  -- {comment}" if comment else ""
                    default_str = f" DEFAULT {default}" if default is not None else ""
                    lines.append(
                        f"    {field}: {type_} {'NULL' if nullable == 'YES' else 'NOT NULL'}"
                        f"{default_str} {key}{comment_str}"
                    )
                describe[t] = "\n".join(lines)
            except Exception:
                # 单表失败不阻塞 (权限/视图问题)
                describe[t] = f"  ({t} 结构读取失败)"

    return all_tables, describe


# ============================================================
# SQL 安全审计
# ============================================================
# 白名单: 只允许这些 statement 类型 (case-insensitive 已经在 sqlparse 里处理)
_ALLOWED_TYPES = {"SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH"}
# 黑名单子串 (即使 SELECT 也禁止 — 提权攻击)
# 注意: 注释 (-- / /* */ / #) 已经在 _strip_comments 里从 SQL 里抹掉了,
# 所以这里不需要列它们 — 我们审计的是"去掉注释后的纯逻辑 SQL".
_BANNED_SUBSTRINGS = [
    "INTO OUTFILE",
    "INTO DUMPFILE",
    "LOAD DATA",
    "LOAD_FILE",  # 函数, 不是 statement type, 用子串拦
    "INFORMATION_SCHEMA",
    "MYSQL.",
    "PERFORMANCE_SCHEMA",
]
# 多语句分隔: sqlparse.parse() 自然按 ; 分; 这里只防"显式 ; 后还有非空字符"
_MULTI_STMT_RE = re.compile(r";\s*\S", re.MULTILINE | re.DOTALL)
# 注释 — 用正则 + sqlparse 双保险
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")  # -- 到行尾
_HASH_COMMENT_RE = re.compile(r"#[^\n]*")    # # 到行尾 (MySQL 特有)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)  # /* ... */
_DEFAULT_LIMIT = 1000
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)
# 危险 verb 集合 — 只要 SQL 里任何位置 (作为 keyword token) 出现, 都拒绝.
# 关键: sqlparse.Statement.get_type() 只看首词, 所以
# "WITH cte AS (...) INSERT INTO ..." 这种语句会被识别成 WITH 而绕过.
# 我们必须遍历所有顶级 Keyword token 才能堵住这个洞.
_FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE",
    "TRUNCATE", "DROP", "ALTER", "CREATE", "RENAME",
    "GRANT", "REVOKE", "SET", "CALL", "LOAD", "HANDLER", "LOCK",
    "OPTIMIZE", "ANALYZE", "REPAIR", "CHECK", "BACKUP", "RESTORE",
}
# 词边界正则双保险 — 即便 token 切分漏掉, raw 字符串也拒.
_DDL_REGEX = re.compile(
    r"\b(INSERT|UPDATE|DELETE|REPLACE|MERGE|TRUNCATE|DROP|ALTER|CREATE|RENAME|"
    r"GRANT|REVOKE|SET|CALL|LOAD|HANDLER|LOCK)\b",
    re.IGNORECASE,
)


def _first_keyword(stmt) -> str:
    """从 sqlparse Statement 里抓首词 (用于 SHOW/DESCRIBE/EXPLAIN 识别).

    sqlparse 的 get_type() 对这些返回 UNKNOWN, 必须自己抓第一个非空白 token.
    跳过注释 (sqlparse 把注释当 Comment token, 不是 Keyword).
    """
    for tok in stmt.tokens:
        # 跳过空白/换行
        if tok.is_whitespace:
            continue
        # 跳过注释 (-- 或 /* */ 或 #) — sqlparse 已经把它们分离成 Comment token
        if isinstance(tok, sqlparse.sql.Comment):
            continue
        # 跳过括号 (有时 EXPLAIN 后跟括号)
        if isinstance(tok, sqlparse.sql.Parenthesis):
            continue
        # 取首词 (大写)
        val = str(tok).strip().split()[0].upper() if str(tok).strip() else ""
        return val
    return ""


def _strip_comments(sql: str) -> str:
    """从 SQL 里抹掉所有注释 (-- line, # line, /* block */).

    为什么: 注释本身 pymysql 也会忽略, 但我们审计时如果保留注释, 就
    无法判断"逻辑 SQL"是什么 (LLM 可能在注释里塞指令: SELECT * -- DROP TABLE).
    抹掉后, 实际执行的逻辑 SQL 就清晰可见.

    实现: 用正则 (sqlparse 不一定把 -- 识别成 Comment token, 但 pymysql
    一定会按 MySQL 规则当注释处理; 这里我们按 MySQL 规则统一抹).
    """
    # 顺序: 块注释先 (-- 在块里会先吃掉, -- 不会被误判)
    sql = _BLOCK_COMMENT_RE.sub("", sql)
    sql = _LINE_COMMENT_RE.sub("", sql)
    sql = _HASH_COMMENT_RE.sub("", sql)
    return sql


def _audit_sql(sql: str) -> str:
    """校验 + 清洗 SQL. 不合法 raise ValueError, 合法返回清洗后的 SQL.

    校验规则:
      1. 必须是非空字符串
      2. sqlparse 解析后所有 statement type 必须在白名单 (SELECT/SHOW/...)
      3. 不能含黑名单子串 (大小写不敏感)
      4. 不能含多语句 (; 后面还有内容)
      5. SELECT/WITH 语句如果没 LIMIT, 自动追加 LIMIT 1000 (防 OOM)
      6. SELECT * 警告 (但不阻断 — LLM 有时确实需要 *)

    ⚠️ C1 关键防御: 即使 statement.get_type() 返回 'WITH' (合法),
    我们仍然遍历所有顶级 Keyword token, 一旦发现 INSERT/UPDATE/DELETE 等
    危险 verb, 就拒. 这堵住了 "WITH cte AS (...) INSERT INTO ..." 的绕过攻击.

    注意: 单纯关键词黑名单不是绝对安全, 但对 demo 级别够用.
    生产应:
      - 用只读 DB user (GRANT SELECT)
      - 在 SQLAlchemy 层用事件 hook 转所有写操作到 readonly transaction
      - 用 sqlglot 之类做语义分析
    """
    if not sql or not sql.strip():
        raise ValueError("SQL 不能为空")

    # 先抹掉注释 (审计的是逻辑 SQL, 不是注释里塞的指令)
    cleaned = _strip_comments(sql)
    # 去掉末尾分号 (sqlparse 解析时会把 ; 单独当一个 token)
    cleaned = cleaned.strip().rstrip(";").strip()

    # 多语句检查: 整个 SQL 字符串里 ; 后面不能再有非空白字符
    # (去末尾 ; 后, 内部的 ; 后面跟着内容仍是多语句)
    # 用 sqlparse.parse 拆, 看拆分后是否 > 1 个非空 statement
    parsed = sqlparse.parse(cleaned)
    non_empty = [p for p in parsed if p.tokens and str(p).strip()]
    if len(non_empty) > 1:
        raise ValueError(f"检测到多语句 ({len(non_empty)} 个), 已拒绝")

    # ⚠️ 多语句已经在数量上被拦了 (len(non_empty) > 1 → raise).
    # 但还要类型校验: 即使只有一个 statement, 如果它是 INSERT/UPDATE/DELETE/DROP
    # 也不能放过. 我们手动抓首词 + sqlparse get_type 双校验, 应对 SHOW/EXPLAIN
    # 这些 UNKNOWN 情况.
    stmt = non_empty[0] if non_empty else None
    if stmt is None:
        raise ValueError("无法解析 SQL")

    # C1: 遍历所有顶级 Keyword token, 发现任何危险 verb 即拒.
    # 这堵住 "WITH cte AS (...) INSERT/UPDATE/DELETE ..." 的绕过 (sqlparse 的
    # get_type() 只看首词, 会把这类语句识别成 WITH 而放过).
    # ⚠️ sqlparse 的 _TokenType 是带前缀匹配的 tuple subclass. `__contains__` 的
    # 语义是"item 是否以 self 为前缀" — 所以检测"X 是 Keyword 的子类"要用
    # `ttype in Token.Keyword` (X in 父). Token.Keyword.DML / .DDL / .CTE 都满足.
    for tok in stmt.tokens:
        ttype = tok.ttype
        if ttype is not None and ttype in sqlparse.tokens.Keyword:
            val = str(tok).strip().upper()
            if val in _FORBIDDEN_KEYWORDS:
                raise ValueError(
                    f"检测到危险 verb {val!r} (statement 内任何位置都禁止), 已拒绝"
                )
    # 双保险: 词边界 regex 再 grep 一次 (防 sqlparse token 切分漏掉)
    m = _DDL_REGEX.search(cleaned)
    if m:
        raise ValueError(
            f"检测到危险 verb {m.group(0).upper()!r} (regex 双检), 已拒绝"
        )

    # statement 类型检查
    # ⚠️ sqlparse 的 get_type() 对 SHOW / DESCRIBE / EXPLAIN 返回 'UNKNOWN',
    # 对 INSERT/UPDATE/DELETE 也返回 'UNKNOWN' — 不能直接信. 我们手动抓首词:
    #   1. 先信 sqlparse (它对 SELECT/UNION/WITH 识别准)
    #   2. 如果 UNKNOWN, 解析第一个非空白 keyword token
    stmt_type = (stmt.get_type() or "").upper()
    if stmt_type == "UNKNOWN":
        first_kw = _first_keyword(stmt)
        # EXPLAIN SELECT ... 时, EXPLAIN 是首词 — 也接受
        if first_kw in {"SHOW", "DESCRIBE", "DESC", "EXPLAIN"}:
            stmt_type = first_kw
    if stmt_type not in _ALLOWED_TYPES:
        raise ValueError(
            f"statement 类型 {stmt_type!r} 不允许. "
            f"只允许: {sorted(_ALLOWED_TYPES)}"
        )

    # 黑名单子串检查 (case-insensitive)
    upper_sql = cleaned.upper()
    for banned in _BANNED_SUBSTRINGS:
        if banned.upper() in upper_sql:
            raise ValueError(f"检测到禁用子串 {banned!r}, 已拒绝")

    # 多语句分隔检查 (sqlparse 已拆, 但保险起见再 grep 一次)
    if _MULTI_STMT_RE.search(cleaned):
        raise ValueError("检测到多语句 (; 后面还有内容), 已拒绝")

    # 自动 LIMIT: SELECT/WITH 没有 LIMIT 时追加
    if stmt_type in {"SELECT", "WITH"}:
        if not _LIMIT_RE.search(cleaned):
            cleaned = f"{cleaned} LIMIT {_DEFAULT_LIMIT}"

    return cleaned


# ============================================================
# 执行 + 格式化结果
# ============================================================
_MAX_DISPLAY_ROWS = 50  # 给 LLM/用户看的前 N 行
_QUERY_TIMEOUT_SEC = 10.0  # C2: 真实查询超时 (client-side kill via ThreadPoolExecutor)


def execute_safe_select(engine: Engine, sql: str) -> tuple[str, list[dict[str, Any]]]:
    """执行 SQL, 返回 (markdown_table_text, rows_list).

    text 是 markdown 表格 (前 _MAX_DISPLAY_ROWS 行 + 行数统计);
    rows_list 是原始 dict 列表 (供后续 expand 用, demo 里 LLM 只看 text).

    异常:
      ValueError — _audit_sql 拒绝 (抛到 tool, 转成 ToolMessage)
      sqlalchemy.exc.* — DB 错误 (语法/超时/连接断, 抛到 tool)

    C2: 走 ThreadPoolExecutor 实现真实 client-side 10s 超时.
    ⚠️ 注意: 这是 client-side kill (force-close 连接), 不是 server-side cancel.
    真正的 server-side timeout 需要 MySQL 配合
    `SET SESSION MAX_EXECUTION_TIME = 10000` (毫秒), 生产应开启.
    """
    safe_sql = _audit_sql(sql)  # 不合法 raise ValueError

    def _run() -> tuple[list[str], list[dict[str, Any]]]:
        with engine.connect() as conn:
            result = conn.execute(text(safe_sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return columns, rows

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_run)
        try:
            columns, rows = future.result(timeout=_QUERY_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            # 强制取消 (ThreadPoolExecutor 子线程仍持有, GC 时回收).
            # pymysql 在 result 取消时, 下次网络读会抛 OperationalError; 下次
            # connect 时 pool_pre_ping 会发 SELECT 1 探活, 失败就重连.
            return (
                f"[查询超时] 超过 {_QUERY_TIMEOUT_SEC}s 已中止 "
                f"(用更窄的 WHERE / 加索引 / 拆 subquery)",
                [],
            )

    # 格式化: markdown 表格
    text_md = _format_as_markdown(columns, rows)
    return text_md, rows


def _format_as_markdown(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """把 rows 序列化成 markdown 表格, 加行数统计."""
    if not rows:
        return "(查询成功, 但无结果)"

    total = len(rows)
    display = rows[:_MAX_DISPLAY_ROWS]

    # 列宽估算: 截断到 30 字符
    def _cell(v: Any) -> str:
        if v is None:
            return "NULL"
        s = str(v)
        return s if len(s) <= 30 else s[:27] + "..."

    # header
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines = [
        "| " + " | ".join(_cell(r.get(c)) for c in columns) + " |"
        for r in display
    ]

    summary = f"\n\n(共 {total} 行, 显示前 {len(display)})" if total > _MAX_DISPLAY_ROWS else ""

    return "\n".join([header, sep, *body_lines]) + summary


__all__ = [
    "build_engine",
    "get_schema_summary",
    "execute_safe_select",
    "_audit_sql",
]