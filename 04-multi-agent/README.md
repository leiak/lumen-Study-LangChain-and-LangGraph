# L4 — Multi-Agent 编排

> 3 个模块覆盖 3 种主流 Multi-Agent 模式。
> 学完这一层,你能编排**多个 Agent 协作**完成复杂任务。

## 模块清单

| # | 文件 | 模式 | 一句话目标 |
|---|------|------|----------|
| 13 | `13_supervisor.py` | 中央调度器派发 | Supervisor 路由到专家 Agent |
| 14 | `14_handoff.py` | Agent 之间转交控制权 | 对话路由,用户被转到合适专家 |
| 15 | `15_swarm.py` | 群智,Agent 动态互通 | 探索型 / 协作型任务 |

## 什么时候用哪种?

```
              ┌──────────────────────────────────────────┐
              │ 任务清晰、流程固定                        │
              │ → Supervisor                              │
              │ → 例如: 客服系统,工单分类后转给专家        │
              └──────────────────────────────────────────┘
              ┌──────────────────────────────────────────┐
              │ 用户主导、专家之间需要"转交"                │
              │ → Handoff                                │
              │ → 例如: 销售被转给技术支持                 │
              └──────────────────────────────────────────┘
              ┌──────────────────────────────────────────┐
              │ 任务复杂、Agent 需要协商                   │
              │ → Swarm                                  │
              │ → 例如: 研究报告,各 Agent 贡献一段         │
              └──────────────────────────────────────────┘
```

## 跑起来

```bash
pip install -r ../../requirements.txt
python 13_supervisor.py
python 14_handoff.py
python 15_swarm.py
```

## 学完 L4 你能

1. 用 Supervisor 模式协调 3 个专家 Agent
2. 用 Handoff 让 Agent 互相转交
3. 用 Swarm 让 Agent 群智协作

## 关键心智模型

```
Single Agent   = 一个 LLM + tools
Multi-Agent    = 多个 Agent + Coordinator (LangGraph)

Coordinator 形式:
  - Supervisor: 一个中心节点路由
  - Handoff:    Agent 互相调用 (Command(goto=...))
  - Swarm:      任何 Agent 可联系任何 Agent
```
