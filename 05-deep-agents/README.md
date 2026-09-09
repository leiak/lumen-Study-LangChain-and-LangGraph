# L5 — Deep Agents

> Deep Agents 是 LangChain 官方在 LangGraph 之上封装的**高级 Agent Harness**。
> 自动包含 planning、subagents、virtual filesystem、context management。

## 模块清单

| # | 文件 | 关键能力 |
|---|------|---------|
| 16 | `16_deep_agents.py` | `create_deep_agent` 一行起手 + planning + subagents + FS |

## Deep Agents vs 普通 Agent

| 维度 | 普通 Agent (`create_agent`) | Deep Agents |
|------|--------------------------|-------------|
| 自动规划 | ❌ | ✅ (内部 TODO 管理) |
| 虚拟文件系统 | ❌ | ✅ (write/read/ls/edit) |
| Subagents | ❌ | ✅ (内置 task 工具委派) |
| Context 管理 | ❌ | ✅ (自动摘要) |
| 复杂任务 | 5-10 步容易丢上下文 | 20+ 步仍稳定 |

## 跑起来

```bash
pip install -r ../../requirements.txt
pip install deepagents
python 16_deep_agents.py
```

## 什么时候用 Deep Agents?

- 任务需要多步、可能分叉、可能回退
- 任务需要"先列 TODO 再执行"
- 任务需要写文件 / 读文件 (中间产物)
- 任务可以拆成子任务并行

## 不需要用

- 简单问答
- 一次 tool call 就能解决
- 任务结构非常固定
