# L3-12 · LangSmith Evaluation:给 Agent 装考试系统

> Agent 改了一个 prompt,怎么知道有没有变好?靠"感觉"?靠"线上观察"?都不靠谱。LangSmith Evaluation 提供**离线评估流水线**:固定 dataset + 多维度 evaluator + 自动跑分 + 防回归。这篇拆 10 个 demo,从 keyword 匹配到 LLM-as-judge,生产评估闭环。

## 为什么学这个

Agent 工程化最难的不是"做出来",而是"持续做好"。生产里三大评估需求:

1. **改 prompt 前**:旧 prompt 分数多少?baseline
2. **改 prompt 后**:新 prompt 分数多少?有没有回归?
3. **每次 PR**:CI 跑 evaluator,分数下降就 fail

LangSmith Evaluation 解决:

- **Dataset**:固定测试集(典型用户问题 + 期望答案)
- **Evaluator**:打分函数(关键词 / 工具调用 / 长度 / 延迟 / LLM judge)
- **Experiment**:对同一个 dataset 跑两个版本,对比分数
- **Regression check**:CI 流水线,分数下降就报警

跟单元测试是同一个思想,只不过测的是 LLM 输出而不是代码逻辑。

## 学完你能回答 10 个问题

1. 怎么定义 evaluator(打分函数)?
2. 怎么准备 dataset?
3. 怎么跑 experiment 对比两个版本?
4. 怎么写 LLM-as-judge evaluator?
5. 怎么写 heuristic evaluator(长度 / 格式 / 延迟)?
6. 怎么汇总多 evaluator 的分数?
7. 怎么按 group 分组对比(业务场景)?
8. 怎么防回归(CI 里跑 evaluator)?
9. 怎么评估 tool 选择准确性?
10. 实战里评估流水线怎么搭?

## 1. Evaluator 基础 — 多种打分函数

Evaluator 是一个函数:`(Run, Example) → dict[key, score]`。

```python
from langsmith.schemas import Example, Run

def evaluator_keyword_match(run: Run, example: Example) -> dict:
    """检查 Agent 输出是否包含预期关键词(hit rate)。"""
    expected = (example.outputs or {}).get("expected_keywords", [])
    output = ""
    if run.outputs and "messages" in run.outputs:
        msgs = run.outputs["messages"]
        output = " ".join(m.content for m in msgs if hasattr(m, "content"))

    hits = sum(1 for kw in expected if kw.lower() in output.lower())
    score = hits / max(len(expected), 1) if expected else 1.0
    return {"key": "keyword_match", "score": score}
```

四种常用 heuristic evaluator:

| evaluator | 检查项 | 适用 |
|---|---|---|
| `keyword_match` | 输出含特定关键词 | FAQ / 明确答案 |
| `tool_call_accuracy` | 调用的工具名是否匹配 | 工具选择 |
| `response_length` | 长度在合理区间 | 简短 / 详尽要求 |
| `latency` | 响应时间 | 性能要求 |

## 2. tool_call_accuracy — 评估工具选择

```python
def evaluator_tool_call_accuracy(run: Run, example: Example) -> dict:
    """检查 Agent 调用的工具次数 / 名称是否匹配预期。"""
    actual_calls: list[str] = []
    if run.outputs and "messages" in run.outputs:
        for m in run.outputs["messages"]:
            if hasattr(m, "tool_calls") and m.tool_calls:
                actual_calls.extend(tc["name"] for tc in m.tool_calls)

    expected_calls = (example.outputs or {}).get("expected_tool_calls", [])
    expected_set = set(expected_calls) if isinstance(expected_calls, list) else {expected_calls}

    if not expected_set:
        # 没期望 → 没调用 = 1.0, 调了 = 0.0
        return {"key": "tool_call_accuracy", "score": 1.0 if not actual_calls else 0.0}

    correct = len(set(actual_calls) & expected_set)
    return {"key": "tool_call_accuracy", "score": correct / len(expected_set)}
```

