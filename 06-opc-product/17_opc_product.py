"""17_opc_product.py — OPC (One Person Company) AI 客服中心 端到端 Demo.

整合 L1-L5 所有能力:
  - L1: Tools / Agents / Middleware (PII) / Retrieval (RAG)
  - L2: StateGraph / Persistence / Interrupt (HITL) / Streaming
  - L3: LangSmith Trace (自动)
  - L4: Multi-Agent Supervisor
  - L5: Deep Agent (可选)

业务场景:
  客户提问 → Supervisor 路由 → 售前/售后/技术 Agent
              售前: 走 RAG 知识库
              售后: 普通查询直接答, 退款 > 100 触发 HITL
              技术: 简单技术问题直答

学完这个模块你能回答:
 1. 怎么用 LangGraph + Supervisor + create_agent 搭端到端客服?
 2. 怎么把 RAG / 中间件 / HITL / 流式 / LangSmith 整合到一起?
 3. 怎么让 PII 脱敏对所有 agent 都生效?
 4. 怎么让大额退款自动触发主管审批?
 5. 怎么用 token 流式输出让前端"打字机"显示?
 6. 怎么用 PostgresSaver 持久化多轮会话?
 7. 怎么在前端展示 Supervisor 路由决策?
 8. 怎么从 mock 数据升级到真实业务系统?
 9. 怎么用 LangSmith 监控生产质量?
10. 怎么把 demo 包装成生产服务 (Docker + FastAPI)?

跑法:
    pip install -r ../requirements.txt
    python 17_opc_product.py

设置 LANGSMITH_API_KEY 后, 跑完到 https://smith.langchain.com 看 trace。
"""
from __future__ import annotations

import os
import re
import sys
from typing import Literal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt
from langchain_text_splitters import RecursiveCharacterTextSplitter

from _common import banner, get_llm

# ============================================================
# 1. 准备产品知识库 (RAG) — L1 retrieval
# ============================================================
banner("1. 准备产品知识库 (RAG)")


_PRODUCT_DOCS = {
    "pricing.txt": """
产品定价

基础版: ¥99/月
  - 5 个用户席位
  - 10GB 存储
  - 邮件支持

专业版: ¥499/月
  - 20 个用户席位
  - 100GB 存储
  - 7x24 工单支持
  - 自定义域名

企业版: ¥2999/月
  - 不限用户席位
  - 1TB 存储
  - 专属客户经理
  - SLA 99.99%

年付优惠: 8 折
""",
    "refund_policy.txt": """
退订政策

1. 购买后 7 天内, 未使用可全额退款。
2. 购买后 7-30 天, 按未使用月份退款 (扣除 10% 手续费)。
3. 30 天后不支持退款。
4. 企业版按合同执行。
""",
    "faq.txt": """
常见问题

Q: 支持哪些支付方式?
A: 支付宝、微信支付、信用卡、银行转账。

Q: 可以开发票吗?
A: 可以, 在账单页面申请, 3 个工作日内开出。

Q: 数据存储在哪里?
A: 中国大陆 (阿里云上海), 符合等保三级。

Q: 是否支持私有部署?
A: 企业版支持私有部署, 详询销售。
""",
}


def build_knowledge_base():
    """把产品文档加载、切块、向量化."""
    docs: list[Document] = []
    for fname, content in _PRODUCT_DOCS.items():
        docs.append(Document(page_content=content, metadata={"source": fname}))

    splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=20)
    chunks = splitter.split_documents(docs)

    # 用 safe embedding (M3 不支持时降级到 fake)
    from langchain_openai import OpenAIEmbeddings
    from langchain_community.embeddings import DeterministicFakeEmbedding

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("MINIMAX_BASE_URL")
    try:
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
        )
        embeddings.embed_query("test")  # 探测
    except Exception as e:
        print(f">>> [降级] 真实 embedding 不可用 ({type(e).__name__}), 用 fake")
        embeddings = DeterministicFakeEmbedding(size=384)

    vectorstore = FAISS.from_documents(chunks, embeddings)
    print(f">>> 知识库 chunks: {len(chunks)}")
    return vectorstore.as_retriever(search_kwargs={"k": 2})


