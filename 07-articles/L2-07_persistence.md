# L2-07 · 持久化与 Checkpointer:多轮对话的"记忆"

> 没有持久化的 Agent 跟金鱼一样——每次 invoke 都是"全新开始"。LangGraph 的 Checkpointer 把每次 state 存盘,跨进程、跨重启、跨设备都能续上对话。这篇拆 9 个 demo,从 InMemorySaver 到 PostgresSaver,从线程隔离到时光机。

## 为什么学这个

`StateGraph.compile()` 默认不存状态,每次 `invoke()` 都是干净启动。多轮对话 / 长时间任务 / 进程崩溃恢复,全部要靠 Checkpointer。

生产里 Checkpointer 解决三大问题:

1. **多轮对话**:用户第 5 次提问,LLM 知道前 4 轮说过啥
2. **跨进程**:web 服务重启,用户会话不丢
3. **审计 / 撤销**:能拿到所有历史 state,随时"时光倒流"

跟 Spring Session / Redis 是一回事,只不过存的是 Agent state 而不是 HTTP session。

## 学完你能回答 9 个问题

1. `InMemorySaver` 怎么存线程级状态?
2. `thread_id` 是什么?怎么隔离多会话?
3. `get_state_history` 怎么审计所有 checkpoint?
4. `Store` 怎么存跨 thread 的长期记忆?
5. 怎么序列化和反序列化 state?
6. `SqliteSaver` 怎么单文件持久化?
7. `PostgresSaver` 在生产怎么用?
8. 怎么"时光机"回到历史 checkpoint 重新走?
9. 怎么从历史 checkpoint fork 出新分支?

## 1. InMemorySaver — 进程内存

```python
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent

checkpointer = InMemorySaver()  # 进程重启就丢
agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)

config = {"configurable": {"thread_id": "user-001"}}

agent.invoke({"messages": [HumanMessage("我是王明, 北京人")]}, config=config)
r = agent.invoke({"messages": [HumanMessage("我叫什么?")]}, config=config)
# 第 2 轮 LLM 看到历史 → 答"王明"
```

`thread_id` = 对话唯一标识。同 thread 共享历史,不同 thread 隔离。

| Saver | 持久化 | 适用 |
| --- | --- | --- |
| `InMemorySaver` | 进程内存 | 教学 / 单测 |
| `SqliteSaver` | 单文件 SQLite | demo / 小项目 |
| `PostgresSaver` | PostgreSQL | 生产 / 多副本 |

## 2. 多 thread 隔离

```python
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

# 验证: thread A 不知道 Bob
r = agent.invoke(
    {"messages": [HumanMessage("我叫什么?")]},
    config={"configurable": {"thread_id": "thread-A"}},
)
# → "你是 Alice"
```

`thread_id` 设计:

| 设计 | 适用 |
| --- | --- |
| `"user-001"` | 单用户单会话 |
| `"user-001-conv-A"` | 单用户多会话 |
| `"team-123-thread-456"` | 团队协作 |

业务含义自己定,关键是 thread_id 唯一即可。

## 3. get_state_history — 看所有 checkpoint

```python
config = {"configurable": {"thread_id": "audit-thread"}}

agent.invoke({"messages": [HumanMessage("北京?")]}, config=config)
agent.invoke({"messages": [HumanMessage("上海?")]}, config=config)
agent.invoke({"messages": [HumanMessage("广州?")]}, config=config)

history = list(agent.get_state_history(config))
print(f"共 {len(history)} 个 checkpoint:")
for i, state in enumerate(history):
    cid = state.config["configurable"]["checkpoint_id"][:8]
    msgs = len(state.values.get("messages", []))
    print(f"  [{i}] id={cid}... msgs={msgs}")
```

实战用途:

| 用途 | 说明 |
| --- | --- |
| 调试 | 看每一步 state 变化 |
| 审计 | "我昨天聊到哪了?" |
| 撤销 | 回到上一个 checkpoint 重走 |

## 4. Store — 跨 thread 的长期记忆

Checkpointer 存 thread 级(短期),Store 存 namespace 级(长期):

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()
agent = create_agent(
    model=llm, tools=[get_weather],
    checkpointer=InMemorySaver(),
    store=store,
)

