# L2-10 · Durable Execution:进程挂了状态不丢

> AI Agent 跑长时间任务最怕什么?跑了 1 小时,进程被 OOM killer / 部署升级 / 网络抖动搞挂了,前功尽弃。LangGraph 的 Durable Execution 通过 checkpoint + replay + time travel 让 Agent **天然容错**——进程挂了重启,从 checkpoint 续走,LLM 调用记录在 checkpoint 里不重复扣 token。

## 为什么学这个

生产里 Agent 系统不是"调一次 LLM 就完事",经常是:

- 长报告生成(10+ 轮 LLM + 工具调用)
- 多步研究任务(几十分钟)
- 多 Agent 协作(Swarm / Supervisor)
- 长时间 HITL 审批(等人审批几小时)

这些场景里"进程挂了不能丢状态"是底线。LangGraph 提供四把武器:

1. **Checkpoint**(L2-07 讲过)— 每个节点结束自动存盘
2. **Replay** — 从某 checkpoint 重放,不重跑 LLM
3. **Time travel** — 改历史 state 续走
4. **Fork** — 从历史开新分支

加上 PostgresSaver 跨进程 + LangSmith trace 审计,生产架构就齐了。

## 学完你能回答 10 个问题

1. 怎么从某个 checkpoint 重放(不重跑 LLM)?
2. 怎么 fork state 走分支(time travel)?
3. 进程挂了 state 怎么不丢?(checkpointer + 重连)
4. 怎么审计完整执行链路(events)?
5. 怎么用 update_state 改历史(人类修正)?
6. 怎么用 SqliteSaver 跨进程持久?
7. 怎么区分 Checkpointer(短期)vs Store(长期)?
8. 怎么用 as_node 参数把 update_state 注入到指定节点?
9. 怎么并发触发多次分支对比(A/B 探索)?
10. 实战里 durable execution 怎么落地(生产架构)?

## 1. `get_state_history` — 列出所有 checkpoint

```python
app = build_graph(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "audit-1"}}

app.invoke({"messages": [HumanMessage("北京?")]}, config=config)
app.invoke({"messages": [HumanMessage("上海?")]}, config=config)

history = list(app.get_state_history(config))
print(f"共 {len(history)} 个 checkpoint (新 → 旧):")
for i, snap in enumerate(history):
    ts = snap.created_at
    msgs = snap.values.get("messages", [])
    next_node = snap.next
    ckpt_id = snap.config["configurable"]["checkpoint_id"][:8]
    print(f"  [{i}] ts={ts} | next={next_node} | msgs={len(msgs)} | ckpt={ckpt_id}...")
```

实战用途:

| 用途 | 说明 |
|---|---|
| 调试 | 每一步 state 长啥样 |
| 审计 | 用户问"我昨天聊到哪了?" |
| 撤销 | 取上一个 checkpoint 重走 |
| 合规 | 金融 / 医疗场景要追溯每一步决策 |

## 2. Time travel — 从中间 checkpoint fork

```python
r1 = app.invoke({"messages": [HumanMessage("北京?")]}, config=config)

# history[-1] 是最老的 checkpoint (第 1 轮后)
history = list(app.get_state_history(config))
first_ckpt = history[-1]

# 从第 1 轮 fork: 把"北京"改成"上海"
new_config = app.update_state(
    first_ckpt.config,
    {"messages": [HumanMessage("上海?")]},  # 改写输入
)
# 默认 update_state 会创建新 thread_id, 原 thread 不被污染

# 在新 thread 上续走
r2 = app.invoke(
    {"messages": [HumanMessage("延续上一轮")]},
    config=new_config,
)

# 验证: 原 thread 还是只有"北京"
orig_state = app.get_state(config)
print(f"原 thread messages 数: {len(orig_state.values['messages'])}")
```

实战:

| 场景 | 说明 |
|---|---|
| 用户撤回 | "刚才那条不算,我重新说" |
| 错误纠正 | LLM 答错了,主管手动改完再走 |
| A/B 测试 | 同一起点,fork 出 N 个分支对比 |

## 3. Replay — 重放同一个 checkpoint(不重跑 LLM)

```python
history = list(app.get_state_history(config))
first_ckpt = history[-1]

# 重放到第一个 checkpoint(不会重新调 LLM)
replay_config = {
    "configurable": {
        "thread_id": config["configurable"]["thread_id"],
        "checkpoint_id": first_ckpt.config["configurable"]["checkpoint_id"],
    }
}
state = app.get_state(replay_config)
print(f"Replay 拿到 checkpoint, messages 数: {len(state.values['messages'])}")
```

