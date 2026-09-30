# CLI Personal Assistant — Design Spec

**Date**: 2026-09-30
**Status**: Awaiting user review
**Owner**: fang
**Location**: `08-cli-assistant/`

## 1. Purpose

在项目根目录新建一个**独立模块 `08-cli-assistant/`**,实现一个**可交互的 CLI 个人助手**。这个助手本身不是产品,而是把项目中分散在各 demo 里的**高级用法**串成一个真正能跑的端到端工具,作为 L1-L4 知识的"期末复习"。

学习者跑 `python 08-cli-assistant/main.py` 就能:
- 像 ChatGPT 那样跟 agent 对话(逐字打印 token 流)
- 触发危险操作时被强制暂停、人工审批
- 体验 supervisor 把任务派给不同 specialist
- 透过 `/history /rewind /fork` 看到 LangGraph 的 time travel / replay
- 通过 `/memory` 看到长期 Store 记忆跨会话保留
- 体验 PII 脱敏和 dynamic prompt 等自定义 middleware

## 2. Out of Scope (YAGNI)

为保持"小"——以下**不**做:
- 不接入 FastAPI / WebSocket / HTTP 端点(纯 stdin/stdout)
- 不引入 prompt_toolkit / readline 等额外 UI 库(标准库 input 足够)
- 不写测试(整个项目一贯风格:只教程 + 可运行代码)
- 不接入真实订单/天气/计算 API(全部 mock 工具)
- 不接入 MCP server
- 不做 deep agents(本次聚焦 L1+L2+L4, deep agents 留作 16_deep_agents.py)
- 不做 evaluation(留作 L3)

## 3. Architecture

### 3.1 目录结构

```
08-cli-assistant/
├── README.md           # 学完你能回答 N 个问题 + 跑法 + 7 个 demo 场景
├── _common.py          # 复用 01-langchain-basics/_common.py 的 get_llm/banner
├── main.py             # 入口 (~30 行): load .env, 启动 REPL
├── cli.py              # REPL 主循环 (~120 行): 命令分发 + stream 打印
├── agent.py            # supervisor + 4 specialists 装配 (~120 行)
├── tools.py            # 工具定义 (~80 行): weather/calc/notes/orders
├── middleware.py       # PII redaction + dynamic prompt (~50 行)
└── memory.py           # Store 初始化 + 偏好读写 (~40 行)
```

合计约 **440 行**,作为"小"程序边界。

### 3.2 数据流

```
stdin input
   ↓
cli.REPL.read()
   ↓  (分支)
   ├─ 以 "/" 开头 ──→ cli.handle_command()  (内置命令)
   └─ 普通文本   ──→ agent.supervisor_graph.astream(stream_mode="messages")
                         ↓
                       middleware: PII redaction (redact_phone)
                       middleware: dynamic_prompt (按语气切 system msg)
                         ↓
                       supervisor node (LLM 决定派给谁)
                         ↓ (Command 路由, langgraph_supervisor 内部)
                       specialist × 4 (weather/calc/notes/orders)
                         ↓
                       工具调用 → HumanInTheLoopMiddleware 检查
                         ├─ 危险工具 (refund_order / write_note)
                         │     → interrupt() 暂停, 等 stdin approve/edit/reject
                         └─ 普通工具 → 直接执行
                         ↓
                       stream token → cli 逐字打印到 stdout
```

### 3.3 State 模型

- **Checkpointer**: `InMemorySaver()` — 短期对话历史,thread 级别
- **Store**: `InMemoryStore()` — 长期偏好,namespace = `("user_prefs", user_id)`
- **thread_id (主对话)**: 单一固定 `"cli-session-1"`(CLI 是单用户单会话)
- **thread_id (fork 分支)**: `update_state` 默认生成新 thread,形如 `cli-session-1:fork:<uuid>`,**主对话 thread 不被污染**(这点跟 10_durable_execution.py 第 2 段一致)
- **user_id**: 从 `.env` 读 `CLI_USER_ID`,默认 `"default"`

