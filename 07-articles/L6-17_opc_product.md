# L6-17 · OPC AI 客服中心:把 L1-L5 串成端到端产品

> 学完 L1-L5 所有 demo,怎么把它们拼成一个"能卖给客户"的产品?这篇用一个 AI 客服中心 demo 把所有能力串起来:Supervisor 路由 / 售前 RAG / 售后订单 / 退款 HITL / 技术支持 / PII 脱敏 / 多轮对话 / Token 流式 / LangSmith trace / Postgres 持久化 / FastAPI 服务化。从 mock 数据到生产升级路径全覆盖。

## 为什么学这个

学完 L1-L5 之后,最常见的问题是"怎么把它们拼起来"。demo 是分散的,产品是集成的。这篇:

- **整合**:L1 Models/Tools/Agents/Middleware/Retrieval + L2 StateGraph/Persistence/Interrupt/Streaming + L3 LangSmith + L4 Supervisor + L5 Deep Agent(可选)
- **实战**:7 个端到端场景,涵盖真实客服的典型 query
- **落地**:从 mock → 真实业务系统 → Docker 部署的完整路径

## 学完你能回答 10 个问题

1. 怎么用 LangGraph + Supervisor + create_agent 搭端到端客服?
2. 怎么把 RAG / 中间件 / HITL / 流式 / LangSmith 整合到一起?
3. 怎么让 PII 脱敏对所有 agent 都生效?
4. 怎么让大额退款自动触发主管审批?
5. 怎么用 token 流式输出让前端"打字机"显示?
6. 怎么用 PostgresSaver 持久化多轮会话?
7. 怎么在前端展示 Supervisor 路由决策?
8. 怎么从 mock 数据升级到真实业务系统?
9. 怎么用 LangSmith 监控生产质量?
10. 怎么把 demo 包装成生产服务(Docker + FastAPI)?

## 1. 准备产品知识库 (RAG) — L1 Retrieval

```python
_PRODUCT_DOCS = {
    "pricing.txt": "产品定价: 基础版 ¥99/月, 专业版 ¥499/月, 企业版 ¥2999/月, 年付 8 折...",
    "refund_policy.txt": "退订政策: 7 天内全额, 7-30 天扣 10%, 30 天后不支持...",
    "faq.txt": "常见问题: 支付方式 / 发票 / 数据存储 / 私有部署...",
}


def build_knowledge_base():
    docs = [Document(page_content=c, metadata={"source": f}) for f, c in _PRODUCT_DOCS.items()]
    splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=20)
    chunks = splitter.split_documents(docs)

    # safe embedding (M3 没 embedding 端点时降级)
    try:
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small", ...)
        embeddings.embed_query("test")  # 探测
    except Exception:
        embeddings = DeterministicFakeEmbedding(size=384)  # 降级

    return FAISS.from_documents(chunks, embeddings).as_retriever(search_kwargs={"k": 2})
```

实战三件套:

- **TextLoader / Document**:加载文本(L1-05)
- **RecursiveCharacterTextSplitter**:chunk_size=200 / overlap=20(平衡召回)
- **safe embedding 模式**:M3 没 embedding 端点,降级到 DeterministicFake

## 2. 工具定义 — 模拟业务系统

```python
@tool
def search_knowledge_base(query: str) -> str:
    """搜索产品知识库 (定价/退订/FAQ)。"""
    docs = _retriever.invoke(query)
    if not docs:
        return "知识库无结果"
    return "\n\n".join(f"[来源 {d.metadata['source']}] {d.page_content}" for d in docs)


@tool
def check_order(order_id: str) -> str:
    """(mock) 查询订单状态。"""
    mock_db = {
        "123": {"status": "已发货", "amount": 250, "eta": "明天"},
        "456": {"status": "处理中", "amount": 99, "eta": "3 天后"},
        "999": {"status": "已送达", "amount": 1500, "eta": "已送达"},
    }
    info = mock_db.get(order_id)
    if info:
        return f"订单 {order_id}: 状态={info['status']}, 金额=¥{info['amount']}, 预计={info['eta']}"
    return f"订单 {order_id} 不存在"


@tool
def refund_order(order_id: str, amount: float, reason: str) -> str:
    """(mock) 退款操作。生产环境危险, 需要 HITL 审批。"""
    return f"[已退款] 订单 {order_id} 退款 ¥{amount} 元, 原因: {reason}"


@tool
def search_tech_docs(query: str) -> str:
    """(mock) 搜索技术文档。"""
    return f"[技术文档] 关于 '{query}' 的解决方案: 检查 API key 是否正确, 然后查看错误码表。"


@tool
def escalate_to_human(reason: str) -> str:
    """(mock) 升级到人工客服。"""
    return f"[已升级] 转人工处理, 原因: {reason}"
```

