# 08-cli-assistant — 智能个人助手 CLI

> ✅ Smoke-tested: import chain OK · 6 tools OK · memory prefs OK · async command routing OK · PII redaction OK (phone + ID + mixed 不互相 mangled) · AST parse 7/7 OK

把项目里分散在各 demo 的**高级用法**串成一个真正能跑的端到端 CLI 工具:
streaming token 打印 + HITL 审批 + supervisor 多 agent 路由 + PII middleware
脱敏 + 动态语气 + long-term Store + time-travel rewind / fork。

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

### HITL 决策细节

CLI 只暴露 `[a]pprove` / `[r]eject` 两种 — 没有 `[e]dit`。
原因: LangGraph 协议层仍支持 `["approve","edit","reject"]` 三种, 但 `edit`
常被误按成 `approve`, UX 上直接砍掉。
`r` 之后会追问 "拒绝原因", 拼到 `{"type":"reject","reason":...}` 里回传。

### PII 脱敏细节

- 手机号 (11 位, `1[3-9]\d{9}`) → `1XX-XXXX-XXXX`
- 身份证号 (18 位, `\d{17}[\dXx]`) → `1XXX-XXXX-XXXX-XXXX-X`
- 身份证正则必须在手机号**之前** (顺序敏感 — 不然 ID 里的 11 位子串会被当成手机号 mangled)
- 脱敏发生在 wrap_model_call 拦截器内, 用 `model_copy(update={...})` 构造新消息
  不污染原 agent state / checkpoint / trace

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
| `/quit`, `/exit` | 退出 REPL |

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
                   middleware: redact_pii (@wrap_model_call, 4 个 specialist 都有)
                   middleware: tone_prompt (@dynamic_prompt, 4 个 specialist 都有)
                     ↓
                   supervisor node → Command 路由
                     ↓
                   specialist × 4 (weather/calc/notes/orders)
                     ↓
                   工具调用 → HumanInTheLoopMiddleware 检查
                     ├─ 危险工具 (refund_order / write_note)
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

HITL 只挂在有危险工具的 specialist 上 — 其它 specialist 挂 `hitl` 不触发 = 浪费节点。

## 文件结构

```
08-cli-assistant/
├── _common.py     # 复用 01-langchain-basics/_common.py (via importlib shim)
├── tools.py       # 6 个 mock 工具 (weather/calc/notes/orders)
├── middleware.py  # PII 脱敏 + 动态语气
├── memory.py      # Store 包装 + 偏好读写
├── agent.py       # supervisor + 4 specialists + HITL
├── cli.py         # REPL + 命令 + 流式 + HITL 审批
├── main.py        # 入口 + API key 检查
└── README.md      # 本文件
```

### 各文件关键点

| 文件 | 关键点 |
|---|---|
| `_common.py` | 用 `importlib.util.spec_from_file_location` 按路径加载 L1 的 `_common.py`, 不复制不污染 `sys.path` |
| `tools.py` | `calc` 用 `ast.parse` + 白名单节点 (`Constant/BinOp/UnaryOp`) + 1s ThreadPoolExecutor timeout + `_MAX_EXP=10000` 防 `9**9**9` DoS; `write_note` name 限 `[a-z0-9_]{1,32}` 防路径穿越; `refund_order` 金额 > 10000 业务拒绝 |
| `middleware.py` | PII 正则 `\d{17}[\dXx]\|1[3-9]\d{9}` (ID 在前, 顺序敏感); `redact_pii` 用 `model_copy(update={...})` 不污染原 state; `tone_prompt` 以 `request.system_prompt` 为 base 追加 |
| `memory.py` | namespace `("user_prefs", user_id)` (`user_id` 来自 env `CLI_USER_ID`, 默认 `"default"`); 默认 prefs: `nickname=friend`, `city=上海`, `language=中文` |
| `agent.py` | `supervisor.compile()` 不接受 `middleware=` — middleware 全部下沉到 `create_agent(middleware=[...])`; `output_mode="last_message"` 让 supervisor 内部 routing 不进 messages |
| `cli.py` | `astream(stream_mode="messages")` token 流; HITL 检查 `state.next` + `state.tasks[0].interrupts[0].value`; rewind 一次性, `run_turn` 完成后清 `_rewind_ckpt`; `_stream_and_print` 异常捕获 |
| `main.py` | API key 4-provider 检测 → `InMemorySaver` + `build_store()` → `asyncio.run(cli.run())` |

## 4 个高级特性对应实现

| 特性 | 实现位置 | 复用自 |
|---|---|---|
| Streaming | `cli.py` `_stream_and_print` 用 `astream(stream_mode="messages")` | `02-langgraph-orchestration/09_streaming.py` demo 3 |
| HITL | `agent.py` 每个 specialist 挂 `HumanInTheLoopMiddleware`; `cli.py` `_maybe_hitl` 处理 interrupt | `01-langchain-basics/04_middleware.py` demo 5 |
| Supervisor | `agent.py` 用 `langgraph_supervisor.create_supervisor` 派 4 specialists | `04-multi-agent/13_supervisor.py` |
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
   中间 11 位子串会被当成手机号 mangled, 身份证永远识别不出。
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

## 复用项目内 demo

- `01-langchain-basics/04_middleware.py` — middleware/HITL 全套模式
- `02-langgraph-orchestration/08_interrupt_hitl.py` — HITL interrupt 模式
- `02-langgraph-orchestration/09_streaming.py` — streaming modes
- `02-langgraph-orchestration/10_durable_execution.py` — time travel + Store
- `04-multi-agent/13_supervisor.py` — supervisor 模式
- `01-langchain-basics/_common.py` — 4-provider LLM 工厂 (`get_llm` / `banner`)