# 写入用户偏好(任何 thread 都能读到)
user_id = "user-123"
namespace = ("preferences", user_id)  # (类型, id) tuple
store.put(namespace, "language", {"value": "中文"})
store.put(namespace, "city", {"value": "上海"})

# 另一个 thread 读
item = store.get(namespace, "language")
print(f"跨 thread 读偏好: {item.value}")

# 列出所有偏好
items = store.search(namespace)
for it in items:
    print(f"  - {it.key}: {it.value}")
```

| 维度 | Checkpointer | Store |
| --- | --- | --- |
| 粒度 | thread 级 | namespace 级 |
| 用途 | 对话历史 | 用户偏好 / 知识 |
| 量级 | 大(每条都存) | 小(只存关键) |
| 持久化 | SqliteSaver / PostgresSaver | PostgresStore |

> 一个进程 1 个 store,但 N 个 thread 的 checkpoint。

## 5. 序列化 state — 跨进程恢复

```python
state = agent.get_state(config)
serialized = state.values["messages"]

# 序列化成 JSON
import json
dumped = [m.model_dump() for m in serialized]
blob = json.dumps(dumped, ensure_ascii=False, default=str)

# 反序列化
_MSG_CLASSES = {
    "human": HumanMessage,
    "ai": AIMessage,
    "system": SystemMessage,
    "tool": ToolMessage,
}
loaded_msgs = [
    _MSG_CLASSES.get(m.get("type"), HumanMessage).model_validate(m)
    for m in json.loads(blob)
]
```

JSON 序列化是跨进程 / 跨服务传 state 的基础。生产里通常用 Redis 缓存 + DB 持久化组合。

## 6. SqliteSaver — 单文件持久化

```python
from langgraph.checkpoint.sqlite import SqliteSaver
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmp:
    db_path = str(Path(tmp) / "state.db")

    # 进程 1:写
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)
        agent.invoke({"messages": [HumanMessage("北京?")]},
                     config={"configurable": {"thread_id": "sqlite-thread"}})

    # 进程 2:模拟重启,读
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        agent = create_agent(model=llm, tools=[get_weather], checkpointer=checkpointer)
        state = agent.get_state({"configurable": {"thread_id": "sqlite-thread"}})
        print(f"重启后历史: {len(state.values['messages'])} 条")
```

> 需要 `pip install langgraph-checkpoint-sqlite`。

SqliteSaver 适用:单机 demo / 个人项目 / 没有 PG 的环境。**不要在生产用**——单点故障 + 不能分布式。

## 7. PostgresSaver — 生产持久化

```python
from langgraph.checkpoint.postgres import PostgresSaver

DB_URI = "postgresql://postgres:postgres@db:5432/langgraph"

with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
    checkpointer.setup()  # 首次跑建表

    agent = create_agent(
        model=llm, tools=[get_weather],
        checkpointer=checkpointer,
    )

    # 多副本 / 多 worker 共享同一个 PG → state 自动同步
    agent.invoke(
        {"messages": [HumanMessage("我是王明")]},
        config={"configurable": {"thread_id": "user-001"}},
    )
```

生产优势:

| 优势 | 说明 |
| --- | --- |
| 跨进程 | 多个 worker 共享同一 DB |
| 跨设备 | 同一 thread 在不同机器接续 |
| 高可用 | PG 主从 / 备份 |
| 可观测 | 用 SQL 直接查 state |

部署模式:StatefulSet + 共享 PG,任意副本挂了重启都能从 checkpoint 续上。

## 8. 时间旅行 — 回到历史 checkpoint

```python
config = {"configurable": {"thread_id": "time-travel"}}

agent.invoke({"messages": [HumanMessage("我叫张三")]}, config=config)
agent.invoke({"messages": [HumanMessage("我住在北京")]}, config=config)
agent.invoke({"messages": [HumanMessage("我做 Python")]}, config=config)