### 3.4 Streaming 模式

主对话用 `astream(stream_mode="messages")`,逐字打印 LLM token。
配合 `sys.stdout.flush()` 实现"打字机"效果。

不订阅多个 mode(list)——简化 CLI,token 流够了。

## 4. Advanced Features — 实现细节

### 4.1 Streaming Token Output

**位置**: `cli.py` `run_turn(text: str) -> None`

```python
async for token, metadata in graph.astream(
    {"messages": [HumanMessage(text)]},
    config=config,
    stream_mode="messages",
):
    if hasattr(token, "content") and token.content:
        print(token.content, end="", flush=True)
print()  # 换行
```

**复用**: `02-langgraph-orchestration/09_streaming.py` 第 3 段 `demo_messages_mode`

### 4.2 HITL (Human-in-the-Loop)

**实现**: `HumanInTheLoopMiddleware` (1.x 官方, 不用手搓 interrupt())

```python
from langchain.agents.middleware import HumanInTheLoopMiddleware

middleware = HumanInTheLoopMiddleware(
    interrupt_on={
        "refund_order": {"allowed_decisions": ["approve", "edit", "reject"]},
        "write_note":   {"allowed_decisions": ["approve", "edit", "reject"]},
    },
)
```

CLI 接到 interrupt 时:
1. 打印待审批的工具调用详情
2. 提示 `[a]pprove / [e]dit / [r]eject`
3. 用户输入 → `Command(resume={"decisions": [{"type": ...}]})` 恢复

**复用**: `01-langchain-basics/04_middleware.py` 第 5 段 `demo_human_in_the_loop`

### 4.3 Supervisor 多 Agent

**实现**: `langgraph_supervisor.create_supervisor` (项目已用过)

```python
from langgraph_supervisor import create_supervisor

supervisor = create_supervisor(
    model=get_llm(),
    agents=[weather_agent, calc_agent, notes_agent, orders_agent],
    prompt=("你是智能助手, 把任务派给合适的 specialist: "
        "[WeatherAgent]/[CalcAgent]/[NotesAgent]/[OrdersAgent]. "
        "不要自己直接调工具."),
    output_mode="last_message",  # 只回 supervisor 的 final message
)
graph = supervisor.compile(checkpointer=checkpointer, store=store)
```

**4 个 specialist**:
- `WeatherAgent` — tools=[get_weather]
- `CalcAgent` — tools=[calc] (AST 安全求值)
- `NotesAgent` — tools=[read_note, write_note]
- `OrdersAgent` — tools=[get_order, refund_order]

每个 specialist = `create_agent(model=llm, tools=[...], system_prompt="...")`

**HITL middleware 挂哪一层**: 挂在 `supervisor.compile()` 上,因为 HITL 中断需要让 graph 暂停;specialist 内部不重复挂。

**复用**: `04-multi-agent/13_supervisor.py`

### 4.4 Time Travel Commands

**位置**: `cli.py` 内置命令处理

| 命令 | 实现 |
|---|---|
| `/history` | `graph.get_state_history(config)` 列出 checkpoints (ts/next/msgs/ckpt_id)。**索引规则**: history[0]=最新(刚发生的), history[-1]=最老(最开始)。打印时标注 `[0]=最新 ... [-1]=最老` |
| `/rewind N` | 取 history[N] 的 checkpoint_id (N 是 history 列表索引, 0=最新),作为新 config 起点;不重跑 LLM |
| `/fork <text>` | 取最新 checkpoint (`history[0]`),`update_state(values={"messages": [HumanMessage(<text>)]})` 追加一条人类消息到该 checkpoint,然后在新生成的 thread 上续走 |

**复用**: `02-langgraph-orchestration/10_durable_execution.py` 第 1/2/6 段

