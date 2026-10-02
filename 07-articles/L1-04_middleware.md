# L1-04 · Middleware 横切:AOP 思想在 Agent 上的实现

> LangChain 1.x 的 Middleware 就是 Agent 版的 Spring AOP / Gin middleware。在 LLM 调用 / 工具执行的前后插桩,做日志、PII 脱敏、限流、token 计数、安全护栏、HITL,业务代码完全无侵入。

## 为什么学这个

写过 Spring 的都知道 `@Transactional` / `@Cacheable` 这种 AOP 注解——业务方法不用改,横切逻辑自动生效。LangChain 1.x 的 Middleware 是同一个思想,但横切的不是 HTTP 请求,而是 LLM 调用 / 工具执行 / 节点进入。

生产里 Agent 系统 80% 的需求都用 Middleware 实现:

- 审计日志(谁在什么时候调了 LLM)
- PII 脱敏(手机号 / 身份证不能发给模型)
- token 计数 / 成本监控
- 限流 / 风控
- HITL 危险工具审批
- 长对话自动摘要
- 输出过滤 / 安全护栏

这篇拆 8 个 hook,从最简到 production-grade。

## 学完你能回答 8 个问题

1. `@dynamic_prompt` 怎么根据请求动态生成 system prompt?
2. `@wrap_model_call` 怎么拦截模型调用?
3. `@before_model` / `@after_model` 比 `wrap_model_call` 简单在哪?
4. `@wrap_tool_call` 怎么拦截工具执行?
5. `HumanInTheLoopMiddleware` 怎么给危险工具加审批?
6. `SummarizationMiddleware` 怎么自动压缩长对话?
7. 多个 middleware 的执行顺序是怎样的?
8. 怎么写自定义 middleware 做 PII 脱敏?

## 1. `@dynamic_prompt` — 动态 prompt

```python
from langchain.agents.middleware import dynamic_prompt

@dynamic_prompt
def tone_prompt(request):
    """根据请求动态选择语气. request 含 .messages / .model / .tools."""
    user_msg = next(
        (m.content for m in request.messages if isinstance(m, HumanMessage)),
        "",
    )
    if "正式" in user_msg:
        return "你用正式语气回答,使用'您'。"
    if "轻松" in user_msg:
        return "你用轻松幽默的语气回答,可以用 emoji。"
    return "你正常回答。"

agent = create_agent(model=llm, tools=[], middleware=[tone_prompt])

agent.invoke({"messages": [HumanMessage("正式介绍一下 LangChain")]})
agent.invoke({"messages": [HumanMessage("轻松介绍一下 LangChain")]})
```

`request` 包含:
- `.messages` — 当前 messages
- `.model` — 调用的 model
- `.tools` — 可用工具列表
- `.runtime.context` — 注入的 context

实战多租户场景:根据 `request.runtime.context.tenant_id` 选不同品牌指南。

## 2. `@wrap_model_call` — 完全控制模型调用

最 powerful 的 hook,可以改 request / 重试 / fallback:

```python
from langchain.agents.middleware import wrap_model_call

@wrap_model_call
def log_and_rewrite(request, handler):
    """打日志 + 强制中文回复。"""
    print(f"→ 调 LLM, {len(request.messages)} 条消息")

    # 调用前:可改 request(加 system / 改 user / 切模型)
    if not any(isinstance(m, SystemMessage) for m in request.messages):
        request.messages.insert(0, SystemMessage(content="你必须用中文回答。"))

    # 调真正的模型 — 这一行必须存在,否则 agent 不工作
    response = handler(request)

    # 调用后处理:改 response / 重试 / 缓存
    last = response.result[0] if response.result else None
    print(f"← LLM 回复, {len(last.content) if last else 0} 字符")
    return response
```

实战场景:

| 用途 | 做法 |
| --- | --- |
| token 用量统计 | 读 `response.usage` |
| fallback:第一次失败换模型 | try/except + handler |
| 输出过滤 | 扫 response 敏感词 raise |
| A/B 实验 | 不同 user 走不同 model |

## 3. `@before_model` / `@after_model` — 简化版

只想看 state、不改 request 时用简化版:

```python
from langchain.agents.middleware import before_model, after_model

@before_model
def log_before(state, runtime):
    """调 LLM 前打日志. 不改 state."""
    print(f"准备调 LLM, 消息数: {len(state['messages'])}")
    return None  # 不改 state,返回 dict 才改

@after_model
def log_after(state, runtime):
    """LLM 返回后打日志."""
    last = state["messages"][-1]
    print(f"LLM 返回: {(last.content or '')[:60]}...")
    return None
```