实战:

- 检查 LLM 是否选了正确的工具(查天气 vs 查订单)
- 检查 LLM 是否多调了不该调的工具
- 检查参数是否正确(`city="北京"` vs `city="上海"`)

## 3. response_length — 长度评分

```python
def evaluator_response_length(run: Run, example: Example) -> dict:
    """回答长度评分: 太短(没信息)/ 太长(啰嗦)都扣分。"""
    output = ""
    if run.outputs and "messages" in run.outputs:
        msgs = run.outputs["messages"]
        output = " ".join(m.content for m in msgs if hasattr(m, "content"))

    min_len = (example.outputs or {}).get("min_length", 10)
    max_len = (example.outputs or {}).get("max_length", 100)
    n = len(output)

    if n < min_len:
        score = max(0.0, n / min_len)
    elif n > max_len:
        score = max(0.0, 1.0 - (n - max_len) / max_len)
    else:
        score = 1.0
    return {"key": "response_length", "score": score}
```

实战:

- 客户支持 / FAQ:长度 50-200 字
- 摘要 / 总结:长度 1-3 句
- 详情 / 报告:长度 500-2000 字

## 4. Dataset 准备

```python
from langsmith.schemas import Example

def build_dataset() -> list[Example]:
    return [
        Example(
            inputs={"messages": [HumanMessage("北京天气怎么样?")]},
            outputs={
                "expected_keywords": ["晴", "25"],
                "expected_tool_calls": ["get_weather"],
                "min_length": 5,
                "max_length": 80,
            },
            metadata={"category": "weather", "difficulty": "easy"},
        ),
        # ... 更多 case
    ]
```

dataset 三种来源:

| 来源 | 做法 |
|---|---|
| 内存构造 | 测试用,直接在代码里写 |
| CSV 导入 | LangSmith UI 批量上传 |
| 生产采样 | 线上抽样 + 人工标注 |

实战建议:

- 起步 20-50 条典型 case
- 按 category / difficulty 分组
- dataset 版本化(跟代码一起 git tag,防数据漂移)

## 5. 离线评估 — 本地打分

不依赖 LangSmith,本地直接跑:

```python
def make_mock_run(query: str, output_text: str, tool_calls: list[str]) -> Run:
    """构造 mock Run 用于本地评估(不需要真跑 LLM)。"""
    msgs = [HumanMessage(query)]
    if tool_calls:
        msgs.append(AIMessage(content="", tool_calls=[
            {"name": n, "args": {}, "id": f"id-{i}"}
            for i, n in enumerate(tool_calls)
        ]))
    msgs.append(AIMessage(content=output_text))
    return Run(
        id=f"mock-{query[:10]}",
        name="weather_agent",
        inputs={"messages": [HumanMessage(query)]},
        outputs={"messages": msgs},
        run_type="chain",
    )

# 跑
cases = [
    ("北京天气怎么样?", "北京今天晴 25°C, 适合出门。", ["get_weather"]),
    ("上海时间?", "上海当前 14:30。", ["get_time"]),
]
dataset = build_dataset()
evaluators = [evaluator_keyword_match, evaluator_tool_call_accuracy, evaluator_response_length]

all_scores: dict[str, list[float]] = {ev.__name__: [] for ev in evaluators}
for (query, output, tools), ex in zip(cases, dataset):
    run = make_mock_run(query, output, tools)
    for ev in evaluators:
        s = ev(run, ex)
        all_scores[ev.__name__].append(s["score"])

# 汇总
for name, scores in all_scores.items():
    avg = sum(scores) / len(scores)
    print(f"  {name}: {avg:.2f}")
```

## 6. LLM-as-judge — 用 LLM 当裁判

主观题 / 开放式回答 / 没明确 ground truth 的场景:

