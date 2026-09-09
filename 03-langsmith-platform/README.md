# L3 — LangSmith 平台

> 2 个模块覆盖 LangSmith 的核心能力。
> 学完这一层,你的 Agent **看得见、可评估**。

## 模块清单

| # | 文件 | 关键能力 | 一句话目标 |
|---|------|---------|----------|
| 11 | `11_langsmith_tracing.py` | `LANGSMITH_TRACING=true` / `@traceable` | 每一次 LLM 调用都有 trace |
| 12 | `12_langsmith_evaluation.py` | datasets / evaluators / experiments | 离线打分 + A/B |

## 为什么需要 LangSmith?

| 没有 LangSmith | 有 LangSmith |
|----------------|--------------|
| "上周一次失败的对话是哪一步错的?" ❓ | 直接看 trace,清楚每一步 |
| "改 prompt 之后好没好?" 🤔 | 跑 evaluator,数据说话 |
| "生产环境哪个 token 最贵?" ❓ | 看 token 用量面板 |
| "新模型上线风险?" 😰 | 先在 LangSmith 跑同一批 case |

## 跑起来

```bash
pip install -r ../../requirements.txt
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_pt_...
export LANGSMITH_PROJECT=0401-langchain-langgraph-v1

python 11_langsmith_tracing.py
python 12_langsmith_evaluation.py
```

跑完去 https://smith.langchain.com 看 trace。

## 关键心智模型

```
你的代码
   ↓
LangChain / LangGraph 自动埋点
   ↓
LangSmith 后端
   ↓
你看到:
  - Trace (树形调用链)
  - Token 用量
  - Latency
  - 错误堆栈
  - 输入输出
```

## 关键配置

环境变量 (见 `.env.example`):

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=0401-langchain-langgraph-v1
```

设置后,所有 `create_agent` / `StateGraph` 都会自动上报 trace,无需改代码。