| 维度 | Replay | Time travel |
|---|---|---|
| 行为 | 只读历史 state | 改历史 state,续走 |
| 是否调 LLM | 否 | 续走部分会调 |
| 用途 | 审计 / 调试 | 撤销 / 分支 |

> Replay **完全不消耗 LLM token**(从 checkpoint 直接读),适合审计场景。

## 4. Crash recovery — 进程挂了 state 不丢

生产用 PostgresSaver,SqliteSaver 是单机版:

```python
from langgraph.checkpoint.sqlite import SqliteSaver
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    db_path = str(Path(tmp) / "crash.db")

    # 进程 1:跑 Agent
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        app1 = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "crash-1"}}
        app1.invoke({"messages": [HumanMessage("北京?")]}, config=config)

    # SqliteSaver with 块退出 → 连接关闭, 模拟"进程死掉"

    # 进程 2:用同一个 db 文件启动
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        app2 = build_graph(checkpointer=checkpointer)
        state = app2.get_state({"configurable": {"thread_id": "crash-1"}})
        print(f"进程 2: 恢复, 历史 messages={len(state.values['messages'])}")
```

生产用 PostgresSaver:

```python
from langgraph.checkpoint.postgres import PostgresSaver

DB = "postgresql://user:pwd@host:5432/langgraph"
with PostgresSaver.from_conn_string(DB) as checkpointer:
    checkpointer.setup()  # 首次跑建表
    app = build_graph(checkpointer=checkpointer)
```

**架构**:StatefulSet + 共享 PG,任意副本挂了重启能从 checkpoint 续上。

## 5. Events audit — 完整事件流

```python
counts = {}
for event in app.stream(
    {"messages": [HumanMessage("北京?")]},
    config=config,
    stream_mode="events",
):
    kind = list(event.keys())[0]
    counts[kind] = counts.get(kind, 0) + 1
    data = event[kind]
    if kind == "on_chain_start":
        print(f"[+] node={data.get('name', '?')} 开始")
    elif kind == "on_llm_end":
        resp = data.get("output", {})
        content = resp.get("generations", [[{}]])[0][0].get("text", "")
        print(f"[LLM] 返回: {content[:80]}")
    elif kind == "on_tool_end":
        print(f"[tool] 返回: {str(data.get('output'))[:80]}")

print(f"\n事件统计: {counts}")
```

实战:

| 用途 | 说明 |
|---|---|
| 调试 | 看哪一步慢 / 哪一步报错 |
| 监控 | 上报到 LangSmith / Prometheus |
| 审计 | 合规要求记录每一步决策 |

## 6. update_state — 改历史(人类修正)

场景:用户说"刚才那句话不算, 改成 X":

```python
app.invoke({"messages": [HumanMessage("我叫王明")]}, config=config)
app.invoke({"messages": [HumanMessage("我住在北京")]}, config=config)

# 用户反悔: "我不住北京, 改住上海"
history = list(app.get_state_history(config))
after_first = history[-2]  # 第 1 轮后

# 在那个 checkpoint 上插入"我住在上海"
new_config = app.update_state(
    after_first.config,
    {"messages": [HumanMessage("我住在上海")]},
)

# 续走: Agent 看到的 history 是 [我叫王明, 我住在上海]
r = app.invoke({}, config=new_config)
```

实战:

| 场景 | 说明 |
|---|---|
| 用户编辑自己的历史消息 | "刚才那条改一下" |
| 主管改 Agent 的中间输出 | HITL 流程 |
| A/B 测试 | 同一上下文,fork 不同决策对比 |

## 7. Checkpointer vs Store

| 维度 | Checkpointer | Store |
|---|---|---|
| 粒度 | thread 级 | namespace 级 |
| 用途 | 对话历史(短期) | 用户偏好 / 知识(长期) |
| 量级 | 大(每条都存) | 小(只存关键) |
| 持久化 | SqliteSaver / PostgresSaver | PostgresStore |
| 数量 | 1 thread 1 个 | 1 进程 1 个,N 个 thread 共用 |

实战用法:

```python
checkpointer = PostgresSaver.from_conn_string(DB)  # 短期对话
store = PostgresStore.from_conn_string(DB)          # 长期记忆
app = graph.compile(checkpointer=checkpointer, store=store)
```

## 8. `update_state + as_node` — 注入到指定节点

`update_state` 默认把消息当 HumanMessage 加到末尾。但有时想模拟"某个节点内部产生了某个 state":

