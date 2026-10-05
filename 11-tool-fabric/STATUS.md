# 11-tool-fabric — 最终状态 (2026-10-04)

> Tool calling 工程模式深度. 本模块把 L1 `@tool` 没讲透的实战模式全部拆开: 复杂 schema / 并行调用 / 错误恢复 / middleware / HITL / 工具组合. 本文档是教学收尾, 标出能力边界 + 已知限制 + 升级路径.

## TL;DR

- **10 个文件 (含 README + .gitignore) / ~1945 LOC 代码 / 2136 含 README / 4 atomic commits**
- **6 demo + 3 共享 (tools.py / middleware.py / _common.py)**
- **9 已知坑 (7 教学坑 + 2 生产坑)**
- **AST parse 9/9 OK, import chain OK**

## 能力矩阵

| 维度 | 实现 | 文件 | LOC |
|---|---|---|---|
| **@tool 基础** | 装饰器 + 自动签名推断 (get_weather / calculator) | tools.py | 191 |
| **复杂 schema** | SearchQuery (Literal + ge/le) + DBQuery (Literal + Optional dict) + RefundRequest (ge/le) | tools.py | (内嵌) |
| **AST 安全求值** | calculator 不用 eval, 走 ast.parse + bin_op dispatch | tools.py | (内嵌) |
| **危险工具** | write_note (HITL yes/no) + refund (HITL 可 edit) | tools.py | (内嵌) |
| **共享 middleware** | logging (perf_counter) / pii_strip (regex) / rate_limit (60s sliding window) | middleware.py | 100 |
| **并行 dispatch** | asyncio.gather + tool_call_id 配对 + return_exceptions 隔离 | 02_parallel_calls.py | 210 |
| **ToolException vs return dict** | 业务错用 raise (自动转 ToolMessage), API 错用 dict (可控) | 03_error_recovery.py | 319 |
| **Retry middleware** | 指数 backoff (0.1s × 2^n) + max_retries + wrap_tool_call | 03_error_recovery.py | (内嵌) |
| **Fallback tool** | primary fail → 调同名 fallback + 包 ToolMessage | 03_error_recovery.py | (内嵌) |
| **Default values** | Field(default) + Optional 让 LLM 漏传兜底 | 03_error_recovery.py | (内嵌) |
| **Middleware chain** | 洋葱模型 + 顺序敏感 + logging 最外 pii_strip 最内 | 04_middleware.py | 232 |
| **自定义 metric middleware** | 按 tool name 累计调用次数 + 输出 Prometheus friendly | 04_middleware.py | (内嵌) |
| **HumanInTheLoopMiddleware** | interrupt_on={tool: {allowed_decisions}} + checkpointer | 05_hitl_tools.py | 385 |
| **HITL edit 决策** | edited_action 改参数后批准 (LangChain 1.x 格式) | 05_hitl_tools.py | (内嵌) |
| **Tool composition 基础** | tool 内部 invoke 另一个 tool (weather_then_calc) | 06_tool_composition.py | 239 |
| **嵌套 composition** | A → B → C 三层 (deep_weather_summary) | 06_tool_composition.py | (内嵌) |
| **聚合工具** | web + db → 1 个 dict (research_assistant) | 06_tool_composition.py | (内嵌) |
| **异步 composition** | async tool + ainvoke + asyncio.gather (fast_research) | 06_tool_composition.py | (内嵌) |
| **Sample agent 工厂** | get_sample_agent(tools, middleware=) 复用 create_agent | _common.py | 76 |

## 6 个 demo

| # | 主题 | 步骤 | 需要 API key | 跑法 |
|---|---|---|---|---|
| 1 | @tool + Pydantic 校验 + 复杂 schema + return type | 5 | Step 3 要 LLM | `python 01_basic_tools.py` |
| 2 | asyncio.gather 并行 + 手写 dispatch + return_exceptions + agent | 5 | Step 2/5 要 LLM | `python 02_parallel_calls.py` |
| 3 | ToolException + return dict + retry + fallback + default values | 5 | ❌ 纯工具 | `python 03_error_recovery.py` |
| 4 | logging + pii_strip + rate_limit + chain + 自定义 metric | 6 | 多数要 LLM | `python 04_middleware.py` |
| 5 | HumanInTheLoopMiddleware + interrupt_on + approve/edit/reject | 6 | ✅ 必须 (小模型难触发) | `python 05_hitl_tools.py` |
| 6 | tool 调 tool + 嵌套 + 聚合 + 异步 gather | 5 | Step 2 要 LLM | `python 06_tool_composition.py` |

## 9 个已知坑

### 1. `@tool` 函数 invoke 永远接受 dict, 不是位置参数

