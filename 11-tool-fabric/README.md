# 11-tool-fabric — Tool Calling Deep Dive

L1 讲了 `@tool` 装饰器 + 基础 args_schema. 真实 tool calling 工程还有大量模式: 复杂 schema / 并行调用 / 错误恢复 / middleware / HITL / 工具组合. 本模块 6 个 demo 把这些都过一遍.

## 为什么需要这个模块

| 进阶能力 | L1 没讲 | 实战必备 |
|---|---|---|
| 复杂 Pydantic schema (Nested / Optional / Union) | ⚠️ 部分 | ✅ |
| 并行 tool calls (asyncio.gather) | ❌ | ✅ |
| Retry / fallback / default values | ❌ | ✅ |
| `@wrap_tool_call` middleware | ⚠️ 简单提 | ✅ |
| `HumanInTheLoopMiddleware` | ⚠️ demo 级 | ✅ |
| Tool composition (tool → tool) | ❌ | ✅ |

L1 `02_tools.py` 是入口, 但每个场景只演示基础. 本模块每个 demo 拆开讲 5-7 个 step, over-deliver.

## 学完你能回答 N 个问题

1. **`@tool` + `args_schema`** — Pydantic 校验怎么强制 Literal / ge / le? 校验失败时 LangChain 怎么自动回错误给 LLM?
2. **复杂 schema** — `Literal` / `Field` / `Optional[dict]` / `BaseModel` 嵌套怎么组合? 哪个对 LLM 最友好?
3. **并行调用** — `asyncio.gather` 真并发的关键? `return_exceptions=True` 为什么必加? 串行 vs 并行延迟差几倍?
4. **错误处理** — `raise ToolException` vs `return error dict` 区别? 怎么用 `wrap_tool_call` 做 retry / fallback? 指数 backoff 怎么写?
5. **Middleware 链** — 顺序敏感吗? `logging → rate_limit → pii_strip` 顺序怎么定? 怎么用 `time.perf_counter()` 算 latency?
6. **HITL 工具** — `interrupt_on={tool: {allowed_decisions}}` 怎么配? `Command(resume={"decisions": [...]})` 怎么传 approve/edit/reject? `state.tasks[0].interrupts` 怎么读待审批内容?
7. **Tool composition** — 工具内 `.invoke()` 另一个工具 vs Agent 调两个工具, 区别? 怎么避免循环依赖? 嵌套深度限制?
8. **PII 实战** — 手机号 / 邮箱 regex 怎么写? `ToolMessage` 是 frozen 的, 怎么改 content?

## Demo 表

| Demo | 内容 | 需要 API key | 跑法 |
|---|---|---|---|
| `01_basic_tools.py` | `@tool` + Pydantic 校验 + Literal / Field / Optional 复杂 schema + dict vs string 返回 | ⚠️ Step 3 要 LLM | `python 01_basic_tools.py` |
| `02_parallel_calls.py` | asyncio.gather 并行 + 手写 dispatch + return_exceptions 隔离 | ⚠️ Step 2/5 要 LLM | `python 02_parallel_calls.py` |
| `03_error_recovery.py` | ToolException vs return dict + retry middleware + fallback + default values | ❌ 纯工具 | `python 03_error_recovery.py` |
| `04_middleware.py` | logging + pii_strip + rate_limit + 自定义 metric + chain 顺序 | ⚠️ 多数要 LLM | `python 04_middleware.py` |
| `05_hitl_tools.py` | `HumanInTheLoopMiddleware` interrupt_on + Command(resume=approve/edit/reject) | ✅ 需要 LLM | `python 05_hitl_tools.py` |
| `06_tool_composition.py` | tool 调 tool + 嵌套 + 聚合 + async gather 并发子工具 | ⚠️ Step 2 要 LLM | `python 06_tool_composition.py` |

## 文件结构

