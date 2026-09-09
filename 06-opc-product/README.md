# L6 — OPC AI 产品端到端 Demo

> 整合 L1-L5, 做一个**可上线形态**的 AI 产品 demo。
> 场景: **一人公司 (One Person Company) AI 客服中心**

## 业务场景

```
客户在网页上提问
    ↓
[Supervisor] 路由问题类型
    ↓         ↓            ↓
[售前 Agent]  [售后 Agent]  [技术 Agent]
   (RAG)      (HITL 退款)   (查日志)
    ↓         ↓            ↓
    └─────────┴────────────┘
              ↓
      返回给客户 (流式)
```

## 涉及的能力矩阵

| 能力 | 对应层 | 文件位置 |
|------|-------|---------|
| Tools (查订单/查天气/查 KB) | L1 | `04-…/02_tools.py` |
| Agents (create_agent) | L1 | `04-…/03_agents.py` |
| Middleware (PII 脱敏) | L1 | `04-…/04_middleware.py` |
| Retrieval (产品文档 RAG) | L1 | `04-…/05_retrieval.py` |
| StateGraph + 条件边 | L2 | `05-…/06_state_graph.py` |
| Persistence (跨轮上下文) | L2 | `05-…/07_persistence.py` |
| HITL (退款前人工审批) | L2 | `05-…/08_interrupt_hitl.py` |
| Streaming (前端打字机) | L2 | `05-…/09_streaming.py` |
| Multi-Agent Supervisor | L4 | `06-…/13_supervisor.py` |
| LangSmith Trace | L3 | `06-…/11_langsmith_tracing.py` |

## 跑起来

```bash
pip install -r ../../requirements.txt

# 可选: 开 LangSmith 看 trace
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_pt_...

python 17_opc_product.py
```

## 三种交互场景

1. **售前咨询** ("你们产品多少钱?")
   - Supervisor 路由到 sales_agent
   - sales_agent 用 RAG 查产品文档
   - 流式返回

2. **售后订单查询** ("我的订单 #123 在哪?")
   - Supervisor 路由到 support_agent
   - support_agent 调 check_order 工具
   - 直接返回

3. **退款申请** ("订单 #123 退款 200 元")
   - Supervisor 路由到 support_agent
   - support_agent 调 refund_order 工具
   - **金额 > 100 触发 HITL, 暂停等主管批**
   - 主管批后, 退款执行

## 学完 L6 你能

1. 把 6 层的能力拼成一个真实产品 demo
2. 理解"AI Agent + HITL + RAG + Multi-Agent + 持久化"如何组合
3. 拿到一个可以给投资人演示的 OPC (One Person Company) 产品雏形

## 跑完后能扩展成什么?

| 扩展方向 | 实现难度 |
|---------|---------|
| 加 FastAPI + SSE 做后端 | 1 天 |
| 加 React/Vue 前端 | 1-2 天 |
| 接真实订单数据库 (Postgres) | 0.5 天 |
| 接真实支付 (Stripe/支付宝) | 1 天 |
| 上 LangSmith Production | 0.5 天 |
| 接微信 / Slack / Web 入口 | 1 天/平台 |
