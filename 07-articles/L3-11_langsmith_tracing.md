# L3-11 · LangSmith Tracing:让每一步 Agent 调用都看得见

> Agent 系统跑起来之后,最怕的是"出错了不知道错在哪"。LangSmith 是 LangChain 团队的可观测平台——一行环境变量开启自动 trace,每一步 LLM 调用 / 工具执行 / 节点切换都被记录,UI 上能像 Chrome DevTools 一样层层展开。这篇拆 10 个 demo,从自动 trace 到反馈打分,生产可观测闭环。

## 为什么学这个

生产里 Agent 系统出问题,90% 是这种场景:

- 用户报告"Agent 答得不对",但不知道是 prompt 问题 / RAG 召回问题 / 模型问题
- "调 LLM 多了烧钱",但不知道哪个流程费 token
- "线上报错率升高",但 LangGraph 默认 log 不够细

LangSmith 解决三个核心问题:

1. **可观测**:每次 invoke 的完整调用树
2. **可分析**:按 user / 业务线 / 版本切片
3. **可反馈**:用户赞踩 → 离线分析 → prompt 优化

跟 Java 的 SkyWalking / Go 的 Datadog 是同一类工具,只不过 trace 的是 Agent 而不是 HTTP。

## 学完你能回答 10 个问题

1. 怎么开 LangSmith trace(环境变量)?
2. 怎么用 `@traceable` 装饰自定义函数?
3. 怎么传 metadata / tags 让 trace 更清晰?
4. 怎么在 trace 里看 tool 调用(run_type)?
5. 怎么用 Client API 拉 trace 数据做 dashboard?
6. 怎么构造 parent / child 调用树(嵌套 @traceable)?
7. 怎么用 `tracing_context` 动态控制上报?
8. 怎么给 run 打分(feedback)做离线分析?
9. 怎么区分 sampling(全量 vs 抽样上报)?
10. 实战里 LangSmith + LangGraph 怎么配合?

## 0. 环境配置

```bash
# .env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxx
LANGSMITH_PROJECT=my-agent-prod
LANGSMITH_TRACING_SAMPLING_RATE=0.1   # 10% 抽样降成本
LANGSMITH_ENDPOINT=https://api.smith.langchain.com  # 默认, 国内可能要改
```

设置后,**所有 LangChain / LangGraph 调用自动上报**——不用改业务代码。

## 1. 自动 trace — create_agent 自动埋点

```python
from langchain.agents import create_agent

agent = create_agent(model=llm, tools=[get_weather, get_time])

# invoke 时带 metadata → trace 里能按 user_id 过滤
result = agent.invoke(
    {"messages": [HumanMessage("北京天气?")]},
    config={
        "metadata": {"user_id": "user-001", "session": "demo"},
        "tags": ["production", "refund-flow"],
    },
)
```

LangSmith 会自动抓到:

- 输入 messages
- LLM 调用(prompt / response / token 数 / latency)
- tool 调用(name / args / output)
- 最终 output