```
11-tool-fabric/
├── _common.py                L1 wrapper + get_sample_agent 工厂 + step/output_dir
├── tools.py                  6 sample tools + 3 Pydantic schemas (SearchQuery/DBQuery/RefundRequest)
├── middleware.py             3 wrap_tool_call handlers (logging/pii_strip/rate_limit)
├── 01_basic_tools.py         Demo 1: @tool + Pydantic + 复杂 schema
├── 02_parallel_calls.py      Demo 2: asyncio.gather 并行 dispatch
├── 03_error_recovery.py      Demo 3: ToolException + retry/fallback/defaults
├── 04_middleware.py          Demo 4: @wrap_tool_call patterns + chain
├── 05_hitl_tools.py          Demo 5: HumanInTheLoopMiddleware interrupt_on
├── 06_tool_composition.py    Demo 6: tool 调 tool + 嵌套 + 聚合 + async
├── README.md                 本文件
└── .gitignore                output/ + __pycache__/
```

## 跑法

```bash
cd D:/work-ai/0401-langchain-langgraph-v1

# 不需要 API key 的 demo (纯工具 / middleware 行为)
python 11-tool-fabric/03_error_recovery.py
python 11-tool-fabric/06_tool_composition.py  # Step 1/3/4/5

# 部分需要 LLM (Step 3)
python 11-tool-fabric/01_basic_tools.py

# 完全依赖 LLM (Demo 5 HITL 必须)
python 11-tool-fabric/05_hitl_tools.py
```

LLM provider 配置见 `01-langchain-basics/_common.py` 的 `get_llm()` — 优先级 Anthropic > DeepSeek > MiniMax > OpenAI, `.env` 配 key 即可.

## 核心概念

### 1. 6 个共享 sample tools (`tools.py`)

| 工具 | 类别 | Schema | HITL |
|---|---|---|---|
| `get_weather(city)` | 简单 | 签名自动推断 | ❌ |
| `calculator(expression)` | 简单 (AST) | 签名自动推断 | ❌ |
| `web_search(query, max_results, language)` | 复杂 | `SearchQuery` (Literal + ge/le) | ❌ |
| `db_query(table, where, limit)` | 复杂 | `DBQuery` (Literal + Optional dict) | ❌ |
| `write_note(content)` | 危险 | 签名 | ✅ |
| `refund(order_id, amount_cents, reason)` | 危险 | `RefundRequest` (ge=1, le=100000) | ✅ |

### 2. 3 个共享 middleware (`middleware.py`)

| Middleware | 作用 | 关键代码 |
|---|---|---|
| `logging_middleware` | 记录 input/output/latency | `time.perf_counter()` + print |
| `pii_strip_middleware` | mask 手机号 / 邮箱 | `_PHONE_RE` / `_EMAIL_RE` + 重建 ToolMessage |
| `rate_limit_middleware` | 每分钟限 N 次 | `defaultdict(list)` + 60s 滑动窗口 |

### 3. Demo 5 HITL 决策格式 (LangChain 1.x)

```python
# approve
Command(resume={"decisions": [{"type": "approve"}]})

# reject
Command(resume={"decisions": [{"type": "reject"}]})

# edit — 改参数后通过
Command(resume={
    "decisions": [{
        "type": "edit",
        "edited_action": {
            "name": "refund",
            "args": {"order_id": 999, "amount_cents": 5000, "reason": "..."},
        },
    }],
})
```

## 已知坑 (7 个)

### 1. `@tool` 函数 invoke 永远接受 dict, 不是位置参数

**现象**: `get_weather.invoke("北京")` → TypeError.

**原因**: LLM 的 tool_call 永远产出 `{"name": ..., "args": {...}}`, 框架 dispatch 时统一 `tool.invoke(tc["args"])`. 位置参数会让 dispatch 框架复杂化.

**实战**: 永远用 `.invoke({"arg_name": value})`. 单元测试也这么写.

### 2. Pydantic 校验失败 — `ValidationError` vs `ToolException`

**现象**: 工具内 `raise ToolException("xxx")` 和 `raise ValidationError("xxx")` 在 create_agent 里行为不一样.