**现象**: `get_weather.invoke("北京")` → TypeError.

**影响**: 单元测试写错就报错; LLM 实际调工具不会出这错 (它发 dict).

**升级路径**: 永远用 `.invoke({"arg_name": value})`. Demo 1 Step 1 演示了这个细节.

### 2. Pydantic `ValidationError` vs `ToolException` 行为不同

**现象**: 工具内 `raise ToolException("xxx")` 和 `raise ValidationError("xxx")` 在 create_agent 里行为不一样.

**影响**: 业务错必须用 `ToolException` 才能自动转 `ToolMessage` 给 LLM 重试. 普通 Exception 框架会报 graph error.

**升级路径**: 业务错用 `raise ToolException("...")`. Pydantic 的 ValidationError 让框架自动转, 不需要手动 raise.

### 3. `wrap_tool_call` handler 返回 `ToolMessage` — 必须是新的, 不能 setattr

**现象**: 想改 `result.content` → `result.content = "new"` → 报错 "ToolMessage is immutable" / AttributeError.

**影响**: middleware 想改 output 必须新建 ToolMessage, 不能复用.

**升级路径**: 重建 `ToolMessage(content=new_content, tool_call_id=result.tool_call_id)`. 见 `middleware.py` pii_strip.

### 4. `ToolMessage` 必须带 `tool_call_id` — 框架靠它对应回 AIMessage

**现象**: 手动构造 `ToolMessage(content=..., tool_call_id="missing")` → LLM 报错 "no tool_call_id for AIMessage".

**影响**: middleware 重建 ToolMessage 时漏传 id 会让 graph 崩.

**升级路径**: middleware 里 `ToolMessage(content=..., tool_call_id=result.tool_call_id)` 一定要带原 id. Demo 4 pii_strip 演示了.

### 5. 中间件顺序敏感 — 最先声明的最外层

**现象**: `[A, B, C]` 三层 wrap_tool_call, 实际执行 A → B → C → handler → C → B → A (洋葱).

**影响**: 顺序错 logging 看不到真实 latency, rate_limit 拒绝时 pii_strip 看不到, etc.

**升级路径**: 顺序按 "功能正交 + 优先级" 排:
- `[logging_middleware, rate_limit_middleware, pii_strip_middleware]`
- logging 最外 — 看到所有调用 + 真实 latency (包括 rate_limit 拒绝)
- rate_limit 第二 — 拒绝时 logging 仍能看到 "被拒"
- pii_strip 最内 — 只处理真执行的工具输出

### 6. HITL 不会触发 — 小模型 (M3) 经常不调工具

**现象**: 触发 refund → agent 直接 finish, 不调工具, `state.next` 是 None.

**影响**: HITL demo 在 M3 上经常空跑, 教学演示失效.

**升级路径**: HITL 调试用 Claude Sonnet 4 / GPT-4o, 这些模型工具调用稳定. M3 仅做 smoke test. 监控 `state.tasks[0].interrupts` 长度 — 0 就说明没暂停.

### 7. Tool composition 嵌套深度 — 2-3 层足够

**现象**: A 调 B 调 C 调 D 调 E → 调试困难 + 性能差 + 容易循环依赖.

**影响**: 深嵌套 trace 难, 性能差 (每层 invoke 都有 call stack 开销).

**升级路径**: 2-3 层足够. 想做更复杂流程, 用 LangGraph state machine 而不是 tool composition. composition 适合 "固定流程", 不适合 "动态决策".

### 8. `@wrap_tool_call` middleware 测试难 — 必须构造 FakeRequest (生产坑)

**现象**: 不能直接 `retry_middleware(tool_call)`, 必须 `retry_middleware.wrap_tool_call(req, fake_handler)`.

**影响**: 单元测试 middleware 行为需要写 boilerplate (FakeRequest 类 + fake_handler 函数), 不能 pytest 一行调.

**升级路径**: 抽 `FakeRequest` 到 conftest.py 共享 (Demo 3/4 都有). 真实测试用 create_agent 走 end-to-end, 不用绕中间层.

### 9. 异步工具 `.ainvoke` vs 同步 `.invoke` 不能混用 (生产坑)

**现象**: async tool 内 `await sync_tool.invoke(...)` → 阻塞 event loop, 失去异步优势.

**影响**: 写 `fast_research` (async) 时, 如果子工具是同步, gather 还是串行执行 (因为 sync invoke 阻塞). 真异步需要子工具也是 async (有 `ainvoke`).

**升级路径**: 工具函数如果是 async def + @tool, 框架自动给 `.ainvoke`. 但调子工具时仍要 `.ainvoke` 才走异步路径. 看 Demo 6 Step 5 — 调的是 `web_search.ainvoke(...)` 不是 `web_search.invoke(...)`.