| 类型 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| `before/after_model` | 看 state、加日志、改 state | 改 request、换模型、重试 |
| `wrap_model_call` | 上面所有 + 完全控制 | 需要写 `handler(request)` |

> 💡 **实战原则**:横切需求 80% 用 `before/after_model` 就够,只有"改模型 / 重试 / fallback"才用 `wrap_model_call`。

## 4. `@wrap_tool_call` — 拦截工具执行

工具执行的横切点,做权限 / 超时 / 重试 / metric:

```python
@wrap_tool_call
def tool_call_logger(request, handler):
    """打日志 + 模拟超时控制。"""
    tool_name = request.tool_call["name"]
    tool_args = request.tool_call["args"]
    print(f"→ 调工具: {tool_name}({tool_args})")

    try:
        response = handler(request)  # 真的执行工具
        content = getattr(response, "content", str(response))
        print(f"← 工具返回: {str(content)[:80]}")
        return response
    except Exception as e:
        print(f"✗ 工具失败: {type(e).__name__}: {e}")
        raise
```

⚠️ 注意 `wrap_tool_call` 的 handler **直接返回 `ToolMessage` / `Command`**,有 `.content`,**没有 `.result`**。跟 `wrap_model_call` 不一样。

实战场景:

| 用途 | 做法 |
| --- | --- |
| 权限检查(RBAC) | 拒绝特定 user 调特定 tool |
| 超时控制 | `asyncio.wait_for(handler, timeout=1.0)` |
| 重试 | `tenacity` 库 |
| 上报 metric | latency / success rate → Prometheus |

## 5. `HumanInTheLoopMiddleware` — 危险工具审批

```python
from langchain.agents.middleware import HumanInTheLoopMiddleware

agent = create_agent(
    model=llm,
    tools=[refund_order],  # 退款是危险工具
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "refund_order": {
                    "allowed_decisions": ["approve", "edit", "reject"],
                },
            },
        ),
    ],
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "hitl-demo"}}
agent.invoke({"messages": [HumanMessage("帮订单 #12345 退款 100 元")]}, config=config)

state = agent.get_state(config)
if state.next:
    print(f"暂停在: {state.next}")
    # 主管审批
    result = agent.invoke(
        Command(resume={"decisions": [{"type": "approve"}]}),
        config=config,
    )
```

三种决策:

| 决策 | 含义 |
| --- | --- |
| `approve` | 通过,执行工具 |
| `edit` | 修改参数(金额 / 收货地址) |
| `reject` | 拒绝,把拒绝理由回给 LLM |

> ⚠️ L1-03 那个坑再说一次:小模型(M3)经常不调工具,interrupt 根本不触发,`resume` 会挂死。先 `check state.tasks` 确认。

## 6. `SummarizationMiddleware` — 长对话压缩

```python
from langchain.agents.middleware import SummarizationMiddleware

agent = create_agent(
    model=llm,
    tools=[],
    middleware=[
        SummarizationMiddleware(
            model=llm,
            max_tokens_before_summary=4000,   # 总 token 超这个 → 触发摘要
            messages_to_keep=4,                # 保留最近 N 条
            summary_prompt="...",              # 自定义摘要 prompt(可选)
        ),
    ],
)
```

摘要 vs 截断对比:

| 方式 | 优点 | 缺点 |
| --- | --- | --- |
| 截断(truncate) | 简单 | LLM 不知道历史 |
| 摘要(summarize) | LLM 从 SystemMessage 看历史要点 | 多一次 LLM 调用 |

阈值经验:

| LLM | context window | 建议阈值 |
| --- | --- | --- |
| GPT-4o | 128k | 80000 |
| Claude | 200k | 120000 |
| 国产推理模型(M3/R1) | 32k~128k | 20000 |

## 7. middleware 执行顺序

```python
@before_model
def mw_a(state, runtime):
    print("    [mw_a] before_model")
    return None

@before_model
def mw_b(state, runtime):
    print("    [mw_b] before_model")
    return None

agent = create_agent(model=llm, tools=[], middleware=[mw_a, mw_b])
agent.invoke({"messages": [HumanMessage("hi")]})
# 输出: [mw_a] → [mw_b] → LLM
```

顺序规则:

| 类型 | 顺序 |
| --- | --- |
| `before_model` | 列表顺序执行(a → b → ... → LLM) |
| `after_model` | 列表顺序执行(LLM → c → d) |
| `wrap_model_call` | 嵌套调用——最先声明的最外层 |

> ⚠️ middleware 顺序敏感:改顺序 = 改行为。PII 脱敏要在最外层(所有其他 hook 看到的都是脱敏后的内容)。

## 8. 自定义 middleware:实战 PII 脱敏

```python
import re
from langchain.agents.middleware import wrap_model_call

PHONE_RE = re.compile(r"1[3-9]\d{9}")

@wrap_model_call
def redact_phone_numbers(request, handler):
    """把用户消息里的手机号脱敏再发给 LLM。"""
    for m in request.messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            m.content = PHONE_RE.sub("1XX-XXXX-XXXX", m.content)
    return handler(request)

agent = create_agent(model=llm, tools=[], middleware=[redact_phone_numbers])

result = agent.invoke({
    "messages": [HumanMessage("我的手机号是 13800138000, 请帮我记一下")]
})
```

完整版 PII 脱敏(手机 / 邮箱 / 身份证 / 银行卡):

```python
import re
from langchain.agents.middleware import wrap_model_call

PHONE_RE = re.compile(r"1[3-9]\d{9}")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
ID_RE = re.compile(r"\d{17}[\dXx]")

@wrap_model_call
def pii_redaction(request, handler):
    """生产级 PII 脱敏 — 所有 agent 都生效。"""
    for m in request.messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            content = m.content
            content = PHONE_RE.sub("1XX-XXXX-XXXX", content)
            content = EMAIL_RE.sub("xxx@example.com", content)
            content = ID_RE.sub("XXXXXXXXXXXXXXXXXX", content)
            m.content = content
    return handler(request)
```

这套 middleware 加到 create_agent 后,**所有 specialist agent 都自动生效**,不用每个 agent 加一遍。

## 实战踩坑

| 坑 | 原因 | 解法 |
| --- | --- | --- |
| middleware 不生效 | 装饰器名字写错 | 必须 `@wrap_model_call` / `@before_model` 等 |
| `wrap_tool_call` 没有 `.result` | 它返回 ToolMessage | `getattr(response, "content", ...)` |
| Summarization 摘要慢 | 阈值设太低 | 阈值按 context window 50-60% 设 |
| HITL resume 挂死 | 模型没调工具 | 先 `state.tasks` 检查 |
| PII 漏脱敏 | 中间件顺序错 | PII 放最外层 |
| 多个 before_model 顺序乱 | 没看文档 | 列表顺序 = 执行顺序 |

## 生产架构

```python
agent = create_agent(
    model=llm,
    tools=business_tools,
    middleware=[
        # 最外层:全局安全
        pii_redaction_mw,
        rate_limit_mw,
        # 日志 / 监控
        logging_mw,
        token_count_mw,
        # 业务横切
        dynamic_business_prompt_mw,
        # 长对话
        SummarizationMiddleware(model=llm, max_tokens_before_summary=80000),
        # 危险工具
        HumanInTheLoopMiddleware(interrupt_on={"refund": {...}}),
    ],
)
```

middleware 顺序的设计原则:**先全局(安全 / 日志),再业务(动态 prompt),最后兜底(摘要 / HITL)**。

## 小结

- Middleware 是 Agent 版的 AOP,横切逻辑不改业务代码
- 4 个核心 hook:`@before_model` / `@after_model` / `@wrap_model_call` / `@wrap_tool_call`
- 内置:`HumanInTheLoopMiddleware`(危险工具审批)+ `SummarizationMiddleware`(长对话压缩)
- `@dynamic_prompt` 根据请求动态生成 system prompt
- PII 脱敏用 `@wrap_model_call` 改 messages,所有 specialist 自动生效
- middleware 顺序敏感,PII 放最外层

middleware 解决了"Agent 怎么生产化"。下一步是给 Agent 接**私有知识库**——下一篇 RAG 展开讲。

## 延伸阅读

- [LangChain Middleware 官方文档](https://python.langchain.com/docs/concepts/middleware/)
- 上一篇:[L1-03 create_agent 一统天下](./L1-03_agents.md)
- 下一篇:[L1-05 RAG 入门](./L1-05_retrieval.md)
- 源码:`01-langchain-basics/04_middleware.py`