# ============================================================
# 2. 工具定义 — 模拟业务系统
# ============================================================
banner("2. 工具定义")


@tool
def search_knowledge_base(query: str) -> str:
    """搜索产品知识库 (定价/退订/FAQ)。"""
    docs = _retriever.invoke(query)
    if not docs:
        return "知识库无结果"
    return "\n\n".join(
        f"[来源 {d.metadata.get('source', '?')}] {d.page_content}" for d in docs
    )


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
    """(mock) 升级到人工客服."""
    return f"[已升级] 转人工处理, 原因: {reason}"


# ============================================================
# 3. PII 脱敏 Middleware (L1)
# ============================================================
banner("3. PII 脱敏 Middleware")


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
                "xxx@example.com",
                content,
            )
            # 身份证
            content = re.sub(r"\d{17}[\dXx]", "XXXXXXXXXXXXXXXXXX", content)
            m.content = content
    return handler(request)


# ============================================================
# 4. 三个专家 Agent 子图
# ============================================================
banner("4. 三个专家 Agent")


def make_specialist(name: str, tools: list, system_prompt: str):
    """工厂: create_agent + middleware."""
    agent = create_agent(
        model=get_llm(),
        tools=tools,
        system_prompt=system_prompt,
        middleware=[pii_redaction_middleware],
    )
    return agent


def sales_agent_node(state: MessagesState) -> Command:
    """售前专家: 用 RAG 答产品问题。"""
    agent = make_specialist(
        "售前专家",
        [search_knowledge_base],
        "你是售前专家。用户问产品功能、价格、FAQ 时, 必须先调 "
        "search_knowledge_base 工具,然后基于返回内容回答,引用来源。",
    )
    result = agent.invoke({"messages": state["messages"]})
    last = result["messages"][-1]
    return Command(goto="END", update={"messages": [last]})


def support_agent_node(state: MessagesState) -> Command:
    """售后专家: 查订单 + 退款(HITL)。"""
    last_msg = state["messages"][-1]
    if isinstance(last_msg, HumanMessage) and "退款" in last_msg.content:
        # 解析金额, 触发 HITL
        m = re.search(r"(\d+)\s*元", last_msg.content)
        amount = float(m.group(1)) if m else 0.0

        if amount > 100:
            decision = interrupt(
                {
                    "type": "refund_approval",
                    "amount": amount,
                    "request": last_msg.content,
                    "question": f"客户申请退款 {amount} 元, 是否批准?",
                }
            )
            if decision != "approve":
                return Command(
                    goto="END",
                    update={
                        "messages": [
                            AIMessage(content=f"[售后] 退款被拒绝: {decision}")
                        ]
                    },
                )

    agent = make_specialist(
        "售后专家",
        [check_order, refund_order, escalate_to_human],
        "你是售后专家。查订单用 check_order, 退款用 refund_order, "
        "复杂问题用 escalate_to_human 升级。",
    )
    result = agent.invoke({"messages": state["messages"]})
    last = result["messages"][-1]
    return Command(goto="END", update={"messages": [last]})


def tech_agent_node(state: MessagesState) -> Command:
    """技术专家: 答 API/技术问题。"""
    agent = make_specialist(
        "技术专家",
        [search_tech_docs],
        "你是技术专家。回答 API、报错、架构问题, 必要时调 search_tech_docs。",
    )
    result = agent.invoke({"messages": state["messages"]})
    last = result["messages"][-1]
    return Command(goto="END", update={"messages": [last]})


# ============================================================
# 5. Supervisor — 中央路由 (L4)
# ============================================================
banner("5. Supervisor 路由")


SUPERVISOR_PROMPT = """你是 Supervisor, 把用户问题分类到:
- sales:   产品功能、价格、FAQ、退订政策
- support: 订单状态、退款申请、物流
- tech:    API 报错、技术原理、架构
- __end__: 不清楚/不相关

只返回分类名 (sales / support / tech / __end__)。

用户问题: {question}"""


