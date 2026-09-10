"""12_langsmith_evaluation.py — LangSmith 离线评估.

学完这个模块你能回答:
 1. 怎么定义 evaluator (打分函数)?
 2. 怎么准备 dataset?
 3. 怎么跑 experiment 对比两个版本?
 4. 怎么写 LLM-as-judge evaluator?
 5. 怎么写 heuristic evaluator (长度 / 格式 / 延迟)?
 6. 怎么汇总多 evaluator 的分数?
 7. 怎么按 group 分组对比 (业务场景)?
 8. 怎么防回归 (CI 里跑 evaluator)?
 9. 怎么评估 tool 选择准确性?
10. 实战里评估流水线怎么搭?

跑法:
    1. 设置 LANGSMITH_API_KEY (可选, 不设也能跑本地 demo)
    2. python 12_langsmith_evaluation.py
    3. 去 https://smith.langchain.com 看 experiment 结果

注意: 评估需要 LangSmith 后端, 离线 demo 用本地 evaluator。
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langsmith.schemas import Example, Run

from _common import banner, get_llm

# ============================================================
# 0. 检查
# ============================================================
banner("0. 检查 LangSmith 配置")

LANGSMITH_OK = bool(os.getenv("LANGSMITH_API_KEY"))
if LANGSMITH_OK:
    print("[OK] LangSmith 已配置, 可以跑实验")
else:
    print("[WARN] 未配置 LANGSMITH_API_KEY, 只能跑本地离线评估 demo")
print()


# ============================================================
# 1. 工具定义
# ============================================================


@tool
def get_weather(city: str) -> str:
    """查天气."""
    return f"{city} 晴 25°C"


@tool
def get_time(city: str) -> str:
    """查时间."""
    return f"{city} 当前 14:30"


# ============================================================
# 2. Evaluator 基础 — 多种打分函数
# ============================================================
banner("2. Evaluator 基础 — 多种打分函数")


def evaluator_keyword_match(run: Run, example: Example) -> dict:
    """检查 Agent 输出是否包含预期关键词 (hit rate)."""
    expected = (example.outputs or {}).get("expected_keywords", [])
    output = ""
    if run.outputs and "messages" in run.outputs:
        msgs = run.outputs["messages"]
        output = " ".join(m.content for m in msgs if hasattr(m, "content"))

    hits = sum(1 for kw in expected if kw.lower() in output.lower())
    score = hits / max(len(expected), 1) if expected else 1.0
    return {"key": "keyword_match", "score": score}


def evaluator_tool_call_accuracy(run: Run, example: Example) -> dict:
    """检查 Agent 调用的工具次数 / 名称是否匹配预期."""
    actual_calls: list[str] = []
    if run.outputs and "messages" in run.outputs:
        for m in run.outputs["messages"]:
            if hasattr(m, "tool_calls") and m.tool_calls:
                actual_calls.extend(tc["name"] for tc in m.tool_calls)

    expected_calls = (example.outputs or {}).get("expected_tool_calls", [])
    expected_set = set(expected_calls) if isinstance(expected_calls, list) else {expected_calls}

    # 实际调用集合 vs 预期集合
    if not expected_set:
        # 没期望 → 没调用 = 1.0, 调了 = 0.0
        return {"key": "tool_call_accuracy", "score": 1.0 if not actual_calls else 0.0}

    correct = len(set(actual_calls) & expected_set)
    return {"key": "tool_call_accuracy", "score": correct / len(expected_set)}


def evaluator_response_length(run: Run, example: Example) -> dict:
    """回答长度评分: 太短 (没信息) / 太长 (啰嗦) 都扣分.

    期望范围从 example 里取, 默认 10-100 字.
    """
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


def evaluator_latency(run: Run, example: Example) -> dict:
    """延迟评分: 越快越好, 但要有下限 (太快 = 没真跑)."""
    # Run 对象有 end_time - start_time
    if run.start_time and run.end_time:
        latency_ms = (run.end_time - run.start_time).total_seconds() * 1000
    else:
        latency_ms = 9999  # 没数据, 给最差

    # 期望: 1-10 秒合理
    if latency_ms < 1000:
        score = 0.5  # 太可疑
    elif latency_ms < 10000:
        score = 1.0
    elif latency_ms < 30000:
        score = 0.7
    else:
        score = 0.3
    return {"key": "latency", "score": score}


# ============================================================
# 3. Dataset 准备
# ============================================================
banner("3. Dataset 准备")


def build_dataset() -> list[Example]:
    """构造 in-memory dataset.

    实战里 dataset 从 LangSmith UI 创建 / 从 CSV 导入 / 从生产数据采样.
    """
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
        Example(
            inputs={"messages": [HumanMessage("上海时间?")]},
            outputs={
                "expected_keywords": ["14:30"],
                "expected_tool_calls": ["get_time"],
                "min_length": 5,
                "max_length": 50,
            },
            metadata={"category": "time", "difficulty": "easy"},
        ),
        Example(
            inputs={"messages": [HumanMessage("你好")]},
            outputs={
                "expected_keywords": [],
                "expected_tool_calls": [],
                "min_length": 1,
                "max_length": 100,
            },
            metadata={"category": "chitchat", "difficulty": "trivial"},
        ),
    ]


def demo_dataset() -> None:
    dataset = build_dataset()
    print(f">>> 内存 dataset: {len(dataset)} 条")
    for ex in dataset:
        q = ex.inputs["messages"][0].content
        cat = ex.metadata.get("category")
        print(f"  - [{cat}] Q: {q}")

    if LANGSMITH_OK:
        try:
            from langsmith import Client

            client = Client()
            ds_name = "weather-agent-v1"
            try:
                ds = client.read_dataset(dataset_name=ds_name)
            except Exception:
                ds = client.create_dataset(dataset_name=ds_name)

            for ex in dataset:
                try:
                    client.create_example(
                        inputs=ex.inputs,
                        outputs=ex.outputs,
                        dataset_id=ds.id,
                        metadata=ex.metadata,
                    )
                except Exception:
                    pass  # 已存在
            print(f">>> Dataset '{ds_name}' 已上传到 LangSmith")
        except Exception as e:
            print(f">>> 上传 dataset 失败: {type(e).__name__}: {str(e)[:60]}")


# ============================================================
# 4. 离线评估 — 本地打分
# ============================================================
banner("4. 离线评估 — 本地打分")


def make_mock_run(query: str, output_text: str, tool_calls: list[str]) -> Run:
    """构造 mock Run 用于本地评估 (不需要真跑 LLM)."""
    from langchain_core.messages import AIMessage

    msgs = [HumanMessage(query)]
    if tool_calls:
        from langchain_core.messages import AIMessage as AI

        msgs.append(AI(content="", tool_calls=[{"name": n, "args": {}, "id": f"id-{i}"} for i, n in enumerate(tool_calls)]))
    msgs.append(AIMessage(content=output_text))
    return Run(
        id=f"mock-{query[:10]}",
        name="weather_agent",
        inputs={"messages": [HumanMessage(query)]},
        outputs={"messages": msgs},
        run_type="chain",
        start_time=None,
        end_time=None,
    )


def demo_offline_eval() -> None:
    """直接本地跑 evaluator, 不依赖 LangSmith."""
    print(">>> 离线评估 (mock run, 不调 LLM):\n")

    # 准备 (query, output, tool_calls) 数据
    cases = [
        ("北京天气怎么样?", "北京今天晴 25°C, 适合出门。", ["get_weather"]),
        ("上海时间?", "上海当前 14:30。", ["get_time"]),
        ("你好", "你好! 有什么可以帮你的?", []),
    ]

    dataset = build_dataset()
    evaluators = [
        evaluator_keyword_match,
        evaluator_tool_call_accuracy,
        evaluator_response_length,
    ]

    all_scores: dict[str, list[float]] = {ev.__name__: [] for ev in evaluators}

    for (query, output, tools), ex in zip(cases, dataset):
        run = make_mock_run(query, output, tools)
        # 给 run 一个假的耗时
        from datetime import datetime, timedelta

        run.start_time = datetime.now()
        run.end_time = run.start_time + timedelta(seconds=2)

        print(f"  Q: {query}")
        for ev in evaluators:
            s = ev(run, ex)
            all_scores[ev.__name__].append(s["score"])
            marker = "✓" if s["score"] >= 0.8 else "✗"
            print(f"    {marker} {s['key']}: {s['score']:.2f}")
        print()

    # 汇总
    print(">>> 汇总 (各 evaluator 平均分):")
    for name, scores in all_scores.items():
        avg = sum(scores) / len(scores) if scores else 0
        print(f"  {name}: {avg:.2f}")


# ============================================================
# 5. LLM-as-judge — 用 LLM 给结果打分
# ============================================================
banner("5. LLM-as-judge — 用 LLM 当裁判")


JUDGE_PROMPT = """你是评估员, 给 Agent 的回答打分 (0-1).

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
    """LLM-as-judge: 用 LLM 评估另一个 LLM 的输出."""
    output = ""
    if run.outputs and "messages" in run.outputs:
        msgs = run.outputs["messages"]
        output = " ".join(m.content for m in msgs if hasattr(m, "content"))
    query = example.inputs["messages"][0].content
    expected = (example.outputs or {}).get("expected_keywords", [])

    judge = get_llm(temperature=0.0)
    prompt = JUDGE_PROMPT.format(query=query, expected=expected, output=output)
    try:
        resp = judge.invoke(prompt)
        score = float(resp.content.strip())
        score = max(0.0, min(1.0, score))
    except Exception:
        score = 0.5  # 评估失败给中间分

    return {"key": "llm_judge", "score": score}