```python
JUDGE_PROMPT = """你是评估员, 给 Agent 的回答打分 (0-1)。
用户问题: {query}
期望要点: {expected}
Agent 回答: {output}
请按以下标准打分:
- 1.0: 完全正确, 信息完整, 表达清晰
- 0.7: 基本正确, 但有小瑕疵
- 0.4: 部分正确, 有明显遗漏
- 0.0: 完全错误 / 答非所问
只输出一个数字, 不要解释."""

def llm_judge_evaluator(run: Run, example: Example) -> dict:
    output = ""
    if run.outputs and "messages" in run.outputs:
        msgs = run.outputs["messages"]
        output = " ".join(m.content for m in msgs if hasattr(m, "content"))
    query = example.inputs["messages"][0].content
    expected = (example.outputs or {}).get("expected_keywords", [])

    judge = get_llm(temperature=0.0)  # judge LLM 要稳定
    prompt = JUDGE_PROMPT.format(query=query, expected=expected, output=output)
    try:
        resp = judge.invoke(prompt)
        score = float(resp.content.strip())
        score = max(0.0, min(1.0, score))
    except Exception:
        score = 0.5
    return {"key": "llm_judge", "score": score}
```

实战注意:

- judge LLM 选强的(推荐 Claude / GPT-4)
- judge 本身有误差,多个 judge 取平均更稳
- temperature=0 保证稳定性
- 不同维度分开打(相关性 / 准确性 / 流畅度)

## 7. A/B 实验 — 对比两个 prompt

```python
agent_a = create_agent(
    model=llm, tools=[get_weather, get_time],
    system_prompt="你回答问题。",
)

agent_b = create_agent(
    model=llm, tools=[get_weather, get_time],
    system_prompt=(
        "你是天气助手, 必须先调用工具拿到准确数据,"
        "再整理成不超过 20 字的简短回复。"
    ),
)

test_queries = ["北京天气?", "上海时间?", "你好"]
for q in test_queries:
    ra = agent_a.invoke({"messages": [HumanMessage(q)]})
    rb = agent_b.invoke({"messages": [HumanMessage(q)]})
    a_tools = sum(1 for m in ra["messages"] if getattr(m, "tool_calls", None))
    b_tools = sum(1 for m in rb["messages"] if getattr(m, "tool_calls", None))
    print(f"  A: tools={a_tools}, out={ra['messages'][-1].content[:50]}")
    print(f"  B: tools={b_tools}, out={rb['messages'][-1].content[:50]}")
```

LangSmith UI 里更直观:

```python
from langsmith import Client
client = Client()
# 上传两个 experiment 对比
client.upload_experiment(
    experiment_name="prompt-v1",
    runs=runs_v1,
    dataset_id=ds.id,
)
client.upload_experiment(
    experiment_name="prompt-v2",
    runs=runs_v2,
    dataset_id=ds.id,
)
```

UI 上可以并排看两个版本的分数。

## 8. 汇总统计 — 多 evaluator 聚合

```python
@dataclass
class EvalSummary:
    n_examples: int
    avg_scores: dict[str, float]
    pass_rate: float  # 所有 evaluator 平均分 >= 0.8 的占比

def summarize(results: list[dict[str, dict]]) -> EvalSummary:
    if not results:
        return EvalSummary(0, {}, 0.0)

    keys = set()
    for r in results:
        keys.update(r.keys())
    avg_scores = {}
    for k in keys:
        scores = [r[k]["score"] for r in results if k in r]
        avg_scores[k] = sum(scores) / len(scores) if scores else 0.0

    pass_count = 0
    for r in results:
        example_avg = sum(v["score"] for v in r.values()) / len(r)
        if example_avg >= 0.8:
            pass_count += 1
    pass_rate = pass_count / len(results)

    return EvalSummary(n_examples=len(results), avg_scores=avg_scores, pass_rate=pass_rate)
```

汇总指标:

| 指标 | 含义 |
|---|---|
| `n_examples` | 跑了多少 case |
| `avg_scores[key]` | 每个 evaluator 平均分 |
| `pass_rate` | 整体通过率(所有分 ≥ 0.8) |

## 9. 防回归 — CI 里跑 evaluator

```python
BASELINE = {
    "keyword_match": 0.85,
    "tool_call_accuracy": 0.90,
    "response_length": 0.80,
}
REGRESSION_THRESHOLD = 0.05  # 下降 5% 报警

# 模拟当前分数
current = {
    "keyword_match": 0.83,
    "tool_call_accuracy": 0.92,
    "response_length": 0.78,
}

regression_found = False
for k, baseline_v in BASELINE.items():
    cur_v = current.get(k, 0)
    diff = cur_v - baseline_v
    if diff < -REGRESSION_THRESHOLD:
        regression_found = True
        print(f"  ✗ {k}: baseline={baseline_v:.2f}, current={cur_v:.2f}, diff={diff:+.2f}")

if regression_found:
    print("\n>>> [FAIL] 检测到回归, 建议不合并")
else:
    print("\n>>> [PASS] 分数稳定, 可以合并")
```

CI 流水线:

```
PR 触发
   ↓
拉 LangSmith dataset(固定版本)
   ↓
跑 target agent → 拿 outputs
   ↓
跑多 evaluator(heuristic + LLM-as-judge + 人工抽样)
   ↓
汇总分数 → 对比 baseline
   ↓
分数达标 → merge, 不达标 → 报警
```

## 10. 评估流水线 — 生产架构

```python
# 生产评估流水线:
#
# 1. CI 触发(PR / 定时)
#      ↓
# 2. 拉 LangSmith dataset(固定版本, 防数据漂移)
#      ↓
# 3. 跑 target agent → 拿 outputs
#      ↓
# 4. 跑多 evaluator(heuristic + LLM-as-judge + 人工抽样)
#      ↓
# 5. 汇总分数 → 对比 baseline
#      ↓
# 6. 写回 LangSmith experiment(可视化)
#      ↓
# 7. PR 决策(达标 → merge, 不达标 → 报警)
```

防坑指南:

- 别只看平均分:极端 case(低分)也要看
- LLM-as-judge 不要用太弱的 model(M3 / Haiku 准度不够)
- Dataset 要随业务演化(定期加新 case)
- 别在 eval 里调外部 API(成本 + 不稳定)

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| 分数波动大 | LLM 输出随机 | `temperature=0` + 多 judge 取均 |
| LLM judge 准度低 | judge 用了小模型 | 用 Claude / GPT-4 当 judge |
| dataset 太短 | 测试覆盖不足 | 起步 50+ 条,业务演化 |
| 防回归误报 | baseline 太严 | 阈值设 5-10%,留缓冲 |
| eval 跑得太慢 | judge LLM 慢 | judge 异步 + 缓存 |
| dataset 漂移 | 数据未版本化 | dataset 跟代码一起 git tag |

## 小结

- Evaluator = 打分函数,输入 Run + Example,输出 score
- Heuristic evaluator:keyword / tool call / length / latency
- LLM-as-judge:主观题 / 开放式回答
- Dataset:固定测试集,版本化,跟代码同步
- Experiment:同一 dataset 跑两个版本,对比分数
- 防回归:CI 流水线,分数下降 5-10% 报警
- 生产评估:heuristic + LLM judge + 人工抽样组合

评估让 Agent "持续做好"。下一步是让 Agent **多人协作**——L4-13 Supervisor 见。

## 延伸阅读

- [LangSmith Evaluation 官方文档](https://docs.smith.langchain.com/evaluation)
- 上一篇:[L3-11 LangSmith Tracing](./L3-11_langsmith_tracing.md)
- 下一篇:[L4-13 Supervisor 模式](./L4-13_supervisor.md)
- 源码:`03-langsmith-platform/12_langsmith_evaluation.py`