def supervisor_route(state: MessagesState) -> Literal["sales", "support", "tech", "__end__"]:
    """根据用户最新问题, LLM 决定派给哪个专家."""
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage):
        return "__end__"

    llm = get_llm()
    decision = llm.invoke(SUPERVISOR_PROMPT.format(question=last.content)).content.strip().lower()

    print(f"    [supervisor] 路由决策: {decision}")
    if "sales" in decision:
        return "sales"
    if "tech" in decision:
        return "tech"
    if "support" in decision:
        return "support"
    return "__end__"


# ============================================================
# 6. 拼 OPC 主图 (L2 StateGraph + L4 Supervisor + L1 PII)
# ============================================================
banner("6. 拼 OPC 主图")


def build_opc_graph():
    """整合 L1-L4 全部能力."""
    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", lambda s: s)
    graph.add_node("sales", sales_agent_node)
    graph.add_node("support", support_agent_node)
    graph.add_node("tech", tech_agent_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        supervisor_route,
        {"sales": "sales", "support": "support", "tech": "tech", "__end__": END},
    )
    graph.add_edge("sales", END)
    graph.add_edge("support", END)
    graph.add_edge("tech", END)

    return graph.compile(checkpointer=InMemorySaver())


# ============================================================
# 7. 演示 — 5 种典型场景
# ============================================================
banner("7. 演示 — 5 种典型场景")


def scenario_1_sales(app, thread_id: str) -> None:
    """场景 1: 售前咨询 (走 RAG)."""
    print(">>> 客户: 你们产品多少钱? 包含什么功能?")
    config = {"configurable": {"thread_id": thread_id}}

    for chunk in app.stream(
        {"messages": [HumanMessage("你们产品多少钱? 包含什么功能?")]},
        config=config,
        stream_mode="values",
    ):
        if chunk.get("messages"):
            last = chunk["messages"][-1]
            if hasattr(last, "content") and last.content and isinstance(last, AIMessage):
                print(f"    [AI] {last.content[:120]}")
    print()


def scenario_2_order(app, thread_id: str) -> None:
    """场景 2: 售后订单查询."""
    print(">>> 客户: 我的订单 #123 在哪?")
    config = {"configurable": {"thread_id": thread_id}}

    for chunk in app.stream(
        {"messages": [HumanMessage("我的订单 #123 在哪?")]},
        config=config,
        stream_mode="values",
    ):
        if chunk.get("messages"):
            last = chunk["messages"][-1]
            if hasattr(last, "content") and last.content and isinstance(last, AIMessage):
                print(f"    [AI] {last.content[:120]}")
    print()


def scenario_3_refund_hitl(app, thread_id: str) -> None:
    """场景 3: 退款 + HITL."""
    print(">>> 客户: 我要退订单 #123, 退款 250 元")
    config = {"configurable": {"thread_id": thread_id}}

    print("    [Step 1] Agent 调用 refund_order, 金额 > 100, 触发 HITL")
    result = app.invoke(
        {"messages": [HumanMessage("我要退订单 #123, 退款 250 元")]},
        config=config,
    )

    state = app.get_state(config)
    if state.next:
        print(f"    [Step 2] Agent 暂停, 等主管审批")
        if state.tasks and state.tasks[0].interrupts:
            interrupt_val = state.tasks[0].interrupts[0].value
            print(f"    [Step 2.1] 待审批: {interrupt_val.get('question')}")

        print("    [Step 3] 主管审批: approve")
        result = app.invoke(Command(resume="approve"), config=config)
        print(f"    [Step 4] 最终回复: {result['messages'][-1].content[:120]}")
    else:
        print(f"    (Agent 没暂停) 最后: {result['messages'][-1].content[:120]}")
    print()


def scenario_4_tech(app, thread_id: str) -> None:
    """场景 4: 技术问题."""
    print(">>> 客户: API 返回 401 错误, 怎么办?")
    config = {"configurable": {"thread_id": thread_id}}

    result = app.invoke(
        {"messages": [HumanMessage("API 返回 401 错误, 怎么办?")]},
        config=config,
    )
    print(f"    [AI] {result['messages'][-1].content[:120]}")
    print()


