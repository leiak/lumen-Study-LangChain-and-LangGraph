"""10_durable_execution.py — 持久执行: replay / time travel / fault recovery.

学完这个模块你能回答:
 1. 怎么从某个 checkpoint 重放 (不重跑 LLM)?
 2. 怎么 fork state 走分支 (time travel)?
 3. 进程挂了 state 怎么不丢? (checkpointer + 重连)
 4. 怎么审计完整执行链路 (events)?
 5. 怎么用 update_state 改历史 (人类修正)?
 6. 怎么用 SqliteSaver 跨进程持久?
 7. 怎么区分 Checkpointer (短期) vs Store (长期)?
 8. 怎么用 as_node 参数把 update_state 注入到指定节点?
 9. 怎么并发触发多次分支对比 (A/B 探索)?
10. 实战里 durable execution 怎么落地 (生产架构)?

跑法:
    python 10_durable_execution.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.store.memory import InMemoryStore

from _common import banner, get_llm

# ============================================================
# 0. 共享工具 + Graph 工厂
# ============================================================


@tool
def get_weather(city: str) -> str:
    """查天气."""
    return f"{city} 晴 25°C"


@tool
def get_time(city: str) -> str:
    """查时间."""
    return f"{city} 当前 14:30"


def build_graph(checkpointer=None, store=None):
    """3 节点图: agent -> tool -> final.

    checkpointer / store 都能从外面注入, 方便不同 demo 换实现 (内存 / SQLite / Postgres).
    """
    llm = get_llm().bind_tools([get_weather, get_time])
    tools_by_name = {t.name: t for t in [get_weather, get_time]}

    def call_llm(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def call_tool(state: MessagesState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in last.tool_calls:
            tool_fn = tools_by_name[tc["name"]]
            results.append(
                ToolMessage(content=str(tool_fn.invoke(tc["args"])), tool_call_id=tc["id"])
            )
        return {"messages": results}

    def final(state: MessagesState) -> dict:
        # 把 final 节点的输出标记一下, 方便 audit 看
        return {"messages": [HumanMessage(content="[final] 处理完毕")]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tool" if getattr(last, "tool_calls", None) else "final"

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_llm)
    graph.add_node("tool", call_tool)
    graph.add_node("final", final)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tool", "final"])
    graph.add_edge("tool", "agent")
    graph.add_edge("final", END)
    return graph.compile(checkpointer=checkpointer, store=store)


# ============================================================
# 1. get_state_history — 列出所有 checkpoint (审计)
# ============================================================
banner("1. get_state_history — 列出所有 checkpoint")


def demo_history() -> None:
    app = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "audit-1"}}

    app.invoke({"messages": [HumanMessage("北京?")]}, config=config)
    app.invoke({"messages": [HumanMessage("上海?")]}, config=config)

    history = list(app.get_state_history(config))
    print(f">>> 共 {len(history)} 个 checkpoint (新 → 旧):")
    for i, snap in enumerate(history):
        ts = snap.created_at
        msgs = snap.values.get("messages", [])
        next_node = snap.next
        ckpt_id = snap.config["configurable"]["checkpoint_id"][:8]
        print(
            f"  [{i}] ts={ts} | next={next_node} | msgs={len(msgs)}"
            f" | ckpt={ckpt_id}..."
        )

    # 💡 实战用途:
    #   - 调试: 每一步 state 长啥样
    #   - 审计: 用户问"我昨天聊到哪了?"
    #   - 撤销: 取上一个 checkpoint 重走 (见 demo_time_travel)
    #   - 合规: 金融/医疗场景要追溯每一步决策


# ============================================================
# 2. Time travel — 从中间 checkpoint fork
# ============================================================
banner("2. Time travel — 从中间 checkpoint fork")


def demo_time_travel() -> None:
    app = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "timetravel-1"}}

    r1 = app.invoke({"messages": [HumanMessage("北京?")]}, config=config)

    # history[-1] 是最老的 checkpoint (第 1 轮后)
    history = list(app.get_state_history(config))
    first_ckpt = history[-1]
    print(
        f">>> 第 1 轮 checkpoint_id: "
        f"{first_ckpt.config['configurable']['checkpoint_id'][:8]}..."
    )
    print(f">>> 第 1 轮 messages 数: {len(first_ckpt.values['messages'])}")

    # 从第 1 轮 fork: 把"北京"改成"上海"
    new_config = app.update_state(
        first_ckpt.config,
        {"messages": [HumanMessage("上海?")]},  # 改写输入
    )
    print(f">>> Fork 后新 thread_id: {new_config['configurable']['thread_id']}")
    # 💡 默认 update_state 会创建新 thread_id, 原 thread 不被污染
    #   也可以手动把 thread_id 设回原值, 实现"覆盖历史"

    # 在新 thread 上续走
    r2 = app.invoke(
        {"messages": [HumanMessage("延续上一轮")]},
        config=new_config,
    )
    print(f">>> Fork 后 messages 数: {len(r2['messages'])}")

    # 验证: 原 thread 还是只有"北京"
    orig_state = app.get_state(config)
    print(f">>> 原 thread messages 数: {len(orig_state.values['messages'])}")

    # 💡 实战:
    #   - 用户撤回: "刚才那条不算, 我重新说"
    #   - 错误纠正: LLM 答错了, 主管手动改完再走
    #   - A/B 测试: 同一起点, fork 出 N 个分支对比


# ============================================================
# 3. Replay — 同一个 checkpoint 重放 (不重跑 LLM)
# ============================================================
banner("3. Replay — 重放同一个 checkpoint (不重跑 LLM)")


def demo_replay() -> None:
    app = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "replay-1"}}

    app.invoke({"messages": [HumanMessage("北京?")]}, config=config)

    history = list(app.get_state_history(config))
    first_ckpt = history[-1]

    # 重放到第一个 checkpoint (不会重新调 LLM)
    replay_config = {
        "configurable": {
            "thread_id": "replay-1",
            "checkpoint_id": first_ckpt.config["configurable"]["checkpoint_id"],
        }
    }
    state = app.get_state(replay_config)
    print(
        f">>> Replay 拿到 checkpoint, messages 数: {len(state.values['messages'])}"
    )

    # 💡 Replay vs Time travel:
    #   - Replay: 只读历史 state, 不修改 (审计 / 调试)
    #   - Time travel: 改历史 state, 续走 (撤销 / 分支)
    #   - Replay 完全不消耗 LLM token (从 checkpoint 直接读)


# ============================================================
# 4. Crash recovery — 进程挂了 state 不丢
# ============================================================
banner("4. Crash recovery — 模拟进程崩溃后恢复")


def demo_crash_recovery() -> None:
    """场景: Agent 跑到一半, 进程挂了, 重启后从 checkpoint 恢复."""
    # 真实生产: 用 PostgresSaver, 进程重启后从 DB 重新加载
    # 这里用 SqliteSaver 做真实持久化演示 (比 InMemorySaver 真实一档)

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        print(">>> 需要安装 langgraph-checkpoint-sqlite: pip install langgraph-checkpoint-sqlite")
        return

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "crash.db")

        # ----- 第 1 个"进程": 跑 Agent -----
        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            app1 = build_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": "crash-1"}}
            print(">>> 进程 1: invoke Agent")
            app1.invoke({"messages": [HumanMessage("北京?")]}, config=config)
            print(f">>> 进程 1: 写完 checkpoint, db={Path(db_path).stat().st_size}B")

        # SqliteSaver with 块退出 → 连接关闭, 模拟"进程死掉"
        print(">>> 进程 1 退出 (with 块结束)")

        # ----- 第 2 个"进程": 用同一个 db 文件启动 -----
        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            app2 = build_graph(checkpointer=checkpointer)
            state = app2.get_state({"configurable": {"thread_id": "crash-1"}})
            print(
                f">>> 进程 2: 恢复, 历史 messages={len(state.values['messages'])}"
            )
            print(">>> 注: 生产用 PostgresSaver, 多副本共享同一 DB")


# ============================================================
# 5. Events audit — 完整事件流 (on_chain_start / on_tool_end 等)
# ============================================================
banner("5. Events audit — 完整事件流")


def demo_audit() -> None:
    app = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "audit-2"}}

    print(">>> 完整事件流:")
    counts: dict[str, int] = {}
    for event in app.stream(
        {"messages": [HumanMessage("北京?")]},
        config=config,
        stream_mode="events",
    ):
        kind = list(event.keys())[0]
        counts[kind] = counts.get(kind, 0) + 1
        data = event[kind]
        if kind == "on_chain_start":
            print(f"  [+] node={data.get('name', '?')} 开始")
        elif kind == "on_chain_end":
            print(f"  [-] node={data.get('name', '?')} 结束")
        elif kind == "on_llm_start":
            inp = data.get("input", {})
            n = len(inp.get("messages", [])) if isinstance(inp, dict) else 0
            print(f"  [LLM] 调用, msgs={n}")
        elif kind == "on_llm_end":
            resp = data.get("output", {})
            content = ""
            try:
                content = resp.get("generations", [[{}]])[0][0].get("text", "")
            except Exception:
                content = str(resp)[:80]
            print(f"  [LLM] 返回: {content[:80]}")
        elif kind == "on_tool_start":
            print(f"  [tool] {data.get('name', '?')}({data.get('input', {})})")
        elif kind == "on_tool_end":
            print(f"  [tool] 返回: {str(data.get('output'))[:80]}")

    print(f"\n>>> 事件统计: {counts}")

    # 💡 实战:
    #   - 调试: 看哪一步慢 / 哪一步报错
    #   - 监控: 上报到 LangSmith / Prometheus
    #   - 审计: 合规要求记录每一步决策


# ============================================================
# 6. update_state — 改历史 (人类修正)
# ============================================================
banner("6. update_state — 改历史")


def demo_update_state() -> None:
    """场景: 用户说'刚才那句话不算, 改成 X', update_state 改完后让 Agent 重答."""
    app = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "edit-1"}}

    # 跑两轮
    app.invoke({"messages": [HumanMessage("我叫王明")]}, config=config)
    app.invoke({"messages": [HumanMessage("我住在北京")]}, config=config)

    # 用户反悔: "我不住北京, 改住上海"
    # 拿到第 1 轮后的 checkpoint (那时还没有"住在北京")
    history = list(app.get_state_history(config))
    # history[0]=最新, history[-1]=最老; 第 1 轮之后 = history[-2]
    after_first = history[-2]
    print(
        f">>> 取第 1 轮后 checkpoint, 当时只有 "
        f"{len(after_first.values['messages'])} 条消息"
    )

    # 在那个 checkpoint 上插入"我住在上海"
    new_config = app.update_state(
        after_first.config,
        {"messages": [HumanMessage("我住在上海")]},
    )
    print(">>> update_state 改了历史")

    # 续走: Agent 看到的 history 是 [我叫王明, 我住在上海]
    r = app.invoke({}, config=new_config)
    print(f">>> 续走最终 messages 数: {len(r['messages'])}")
    for m in r["messages"][-3:]:
        print(f"  [{type(m).__name__}] {(m.content or '')[:80]}")

    # 💡 实战:
    #   - 用户编辑自己的历史消息
    #   - 主管改 Agent 的中间输出 (HITL 流程)
    #   - A/B 测试: 同一上下文, fork 不同决策对比


# ============================================================
# 7. Checkpointer vs Store — 短期 vs 长期记忆
# ============================================================
banner("7. Checkpointer vs Store — 短期 vs 长期记忆")


def demo_checkpoint_vs_store() -> None:
    """Checkpointer 存 thread 级别的对话历史, Store 存跨 thread 的长期记忆."""
    checkpointer = InMemorySaver()
    store = InMemoryStore()
    app = build_graph(checkpointer=checkpointer, store=store)

    # ---- Checkpointer: thread 级别 ----
    config = {"configurable": {"thread_id": "short-term-1"}}
    app.invoke({"messages": [HumanMessage("北京?")]}, config=config)
    app.invoke({"messages": [HumanMessage("上海?")]}, config=config)

    state = app.get_state(config)
    print(f">>> Checkpointer: thread 'short-term-1' 有 {len(state.values['messages'])} 条消息")

    # ---- Store: 跨 thread 级别 ----
    user_id = "user-001"
    namespace = ("preferences", user_id)
    store.put(namespace, "language", {"value": "中文"})
    store.put(namespace, "city", {"value": "上海"})

    # 另一个 thread 也能读到
    items = store.search(namespace)
    print(f">>> Store: 用户 {user_id} 的长期偏好 ({len(items)} 条):")
    for it in items:
        print(f"  - {it.key}: {it.value}")

    # 💡 实战区别:
    #   Checkpointer: thread 级别, 对话历史 (短期, 量大, 自动过期可)
    #   Store:        namespace 级别, 长期记忆 (用户偏好/知识, 少量, 永久)
    #   一个进程 1 个 store, N 个 thread 的 checkpoint


# ============================================================
# 8. update_state + as_node — 把补丁注入到指定节点
# ============================================================
banner("8. update_state + as_node — 把补丁注入到指定节点")


def demo_update_state_as_node() -> None:
    """update_state 默认会把消息当 HumanMessage 加到 messages 末尾。
    但有时想模拟"某个节点内部产生了某个 state", 这时用 as_node= 标记。
    """
    from typing import Annotated, TypedDict

    from langgraph.graph.message import add_messages

    class CustomState(TypedDict):
        messages: Annotated[list, add_messages]
        score: int

    def scorer(state: CustomState) -> dict:
        return {"score": sum(len(m.content or "") for m in state["messages"])}

    g = StateGraph(CustomState)
    g.add_node("scorer", scorer)
    g.add_edge(START, "scorer")
    g.add_edge("scorer", END)
    app = g.compile(checkpointer=InMemorySaver())

    config = {"configurable": {"thread_id": "as-node-1"}}
    app.invoke({"messages": [HumanMessage("hello world")]}, config=config)

    # 模拟: 主管改 score 后, 让流程继续 (这里就到 END, 但展示了 as_node 用法)
    new_config = app.update_state(
        config,
        values={"score": 999},
        as_node="scorer",  # 关键: 让框架以为这个 patch 是 scorer 节点产生的
    )
    state = app.get_state(new_config)
    print(f">>> update_state(as_node='scorer') 后, score={state.values['score']}")

    # 💡 as_node 实战:
    #   - 测试: 不跑真节点, 注入 mock state
    #   - 修复: 某个节点坏了, 手动算好它的输出塞回去
    #   - 复杂 fork: 从某个节点状态重新出发


# ============================================================
# 9. 并发 fork — A/B 探索
# ============================================================
banner("9. 并发 fork — A/B 探索")


def demo_concurrent_fork() -> None:
    """从同一历史 fork 出多个分支, 并发跑对比结果."""
    app = build_graph(checkpointer=InMemorySaver())
    base_config = {"configurable": {"thread_id": "base-A"}}
    app.invoke({"messages": [HumanMessage("初始问题")]}, config=base_config)

    # 从第 1 轮后 fork
    history = list(app.get_state_history(base_config))
    after_first = history[-1]

    # 分支 A: 让 Agent 关注天气
    config_a = app.update_state(
        after_first.config,
        {"messages": [HumanMessage("详细说天气")]},
    )
    # 分支 B: 让 Agent 关注时间
    config_b = app.update_state(
        after_first.config,
        {"messages": [HumanMessage("详细说时间")]},
    )
    print(">>> Fork 出 A/B 两个分支")

    # 续走
    r_a = app.invoke({}, config=config_a)
    r_b = app.invoke({}, config=config_b)

    print(f">>> A 分支最终 messages: {len(r_a['messages'])} 条")
    print(f">>> B 分支最终 messages: {len(r_b['messages'])} 条")
    print(f">>> A 最后一条: {r_a['messages'][-1].content[:80]}")
    print(f">>> B 最后一条: {r_b['messages'][-1].content[:80]}")

    # 💡 实战:
    #   - A/B 测试: 同一 prompt, 换不同 model / temperature 对比
    #   - 多策略: 同一起点, 跑多种解法选最优
    #   - Monte Carlo: 同一起点, 跑 N 次统计稳定性


# ============================================================
# 10. 生产架构 — durable execution 落地
# ============================================================
banner("10. 生产架构 — durable execution 落地")


def demo_production_snippet() -> None:
    """生产环境的标准接法: PostgresSaver + Store + interrupt + LangSmith."""
    snippet = """
    # 1. PostgresSaver — 跨进程 / 分布式 state
    from langgraph.checkpoint.postgres import PostgresSaver
    DB = "postgresql://user:pwd@host:5432/langgraph"

    with PostgresSaver.from_conn_string(DB) as checkpointer:
        checkpointer.setup()  # 首次跑建表

    # 2. PostgresStore — 长期记忆 / 知识
    from langgraph.store.postgres import PostgresStore
    with PostgresStore.from_conn_string(DB) as store:
        store.setup()

    # 3. 组装图
    app = graph.compile(checkpointer=checkpointer, store=store, interrupt_before=["human_review"])

    # 4. 触发 + 恢复
    config = {"configurable": {"thread_id": "user-001"}}
    for chunk in app.stream({"messages": [HumanMessage("退款")]}, config=config):
        ...

    # 5. 主管审批 (前端 POST /resume)
    from langgraph.types import Command
    app.invoke(Command(resume="approve"), config=config)

    # 6. 监控 (LangSmith 自动 trace, 也可以手动上报)
    #   LANGSMITH_TRACING=true  → 环境变量开就自动 trace
    """
    print(snippet)

    # 💡 关键架构点:
    #   - Checkpointer + Store 分离: 短期对话 vs 长期知识
    #   - interrupt_before / interrupt_after: 关键节点留审批口
    #   - thread_id 设计: 用户级别 vs 会话级别
    #   - 多副本: 同一 DB → 任意副本都能接续 (StatefulSet 部署)
    #   - 监控: LangSmith 自动 trace, 错误 / 慢节点 / token 用量一目了然


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
        ("demo_history", demo_history),
        ("demo_time_travel", demo_time_travel),
        ("demo_replay", demo_replay),
        ("demo_crash_recovery", demo_crash_recovery),
        ("demo_audit", demo_audit),
        ("demo_update_state", demo_update_state),
        ("demo_checkpoint_vs_store", demo_checkpoint_vs_store),
        ("demo_update_state_as_node", demo_update_state_as_node),
        ("demo_concurrent_fork", demo_concurrent_fork),
        ("demo_production_snippet", demo_production_snippet),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 10_durable_execution.py 全部 demo 跑完。")
