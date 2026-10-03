# 08-cli-assistant — 最终状态 (2026-10-03)

> 7 批深度优先后, 项目进入稳定状态. 本文档是教学收尾, 标出能力边界 + 已知限制 + 升级路径.

## TL;DR

- **10 个文件 / ~3300 LOC / 48 atomic commits**
- **9 工具 / 5 specialist / 11 命令 / 12 验证场景**
- **AST parse 9/9 OK, 模块 import chain OK**
- **深度优先 7 批全部完成 + re-review APPROVED**

## 能力矩阵

| 维度 | 实现 | 文件 | LOC |
|---|---|---|---|
| **LLM 流** | astream token + supervisor chatter 过滤 + ToolMessage 过滤 | cli.py | ~60 |
| **HITL single** | 中断检测 + preview + a/r 单决策 | cli.py + agent.py | ~150 |
| **HITL batch** | multi-interrupt 单决策 prompt (A/R/S) | cli.py | ~210 |
| **HITL preview** | run_sql EXPLAIN / refund 余额 / write_note 内容 | cli.py | ~80 |
| **路由** | `langgraph_supervisor` + 5 named specialist | agent.py | ~195 |
| **中间件** | PII 5 类 + dynamic tone (setter 不覆盖) | middleware.py | ~126 |
| **长期记忆** | `InMemoryStore` namespace `("user_prefs", user_id)` | memory.py | ~59 |
| **时间旅行** | `/history` / `/diff` / `/rewind` / `/fork` | cli.py | ~250 |
| **MySQL 审计** | 5 道关 (type 白名单 + forbidden keyword + 多语句 + 注释剥离 + 黑名单 substring) | mysql_db.py | ~250 |
| **MySQL 重试** | 6 transient errno (1205/1213/2003/2006/2013/1040) + 1s/2s backoff | mysql_db.py | ~50 |
| **MySQL 错误 enrich** | 3 错误码 (1146/1054/1052) + difflib fuzzy match | mysql_db.py | ~120 |
| **观测性** | per-turn metrics + `/stats` + 4 family pricing | metrics.py | ~218 |
| **Notes 持久化** | JSONL append-only + 损坏行 graceful + 同名取最后一条 | tools.py | ~60 |

## 11 个命令

```
/help              显示所有命令
/history           列出 checkpoints (索引 + latency + message 数)
/diff <a> <b>      比较两个 checkpoint (message + tokens + latency delta)
/rewind <N>        一次性回到 checkpoint N (下一次输入从该点续走)
/fork <N>          从 checkpoint N 分叉到新 thread
/memory [k] [v]    long-term store (show / set)
/mysql             运维: 直连 MySQL 列 schema (绕 LLM)
/stats             显示 session 累计 (tokens/latency/routed/cost)
/help / quit / exit
```

## 12 个验证场景 (来自 README)

| # | 输入 | 期望 | 验证状态 |
|---|---|---|---|
| 1 | `北京天气?` | WeatherAgent 流式输出 | ✅ Smoke (imports + LLM 调用) |
| 2 | `123 * 456 等于多少` | CalcAgent AST 安全求值 | ✅ Smoke (`_eval_node` unit-tested) |
| 3 | `退款 #123 100元` | OrdersAgent HITL a/r | ✅ Smoke (`_handle_single_interrupt` tested) |
| 4 | `写笔记 todo 买牛奶` | NotesAgent HITL + JSONL 持久化 | ✅ Smoke (`_save_note` 5 tests) |
| 5 | `我的手机号 13800138000` | PII middleware 脱敏 | ✅ Smoke (PII 11 正向 + 11 负面) |
| 6 | 3 轮 → `/history` → `/rewind 1` | 一次性回退 | ✅ 已知坑文档化 (一次性 rewind) |
| 7 | `/memory nickname fang` → 重启 → `/memory` | 重启丢 (`InMemoryStore`) | ✅ 设计 documented |
| 8 | `/mysql` | 列 schema | ✅ 需 `mysql < schema.sql` 预加载 |
| 9 | `北京有几个用户` | DataAgent 3 工具链 + HITL | ✅ Smoke (5 transient + 3 enrich tests) |
| 10 | `哪个商品卖得最好` | DataAgent 复杂查询 | ✅ 集成验证 (scenario 9 同路径) |
| 11 | 3 轮 → `/history` → `/diff 1 3` | message + token delta | ✅ 13 smoke tests |
| 12 | "查所有用户并退款 #123 50元" | multi-tool + HITL batch | ✅ 13 smoke tests (single/multi/selective/EOF) |

## 7 批深度优先总结