def scenario_5_pii(app, thread_id: str) -> None:
    """场景 5: PII 脱敏 (L1 middleware 验证)."""
    print(">>> 客户: 我的手机 13800138000, 邮箱 test@example.com, 帮我查订单")
    config = {"configurable": {"thread_id": thread_id}}

    result = app.invoke(
        {"messages": [HumanMessage("我的手机 13800138000, 邮箱 test@example.com, 帮我查订单 #456")]},
        config=config,
    )
    print(f"    [AI] {result['messages'][-1].content[:120]}")
    print("    (注意: 上面 PII 已被 middleware 脱敏再发给 LLM)")
    print()


# ============================================================
# 8. 多轮对话 — 同 thread 自动续 history
# ============================================================
banner("8. 多轮对话 — 同 thread_id 自动续 history")


def scenario_6_multi_turn(app, thread_id: str) -> None:
    """演示 InMemorySaver 怎么保留上下文."""
    config = {"configurable": {"thread_id": thread_id}}

    print(">>> 第 1 轮: 自我介绍")
    r1 = app.invoke({"messages": [HumanMessage("我叫王明, 北京人")]}, config=config)
    print(f"    [AI] {r1['messages'][-1].content[:80]}")

    print(">>> 第 2 轮: 问之前的名字 (supervisor 重新路由到 sales 答通用问题)")
    r2 = app.invoke({"messages": [HumanMessage("我叫什么?")]}, config=config)
    print(f"    [AI] {r2['messages'][-1].content[:80]}")

    print(">>> 第 3 轮: 问订单 (同 thread, supervisor 路由到 support)")
    r3 = app.invoke({"messages": [HumanMessage("我的订单 #456 在哪?")]}, config=config)
    print(f"    [AI] {r3['messages'][-1].content[:80]}")
    print()


# ============================================================
# 9. Token 流式 — 前端"打字机"
# ============================================================
banner("9. Token 流式输出 (stream_mode='messages')")


def scenario_7_token_stream(app, thread_id: str) -> None:
    """用 messages mode 流式输出, 像 ChatGPT 那样一个字一个字蹦."""
    config = {"configurable": {"thread_id": thread_id}}

    print(">>> 客户: 介绍 LangGraph 3 大特性")
    print(">>> AI (流式): ", end="", flush=True)
    for token, metadata in app.stream(
        {"messages": [HumanMessage("用 30 字介绍 LangGraph")]},
        config=config,
        stream_mode="messages",
    ):
        if hasattr(token, "content") and token.content:
            print(token.content, end="", flush=True)
    print("\n")


# ============================================================
# 10. LangSmith 集成 (L3)
# ============================================================
banner("10. LangSmith 集成 (L3)")


def demo_langsmith_integration() -> None:
    """演示 LangSmith 自动 trace 怎么工作."""
    if os.getenv("LANGSMITH_API_KEY"):
        print("[OK] LANGSMITH_API_KEY 已配置, 所有 invoke 自动上报")
        print(f"  project: {os.getenv('LANGSMITH_PROJECT', 'default')}")
        print(">>> 去 https://smith.langchain.com 看:")
        print("  - 每个 Supervisor 路由决策")
        print("  - 每个 Specialist Agent 的 LLM 调用")
        print("  - 每次工具调用 (search_kb / refund / etc.)")
        print("  - 每次 HITL interrupt + resume")
        print("  - 每个 thread 的完整时间线")
    else:
        print("[WARN] 未配置 LANGSMITH_API_KEY")
        print(">>> 配置后, 上面的 invoke 会自动上报到 LangSmith:")
        print("  export LANGSMITH_TRACING=true")
        print("  export LANGSMITH_API_KEY=lsv2_pt_...")
        print("  export LANGSMITH_PROJECT=opc-prod")


# ============================================================
# 11. Metrics / 可观测性
# ============================================================
banner("11. Metrics — 生产质量监控")