def demo_llm_judge() -> None:
    """LLM 当裁判: 适合主观题 / 开放式回答 / 没明确 ground truth 的场景."""
    cases = [
        ("北京天气怎么样?", "北京今天晴 25°C, 适合出门。", ["晴", "25"]),
        ("介绍一下 LangGraph", "LangGraph 是一个用于构建有状态 Agent 的框架。", []),
    ]

    print(">>> LLM-as-judge (用 LLM 给答案打分):")
    for query, output, expected in cases:
        run = make_mock_run(query, output, [])
        ex = Example(
            inputs={"messages": [HumanMessage(query)]},
            outputs={"expected_keywords": expected},
        )
        s = llm_judge_evaluator(run, ex)
        print(f"  Q: {query}")
        print(f"  A: {output[:60]}")
        print(f"  score: {s['score']:.2f}\n")

    # 💡 LLM-as-judge 实战:
    #   - 主观题: 创意 / 翻译 / 总结质量
    #   - 长文评估: 几个维度分别打 (相关性 / 准确性 / 流畅度)
    #   - 注意: judge LLM 也要选强的 (推荐 Claude / GPT-4)
    #   - 注意: 评估本身有误差, 多个 judge 取平均更稳


# ============================================================
# 6. A/B 实验 — 对比两个 prompt
# ============================================================
banner("6. A/B 实验 — 对比 prompt 版本")


