"""07_persistence.py — 持久化: 长对话 + 跨进程恢复.

学完这个模块你能回答:
1.  InMemorySaver 怎么存线程级状态?
2.  thread_id 是什么? 怎么隔离多会话?
3.  get_state_history 怎么审计所有 checkpoint?
4.  Store 怎么存跨 thread 的长期记忆 (用户偏好)?
5.  怎么序列化和反序列化 state?
6.  SqliteSaver 怎么单文件持久化 (教学/小项目)?
7.  PostgresSaver 在生产怎么用?
8.  怎么"时光机"回到历史 checkpoint 重新走?
9.  怎么从历史 checkpoint fork 出新分支?

跑法:
    python 07_persistence.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from _common import banner, get_llm

# ============================================================
# 共享工具
# ============================================================


@tool
def get_weather(city: str) -> str:
    """查天气."""
    return f"{city} 晴 25°C"


# ============================================================
# 1. InMemorySaver — 进程内存 (教学用)
# ============================================================
banner("1. InMemorySaver — 进程内存")


def demo_in_memory() -> None:
    llm = get_llm()
    checkpointer = InMemorySaver()  # 进程重启就丢

    agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

    # thread_id = 对话唯一标识 — 同 thread 共享历史, 不同 thread 隔离
    config = {"configurable": {"thread_id": "user-001"}}

    r1 = agent.invoke({"messages": [HumanMessage("我是王明, 北京人")]}, config=config)
    print(f">>> 第 1 轮: {r1['messages'][-1].content[:80]}")

    # 第 2 轮: 同 thread_id, 自动续上
    r2 = agent.invoke({"messages": [HumanMessage("我叫什么?")]}, config=config)
    print(f">>> 第 2 轮: {r2['messages'][-1].content[:80]}")

    state = agent.get_state(config)
    print(f">>> 历史消息数: {len(state.values['messages'])}")

    # 💡 Checkpointer vs 普通 dict:
    #   dict: 程序退出就丢
    #   InMemorySaver: 进程内持久 (教学用)
    #   SqliteSaver: 单文件持久 (单机小项目)
    #   PostgresSaver: 跨进程 / 分布式 (生产)


# ============================================================
# 2. 多 thread 隔离
# ============================================================
banner("2. 多 thread 隔离")


def demo_multi_thread() -> None:
    llm = get_llm()
    checkpointer = InMemorySaver()
    agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

    # thread A: Alice
    agent.invoke(
        {"messages": [HumanMessage("我是 Alice")]},
        config={"configurable": {"thread_id": "thread-A"}},
    )

    # thread B: Bob
    agent.invoke(
        {"messages": [HumanMessage("我是 Bob")]},
        config={"configurable": {"thread_id": "thread-B"}},
    )

    # 验证隔离: thread A 不知道自己叫 Bob
    r = agent.invoke(
        {"messages": [HumanMessage("我叫什么?")]},
        config={"configurable": {"thread_id": "thread-A"}},
    )
    print(f">>> thread A: {r['messages'][-1].content[:80]}")

    r = agent.invoke(
        {"messages": [HumanMessage("我叫什么?")]},
        config={"configurable": {"thread_id": "thread-B"}},
    )
    print(f">>> thread B: {r['messages'][-1].content[:80]}")

    # 💡 thread_id 设计:
    #   - 单用户单会话: "user-001"
    #   - 单用户多会话: "user-001-conv-A"
    #   - 团队协作: "team-123-thread-456"
    #   - 关键: thread_id 唯一即可, 业务含义自己定


# ============================================================
# 3. get_state_history — 看所有 checkpoint
# ============================================================
banner("3. get_state_history — checkpoint 历史")


def demo_state_history() -> None:
    llm = get_llm()
    checkpointer = InMemorySaver()
    agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "audit-thread"}}

    # 跑 3 轮 → 3 个 checkpoint
    agent.invoke({"messages": [HumanMessage("北京?")]}, config=config)
    agent.invoke({"messages": [HumanMessage("上海?")]}, config=config)
    agent.invoke({"messages": [HumanMessage("广州?")]}, config=config)

    history = list(agent.get_state_history(config))
    print(f">>> 共 {len(history)} 个 checkpoint:")
    for i, state in enumerate(history[:5]):
        cid = state.config["configurable"]["checkpoint_id"][:8]
        msgs = len(state.values.get("messages", []))
        print(f"  [{i}] id={cid}... msgs={msgs}")

    # 💡 实战用途:
    #   - 调试: 看每一步 state 变化
    #   - 审计: 用户问"我昨天聊到哪了?"
    #   - 撤销: 回到上一个 checkpoint 重走 (见 demo_time_travel)


# ============================================================
# 4. Store — 跨 thread 的长期记忆
# ============================================================
banner("4. Store — 跨 thread 长期记忆")


def demo_store() -> None:
    llm = get_llm()
    store = InMemoryStore()  # 生产用 PostgresStore
    checkpointer = InMemorySaver()

    agent = create_agent(
        model=llm, tools=[get_weather],
        checkpointer=checkpointer, store=store,
    )

    # 模拟写入用户偏好 (实际场景可以在工具里写)
    user_id = "user-123"
    namespace = ("preferences", user_id)  # 命名空间 = (类型, id) tuple
    store.put(namespace, "language", {"value": "中文"})
    store.put(namespace, "city", {"value": "上海"})

    # 在另一个 thread 里读取 (跨 thread!)
    item = store.get(namespace, "language")
    print(f">>> 跨 thread 读偏好: {item.value}")

    # 列出所有偏好
    items = store.search(namespace)
    print(f">>> 该用户共 {len(items)} 条偏好:")
    for it in items:
        print(f"  - {it.key}: {it.value}")

    # 💡 Checkpointer vs Store:
    #   Checkpointer: thread 级别, 对话历史 (短期, 量大)
    #   Store:        namespace 级别, 长期记忆 (用户偏好 / 知识, 少量)
    # 一个进程有 1 个 store, 但有 N 个 thread 的 checkpoint


# ============================================================
# 5. 序列化 state — 跨进程恢复
# ============================================================
banner("5. 序列化 state (跨进程)")


def demo_serialize() -> None:
    llm = get_llm()
    checkpointer = InMemorySaver()
    agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "serialize-demo"}}
    agent.invoke({"messages": [HumanMessage("我是王明")]}, config=config)

    state = agent.get_state(config)
    serialized = state.values["messages"]

    # 模拟跨进程: 序列化成 JSON
    dumped = [m.model_dump() for m in serialized]
    blob = json.dumps(dumped, ensure_ascii=False, default=str)
    print(f">>> 序列化大小: {len(blob)} chars")

    # 反序列化 (按 type 分发到对应 Message 类)
    _MSG_CLASSES = {"human": HumanMessage, "ai": AIMessage, "system": SystemMessage, "tool": ToolMessage}
    loaded_msgs = [(_MSG_CLASSES.get(m.get("type"), HumanMessage)).model_validate(m) for m in json.loads(blob)]
    print(f">>> 反序列化消息数: {len(loaded_msgs)}")
    print(f">>> 类型分布: {[type(m).__name__ for m in loaded_msgs]}")


# ============================================================
# 6. SqliteSaver — 单文件持久化 (教学友好)
# ============================================================
banner("6. SqliteSaver — 单文件持久化")


def demo_sqlite() -> None:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        print(">>> 需要安装 langgraph-checkpoint-sqlite: pip install langgraph-checkpoint-sqlite")
        return

    llm = get_llm()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "state.db")

        # SqliteSaver.from_conn_string 直接给 sqlite 文件路径
        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

            config = {"configurable": {"thread_id": "sqlite-thread"}}
            agent.invoke({"messages": [HumanMessage("北京?")]}, config=config)
            print(f">>> 第 1 次 invoke, db 文件: {Path(db_path).stat().st_size} bytes")

        # 重新打开 (模拟进程重启)
        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)
            state = agent.get_state({"configurable": {"thread_id": "sqlite-thread"}})
            print(f">>> 重启后读 state, 消息数: {len(state.values.get('messages', []))}")
            print(f">>> 内容: {state.values['messages'][-1].content[:80]}")

    # 💡 实战选型:
    #   - 单机小项目 / demo: SqliteSaver (无需 docker)
    #   - 分布式 / 多副本: PostgresSaver (需要部署 PG)
    #   - 测试:         InMemorySaver (最快)


# ============================================================
# 7. PostgresSaver — 生产持久化 (示例代码)
# ============================================================
banner("7. PostgresSaver — 生产持久化 (示例代码, 不真跑)")


def demo_postgres_snippet() -> None:
    """生产环境用 PostgresSaver, 需要先有 Postgres 实例."""
    snippet = """
    # 1. 启动 Postgres
    # docker run -d --name pg-langgraph \\
    #   -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16

    from langgraph.checkpoint.postgres import PostgresSaver

    DB_URI = "postgresql://postgres:postgres@localhost:5432/postgres"

    # with 块里: 自动 setup 建表, 退出时关连接
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()  # 第一次跑会建表

        agent = create_agent(
            model=llm, tools=[get_weather],
            checkpointer=checkpointer,
        )

        # 进程重启后, 同 thread_id 自动恢复历史
        agent.invoke(
            {"messages": [HumanMessage("我是王明")]},
            config={"configurable": {"thread_id": "user-001"}},
        )

    # 多个 worker / 多副本 共享同一个 PG → state 自动同步
    """
    print(snippet)


# ============================================================
# 8. 时间旅行 — 回到历史 checkpoint 重新走
# ============================================================
banner("8. 时间旅行 — 回到历史 checkpoint")


def demo_time_travel() -> None:
    llm = get_llm()
    checkpointer = InMemorySaver()
    agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "time-travel"}}

    # 跑 3 轮对话
    agent.invoke({"messages": [HumanMessage("我叫张三")]}, config=config)
    agent.invoke({"messages": [HumanMessage("我住在北京")]}, config=config)
    agent.invoke({"messages": [HumanMessage("我做 Python")]}, config=config)

    # 取第 2 个 checkpoint (用户只说过"我叫张三"那一轮)
    history = list(agent.get_state_history(config))
    if len(history) >= 2:
        past_state = history[1]
        past_config = past_state.config
        print(f">>> 回到第 1 轮后, 消息数: {len(past_state.values['messages'])}")

        # 从这个 checkpoint 继续走 (用 update_state 修改 / 直接 invoke 续)
        # 场景: 用户说"刚才那条我不想说住北京了, 改成住上海"
        new_config = agent.update_state(
            past_config,
            values={"messages": [HumanMessage("我住在上海")]},
        )
        print(">>> update_state 改了历史, 现在是: '我住在上海'")

        # 继续走 → LLM 看到的 history 是 [张三, 上海], 不是 [张三, 北京]
        r = agent.invoke({}, config=new_config)
        print(f">>> 续走: {r['messages'][-1].content[:100]}")


# ============================================================
# 9. Fork — 从历史 checkpoint 开新分支
# ============================================================
banner("9. Fork — 从历史开新分支")


def demo_fork() -> None:
    """和 time_travel 类似, 但保留原 thread 不变, 开新 thread_id."""
    llm = get_llm()
    checkpointer = InMemorySaver()
    agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "original"}}

    agent.invoke({"messages": [HumanMessage("北京天气?")]}, config=config)
    agent.invoke({"messages": [HumanMessage("我应该带伞吗?")]}, config=config)

    history = list(agent.get_state_history(config))
    past_state = history[1]  # 第 1 轮后
    past_config = past_state.config

    # 从第 1 轮 fork, 开新 thread (原 thread 不动)
    # 通过 configurable 改 thread_id, 但 checkpoint_id 指向过去
    forked_config = {
        "configurable": {
            "thread_id": "forked-branch",  # ← 新 thread
            "checkpoint_id": past_config["configurable"]["checkpoint_id"],  # ← 老 checkpoint
        }
    }

    # 在 fork 上改 state, 不影响原 thread
    new_config = agent.update_state(
        forked_config,
        values={"messages": [HumanMessage("上海天气?")]},  # 改成问上海
    )

    r = agent.invoke({}, config=new_config)
    print(f">>> Fork 后回答: {r['messages'][-1].content[:100]}")

    # 验证原 thread 还是"北京"
    r_orig = agent.invoke(
        {"messages": [HumanMessage("我刚才问的是哪个城市?")]},
        config={"configurable": {"thread_id": "original"}},
    )
    print(f">>> 原 thread 仍是: {r_orig['messages'][-1].content[:80]}")

    # 💡 Fork 实战:
    #   - A/B 测试: 同一起点, 走不同分支对比
    #   - 用户撤销: 回到某步, 改一句话, 重走
    #   - 多分支探索: 决策树状探索 (rejected 后回到分歧点)


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

    # 基础
    demo_in_memory()
    demo_multi_thread()
    demo_state_history()
    demo_store()
    demo_serialize()

    # 进阶
    demo_sqlite()
    demo_postgres_snippet()
    demo_time_travel()
    demo_fork()

    print("\n[OK] 07_persistence.py 全部 demo 跑完。")