def demo_metrics() -> None:
    """实战监控指标."""
    print(
        """
    必看指标 (生产环境):

    ┌──────────────────────┬────────────────┬──────────────────┐
    │ 指标                 │ 怎么算          │ 用途              │
    ├──────────────────────┼────────────────┼──────────────────┤
    │ 路由分布             │ 统计 supervisor │ 看问题都去哪      │
    │ (sales/support/tech) │   路由结果     │ 调整专家团队      │
    ├──────────────────────┼────────────────┼──────────────────┤
    │ HITL 触发率          │ interrupt 次数 │ 高 = 信任度低     │
    │                      │ / 总次数       │ 调 prompt / 阈值  │
    ├──────────────────────┼────────────────┼──────────────────┤
    │ 单次对话 cost        │ Σ LLM token    │ 控制成本          │
    │                      │ * 单价          │                  │
    ├──────────────────────┼────────────────┼──────────────────┤
    │ 用户满意度           │ 👍/👎 反馈      │ 评估整体质量      │
    ├──────────────────────┼────────────────┼──────────────────┤
    │ RAG 召回命中率       │ 搜出来的 doc    │ 调 chunk_size /  │
    │                      │ 是否被引用      │ embedding         │
    ├──────────────────────┼────────────────┼──────────────────┤
    │ 错误率               │ 5xx / 总请求    │ SLA 报警          │
    └──────────────────────┴────────────────┴──────────────────┘

    落地:
      - LangSmith: trace / feedback / score
      - Prometheus: 业务指标 (路由 / HITL / cost)
      - 飞书/Slack: 报警 (错误率 / 慢请求)
    """
    )


# ============================================================
# 12. 从 Mock 到生产 — 升级路径
# ============================================================
banner("12. 从 Mock 到生产 — 升级路径")


def demo_mock_to_production() -> None:
    print(
        """
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
    """
    )


# ============================================================
# 13. 生产架构 — 完整 snippet
# ============================================================
banner("13. 生产架构 — FastAPI + LangGraph 整合")


def demo_production_snippet() -> None:
    snippet = """
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
        '''SSE 流式聊天'''
        async def gen():
            async for chunk in opc_app.astream(
                {"messages": [HumanMessage(message)]},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="messages",
            ):
                token, meta = chunk
                if hasattr(token, "content") and token.content:
                    yield f"data: {json.dumps({'token': token.content})}\\n\\n"
            yield "data: [DONE]\\n\\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/resume/{thread_id}")
    async def resume(thread_id: str, decision: str):
        '''主管审批 (HITL resume)'''
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
    """
    print(snippet)


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    # 1. 准备知识库
    _retriever = build_knowledge_base()

    # 2. 拼主图
    app = build_opc_graph()

    # 3. 跑 7 个端到端场景
    banner("=== 场景 1: 售前 RAG ===")
    scenario_1_sales(app, "user-A-sales")

    banner("=== 场景 2: 售后订单 ===")
    scenario_2_order(app, "user-A-order")

    banner("=== 场景 3: 退款 HITL ===")
    scenario_3_refund_hitl(app, "user-A-refund")

    banner("=== 场景 4: 技术支持 ===")
    scenario_4_tech(app, "user-A-tech")

    banner("=== 场景 5: PII 脱敏 ===")
    scenario_5_pii(app, "user-A-pii")

    banner("=== 场景 6: 多轮对话 ===")
    scenario_6_multi_turn(app, "user-A-multi")

    banner("=== 场景 7: Token 流式 ===")
    scenario_7_token_stream(app, "user-A-stream")

    # 4. LangSmith / Metrics / 升级路径 (文本演示)
    demo_langsmith_integration()
    demo_metrics()
    demo_mock_to_production()
    demo_production_snippet()

    print("\n" + "=" * 60)
    print("  OPC AI 产品 demo 全部跑完!")
    print("=" * 60)
    print()
    print(">>> 接下来可以扩展的方向:")
    print("  1. 把 InMemorySaver 换成 PostgresSaver, 支持跨进程持久化")
    print("  2. 加 FastAPI 后端 + SSE 流式返回 (前端打字机效果)")
    print("  3. 接 LangSmith 看 trace, 用 evaluator 评估 prompt 改动")
    print("  4. 加真实订单数据库 + 支付网关 (从 mock 升级)")
    print("  5. 包装成 Docker 镜像上线")
    print()
    if os.getenv("LANGSMITH_API_KEY"):
        print(">>> 去 https://smith.langchain.com 查看 trace")