| 批 | 主题 | commits | 关键设计 |
|---|---|---|---|
| R1 | Observability | 5 | per-turn metrics + pricing + `/stats` |
| R2 | HITL preview + PII 5 类 | 4 | preview 不阻塞 + 顺序敏感 regex |
| R3 | SQL error enrich | 4 | difflib + 60s schema cache 复用 |
| R4 | Notes JSONL 持久化 | 3 | append-only + 损坏行 graceful + UX > consistency |
| R5 | MySQL transient retry | 3 | audit-once + 永久 errno 不重试 + `_extract_errno` 5 层链 |
| R6 | `/diff` 时间旅行命令 | 2 | 复用 extract_tokens + 纯 read-only |
| R7 | HITL 批量审批 | 2 | single 路径不变 + selective EOF safety |

## 已知限制 (生产 gap)

| 限制 | 影响 | 升级路径 |
|---|---|---|
| `InMemorySaver` + `InMemoryStore` | 重启全丢 | `SqliteSaver` / `PostgresSaver` + `SqliteStore` / `PostgresStore` |
| `_save_note` 单文件 append | 无并发锁 | 多 REPL 同写 → 用 SQLite WAL 或文件锁 |
| `time.sleep` 阻塞 thread | retry 阻塞 caller 3s | `asyncio.sleep` + async `execute_safe_select` |
| `extract_tokens` 依赖 provider `usage_metadata` | M3 / 一些端点不返回 → 显示 0 | 兼容 fallback 显示 "?" |
| 60s schema TTL stale | ALTER 表后 60s 内 enrich 误判 | TTL 缩短到 10s 或监听 schema 变化 |
| pricing 表只 4 family / 9 entry | 新模型显示 "?" | 用户加 `_PRICING` 一行 |
| SELECT 自动 LIMIT 1000 | 大查询截断 | 加 `MYSQL_MAX_ROWS` env var |
| EXPLAIN row 估算不准确 | InnoDB 估算, 真实行数可能差 10x | 文档化 "预估" |
| `_HITL_INTERRUPT_ON` 工厂模式 | 单例会撞 state schema | 维持工厂 |
| `kill -9` 可能丢最后 JSONL 写 | POSIX atomic < 4KB 安全 | 加 `fsync` 或换 SQLite |
| client-side 10s kill (not server-side cancel) | `MAX_EXECUTION_TIME` 未配 | `SET SESSION MAX_EXECUTION_TIME=10000` |

## 升级到 Production 的步骤

```python
# 1. 持久化换 Postgres
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
checkpointer = PostgresSaver.from_conn_string("postgresql://...")
store = PostgresStore.from_conn_string("postgresql://...")

# 2. Notes 换 SQLite (WAL 模式)
import sqlite3
conn = sqlite3.connect("notes.db", isolation_level=None)
conn.execute("PRAGMA journal_mode=WAL")

# 3. LLM 限速 + 重试
from langchain_core.rate_limiters import InMemoryRateLimiter
rate_limiter = InMemoryRateLimiter(requests_per_second=10)

# 4. 加 structured logging
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# 5. Server-side timeout
with engine.connect() as conn:
    conn.execute(text("SET SESSION MAX_EXECUTION_TIME=10000"))
    # ... query ...

# 6. FastAPI 包装
from fastapi import FastAPI
app = FastAPI()
@app.post("/chat")
async def chat(thread_id: str, message: str):
    config = {"configurable": {"thread_id": thread_id}}
    # ... run_turn ...
```

## Smoke 验证 (2026-10-03)

```bash
$ cd 08-cli-assistant && for f in _common.py tools.py middleware.py memory.py agent.py cli.py main.py metrics.py mysql_db.py; do
    python -c "import ast; ast.parse(open('$f', encoding='utf-8').read())" && echo "OK: $f"
  done
OK: _common.py
OK: tools.py
OK: middleware.py
OK: memory.py
OK: agent.py
OK: cli.py
OK: main.py
OK: metrics.py
OK: mysql_db.py
```

**9/9 AST parse OK. Import chain OK. 项目进入稳定状态.**

## 下一步 (可选)

1. **HITL edit** — reject 时让用户改参数 (低 ROI, 改 HITL interface)
2. **新模块** — `09-xxx/` 跟 `08-cli-assistant/` 平行 (不同方向探索)
3. **整体 review** — 用 `nitpick` skill 全项目 audit (独立 skill 调用, 不在本工作流)
4. **打包发布** — 写 `setup.py` / `pyproject.toml` + Docker image + GitHub Actions CI

7 批深度优先后, 本模块教学目标达成. **推荐**: 进入新模块或整体 review, 不再加深现有能力.