实战工具原则:

| 工具 | 谁能调 |
|---|---|
| `search_knowledge_base` | 售前 |
| `check_order` / `refund_order` / `escalate_to_human` | 售后 |
| `search_tech_docs` | 技术 |

每个 specialist 只能用自己领域的工具——通过 `create_agent(tools=...)` 限制。

## 3. PII 脱敏 Middleware (L1)

```python
import re

@wrap_model_call
def pii_redaction_middleware(request, handler):
    """把用户消息里的手机号 / 邮箱 / 身份证脱敏再发给 LLM.

    注意: 这种 middleware 是全局的, 所有 specialist agent 都生效.
    """
    for m in request.messages:
        if isinstance(m, HumanMessage):
            content = m.content
            # 手机号 1XX-XXXX-XXXX
            content = re.sub(r"1[3-9]\d{9}", "1XX-XXXX-XXXX", content)
            # 邮箱
            content = re.sub(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                "xxx@example.com", content,
            )
            # 身份证
            content = re.sub(r"\d{17}[\dXx]", "XXXXXXXXXXXXXXXXXX", content)
            m.content = content
    return handler(request)
```

实战:这种 middleware 传给 `create_agent(middleware=[pii_redaction_middleware])`,**所有 specialist 自动脱敏**——一处定义,全员生效。

## 4. 三个专家 Agent 子图

```python
def make_specialist(name, tools, system_prompt):
    """工厂: create_agent + middleware."""
    return create_agent(
        model=get_llm(),
        tools=tools,
        system_prompt=system_prompt,
        middleware=[pii_redaction_middleware],
    )


def sales_agent_node(state) -> Command:
    """售前专家: 用 RAG 答产品问题。"""
    agent = make_specialist("售前", [search_knowledge_base], "你是售前, 必须先调 search_knowledge_base ...")
    result = agent.invoke({"messages": state["messages"]})
    return Command(goto="END", update={"messages": [result["messages"][-1]]})


def support_agent_node(state) -> Command:
    """售后专家: 查订单 + 退款(HITL)。"""
    last_msg = state["messages"][-1]
    if isinstance(last_msg, HumanMessage) and "退款" in last_msg.content:
        m = re.search(r"(\d+)\s*元", last_msg.content)
        amount = float(m.group(1)) if m else 0.0
        if amount > 100:
            decision = interrupt({
                "type": "refund_approval",
                "amount": amount,
                "request": last_msg.content,
                "question": f"客户申请退款 {amount} 元, 是否批准?",
            })
            if decision != "approve":
                return Command(goto="END", update={"messages": [AIMessage(f"[售后] 退款被拒绝: {decision}")]})

    agent = make_specialist("售后", [check_order, refund_order, escalate_to_human], "你是售后...")
    result = agent.invoke({"messages": state["messages"]})
    return Command(goto="END", update={"messages": [result["messages"][-1]]})


def tech_agent_node(state) -> Command:
    """技术专家: 答 API/技术问题。"""
    agent = make_specialist("技术", [search_tech_docs], "你是技术...")
    result = agent.invoke({"messages": state["messages"]})
    return Command(goto="END", update={"messages": [result["messages"][-1]]})
```

实战经验:

- 售前必须先调 search_knowledge_base(prompt 强约束)
- 售后 > 100 元自动 trigger HITL
- 技术走 search_tech_docs

## 5. Supervisor — 中央路由 (L4)

```python
SUPERVISOR_PROMPT = """你是 Supervisor, 把用户问题分类到:
- sales:   产品功能、价格、FAQ、退订政策
- support: 订单状态、退款申请、物流
- tech:    API 报错、技术原理、架构
- __end__: 不清楚/不相关

只返回分类名 (sales / support / tech / __end__)。

用户问题: {question}"""


def supervisor_route(state):
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage):
        return "__end__"

    decision = get_llm().invoke(SUPERVISOR_PROMPT.format(question=last.content)).content.strip().lower()
    print(f"    [supervisor] 路由决策: {decision}")

    if "sales" in decision: return "sales"
    if "tech" in decision: return "tech"
    if "support" in decision: return "support"
    return "__end__"
```

实战:supervisor 输出到日志 → 用户能看到"AI 正在路由到售后"。

## 6. 拼 OPC 主图 (L2 StateGraph + L4 Supervisor + L1 PII)

```python
def build_opc_graph():
    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", lambda s: s)
    graph.add_node("sales", sales_agent_node)
    graph.add_node("support", support_agent_node)
    graph.add_node("tech", tech_agent_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", supervisor_route,
        {"sales": "sales", "support": "support", "tech": "tech", "__end__": END},
    )
    graph.add_edge("sales", END)
    graph.add_edge("support", END)
    graph.add_edge("tech", END)

    return graph.compile(checkpointer=InMemorySaver())
```