### 4.5 Custom Middleware — PII Redaction

**位置**: `middleware.py`

```python
@wrap_model_call
def redact_pii(request, handler):
    phone_re = re.compile(r"1[3-9]\d{9}")
    id_re = re.compile(r"\d{17}[\dXx]")  # 身份证
    for m in request.messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            m.content = phone_re.sub("1XX-XXXX-XXXX", m.content)
            m.content = id_re.sub("1XXXXXXXXXXXXXXXXX", m.content)
    return handler(request)
```

**复用**: `01-langchain-basics/04_middleware.py` 第 8 段 `demo_pii_redaction`

### 4.6 Custom Middleware — Dynamic Prompt

**位置**: `middleware.py`

```python
@dynamic_prompt
def tone_prompt(request):
    history = "\n".join(
        m.content for m in request.messages if isinstance(m, HumanMessage)
    )
    if "正式" in history: return "你用正式语气 (使用'您')"
    if "随便" in history or "哈哈" in history: return "你用轻松语气 (可用 emoji)"
    return "你正常回答"
```

**复用**: `01-langchain-basics/04_middleware.py` 第 1 段 `demo_dynamic_prompt`

### 4.7 Long-term Memory (Store)

**位置**: `memory.py` + `cli.py` `/memory` 命令

```python
store = InMemoryStore()
namespace = ("user_prefs", user_id)

def get_prefs() -> dict:
    items = store.search(namespace)
    return {it.key: it.value for it in items}

def set_pref(key: str, value: str) -> None:
    store.put(namespace, key, {"value": value})
```

**预置 3 个偏好**: nickname / city / language,首次启动时写入默认值。

**复用**: `02-langgraph-orchestration/10_durable_execution.py` 第 7 段 `demo_checkpoint_vs_store`

### 4.8 LangSmith Trace

**位置**: `.env` 加 `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_PROJECT=cli-assistant`

CLI 不写一行 LangSmith 代码,框架自动 trace。

启动时打印"LangSmith trace 已开启"or"未开",给用户提示。

**复用**: `03-langsmith-platform/11_langsmith_tracing.py`

## 5. CLI Command Surface

| 输入 | 行为 | 涉及特性 |
|---|---|---|
| `北京天气?` | supervisor → weather specialist → streaming 输出 | Supervisor + Streaming |
| `123 * 456 等于多少` | calc specialist | Supervisor |
| `查订单 #123` | orders specialist | Supervisor |
| `退款 #123 100元` | orders specialist → **HITL** | Supervisor + HITL |
| `写笔记: 买牛奶` | notes specialist → **HITL** | Supervisor + HITL |
| `/history` | 列出 checkpoints | Time travel |
| `/rewind 2` | 回到第 2 轮 | Time travel |
| `/fork 我没说过 100` | 改历史 | Time travel |
| `/memory` | 查看/编辑长期偏好 | Store |
| `/help` | 帮助 | — |
| `/quit` | 退出 | — |

## 6. Tools Specification

| 工具 | 签名 | mock 返回 | HITL |
|---|---|---|---|
| `get_weather(city)` | `str -> str` | `f"{city} 晴 25°C"` | 无 |
| `calc(expr)` | `str -> str` | AST 安全求值 `eval` | 无 |
| `read_note(name)` | `str -> str` | 从内存 dict 读 | 无 |
| `write_note(name, content)` | `str, str -> str` | 写内存 dict | **触发** |
| `get_order(id)` | `str -> str` | 从 mock dict 查 | 无 |
| `refund_order(id, amount)` | `str, float -> str` | 返回"已退款" | **触发** |

**安全考量**:
- `calc` 用 `ast.parse + eval` + 白名单节点(只允许 BinOp/Num/Name),禁止 `__import__`
- `read_note/write_note` 限制 name 在 `[a-z0-9_]+` 范围内,防路径穿越
- `refund_order` 金额 > 10000 时直接拒绝 (业务规则)

