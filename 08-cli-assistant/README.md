# 08-cli-assistant — 智能个人助手 CLI

> ✅ Smoke-tested: import chain OK · 9 tools OK · memory prefs OK · async command routing OK · PII redaction OK (5 类: ID / 手机 / 银行卡 / 邮箱 / IPv4) · HITL preview OK (run_sql EXPLAIN / refund 余额 / write_note 内容) · AST parse 8/8 OK · MySQL audit OK (SELECT/INSERT/DROP/UNION/--/*/multi-stmt/LOAD_FILE)

把项目里分散在各 demo 的**高级用法**串成一个真正能跑的端到端 CLI 工具:
streaming token 打印 + HITL 审批 + supervisor 多 agent 路由 + PII middleware
脱敏 + 动态语气 + long-term Store + time-travel rewind / fork + MySQL 智能问数。

不是新概念 — 是把前面 7 个 demo 揉进一个 REPL。

## 学完你能回答 10 个问题

1. 怎么用 `astream(stream_mode="messages")` 实现 token 级流式打印?
2. `HumanInTheLoopMiddleware(interrupt_on={...})` 怎么挂上 HITL, 哪些工具危险?
3. HITL 触发后, CLI 怎么用 stdin 输入决策 (approve / reject) 恢复?
4. `langgraph_supervisor.create_supervisor` 怎么装配多个 named specialist?
5. `@wrap_model_call` 怎么拦截请求, 实现 PII 脱敏 (且不污染原 state)?
6. `@dynamic_prompt` 为什么必须 append 而不是覆盖 (会丢 specialist 角色)?
7. `get_state_history` + `checkpoint_id` 注入怎么实现 time-travel rewind?
8. `update_state` + 新 thread 怎么实现 fork (主对话不被污染)?
9. `InMemoryStore` + namespace 怎么存长期偏好?
10. 怎么把 streaming + HITL + 路由 + Store + rewind 整合到一个 REPL?

## 跑法

```bash
# 1. 项目根 .env 里至少有 1 个 LLM key (自动检测)
cat ../.env
#   ANTHROPIC_API_KEY=...
#   DEEPSEEK_API_KEY=...     (或)
#   MINIMAX_API_KEY=...      (或)
#   OPENAI_API_KEY=...

# 2. 启动
cd 08-cli-assistant
python main.py
```

退出: `/quit` / `/exit` / `Ctrl+C` / EOF。
退出 REPL 后短期对话 (`InMemorySaver`) 和长期偏好 (`InMemoryStore`) 都丢 —
演示用, 生产换 `SqliteStore` / `PostgresStore`。

> ⚠️ Shell 全局 `export ANTHROPIC_API_KEY=xxx` 会让 `.env` 改动失效。
> 临时绕过: `env -u ANTHROPIC_API_KEY python main.py`。

## MySQL 智能问数 (DataAgent, 第 5 个 specialist)

LLM 生成 SQL → 安全审计 → HITL 审批 → 执行 → markdown 表格回显。
中间任何一步出错都不会阻塞其它 4 个 specialist (没配 MySQL 完全 OK)。

### 设置

```bash
# 1. .env 加 5 个 MySQL env vars
cat .env
#   MYSQL_HOST=localhost
#   MYSQL_PORT=3306
#   MYSQL_USER=root
#   MYSQL_PASSWORD=xxx
#   MYSQL_DATABASE=cli_demo

# 2. 加载参考 schema (5 用户 / 6 订单 / 6 明细)
mysql -u root -p < 08-cli-assistant/schema.sql

# 3. (可选) 探测连接 + 列表
python main.py
#   >>> MySQL: connected
#   你> /mysql
#   >>> MySQL 连接成功, 共有 3 张表:
#     [users] ...
#     [orders] ...
#     [order_items] ...
```

### 安全审计 (`mysql_db._audit_sql`)

LLM 生成的 SQL 在执行前过 4 道关:

1. **statement type 白名单** — 只允许 `SELECT / SHOW / DESCRIBE / EXPLAIN / WITH`,
   其它 (INSERT/UPDATE/DELETE/DROP/TRUNCATE/GRANT) → ValueError
3. **黑名单子串** — `INTO OUTFILE / INTO DUMPFILE / LOAD DATA / LOAD_FILE /
   INFORMATION_SCHEMA / MYSQL. / PERFORMANCE_SCHEMA` → ValueError
4. **多语句拦截** — sqlparse 解析后 > 1 个 statement → ValueError
5. **注释先剥离再审计** — `--` / `#` / `/* */` 用正则抹掉 (sqlparse 不一定识别
   `--` 为 Comment token), 防 `SELECT 1 -- ; DROP TABLE` 注入

附加:

- **自动 LIMIT 1000** — SELECT/WITH 没 LIMIT 时自动追加 (用 `_LIMIT_RE` 检测,
  不是简单 substring; 防 `LIMIT 1000000` 之类)
- **10s 超时** — SQLAlchemy `execution_options={"timeout": 10}`
- **markdown 输出** — 表格前 50 行 + 总行数; 列宽 30 字符截断

### HITL 触发

`run_sql` 也挂 HITL — 即使审计通过, 也让用户在终端看到实际 SQL 再 approve。
UX 跟 `refund_order` / `write_note` 一致: `[a]pprove` / `[r]eject` (cli.py `_maybe_hitl`)。

### 已知坑

- **`create_supervisor` 要求 sub-agent 有 `name=`** — 没名字路由不了 (每个
  `create_agent` 必须 `name="DataAgent"` 等)。
- **Pylance type-check warnings on middleware 是 noise, 实际不报错** — VS Code
  Pylance 在 `_hitl()` 调用处报 `Expected type '_AgentMiddleware[StateT]'`,
  实际运行时 middleware 正常工作。这是 LangChain 1.x middleware 装饰器对
  Generic StateT 的 hint 不全, 不是 bug。
- **MySQL 没装 / .env 没配 → 启动不阻塞** — `main.py` 用 try/except 包住
  `build_engine()`, 失败时打印 `>>> MySQL: 未配置 (...)`. 其它 4 个 specialist
  仍能用。

## 7 个手测场景

| # | 输入 | 期望 |
|---|---|---|
| 1 | `北京天气?` | 派给 `WeatherAgent`, streaming token 流式输出 (打字机效果) |
| 2 | `123 * 456 等于多少` | 派给 `CalcAgent`, AST 安全求值 |
| 3 | `退款 #123 100元` | 触发 HITL (OrdersAgent), 输入 `a` 通过 / `r` 拒绝 |
| 4 | `写笔记 todo 买牛奶` | 触发 HITL (NotesAgent), 同上 |
| 5 | `我的手机号 13800138000` | PII middleware 脱敏成 `1XX-XXXX-XXXX` (LLM 看不到原号) |
| 6 | 跑 3 轮对话 → `/history` → `/rewind 1` | 状态回到第 1 轮, 下一次输入从该 checkpoint 续走 (一次性 rewind) |
| 7 | `/memory nickname fang` → `/quit` → 重启 → `/memory` | nickname 默认值 (注: `InMemoryStore` 重启就丢) |
| 8 | `/mysql` (需先 `mysql < schema.sql`) | 列出 users / orders / order_items 三表 + 列结构 |
| 9 | `北京有几个用户` (DataAgent) | 调 `list_tables` → `describe_table users` → `run_sql SELECT COUNT(*) ... WHERE city='北京'`, 触发 HITL 输入 `a` 通过, 返回 `1` |
| 10 | `哪个商品卖得最好` (DataAgent 复杂查询) | 调 `list_tables` → `describe_table order_items` → `run_sql SELECT product, SUM(quantity)... GROUP BY product ORDER BY SUM(quantity) DESC LIMIT 1`, HITL 通过 |

### HITL 决策细节

CLI 只暴露 `[a]pprove` / `[r]eject` 两种 — 没有 `[e]dit`。
原因: LangGraph 协议层仍支持 `["approve","edit","reject"]` 三种, 但 `edit`
常被误按成 `approve`, UX 上直接砍掉。
`r` 之后会追问 "拒绝原因", 拼到 `{"type":"reject","reason":...}` 里回传。

### HITL 影响预览

approve 前 REPL 会先打印"将要发生什么" — 不盲签。

| 工具 | 预览内容 |
|---|---|
| `run_sql` | SQL 全文 + 涉及表 (regex `\bFROM` 提取) + `EXPLAIN` 估算影响行数 + 执行计划摘要 |
| `refund_order` | 订单号 + 当前金额 + 退款金额 + 退款后余额; 金额 > 10000 标 ⚠️ 业务上限 |
| `write_note` | note name + content 预览 (前 50 字符) + 字节数 |

实现 (`cli.py` `_HITL_PREVIEW_FNS`):
- `_preview_run_sql` — `EXPLAIN _audit_sql(sql)` 走 ThreadPoolExecutor 5s 超时 (防 EXPLAIN 自身 hang), audit 保证 EXPLAIN 后面的 SELECT 也走白名单防注入; MySQL 未配置时降级到 `? (MySQL 未配置)` 不抛错
- `_preview_refund_order` — 直接读 `_ORDERS` dict, 不调工具
- `_preview_write_note` — 纯字符串处理, 无外部依赖
- `_format_hitl_preview` — 路由 + try/except 包住, preview 失败只打 `[预览失败]` 一行, 不阻塞决策

⚠️ **EXPLAIN + LIMIT**: `_audit_sql` 会给 SELECT 自动追加 `LIMIT 1000`, 所以
`EXPLAIN SELECT * FROM users` 实际跑的是 `EXPLAIN SELECT * FROM users LIMIT 1000`
(MySQL 完全支持 EXPLAIN + LIMIT, 语法合法)。

### PII 脱敏细节

| PII 类型 | 正则 | 替换 |
|---|---|---|
| 身份证 (18位) | `\b\d{17}[\dXx]\b` | `1XXX-XXXX-XXXX-XXXX-X` |
| 手机号 (11位) | `\b1[3-9]\d{9}\b` | `1XX-XXXX-XXXX` |
| 银行卡 (16-19位纯数字) | `\b\d{16,19}\b` | `XXXX-XXXX-XXXX-XXXX` |
| 邮箱 | `\b[\w.+-]+@[\w-]+\.[\w.-]+\b` | `<email>` |
| IPv4 (4 段 0-255) | `\b(?:25[0-5]\|2[0-4]\d\|[01]?\d?\d)(?:\.(?:25[0-5]\|2[0-4]\d\|[01]?\d?\d)){3}\b` | `x.x.x.x` |

**顺序敏感 (重要!)**: ID → 手机 → 银行卡 → 邮箱 → IPv4.
- 身份证必须先于手机 (ID 里的 11 位子串会被手机 mangled)
- 银行卡必须后于 ID/手机 (ID 的 18 位子串里可能含 16-19 位连续数字段)

**负面用例** (不应被误判):
- `010-12345678` (带连字符, 不是手机)
- `2026-10-02` (有分隔符, 不是卡号/IP)
- `12345.67` (不足 16 位, 不是银行卡)
- `999.999.999.999` (段 > 255, 不匹配 IPv4)

脱敏发生在 wrap_model_call 拦截器内, 用 `model_copy(update={...})` 构造新消息
不污染原 agent state / checkpoint / trace。

### 动态语气细节

`tone_prompt` (`@dynamic_prompt`) 触发条件:

| 用户最近消息含 | 追加 |
|---|---|
| `正式` | `[语气修饰] 用正式语气回答,使用'您'.` |
| `哈哈` / `随便` | `[语气修饰] 用轻松幽默的语气回答,可以用 emoji.` |
| 其它 | (不变) |

**坑**: `@dynamic_prompt` 是 **setter** (装饰器执行 `request.system_prompt = prompt`),
不是 appender。直接返回字符串会覆盖 `create_agent(system_prompt=...)` 里传进去的
specialist 角色 ("你是 WeatherAgent...")。所以必须以 `request.system_prompt` 为
base, 末尾追加语气行。

## 内置命令

| 命令 | 作用 |
|---|---|
| `/help` | 帮助 |
| `/history` | 列出本 thread 所有 checkpoint (history[0]=最新) |
| `/rewind N` | 回到 history[N] 的状态 — **一次性**, 下个 turn 后自动清 |
| `/fork <text>` | 在最新 checkpoint 上追加 text, 用 `update_state` 创建新 thread 续走 |
| `/memory` | 查看长期偏好 (`InMemoryStore` namespace) |
| `/memory <key> <v>` | 设置偏好 (内置: `nickname`/`city`/`language`; 自定义: 必须 `user_xxx` 前缀) |
| `/mysql` | 探测 MySQL 连接 + 列出表结构 (运维视角, 绕过 LLM) |
| `/stats` | Session 累计: turns / tokens / latency / 路由 / cost |
| `/quit`, `/exit` | 退出 REPL |

## Observability (per-turn 指标 + /stats 累计)

每个 turn 完成后, REPL 自动打印一行指标 (latency / tokens / tools / specialist / cost):

```
>>> 280ms · in 124 / out 86 · 1 tools · WeatherAgent · ~$0.0001
```

`/stats` 打印 session 累计:

```
>>> Session 统计 (12 turns):
   tokens:   in 1,420 / out 980  ·  tools 18
   latency:  avg 245ms · max 1.2s
   routed:   Calc 2 · Data 1 · Notes 4 · Orders 2 · Weather 3
   cost:     ~$0.0042 估算 (model: claude-sonnet-5)
```

实现见 `metrics.py` (~216 LOC):
- `TurnMetrics` / `SessionMetrics` dataclass
- `extract_tokens(state)` — 从 final state AIMessages 求和, 按 `message.id` 去重
- `detect_specialist(state)` — 反向遍历找最后一条带 `.name` 的 AIMessage
- `count_tool_calls(state)` — 统计 ToolMessage 数量
- `estimate_cost(model, in, out)` — substring 匹配 pricing 表 (4 个 family: Anthropic/DeepSeek/OpenAI/MiniMax, 9 个 entry)

> ⚠️ `/fork` 后 `active_thread_id` 切换到新 thread — 后续 `/history` 和 `run_turn`
> 都走新 thread, 主对话不被污染。

> ⚠️ `/memory` 自定义 key 校验: 不在白名单的 key 必须以 `user_` 开头, 否则
> `set_pref` 抛 `ValueError`。

## 架构

```
stdin input
   ↓
cli.REPL.read()
   ↓ (分支)
   ├─ "/" → handle_command() (内置命令)
   └─ 普通文本 → supervisor graph (astream stream_mode="messages")
                     ↓
                   [每个 specialist 内的 middleware]
                   middleware: redact_pii (@wrap_model_call, 5 个 specialist 都有)
                   middleware: tone_prompt (@dynamic_prompt, 5 个 specialist 都有)
                     ↓
                   supervisor node → Command 路由
                     ↓
                   specialist × 5 (weather/calc/notes/orders/data)
                     ↓
                   工具调用 → HumanInTheLoopMiddleware 检查
                     ├─ 危险工具 (refund_order / write_note / run_sql)
                     │     → interrupt() 暂停, stdin 决策 a/r
                     └─ 普通工具 → 直接执行
                     ↓
                   stream token → cli 逐字打印
```

### Specialist × 工具矩阵

| Specialist | 工具 | HITL | Middleware |
|---|---|---|---|
| `WeatherAgent` | `get_weather` | — | redact_pii, tone_prompt |
| `CalcAgent` | `calc` (AST 安全) | — | redact_pii, tone_prompt |
| `NotesAgent` | `read_note`, `write_note` | write_note | redact_pii, tone_prompt, hitl |
| `OrdersAgent` | `get_order`, `refund_order` | refund_order | redact_pii, tone_prompt, hitl |
| `DataAgent` | `list_tables`, `describe_table`, `run_sql` | run_sql | redact_pii, tone_prompt, hitl |

HITL 只挂在有危险工具的 specialist 上 — 其它 specialist 挂 `hitl` 不触发 = 浪费节点。

## 文件结构

```
08-cli-assistant/
├── _common.py     # 复用 01-langchain-basics/_common.py (via importlib shim)
├── tools.py       # 9 个工具 (weather/calc/notes/orders/mysql)
├── middleware.py  # PII 脱敏 + 动态语气
├── memory.py      # Store 包装 + 偏好读写
├── agent.py       # supervisor + 5 specialists + HITL
├── mysql_db.py    # MySQL 连接 + schema 查询 + 安全审计 (_audit_sql)
├── schema.sql     # 参考 schema (3 表, 用户手动 mysql < schema.sql)
├── cli.py         # REPL + 命令 + 流式 + HITL 审批
├── main.py        # 入口 + API key 检查 + MySQL 探测
└── README.md      # 本文件
```

### 各文件关键点

| 文件 | 关键点 |
|---|---|
| `_common.py` | 用 `importlib.util.spec_from_file_location` 按路径加载 L1 的 `_common.py`, 不复制不污染 `sys.path` |
| `tools.py` | `calc` 用 `ast.parse` + 白名单节点 (`Constant/BinOp/UnaryOp`) + 1s ThreadPoolExecutor timeout + `_MAX_EXP=10000` 防 `9**9**9` DoS; `write_note` name 限 `[a-z0-9_]{1,32}` 防路径穿越; `refund_order` 金额 > 10000 业务拒绝; `run_sql` 调 `mysql_db.execute_safe_select` (audit + execute + 格式化) |
| `middleware.py` | PII 正则 `\d{17}[\dXx]\|1[3-9]\d{9}` (ID 在前, 顺序敏感); `redact_pii` 用 `model_copy(update={...})` 不污染原 state; `tone_prompt` 以 `request.system_prompt` 为 base 追加 |
| `memory.py` | namespace `("user_prefs", user_id)` (`user_id` 来自 env `CLI_USER_ID`, 默认 `"default"`); 默认 prefs: `nickname=friend`, `city=上海`, `language=中文` |
| `mysql_db.py` | `_audit_sql` 用 sqlparse 拆 statement + 白名单 type (SELECT/SHOW/...) + 正则 strip 注释 + 自动 LIMIT 1000 + 10s `execution_options` timeout; `get_schema_summary` 用 `SHOW FULL COLUMNS` 拿注释 |
| `agent.py` | `supervisor.compile()` 不接受 `middleware=` — middleware 全部下沉到 `create_agent(middleware=[...])`; `output_mode="last_message"` 让 supervisor 内部 routing 不进 messages; DataAgent system_prompt 强制 tool 调用 (不二次确认) |
| `cli.py` | `astream(stream_mode="messages")` token 流; HITL 检查 `state.next` + `state.tasks[0].interrupts[0].value`; rewind 一次性, `run_turn` 完成后清 `_rewind_ckpt`; `_stream_and_print` 异常捕获; `/mysql` 命令绕过 LLM 直连 |
| `main.py` | API key 4-provider 检测 → MySQL 探测 (失败不阻塞) → `InMemorySaver` + `build_store()` → `asyncio.run(cli.run())` |

## 4 个高级特性对应实现

| 特性 | 实现位置 | 复用自 |
|---|---|---|
| Streaming | `cli.py` `_stream_and_print` 用 `astream(stream_mode="messages")` | `02-langgraph-orchestration/09_streaming.py` demo 3 |
| HITL | `agent.py` 每个 specialist 挂 `HumanInTheLoopMiddleware`; `cli.py` `_maybe_hitl` 处理 interrupt | `01-langchain-basics/04_middleware.py` demo 5 |
| Supervisor | `agent.py` 用 `langgraph_supervisor.create_supervisor` 派 5 specialists | `04-multi-agent/13_supervisor.py` |
| Time travel | `cli.py` `_cmd_history` / `_cmd_rewind` / `_cmd_fork` 用 `get_state_history` + `update_state` + `checkpoint_id` 注入 | `02-langgraph-orchestration/10_durable_execution.py` |
| PII Middleware | `middleware.py` `redact_pii` (`@wrap_model_call`) | `01-langchain-basics/04_middleware.py` demo 8 |
| Dynamic Prompt | `middleware.py` `tone_prompt` (`@dynamic_prompt`, append 而非 replace) | `01-langchain-basics/04_middleware.py` demo 1 |
| Long-term Store | `memory.py` + `cli.py` `/memory` 命令 | `02-langgraph-orchestration/10_durable_execution.py` demo 7 |

## 已知坑 (踩过的)

1. **`@dynamic_prompt` 是 setter, 不是 appender** — 直接返回字符串会覆盖
   `create_agent(system_prompt=...)` 传进去的 specialist 角色, 必须以
   `request.system_prompt` 为 base 追加。
2. **`supervisor.compile()` 不接受 `middleware=`** — middleware 必须挂到每个
   `create_agent(middleware=[...])` 上, 不是 supervisor 层。
3. **`create_supervisor` 要求 sub-agent 有 `name=`** — 没名字路由不了 (每个
   `create_agent` 必须 `name="WeatherAgent"` 等)。
4. **PII 正则顺序敏感** — `\d{17}[\dXx]` 必须在 `1[3-9]\d{9}` 之前, 否则 ID
   中间 11 位子串会被当成手机号 mangled, 身份证永远识别不出。同理, 银行卡
   `\b\d{16,19}\b` 必须在 ID/手机之后 (ID 的 18 位子串里可能含 16-19 位连续
   数字段)。
5. **wrap_model_call 不要原地改 `m.content`** — 会污染 agent state /
   checkpoint / trace。必须 `m.model_copy(update={"content": new_content})`
   构造新消息。
6. **Windows GBK 编码** — 顶部 `sys.stdout.reconfigure(encoding="utf-8")`,
   跑命令时也可加 `PYTHONIOENCODING=utf-8 python main.py`。
7. **Shell 全局 stale `ANTHROPIC_API_KEY`** — 让 `.env` 改动失效
   (`load_dotenv override=False`), 临时绕过:
   `env -u ANTHROPIC_API_KEY python main.py`。
8. **Rewind 一次性** — 跑完一个 turn 就清掉 `_rewind_ckpt`, 不然会一直
   time-travel 在那个分支上, 后续 `/history` 也只看 rewound 之后的子集。
9. **HITL 协议层有 3 种 decision, CLI 只暴露 2 种** — `edit` 在协议层支持,
   但 UX 上常被误按成 `approve`, CLI 直接砍掉。
10. **`InMemoryStore` 重启即丢** — 演示用够, 生产换 `PostgresStore.from_conn_string(...)`。
11. **`usage_metadata` 部分 provider 不返回 (e.g. MiniMax M3 内测)** — token 显示 0
    但 cost 仍算 (M3 在 pricing 表里 cost=0, 所以没影响); 其它未接 pricing 的模型
    cost 显示 `$?` 而不是金额.
12. **specialist 检测基于 `AIMessage.name`** — 取决于 LangChain 是否设置。
    langgraph_supervisor 内部 routing AIMessage (e.g. "Transferring back to
    supervisor") 没 name → 只 specialist final reply 有 name → `detect_specialist`
    反向遍历找第一个带 name 的 AIMessage, 结果就是最终被路由到的 specialist。
    如果用自定义 non-named agent, 会显示 `?`.
13. **HITL preview EXPLAIN 防 hang** — `_preview_run_sql` 走 ThreadPoolExecutor
    5s 超时 (罕见但 EXPLAIN 在某些死锁 / 大表 DDL 时会卡)。MySQL 未配置时
    友好降级到 `? (MySQL 未配置)` 不抛错, preview 失败只打 `[预览失败]` 一行
    不阻塞 REPL 决策。
14. **HITL preview 走 `_audit_sql` 防注入** — `EXPLAIN` 后面的 SQL 同样经过
    `_audit_sql` 白名单 (SELECT/SHOW/...)。如果 LLM 生成的 tool_call.args.query
    本身就被 audit 拒, preview 会直接 raise, 被 `_format_hitl_preview` 的
    try/except 接住, 打印 `[预览失败] ValueError: ...` 给用户看。
15. **银行卡正则不吃连字符 / 空格** — `\b\d{16,19}\b` 只匹配纯数字连续段。
    带连字符的卡号 `6222-0212-3456-7890` 不被匹配 (这是有意的: 用户输入带
    格式的卡号时, 我们不脱敏 — 防 false positive; 生产可加 dedicated
    `[\d-]{16,23}` 模式匹配带格式的卡号)。

## 复用项目内 demo

- `01-langchain-basics/04_middleware.py` — middleware/HITL 全套模式
- `02-langgraph-orchestration/08_interrupt_hitl.py` — HITL interrupt 模式
- `02-langgraph-orchestration/09_streaming.py` — streaming modes
- `02-langgraph-orchestration/10_durable_execution.py` — time travel + Store
- `04-multi-agent/13_supervisor.py` — supervisor 模式
- `01-langchain-basics/_common.py` — 4-provider LLM 工厂 (`get_llm` / `banner`)
