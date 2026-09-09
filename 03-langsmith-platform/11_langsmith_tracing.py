"""11_langsmith_tracing.py — LangSmith 链路追踪.

学完这个模块你能回答:
 1. 怎么开 LangSmith trace (环境变量)?
 2. 怎么用 @traceable 装饰自定义函数?
 3. 怎么传 metadata / tags 让 trace 更清晰?
 4. 怎么在 trace 里看 tool 调用 (run_type)?
 5. 怎么用 Client API 拉 trace 数据做 dashboard?
 6. 怎么构造 parent/child 调用树 (嵌套 @traceable)?
 7. 怎么用 tracing_context 动态控制上报?
 8. 怎么给 run 打分 (feedback) 做离线分析?
 9. 怎么区分 sampling (全量 vs 抽样上报)?
10. 实战里 LangSmith + LangGraph 怎么配合?

跑法:
    1. 设置环境变量 (见 .env.example):
       LANGSMITH_TRACING=true
       LANGSMITH_API_KEY=lsv2_pt_...
    2. python 11_langsmith_tracing.py
    3. 去 https://smith.langchain.com 看 trace

注意: 没设置 LANGSMITH_API_KEY 时也能跑, 只是不会上报 trace。
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langsmith import traceable

from _common import banner, get_llm

# ============================================================
# 0. 检查环境变量
# ============================================================
banner("0. 检查 LangSmith 配置")

LANGSMITH_OK = bool(
    os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING") == "true"
)
if LANGSMITH_OK:
    print("[OK] LangSmith 已启用")
    print(f"  project: {os.getenv('LANGSMITH_PROJECT', 'default')}")
    print(f"  endpoint: {os.getenv('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com')}")
else:
    print("[WARN] LangSmith 未启用 (缺 LANGSMITH_API_KEY 或 LANGSMITH_TRACING!=true)")
    print("       跑完后不会上报 trace, 但代码可以正常执行")
print()


# ============================================================
# 1. 自动 trace — create_agent 自动埋点
# ============================================================
banner("1. 自动 trace (create_agent 自动上报)")


@tool
def get_weather(city: str) -> str:
    """查天气."""
    return f"{city} 晴 25°C"


@tool
def get_time(city: str) -> str:
    """查时间."""
    return f"{city} 当前 14:30"


def demo_auto_trace() -> None:
    """只要设置了 LangSmith 环境变量, create_agent 自动上报 trace.

    LangSmith 会抓到:
      - 输入 messages
      - LLM 调用 (prompt, response, token 数, latency)
      - tool 调用 (name, args, output)
      - 最终 output
    """
    from langchain.agents import create_agent

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[get_weather, get_time],
    )

    result = agent.invoke(
        {"messages": [HumanMessage("北京天气?")]},
        config={"metadata": {"user_id": "user-001", "session": "demo"}},
    )
    print(">>> Agent 回复:", result["messages"][-1].content[:100])

    if LANGSMITH_OK:
        print(">>> 查看 trace: https://smith.langchain.com")
        print(">>> 用 metadata 里的 user_id 过滤, 可以看单用户的所有调用")
    else:
        print(">>> [提示] 设置 LANGSMITH_API_KEY 后再跑一次即可看到 trace")


# ============================================================
# 2. @traceable — 装饰自定义函数
# ============================================================
banner("2. @traceable 装饰器 — 自定义函数也埋点")


@traceable(name="user_login")
def user_login(user_id: str, password: str) -> dict[str, Any]:
    """(mock) 用户登录."""
    time.sleep(0.05)
    return {"user_id": user_id, "token": "mock-token-xxx"}


@traceable(name="fetch_user_orders")
def fetch_user_orders(user_id: str, token: str) -> list[dict]:
    """(mock) 拉用户订单."""
    time.sleep(0.05)
    return [
        {"order_id": "ORD-001", "amount": 100},
        {"order_id": "ORD-002", "amount": 200},
    ]


@traceable(name="compute_total")
def compute_total(orders: list[dict]) -> float:
    """(mock) 算订单总额."""
    return sum(o["amount"] for o in orders)


def demo_traceable_decorator() -> None:
    """@traceable 装饰的函数会出现在 trace 树里, 自动建父子关系."""
    login_result = user_login("user-001", "secret")
    orders = fetch_user_orders(login_result["user_id"], login_result["token"])
    total = compute_total(orders)
    print(f">>> 用户 {login_result['user_id']} 共 {len(orders)} 单, 总额 {total}")
    if LANGSMITH_OK:
        print(">>> 看 trace: 会看到 user_login → fetch_user_orders → compute_total 层级")
    else:
        print(">>> 父子关系: @traceable 装饰的函数自动按调用栈嵌套")


# ============================================================
# 3. @traceable + metadata — 给 trace 加标签
# ============================================================
banner("3. @traceable + metadata")


@traceable(name="complex_query", metadata={"version": "v1.2", "env": "dev"})
def complex_query(query: str) -> str:
    """(mock) 复杂查询."""
    time.sleep(0.05)
    return f"query result for: {query}"


def demo_metadata() -> None:
    """metadata 在 LangSmith UI 里可以过滤 (按版本 / 环境 / 业务标签).

    三种 metadata 用法:
      1. 装饰器写死: @traceable(metadata={...})
      2. 运行时传: func(arg, metadata={...})
      3. config 透传: RunnableConfig 里的 metadata 会自动带
    """
    complex_query("refund status for order ORD-001")

    @traceable
    def dynamic_meta(x: int) -> int:
        return x * 2

    dynamic_meta(
        5,
        metadata={"experiment": "A", "model_version": "M3-2026-09"},
    )
    print(">>> 装饰器 + 运行时 metadata 都已埋点")
    if LANGSMITH_OK:
        print(">>> 在 UI 里按 experiment=A 过滤, 就能看到这个 run")


# ============================================================
# 4. @traceable + run_type — 控制 trace 类型
# ============================================================
banner("4. @traceable run_type")


@traceable(name="retrieval_step", run_type="retriever")
def retrieval_step(query: str) -> list[dict]:
    """(mock) 检索步骤."""
    time.sleep(0.05)
    return [{"doc": f"result for {query}"}]


@traceable(name="tool_step", run_type="tool")
def tool_step(tool_input: str) -> str:
    """(mock) 工具步骤."""
    time.sleep(0.05)
    return f"tool output for {tool_input}"


@traceable(name="llm_step", run_type="llm")
def llm_step(prompt: str) -> str:
    """(mock) LLM 步骤."""
    time.sleep(0.05)
    return f"llm output for {prompt}"


def demo_run_types() -> None:
    """不同 run_type 在 UI 里会显示不同图标 + 不同过滤项.

    常用 run_type:
      - chain: 普通链路节点
      - llm:   LLM 调用
      - tool:  工具调用
      - retriever: 检索步骤
      - embedding: embedding 计算
      - prompt: prompt 渲染
      - parser: 输出解析
    """
    retrieval_step("refund policy")
    tool_step("get_weather(city=北京)")
    llm_step("summarize...")
    print(">>> 不同 run_type 在 LangSmith UI 里显示不同")


# ============================================================
# 5. 手动管理 trace — Client API
# ============================================================
banner("5. 手动管理 trace (Client API)")


def demo_client() -> None:
    """用 Client API 直接读 trace, 适合做 dashboard."""
    try:
        from langsmith import Client

        client = Client()
        project_name = os.getenv("LANGSMITH_PROJECT", "default")

        # 列出最近的 run
        runs = list(
            client.list_runs(
                project_name=project_name,
                limit=5,
                execution_order=1,  # 按时间倒序
            )
        )
        print(f">>> project={project_name} 最近的 run 数: {len(runs)}")
        for r in runs[:3]:
            print(
                f"  - {r.name} | type={r.run_type}"
                f" | status={r.status}"
                f" | tokens={(r.total_tokens or 0)}"
            )
    except Exception as e:
        print(f">>> Client API 调用失败: {type(e).__name__}: {str(e)[:80]}")
        print(">>> (可能是没设置 LANGSMITH_API_KEY, 这是正常的)")


# ============================================================
# 6. 嵌套 @traceable — 自动构造调用树
# ============================================================
banner("6. 嵌套 @traceable — 自动构造调用树")


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


def demo_nested_traces() -> None:
    """@traceable 自动按调用栈嵌套, 不用手动指定 parent_run_id."""
    r = step_a(5)
    print(f">>> 嵌套调用最终结果: {r}")
    if LANGSMITH_OK:
        print(">>> 在 UI 看: step_a → step_b → step_c (3 层嵌套, 耗时叠加)")


# ============================================================
# 7. tracing_context — 动态控制上报
# ============================================================
banner("7. tracing_context — 动态控制上报")


def demo_tracing_context() -> None:
    """tracing_context 可以动态开关 trace, 不依赖环境变量."""
    from langsmith import tracing_context

    @traceable
    def sensitive_op(user_id: str) -> str:
        return f"handled for {user_id}"

    # 1. 默认: 跟着环境变量
    sensitive_op("default-1")

    # 2. 临时关闭 (比如敏感操作 / 高频心跳)
    with tracing_context(enabled=False):
        sensitive_op("disabled-1")
    print(">>> enabled=False 块里的调用不上报")

    # 3. 临时开启 + 改 project (A/B 测试时把流量拆到不同 project)
    if LANGSMITH_OK:
        with tracing_context(
            enabled=True,
            project_name="ab-experiment-v2",
            metadata={"experiment": "B"},
        ):
            sensitive_op("experiment-B-1")
        print(">>> 实验 B 的流量上报到独立 project")


# ============================================================
# 8. 反馈打分 — 给 run 打 score 离线分析
# ============================================================
banner("8. 反馈打分 — create_feedback")


def demo_feedback() -> None:
    """给历史 run 打分 (用户赞踩 / 自动 evaluator), 用来做离线分析."""
    try:
        from langsmith import Client

        client = Client()
        # 假设最近有 run
        runs = list(client.list_runs(limit=1))
        if not runs:
            print(">>> 没有历史 run 可打分 (先跑前面的 demo)")
            return
        run_id = runs[0].id
        # 打分
        client.create_feedback(
            run_id=run_id,
            key="user_rating",
            score=1.0,           # 1.0 = 点赞, 0.0 = 踩
            comment="demo feedback",
        )
        print(f">>> 给 run {run_id[:8]}... 打 user_rating=1.0")
    except Exception as e:
        print(f">>> 反馈失败 (正常, 无 API key): {type(e).__name__}: {str(e)[:60]}")

    # 💡 实战:
    #   - 线上: 用户点 👍/👎 → 后端 create_feedback
    #   - 离线: evaluator 跑完后批量打分
    #   - UI: 按 feedback 过滤低分 run, 针对性优化


# ============================================================
# 9. 采样 — 全量 vs 抽样上报
# ============================================================
banner("9. 采样 — 抽样上报降成本")


def demo_sampling() -> None:
    """生产里 trace 上报全量成本太高, 用 sampling 抽样.

    三种粒度:
      - 全部上报: 调试阶段
      - 概率抽样: e.g. 1% 上报, 99% 跳过 (LANGSMITH_TRACING_SAMPLING_RATE=0.01)
      - 规则抽样: 报错的全量, 正常的抽样
    """
    # 方式 1: 环境变量控制 (启动时定)
    #   LANGSMITH_TRACING_SAMPLING_RATE=0.01  → 1% 抽样
    rate = os.getenv("LANGSMITH_TRACING_SAMPLING_RATE", "1.0")
    print(f">>> 当前 LANGSMITH_TRACING_SAMPLING_RATE = {rate}")

    # 方式 2: 代码里手动判断
    import random

    @traceable
    def high_volume_call(x: int) -> int:
        return x * 2

    sent = 0
    for i in range(100):
        if random.random() < 0.1:  # 10% 上报
            high_volume_call(i)
            sent += 1
    print(f">>> 100 次调用, 上报 {sent} 次 (10% 抽样)")

    # 方式 3: 关键路径全量, 非关键抽样
    #   在 @traceable 里 if important: 全量 else: 抽样


# ============================================================
# 10. 生产架构 — LangSmith + LangGraph 整合
# ============================================================
banner("10. 生产架构 — LangSmith + LangGraph 整合")


def demo_production_snippet() -> None:
    snippet = """
    # .env
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=lsv2_pt_...
    LANGSMITH_PROJECT=my-agent-prod
    LANGSMITH_TRACING_SAMPLING_RATE=0.1   # 10% 抽样降成本

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
    #   - 错误 run 全部上报 (用 tags=error 自动标)
    #   - 慢节点 (>2s) 单独建一个 project
    """
    print(snippet)

    # 💡 关键架构点:
    #   - metadata + tags: trace 检索维度 (user / env / version)
    #   - sampling: 生产降成本
    #   - feedback: 用户反馈 / 自动 evaluator 写回
    #   - project: 按环境拆 (dev / staging / prod)
    #   - alerting: LangSmith webhook → 飞书/Slack


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

    for name, fn in [
        ("demo_auto_trace", demo_auto_trace),
        ("demo_traceable_decorator", demo_traceable_decorator),
        ("demo_metadata", demo_metadata),
        ("demo_run_types", demo_run_types),
        ("demo_client", demo_client),
        ("demo_nested_traces", demo_nested_traces),
        ("demo_tracing_context", demo_tracing_context),
        ("demo_feedback", demo_feedback),
        ("demo_sampling", demo_sampling),
        ("demo_production_snippet", demo_production_snippet),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 11_langsmith_tracing.py 全部 demo 跑完。")
    if LANGSMITH_OK:
        print(">>> 现在去 https://smith.langchain.com 看 trace 吧!")