def demo_ab_test() -> None:
    """对比两版 prompt 的表现."""
    from langchain.agents import create_agent

    llm = get_llm()

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
    print(">>> A/B 对比:")
    for q in test_queries:
        ra = agent_a.invoke({"messages": [HumanMessage(q)]})
        rb = agent_b.invoke({"messages": [HumanMessage(q)]})
        a_tools = sum(1 for m in ra["messages"] if getattr(m, "tool_calls", None))
        b_tools = sum(1 for m in rb["messages"] if getattr(m, "tool_calls", None))
        a_len = len(ra["messages"][-1].content)
        b_len = len(rb["messages"][-1].content)
        print(f"  Q: {q}")
        print(f"    A: tools={a_tools}, len={a_len}, out={ra['messages'][-1].content[:50]}")
        print(f"    B: tools={b_tools}, len={b_len}, out={rb['messages'][-1].content[:50]}")


# ============================================================
# 7. 汇总统计 — 多 evaluator 聚合
# ============================================================
banner("7. 汇总统计 — 多 evaluator 聚合")


@dataclass
class EvalSummary:
    """一组 evaluator 的汇总结果."""

    n_examples: int
    avg_scores: dict[str, float]
    pass_rate: float  # 所有 evaluator 平均分 >= 0.8 的占比

    def __str__(self) -> str:
        lines = [f"  examples: {self.n_examples}", f"  pass_rate: {self.pass_rate:.2%}"]
        for k, v in self.avg_scores.items():
            lines.append(f"  {k}: {v:.2f}")
        return "\n".join(lines)


def summarize(results: list[dict[str, dict]]) -> EvalSummary:
    """聚合多次 evaluator 的结果.

    results: [{ev_name: {key, score}}, ...]
    """
    if not results:
        return EvalSummary(0, {}, 0.0)

    # 聚合每个 key
    keys = set()
    for r in results:
        keys.update(r.keys())
    avg_scores = {}
    for k in keys:
        scores = [r[k]["score"] for r in results if k in r]
        avg_scores[k] = sum(scores) / len(scores) if scores else 0.0

    # pass rate: 每个 example 所有 evaluator 平均分 >= 0.8 算通过
    pass_count = 0
    for r in results:
        example_avg = sum(v["score"] for v in r.values()) / len(r)
        if example_avg >= 0.8:
            pass_count += 1
    pass_rate = pass_count / len(results)

    return EvalSummary(n_examples=len(results), avg_scores=avg_scores, pass_rate=pass_rate)


def demo_summary() -> None:
    cases = [
        ("q1", "answer 1", ["get_weather"], ["晴"]),
        ("q2", "answer 2", ["get_time"], ["14:30"]),
        ("q3", "no", [], []),
    ]
    dataset = build_dataset()
    evaluators = [evaluator_keyword_match, evaluator_tool_call_accuracy]

    results = []
    for (q, output, tools, expected), ex in zip(cases, dataset):
        run = make_mock_run(q, output, tools)
        scores = {ev.__name__: ev(run, ex) for ev in evaluators}
        results.append(scores)

    summary = summarize(results)
    print(">>> 评估汇总:")
    print(summary)