```python
new_config = app.update_state(
    config,
    values={"score": 999},
    as_node="scorer",  # 关键: 让框架以为这个 patch 是 scorer 节点产生的
)
```

实战:

| 场景 | 做法 |
|---|---|
| 测试 | 不跑真节点,注入 mock state |
| 修复 | 某个节点坏了,手动算好它的输出塞回去 |
| 复杂 fork | 从某个节点状态重新出发 |

## 9. 并发 fork — A/B 探索

```python
base_config = {"configurable": {"thread_id": "base-A"}}
app.invoke({"messages": [HumanMessage("初始问题")]}, config=base_config)

# 从第 1 轮后 fork
history = list(app.get_state_history(base_config))
after_first = history[-1]

# 分支 A: 让 Agent 关注天气
config_a = app.update_state(after_first.config, {"messages": [HumanMessage("详细说天气")]})
# 分支 B: 让 Agent 关注时间
config_b = app.update_state(after_first.config, {"messages": [HumanMessage("详细说时间")]})

# 并发跑
r_a = app.invoke({}, config=config_a)
r_b = app.invoke({}, config=config_b)
```

实战:

| 场景 | 说明 |
|---|---|
| A/B 测试 | 同一 prompt,换不同 model / temperature 对比 |
| 多策略 | 同一起点,跑多种解法选最优 |
| Monte Carlo | 同一起点,跑 N 次统计稳定性 |

## 10. 生产架构

```python
# 1. PostgresSaver — 跨进程 state
from langgraph.checkpoint.postgres import PostgresSaver
DB = "postgresql://user:pwd@host:5432/langgraph"

with PostgresSaver.from_conn_string(DB) as checkpointer:
    checkpointer.setup()

# 2. PostgresStore — 长期记忆
from langgraph.store.postgres import PostgresStore
with PostgresStore.from_conn_string(DB) as store:
    store.setup()

# 3. 组装图
app = graph.compile(
    checkpointer=checkpointer,
    store=store,
    interrupt_before=["human_review"],  # 关键节点审批
)

# 4. 触发 + 恢复
config = {"configurable": {"thread_id": "user-001"}}
for chunk in app.stream({"messages": [HumanMessage("退款")]}, config=config):
    ...

# 5. 主管审批(前端 POST /resume)
from langgraph.types import Command
app.invoke(Command(resume="approve"), config=config)

# 6. 监控(LangSmith 自动 trace)
#   LANGSMITH_TRACING=true → 环境变量开就自动 trace
```

关键架构点:

- Checkpointer + Store 分离:短期对话 vs 长期知识
- interrupt_before / interrupt_after:关键节点留审批口
- thread_id 设计:用户级别 vs 会话级别
- 多副本:同一 DB → 任意副本都能接续(StatefulSet 部署)
- 监控:LangSmith 自动 trace,错误 / 慢节点 / token 用量一目了然

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| Crash 后状态丢 | 用 InMemorySaver | 换 PostgresSaver |
| PostgresSaver 启动报错 | 表没建 | 调 `checkpointer.setup()` |
| 多副本 state 不一致 | 各自用 InMemorySaver | 共享 PostgresSaver |
| update_state 没生效 | 没用 new_config | 必须用返回的 config 续走 |
| time travel 报错 | checkpoint_id 错了 | 用 `get_state_history` 拿正确 id |
| 并发 fork 状态混乱 | 多线程写同一 thread | 用不同 thread_id |

## 小结

- `get_state_history` 审计所有 checkpoint
- Time travel 改历史走分支,不污染原 thread
- Replay 重放不消耗 LLM token
- Crash recovery 靠持久化 saver(Sqlite 单机 / Postgres 生产)
- Events stream 拿完整链路,debug + 监控用
- update_state 改历史,人类修正必备
- Checkpointer 短期 vs Store 长期分清
- `as_node` 注入 mock state,测试 / 修复用
- 并发 fork 做 A/B 探索
- 生产架构:StatefulSet + 共享 PG + LangSmith

Durable Execution 是 LangGraph 区别于其他 Agent 框架的核心竞争力。下一步是让 **每一步都可观测**——L3-11 LangSmith Tracing 见。

## 延伸阅读

- [LangGraph Durable Execution 官方文档](https://langchain-ai.github.io/langgraph/concepts/durable_execution/)
- 上一篇:[L2-09 Streaming 流式输出](./L2-09_streaming.md)
- 下一篇:[L3-11 LangSmith Tracing](./L3-11_langsmith_tracing.md)
- 源码:`02-langgraph-orchestration/10_durable_execution.py`