## 7. Error Handling & UX

- **缺 API key**: 启动时检查 `ANTHROPIC/DEEPSEEK/MINIMAX/OPENAI_API_KEY` 之一,缺失则打印清晰提示 + 退出码 1
- **小模型 (M3) 不调工具**: streaming 输出正常,但 specialist 收不到——已在 memory 里记录"如遇 M3 不调工具,可改用 Claude/GPT/DeepSeek"
- **HITL 等待输入超时**: 不设超时 (CLI 同步, 用户必须给响应)
- **Windows GBK 编码**: 顶部 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`, 跟项目其它文件一致
- **KeyboardInterrupt (Ctrl+C)**: 优雅退出,打印"再见"
- **每个 demo 命令独立 try/except 包住**, 单点失败不影响 REPL 继续

## 8. Testing Strategy

**不写自动化测试** (项目一贯风格)。但 README 列出 7 个"手测场景":

1. 普通对话: `北京天气?` → 看到 streaming token 流
2. HITL: `退款 #123 100元` → 看到暂停 → 输入 `a` → 看到结果
3. Supervisor 派工: 故意问数学 → 看 supervisor 路由日志
4. PII: `我手机号 13800138000` → 看回复里看不到原号
5. Time travel: 跑 3 轮对话 → `/history` → `/rewind 1` → 看到状态回到第 1 轮
6. Fork: 跑两轮后 `/fork 我住北京` → 新 thread 续走
7. Memory: `/memory nickname fang` → 退出 → 重启 → `/memory` 看到 nickname 还在 (注: InMemoryStore 跨进程会丢,演示时提醒"重启就丢,生产用 PostgresStore")

## 9. Dependencies

无新增依赖。复用项目 `requirements.txt` 现有的:
- `langchain>=1.0.2`
- `langgraph>=1.0`
- `langgraph-supervisor` (已有? 待查; 若无则 README 说明 `pip install langgraph-supervisor`)
- `python-dotenv`

## 10. Open Questions (待用户验证)

1. `langgraph-supervisor` 是否已装? 待 `pip show` 确认。若无,README 提示 `pip install langgraph-supervisor`。
2. `InMemoryStore` 跨进程会丢,演示后用户是否能接受"重启就清空"? 若不能,改用 `SqliteStore`(`langgraph-checkpoint-sqlite` 已有)。
3. HITL `approve/edit/reject` 用单字母 `[a/e/r]` 还是全词? 默认单字母,符合 CLI 习惯。

## 11. Definition of Done

- [ ] 8 个文件全部创建在 `08-cli-assistant/`
- [ ] `python 08-cli-assistant/main.py` 可启动并显示欢迎语
- [ ] 7 个手测场景全部跑通 (Claude/GPT 模型)
- [ ] 小模型 (M3) 跑时优雅降级,不崩溃
- [ ] README.md 含"学完你能回答 10 个问题"清单
- [ ] `_common.py` 顶部 docstring 注释"复用 01-langchain-basics/_common.py"
- [ ] 通过 `python -c "import ast; ast.parse(open('XX.py').read())"` 无语法错误
- [ ] 无新增 pip 依赖 (除 `langgraph-supervisor` 若缺失)

## 12. References

- 项目内复用:
  - `01-langchain-basics/04_middleware.py` — middleware 全套
  - `02-langgraph-orchestration/08_interrupt_hitl.py` — HITL 模式
  - `02-langgraph-orchestration/09_streaming.py` — streaming modes
  - `02-langgraph-orchestration/10_durable_execution.py` — time travel / replay / Store
  - `04-multi-agent/13_supervisor.py` — supervisor 模式
- 官方文档:
  - https://docs.langchain.com/oss/python/langgraph/overview
  - https://docs.langchain.com/oss/python/langgraph/supervisor
  - https://docs.langchain.com/oss/python/langchain/middleware