# ============================================================
# 8. 分组对比 — 按业务场景聚合
# ============================================================
banner("8. 分组对比 — 按 category 分组聚合")


def demo_group_eval() -> None:
    """实战里不同业务场景要求不同, 按 category 分组看分数更合理."""
    dataset = build_dataset()
    cases = [
        ("北京天气怎么样?", "北京今天晴 25°C, 适合出门。", ["get_weather"]),
        ("上海时间?", "上海当前 14:30。", ["get_time"]),
        ("你好", "你好! 有什么可以帮你的?", []),
    ]

    evaluators = [evaluator_keyword_match, evaluator_tool_call_accuracy]

    # 按 category 分组
    groups: dict[str, list[float]] = {}
    for (q, output, tools), ex in zip(cases, dataset):
        run = make_mock_run(q, output, tools)
        cat = ex.metadata.get("category", "other")
        scores = [ev(run, ex)["score"] for ev in evaluators]
        avg = sum(scores) / len(scores)
        groups.setdefault(cat, []).append(avg)

    print(">>> 按 category 分组平均分:")
    for cat, scores in groups.items():
        avg = sum(scores) / len(scores)
        print(f"  {cat}: {avg:.2f} (n={len(scores)})")


# ============================================================
# 9. 防回归 — CI 里跑 evaluator
# ============================================================
banner("9. 防回归 — CI 里跑 evaluator")


def demo_regression_check() -> None:
    """CI 流水线: 每次 PR 跑 evaluator, 分数下降就 fail build.

    实战模式:
      1. 维护 baseline 分 (上一次主干的分数)
      2. PR 跑同一 dataset + evaluator
      3. 分数差 > 阈值 → 报警 / 拒绝合并
    """
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

    print(">>> 防回归检查:")
    regression_found = False
    for k, baseline_v in BASELINE.items():
        cur_v = current.get(k, 0)
        diff = cur_v - baseline_v
        marker = "✓" if diff >= -REGRESSION_THRESHOLD else "✗"
        print(f"  {marker} {k}: baseline={baseline_v:.2f}, current={cur_v:.2f}, diff={diff:+.2f}")
        if diff < -REGRESSION_THRESHOLD:
            regression_found = True

    if regression_found:
        print("\n>>> [FAIL] 检测到回归, 建议不合并")
    else:
        print("\n>>> [PASS] 分数稳定, 可以合并")


# ============================================================
# 10. 评估流水线 — 生产架构
# ============================================================
banner("10. 评估流水线 — 生产架构")


def demo_production_snippet() -> None:
    snippet = """
    # 生产评估流水线:
    #
    # 1. CI 触发 (PR / 定时)
    #      ↓
    # 2. 拉 LangSmith dataset (固定版本, 防数据漂移)
    #      ↓
    # 3. 跑 target agent → 拿 outputs
    #      ↓
    # 4. 跑多 evaluator (heuristic + LLM-as-judge + 人工抽样)
    #      ↓
    # 5. 汇总分数 → 对比 baseline
    #      ↓
    # 6. 写回 LangSmith experiment (可视化)
    #      ↓
    # 7. PR 决策 (达标 → merge, 不达标 → 报警)
    #
    # 关键实践:
    #   - Dataset 版本化 (跟代码一起 git tag)
    #   - Evaluator 复用 (业务级 evaluator 独立 package)
    #   - Baseline 持久化 (S3 / DB, 跟 release 关联)
    #   - 多维度评估 (单分不准, 拆 3-5 个指标)
    #   - 抽样人工 review (LLM judge 准但不能 100% 信任)
    """
    print(snippet)

    # 💡 防坑指南:
    #   - 别只看平均分: 极端 case (低分) 也要看
    #   - LLM-as-judge 不要用太弱的 model (M3 / Haiku 准度不够)
    #   - Dataset 要随业务演化 (定期加新 case)
    #   - 别在 eval 里调外部 API (成本 + 不稳定)


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    for name, fn in [
        ("demo_dataset", demo_dataset),
        ("demo_offline_eval", demo_offline_eval),
        ("demo_llm_judge", demo_llm_judge),
        ("demo_ab_test", demo_ab_test),
        ("demo_summary", demo_summary),
        ("demo_group_eval", demo_group_eval),
        ("demo_regression_check", demo_regression_check),
        ("demo_production_snippet", demo_production_snippet),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 12_langsmith_evaluation.py 全部 demo 跑完。")
    if LANGSMITH_OK:
        print(">>> 实验结果可在 https://smith.langchain.com 查看")