# 取第 2 个 checkpoint(用户只说过"我叫张三"那一轮)
history = list(agent.get_state_history(config))
if len(history) >= 2:
    past_state = history[1]

    # 改历史:从这一轮开始改成"我住在上海"
    new_config = agent.update_state(
        past_state.config,
        values={"messages": [HumanMessage("我住在上海")]},
    )

    # 续走 → LLM 看到 history 是 [张三, 上海],不是 [张三, 北京]
    r = agent.invoke({}, config=new_config)
```

实战:

| 场景 | 做法 |
| --- | --- |
| 用户撤销 | "刚才那句话不算, 我重新说" |
| 错误纠正 | LLM 答错了, 主管手动改完再走 |
| A/B 测试 | 同一起点, 走不同分支 |

## 9. Fork — 从历史开新分支

跟 time_travel 类似,但保留原 thread 不动,开新 thread_id:

```python
config = {"configurable": {"thread_id": "original"}}
agent.invoke({"messages": [HumanMessage("北京天气?")]}, config=config)
agent.invoke({"messages": [HumanMessage("我应该带伞吗?")]}, config=config)

history = list(agent.get_state_history(config))
past_state = history[1]

# 在 fork 上改 state, 不影响原 thread
forked_config = {
    "configurable": {
        "thread_id": "forked-branch",  # 新 thread
        "checkpoint_id": past_state.config["configurable"]["checkpoint_id"],  # 老 checkpoint
    }
}
new_config = agent.update_state(
    forked_config,
    values={"messages": [HumanMessage("上海天气?")]},  # 改成问上海
)
r = agent.invoke({}, config=new_config)

# 原 thread 还是"北京"
r_orig = agent.invoke(
    {"messages": [HumanMessage("我刚才问的是哪个城市?")]},
    config={"configurable": {"thread_id": "original"}},
)
# → "北京"
```

实战:

| 场景 | 说明 |
| --- | --- |
| A/B 测试 | 同一起点, fork 多分支对比 |
| 用户撤销 | 回到某步, 改一句话, 重走 |
| 多分支探索 | 决策树状探索 |

## 实战踩坑

| 坑 | 原因 | 解法 |
| --- | --- | --- |
| 进程重启 state 丢 | 用 InMemorySaver | 换 SqliteSaver / PostgresSaver |
| 多副本 state 不一致 | 各自用 InMemorySaver | 共享 PostgresSaver |
| `update_state` 后 invoke 卡 | 没传 config | 用 `new_config` 续走 |
| Sqlite 锁等待 | 单文件并发写 | 切 PostgresSaver |
| 历史 checkpoint 太多 | 没清理 | 加 retention 策略 |
| thread_id 设计混乱 | 业务含义不清 | 团队约定统一规范 |

## 生产架构

```python
# 1. PostgresSaver 跨进程
with PostgresSaver.from_conn_string(DB) as cp:
    cp.setup()
    agent = create_agent(model=llm, tools=[...], checkpointer=cp)

# 2. Store 长期记忆
with PostgresStore.from_conn_string(DB) as store:
    store.setup()

# 3. 完整配置
app = graph.compile(
    checkpointer=cp,
    store=store,
    interrupt_before=["human_review"],  # 关键节点审批
)

# 4. thread_id 设计
config = {
    "configurable": {"thread_id": f"user-{user_id}-conv-{conv_id}"},
    "metadata": {"user_tier": "vip"},  # LangSmith 上报用
}

# 5. 部署:StatefulSet + 共享 PG → 任意副本挂了能续
```

## 小结

- Checkpointer = 持久化 state,支持多轮 + 跨进程
- `thread_id` 隔离会话,业务自己设计 ID 规则
- Checkpointer 短期(thread)vs Store 长期(namespace)分清
- `get_state_history` 审计 + 撤销 + A/B 测试
- 时光机 / fork 改历史不污染原 thread
- 生产用 PostgresSaver + PostgresStore

Checkpointer 让 Agent 有了"记忆"。下一步是给记忆加 **人工介入**——L2-08 HITL 见。

## 延伸阅读

- [LangGraph Persistence 官方文档](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- 上一篇:[L2-06 StateGraph 把 Agent 拆成图](./L2-06_state_graph.md)
- 下一篇:[L2-08 Interrupt HITL 人工介入](./L2-08_interrupt_hitl.md)
- 源码:`02-langgraph-orchestration/07_persistence.py`