去 [https://smith.langchain.com](https://smith.langchain.com) 看 trace,按 `user_id="user-001"` 过滤,能看到这个用户的所有调用。

## 2. `@traceable` 装饰自定义函数

```python
from langsmith import traceable
import time

@traceable(name="user_login")
def user_login(user_id: str, password: str) -> dict:
    """(mock) 用户登录。"""
    time.sleep(0.05)
    return {"user_id": user_id, "token": "mock-token-xxx"}

@traceable(name="fetch_user_orders")
def fetch_user_orders(user_id: str, token: str) -> list[dict]:
    """(mock) 拉用户订单。"""
    time.sleep(0.05)
    return [{"order_id": "ORD-001", "amount": 100}]

@traceable(name="compute_total")
def compute_total(orders: list[dict]) -> float:
    """(mock) 算订单总额。"""
    return sum(o["amount"] for o in orders)

# 调用时自动按调用栈嵌套
user_login("user-001", "secret")
fetch_user_orders("user-001", "token")
compute_total(...)
```

trace 树会自动长这样:

```
user_login
  └── fetch_user_orders
        └── compute_total
```

不用手动指定 parent_run_id,LangSmith 自动按调用栈嵌套。

## 3. `@traceable + metadata` — 给 trace 加标签

```python
# 装饰器写死
@traceable(name="complex_query", metadata={"version": "v1.2", "env": "dev"})
def complex_query(query: str) -> str:
    return f"query result for: {query}"

# 运行时传
@traceable
def dynamic_meta(x: int) -> int:
    return x * 2

dynamic_meta(5, metadata={"experiment": "A", "model_version": "M3-2026-09"})
```

metadata 在 LangSmith UI 里可以过滤(按版本 / 环境 / 业务标签):

| 维度 | 用途 |
|---|---|
| `version` | 区分 prompt 版本 |
| `env` | dev / staging / prod |
| `experiment` | A/B 测试 |
| `user_tier` | 用户层级(free / vip) |
| `tenant_id` | 多租户 |

## 4. `@traceable + run_type` — 控制 trace 类型

```python
@traceable(name="retrieval_step", run_type="retriever")
def retrieval_step(query: str) -> list[dict]:
    return [{"doc": f"result for {query}"}]

@traceable(name="tool_step", run_type="tool")
def tool_step(tool_input: str) -> str:
    return f"tool output for {tool_input}"

@traceable(name="llm_step", run_type="llm")
def llm_step(prompt: str) -> str:
    return f"llm output for {prompt}"
```

常用 run_type:

| run_type | 含义 | UI 图标 |
|---|---|---|
| `chain` | 普通链路节点 | 链条 |
| `llm` | LLM 调用 | 灯泡 |
| `tool` | 工具调用 | 扳手 |
| `retriever` | 检索步骤 | 放大镜 |
| `embedding` | embedding 计算 | 向量 |
| `prompt` | prompt 渲染 | 文件 |
| `parser` | 输出解析 | 齿轮 |

不同类型在 UI 里显示不同,过滤项也不同。

## 5. 手动管理 trace — Client API

```python
from langsmith import Client

client = Client()
project_name = os.getenv("LANGSMITH_PROJECT", "default")

# 列出最近的 run
runs = list(client.list_runs(
    project_name=project_name,
    limit=5,
    execution_order=1,  # 按时间倒序
))
for r in runs[:3]:
    print(f"  - {r.name} | type={r.run_type} | status={r.status} | tokens={r.total_tokens or 0}")
```

实战:

- dashboard 自动刷新(每分钟拉一次)
- 按 metadata 聚合统计
- 监控关键指标(error rate / P95 latency / token cost)

## 6. 嵌套 `@traceable` — 自动构造调用树

```python
@traceable(name="step_a")
def step_a(x: int) -> int:
    return step_b(x * 2)

@traceable(name="step_b")
def step_b(x: int) -> int:
    return step_c(x + 1)

@traceable(name="step_c")
def step_c(x: int) -> int:
    time.sleep(0.02)
    return x * 10

r = step_a(5)
# trace 树: step_a → step_b → step_c(3 层嵌套)
```

## 7. `tracing_context` — 动态控制上报

```python
from langsmith import tracing_context

@traceable
def sensitive_op(user_id: str) -> str:
    return f"handled for {user_id}"

# 1. 默认:跟着环境变量
sensitive_op("default-1")

# 2. 临时关闭(敏感操作 / 高频心跳)
with tracing_context(enabled=False):
    sensitive_op("disabled-1")  # 不上报

# 3. 临时开启 + 改 project(A/B 测试)
with tracing_context(
    enabled=True,
    project_name="ab-experiment-v2",
    metadata={"experiment": "B"},
):
    sensitive_op("experiment-B-1")  # 上报到独立 project
```

实战:

| 场景 | 做法 |
|---|---|
| 心跳 / 健康检查 | `tracing_context(enabled=False)` |
| 高频批处理 | 抽样 1% 上报 |
| A/B 测试 | 不同 experiment 走不同 project |
| 敏感操作(用户密码) | 临时关闭 |

## 8. 反馈打分 — create_feedback

```python
from langsmith import Client

client = Client()
runs = list(client.list_runs(limit=1))
if runs:
    run_id = runs[0].id
    # 打分(用户赞踩 / 自动 evaluator)
    client.create_feedback(
        run_id=run_id,
        key="user_rating",
        score=1.0,           # 1.0 = 点赞, 0.0 = 踩
        comment="demo feedback",
    )
```

实战三种场景:

| 场景 | 做法 |
|---|---|
| 线上用户反馈 | 👍/👎 → 后端 create_feedback |
| 离线 evaluator | LLM-as-judge 跑完批量打分 |
| 自动化测试 | CI 里 evaluator 写回 |

UI 里按 feedback 过滤低分 run,针对性优化。

## 9. 采样 — 抽样上报降成本

生产里 trace 全量成本太高,三种粒度:

```python
# 方式 1:环境变量控制(启动时定)
# LANGSMITH_TRACING_SAMPLING_RATE=0.01 → 1% 抽样
rate = os.getenv("LANGSMITH_TRACING_SAMPLING_RATE", "1.0")

# 方式 2:代码里手动判断
import random

@traceable
def high_volume_call(x: int) -> int:
    return x * 2

for i in range(100):
    if random.random() < 0.1:  # 10% 上报
        high_volume_call(i)

# 方式 3:关键路径全量,非关键抽样
#   @traceable 里 if important: 全量 else: 抽样
```

采样策略经验:

| 阶段 | 采样率 |
|---|---|
| 调试 / dev | 100% |
| staging | 50% |
| 生产(初期) | 10% |
| 生产(成熟) | 1% |
| 报错(自动触发) | 100% |

## 10. 生产架构 — LangSmith + LangGraph 整合

```python
# .env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=my-agent-prod
LANGSMITH_TRACING_SAMPLING_RATE=0.1

# app.py
from langchain.agents import create_agent

agent = create_agent(
    model=llm,
    tools=[...],
    checkpointer=PostgresSaver(...),  # 持久化
    store=PostgresStore(...),
)

# invoke 时带 metadata → trace 里有 user_id / session_id
config = {
    "configurable": {"thread_id": "user-001"},
    "metadata": {"user_id": "u-001", "channel": "web"},
    "tags": ["production", "refund-flow"],
}
agent.invoke({"messages": [...]}, config=config)

# 监控 dashboard:
#   - LangSmith UI 按 user_id / tag 过滤
#   - 错误 run 全部上报(用 tags=error 自动标)
#   - 慢节点(>2s)单独建一个 project
```

关键实践:

- metadata + tags:trace 检索维度(user / env / version)
- sampling:生产降成本
- feedback:用户反馈 / 自动 evaluator 写回
- project:按环境拆(dev / staging / prod)
- alerting:LangSmith webhook → 飞书 / Slack

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| `LANGSMITH_TRACING=false` 不生效 | .env 没加载 | 用 `python-dotenv` 显式 load |
| 报 `Failed to POST runs/multipart: 403` | API key 无效 / 过期 | 重新生成 key / 暂时关掉 |
| trace 树缺节点 | 没用 `@traceable` | 自定义函数全装饰 |
| A/B 测试 trace 混在一起 | 都在 default project | 用 `tracing_context(project_name=...)` |
| 抽样率生效了但看不到 | 没设 metadata | 加 metadata 才好过滤 |
| feedback 打不上分 | run_id 错 | 用 `list_runs(limit=1)` 拿真实 id |

> ⚠️ **教学阶段常见**:设置了 `LANGSMITH_API_KEY` 但 key 无效 → 每次 invoke 报 `403`。教学阶段可以在 .env 加 `LANGSMITH_TRACING_V2=false` 关掉,生产再开。

## 小结

- `LANGSMITH_TRACING=true` + API key → 自动 trace
- `@traceable` 装饰自定义函数,自动构造调用树
- metadata / tags 让 trace 可切片
- run_type 让 UI 图标 / 过滤项正确
- `tracing_context` 动态控制(关闭 / 改 project / 加 metadata)
- `create_feedback` 写回用户评分
- 抽样上报降成本(生产 1-10%)
- 生产架构:LangSmith + LangGraph + Postgres + alerting

LangSmith 是 Agent 的"X 光机"。下一步是给 Agent **装考试系统**——L3-12 Evaluation 见。

## 延伸阅读

- [LangSmith 官方文档](https://docs.smith.langchain.com/)
- 上一篇:[L2-10 Durable Execution](./L2-10_durable_execution.md)
- 下一篇:[L3-12 LangSmith Evaluation](./L3-12_langsmith_evaluation.md)
- 源码:`03-langsmith-platform/11_langsmith_tracing.py`