**一句话整合**:L1(retrieval / tools / middleware)+ L2(StateGraph / persistence / interrupt)+ L4(supervisor)。

## 7. 演示 — 7 个端到端场景

### 场景 1: 售前 RAG

```python
scenario_1_sales(app, "user-A-sales")
# >>> 客户: 你们产品多少钱? 包含什么功能?
# >>> [AI] 我们的产品分三档: 基础版 ¥99/月 ...
# >>> [AI] (引用来源: pricing.txt)
```

### 场景 2: 售后订单查询

```python
scenario_2_order(app, "user-A-order")
# >>> 客户: 我的订单 #123 在哪?
# >>> [AI] 订单 #123 状态=已发货, 金额=¥250, 预计明天
```

### 场景 3: 退款 + HITL

```python
scenario_3_refund_hitl(app, "user-A-refund")
# >>> 客户: 我要退订单 #123, 退款 250 元
# >>> [Step 1] Agent 调 refund_order, 金额 > 100, 触发 HITL
# >>> [Step 2] Agent 暂停, 等主管审批
# >>> [Step 2.1] 待审批: 客户申请退款 250 元, 是否批准?
# >>> [Step 3] 主管审批: approve
# >>> [Step 4] 最终回复: 已退款 250 元
```

### 场景 4: 技术问题

```python
scenario_4_tech(app, "user-A-tech")
# >>> 客户: API 返回 401 错误, 怎么办?
# >>> [AI] 检查 API key 是否正确, 然后查看错误码表
```

### 场景 5: PII 脱敏

```python
scenario_5_pii(app, "user-A-pii")
# >>> 客户: 我的手机 13800138000, 邮箱 test@example.com, 帮我查订单
# >>> [AI] 您好, 已查订单 #456 ...
# (注意: 上面 PII 已被 middleware 脱敏再发给 LLM)
```

### 场景 6: 多轮对话

```python
scenario_6_multi_turn(app, "user-A-multi")
# >>> 第 1 轮: 我叫王明, 北京人
# >>> 第 2 轮: 我叫什么?
# >>> 第 3 轮: 我的订单 #456 在哪?
# (同 thread_id 自动续 history)
```

### 场景 7: Token 流式

```python
scenario_7_token_stream(app, "user-A-stream")
# >>> AI (流式): 我们的产品支持...
# (一个 token 一个 token 蹦, 前端打字机效果)
```

## 8. LangSmith 集成 (L3)

```bash
# .env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=opc-prod
```