**原因**: LangChain 框架的 tool dispatcher 会**自动捕获 `ToolException` 并转 `ToolMessage`** 给 LLM. 但 `ValidationError` 通常在 invoke 时抛出, 不进 dispatch.

**实战**: 业务错误用 `raise ToolException("...")`. Pydantic 的 ValidationError 让框架自动转, 不需要手动 raise.

### 3. `wrap_tool_call` handler 返回 `ToolMessage` — 必须是新的, 不能 setattr

**现象**: 想改 `result.content` → `result.content = "new"` → 报错 "ToolMessage is immutable" / AttributeError.

**原因**: LangChain `BaseMessage` 是 frozen dataclass, content 不能改.

**实战**: 重建 `ToolMessage(content=new_content, tool_call_id=result.tool_call_id)`. 见 `middleware.py` pii_strip.

### 4. `ToolMessage` 必须带 `tool_call_id` — 框架靠它对应回 AIMessage

**现象**: 手动构造 `ToolMessage(content=..., tool_call_id="missing")` → LLM 报错 "no tool_call_id for AIMessage".

**原因**: 一条 AIMessage 可以有多个 tool_call, 每条 ToolMessage 必须有对应 id.

**实战**: middleware 里 `ToolMessage(content=..., tool_call_id=result.tool_call_id)` 一定要带原 id.

### 5. 中间件顺序敏感 — 最先声明的最外层

**现象**: `[A, B, C]` 三层 wrap_tool_call, 实际执行 A → B → C → handler → C → B → A (洋葱).

**原因**: `create_agent` 把 middleware 包成嵌套调用 — 类似 Python decorator chain.

**实战**: 顺序按 "功能正交 + 优先级" 排. 例如:
- `[logging_middleware, rate_limit_middleware, pii_strip_middleware]`:
  - logging 最外 — 它要看到所有调用 + 真实 latency (包括 rate_limit 拒绝的)
  - rate_limit 第二 — 拒绝时 logging 仍能看到 "被拒"
  - pii_strip 最内 — 只处理真执行的工具输出

### 6. HITL 不会触发 — 小模型 (M3) 经常不调工具

**现象**: 触发 refund → agent 直接 finish, 不调工具, `state.next` 是 None.

**原因**: 小模型工具能力弱, 经常直接回答 "我帮你退款了" 而不是调 `refund()`.

**实战**: HITL 调试用 Claude Sonnet 4 / GPT-4o, 这些模型工具调用稳定. M3 仅做 smoke test. 监控 `state.tasks[0].interrupts` 长度 — 0 就说明没暂停.

### 7. Tool composition 嵌套深度 — 2-3 层足够

**现象**: A 调 B 调 C 调 D 调 E → 调试困难 + 性能差 + 容易循环依赖.

**原因**: 每层 invoke 一次 dispatch (即使同步, 也有 call stack 开销). 嵌套深后 trace 难.

**实战**: 2-3 层足够. 想做更复杂流程, 用 LangGraph state machine 而不是 tool composition. composition 适合 "固定流程", 不适合 "动态决策".

## 进阶阅读

- **LangChain 1.x tool docs**: <https://docs.langchain.com/oss/python/langchain/tools>
- **Pydantic V2 schema**: <https://docs.pydantic.dev/latest/concepts/json_schema/>
- **Human-in-the-loop**: <https://docs.langchain.com/oss/python/langchain/agent-builder/human-in-the-loop>
- **Middleware 概念**: <https://docs.langchain.com/oss/python/langchain/agent-builder/middleware>

## 相关模块

- `01-langchain-basics/02_tools.py` — L1 基础 `@tool` (本模块的前置)
- `01-langchain-basics/04_middleware.py` — L1 基础 middleware (含 HITL 入门)
- `02-langgraph-orchestration/08_interrupt_hitl.py` — 手动 interrupt (vs 本模块的 HITL middleware)
- `06-opc-product/` — L1-L6 全栈 demo, 含完整 HITL 流程 (退款场景)
- `08-cli-assistant/` — 实战 HITL (含 edit 参数 + batch 审批)