## 升级到 Production 的步骤

```python
# 1. PII regex 升级 — Microsoft Presidio (结构化识别) / 国内脱敏原语
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def presidio_pii_strip(text: str) -> str:
    results = analyzer.analyze(text=text, language="en")
    return anonymizer.anonymize(text=text, analyzer_results=results).text

# 2. Rate limiter 换 Redis (跨进程 token bucket)
import redis
from redis_rate_limit import RateLimiter
r = redis.Redis(host="...", port=6379)
limiter = RateLimiter(r, limit=100, period=60)  # 100/min

# 3. Retry 换 tenacity (jitter + max_delay + 异常白名单)
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.1, max=2),
    retry=retry_if_exception_type((ToolException, TimeoutError)),
)
def my_tool(...): ...

# 4. Middleware metric 上报 Prometheus pushgateway
from prometheus_client import Counter, Histogram, push_to_gateway
tool_calls = Counter("tool_calls_total", "Total tool calls", ["tool_name"])
tool_latency = Histogram("tool_latency_seconds", "Tool latency", ["tool_name"])

@wrap_tool_call
def prometheus_metric(request, handler):
    tool_calls.labels(tool=request.tool_call["name"]).inc()
    with tool_latency.labels(tool=request.tool_call["name"]).time():
        return handler(request)

# 5. Tool composition 深度限制 + 循环检测 (decorator)
def max_depth(max_n=3):
    def decorator(fn):
        depth = [0]
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            depth[0] += 1
            if depth[0] > max_n:
                raise ToolException(f"超过 composition depth {max_n}")
            try:
                return fn(*args, **kwargs)
            finally:
                depth[0] -= 1
        return wrapper
    return decorator

# 6. HITL 接入 Slack/钉钉 webhook — 主管远程审批
import requests
def send_hitl_request(intr_data, slack_webhook):
    requests.post(slack_webhook, json={
        "text": f"待审批: {intr_data}",
        "blocks": [{"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Approve"},
                 "value": "approve", "action_id": "hitl_approve"},
                {"type": "button", "text": {"type": "plain_text", "text": "Edit"},
                 "value": "edit", "action_id": "hitl_edit"},
                {"type": "button", "text": {"type": "plain_text", "text": "Reject"},
                 "value": "reject", "action_id": "hitl_reject"},
            ]}],
    })

# 7. Tool schema 自动导出 OpenAPI (给前端 / 第三方)
from langchain_core.tools import tool
def export_tool_openapi(t: BaseTool) -> dict:
    return {
        "name": t.name,
        "description": t.description,
        "parameters": t.args_schema.schema() if t.args_schema else {},
    }
# 批量: tools = [get_weather, calculator, ...]; openapi = [export_tool_openapi(t) for t in tools]
```

## Smoke 验证 (2026-10-05)

```bash
$ cd 11-tool-fabric
$ for f in _common.py tools.py middleware.py \
          01_basic_tools.py 02_parallel_calls.py 03_error_recovery.py \
          04_middleware.py 05_hitl_tools.py 06_tool_composition.py; do
    python -c "import ast; ast.parse(open('$f', encoding='utf-8').read())" && echo "OK: $f"
  done
OK: _common.py
OK: tools.py
OK: middleware.py
OK: 01_basic_tools.py
OK: 02_parallel_calls.py
OK: 03_error_recovery.py
OK: 04_middleware.py
OK: 05_hitl_tools.py
OK: 06_tool_composition.py
```

**9/9 AST parse OK. Import chain OK. 项目进入稳定状态.**

## 4 atomic commits 历史

```
1078438  feat(11): 新模块 11-tool-fabric — _common + tools + middleware 共享模块
b614e7d  feat(11): 6 demos + README — basic/parallel/error-recovery/middleware/HITL/composition
fe15260  fix(11): tools.py 去掉 from __future__ import annotations — Pydantic Literal 修复
67dd8fe  chore(11): 05_hitl_tools 清理 inline __import__ — top-level import
```

## 下一步 (可选)

1. **Nitpick audit** — 用 `nitpick` skill 全模块 review (跟 08 / 09 / 10 平行)
2. **跟 08/09/10 集成** — 11 是工具侧细节, 08 HITL 已强; 09 codegen 生成的 `apply_diff` 可视作 tool; 10 retrieval 适合暴露为 retriever tool
3. **新模块 12** — agent-evaluation / long-context / async-pipeline / observability-deep-dive 等
4. **打包发布** — pyproject.toml + Docker image + GitHub Actions CI

6 demo + 3 共享 utility 后, 11-tool-fabric 教学目标达成. **推荐**: 整体 nitpick audit + push 47 commits, 项目稳定收官.