配置后所有 invoke 自动上报,去 [smith.langchain.com](https://smith.langchain.com) 看:

- 每个 Supervisor 路由决策
- 每个 Specialist Agent 的 LLM 调用
- 每次工具调用(search_kb / refund / etc.)
- 每次 HITL interrupt + resume
- 每个 thread 的完整时间线

## 9. Metrics — 生产质量监控

| 指标 | 怎么算 | 用途 |
|---|---|---|
| 路由分布(sales/support/tech) | 统计 supervisor 路由结果 | 看问题都去哪 / 调整专家团队 |
| HITL 触发率 | interrupt 次数 / 总次数 | 高 = 信任度低 / 调 prompt / 阈值 |
| 单次对话 cost | Σ LLM token * 单价 | 控制成本 |
| 用户满意度 | 👍 / 👎 反馈 | 评估整体质量 |
| RAG 召回命中率 | 搜出来的 doc 是否被引用 | 调 chunk_size / embedding |
| 错误率 | 5xx / 总请求 | SLA 报警 |

落地:

- **LangSmith**:trace / feedback / score
- **Prometheus**:业务指标(路由 / HITL / cost)
- **飞书 / Slack**:报警(错误率 / 慢请求)

## 10. 从 Mock 到生产 — 升级路径

```
升级路径 (从 demo 到生产):

1. 持久化: InMemorySaver → PostgresSaver
   - 多副本共享 state
   - 进程重启可恢复
   - thread_id 跨设备

2. 真实业务系统: mock → 真实 API
   - search_knowledge_base → 接公司 KB / Confluence
   - check_order → 接订单 DB / ERP
   - refund_order → 接支付网关 (注意幂等性)
   - search_tech_docs → 接日志 / 监控 / 文档站

3. 认证:  无 → OAuth / JWT
   - thread_id = user_id
   - 加 user_role / permissions
   - 不同角色看到不同 agent

4. 监控:  无 → LangSmith + Prometheus
   - 路由分布 / HITL 触发率 / cost
   - 错误率 / P95 延迟
   - 用户反馈

5. 限流:  无 → 频控 + 排队
   - 同一用户 10 req/min
   - 全局 1000 req/s
   - 超限返回 fallback

6. 前端:  CLI → Web / 小程序
   - SSE / WebSocket 流式
   - 显示 Supervisor 路由
   - HITL 审批界面

7. 部署:  本地 → Docker → K8s
   - Dockerfile (Python 3.12 + 依赖)
   - docker-compose (Postgres / Redis)
   - K8s Deployment + Service + Ingress
```

## 11. 生产架构 — FastAPI + LangGraph 整合

```python
# 1. FastAPI 后端 (app.py)

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
import json

app = FastAPI()

DB = "postgresql://opc:opc@db:5432/opc"
with PostgresSaver.from_conn_string(DB) as cp:
    cp.setup()
    opc_app = build_opc_graph()
    opc_app.checkpointer = cp  # 替换成 PG


@app.post("/chat/{thread_id}")
async def chat(thread_id: str, message: str):
    """SSE 流式聊天"""
    async def gen():
        async for chunk in opc_app.astream(
            {"messages": [HumanMessage(message)]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            token, meta = chunk
            if hasattr(token, "content") and token.content:
                yield f"data: {json.dumps({'token': token.content})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/resume/{thread_id}")
async def resume(thread_id: str, decision: str):
    """主管审批 (HITL resume)"""
    result = await opc_app.ainvoke(
        Command(resume=decision),
        config={"configurable": {"thread_id": thread_id}},
    )
    return {"messages": [m.content for m in result["messages"]]}


# 2. 前端 (Next.js / React)
#    - EventSource('/chat/thread-001') 收 SSE
#    - 显示打字机效果
#    - HITL 审批界面 (弹窗, 显示 interrupt 内容)

# 3. 监控 (LangSmith)
#    LANGSMITH_TRACING=true
#    LANGSMITH_API_KEY=lsv2_pt_...

# 4. Docker
# FROM python:3.12-slim
# COPY . /app
# RUN pip install -r requirements.txt
# CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| supervisor 路由错 | free text 解析失败 | 用 Pydantic `with_structured_output` |
| PII 没脱敏 | middleware 没传给所有 agent | 工厂函数统一加 middleware |
| HITL 不触发 | refund 金额 < 100 | 调阈值 / 检查 state.tasks |
| 流式没效果 | 没用 `stream_mode="messages"` | 改 messages mode |
| 多轮上下文丢 | thread_id 没固定 | config 复用同一 thread_id |
| M3 没 embedding | 用 text-embedding-3-small 失败 | safe fallback 到 FakeEmbedding |
| LangSmith 403 | API key 无效 | 重新生成 / 暂时关掉 |

## 小结

- **L1 (Models/Tools/Agents/Middleware/Retrieval)**:`create_agent` + PII middleware + safe FAISS
- **L2 (StateGraph/Persistence/Interrupt/Streaming)**:`checkpointer=InMemorySaver` + `interrupt()` + `stream_mode="messages"`
- **L3 (LangSmith)**:env var 配置即用,自动 trace
- **L4 (Supervisor)**:free text 路由 + 3 specialist
- **L5 (Deep Agent)**:可选,长任务场景升级
- **整合**:7 个端到端场景 + 生产 FastAPI 架构 + Docker 部署
- **升级路径**:mock → 真实业务 → OAuth → 监控 → 限流 → 前端 → K8s

## 完整 L1-L6 文章列表

- **L1 基础**:[01 Models](./L1-01_models.md) / [02 Tools](./L1-02_tools.md) / [03 Agents](./L1-03_agents.md) / [04 Middleware](./L1-04_middleware.md) / [05 Retrieval](./L1-05_retrieval.md)
- **L2 编排**:[06 StateGraph](./L2-06_state_graph.md) / [07 Persistence](./L2-07_persistence.md) / [08 HITL](./L2-08_interrupt_hitl.md) / [09 Streaming](./L2-09_streaming.md) / [10 Durable Execution](./L2-10_durable_execution.md)
- **L3 平台**:[11 Tracing](./L3-11_langsmith_tracing.md) / [12 Evaluation](./L3-12_langsmith_evaluation.md)
- **L4 多 Agent**:[13 Supervisor](./L4-13_supervisor.md) / [14 Handoff](./L4-14_handoff.md) / [15 Swarm](./L4-15_swarm.md)
- **L5 高级**:[16 Deep Agents](./L5-16_deep_agents.md)
- **L6 产品**:17 OPC 端到端 demo(本文)

## 延伸阅读

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [LangSmith 官方文档](https://docs.smith.langchain.com/)
- 上一篇:[L5-16 Deep Agents](./L5-16_deep_agents.md)
- 源码:`06-opc-product/17_opc_product.py`

跑完这个 demo,回头看 L1-L5,会发现一切都连起来了——这就是 LangChain 1.x + LangGraph 1.x 的工程化全景。
