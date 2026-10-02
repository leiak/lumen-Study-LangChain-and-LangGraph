# L2-09 · 流式输出:前端打字机效果怎么实现

> ChatGPT 那种"一个字一个字蹦"的体验,LangGraph 用 `stream_mode` 全部支持。这篇拆 7 种流式模式,从完整 state 快照到 LLM token 级推送,生产 SSE / WebSocket 集成一网打尽。

## 为什么学这个

生产里 99% 的 Agent 都要流式输出——用户看到"打字机效果"才会觉得"AI 在思考"。

LangGraph 提供 6 种 `stream_mode`:

| 模式 | 输出粒度 | 用途 |
| --- | --- | --- |
| `values` | 每步完整 state | 调试 / 同步刷新 |
| `updates` | 每步 state delta | 增量 patch / chat |
| `messages` | LLM token | 打字机效果 / SSE |
| `events` | 详细事件 | 调试 / LangSmith 上报 |
| `custom` | 节点内主动推 | 长任务进度 |
| `list` | 同时订阅多种 | 一次拿多源 |

每种都有适用场景,选错模式要么性能差,要么实现难。

## 学完你能回答 7 个问题

1. `stream` vs `astream` 区别?
2. `stream_mode` 有哪些?(values / updates / messages / events / custom)
3. 怎么给前端输出 token 级流?
4. 怎么用 `stream_mode="custom"` 让节点主动推进度?
5. 怎么同时订阅多个 stream_mode(传 list)?
6. async stream 怎么写?

## 1. `stream_mode="values"` — 每步返回完整 state

```python
for chunk in agent.stream(
    {"messages": [HumanMessage("上海天气?")]},
    config={"configurable": {"thread_id": "stream-1"}},
    stream_mode="values",
):
    msgs = chunk.get("messages", [])
    if msgs:
        last = msgs[-1]
        print(f"[{type(last).__name__}] {(last.content or '')[:60]}")
```

每次返回完整的 state 快照。适合:
- 调试(看每步后整个 state 长啥样)
- 同步刷新(整页替换 UI)

## 2. `stream_mode="updates"` — 每步返回 state delta

```python
for chunk in agent.stream(
    {"messages": [HumanMessage("北京天气?")]},
    config={"configurable": {"thread_id": "stream-2"}},
    stream_mode="updates",
):
    # chunk = {node_name: state_delta}
    for node, delta in chunk.items():
        if "messages" in delta:
            for m in delta["messages"]:
                print(f"[node={node}] {type(m).__name__}: {(m.content or '')[:60]}")
```

每个 chunk 是 `{node_name: state_delta}`,只返回"本步新增"。适合:
- 前端 patch 风格(只渲染新增)
- chat 增量更新

## 3. `stream_mode="messages"` — LLM token 级流

```python
print(">>> token 级流 (像 ChatGPT 那样一个字一个字蹦):")
print(">>> ", end="", flush=True)
for token, metadata in agent.stream(
    {"messages": [HumanMessage("介绍 LangGraph")]},
    config={"configurable": {"thread_id": "stream-3"}},
    stream_mode="messages",
):
    if hasattr(token, "content") and token.content:
        # metadata 里能拿到 langgraph_node / langgraph_path
        print(token.content, end="", flush=True)
print()
```

每个 chunk 是 `(AIMessageChunk, metadata)` 元组。`content` 是一个 token 的字符串。

适合:
- 前端 SSE 推 token(打字机)
- FastAPI `text/event-stream`

实战 FastAPI 集成:

```python
from fastapi.responses import StreamingResponse

@app.post("/chat/{thread_id}")
async def chat(thread_id: str, message: str):
    async def gen():
        async for token, _ in app.astream(
            {"messages": [HumanMessage(message)]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            if hasattr(token, "content") and token.content:
                yield f"data: {json.dumps({'token': token.content})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
```

前端 EventSource:

```javascript
const source = new EventSource('/chat/thread-001');
source.onmessage = (e) => {
    if (e.data === '[DONE]') source.close();
    else appendMessage(JSON.parse(e.data).token);
};
```

## 4. `stream_mode="events"` — 详细事件流

```python
for i, event in enumerate(agent.stream(
    {"messages": [HumanMessage("广州?")]},
    config={"configurable": {"thread_id": "stream-4"}},
    stream_mode="events",
)):
    kind = list(event.keys())[0]
    print(f"[{i}] {kind}: {str(event[kind])[:80]}")
    if i >= 5:
        break
```

每步所有事件(`on_chain_start` / `on_llm_start` / `on_tool_start` / `on_llm_stream` / `on_chain_end`...)。

适合:
- 调试(看哪步慢 / 哪步报错)
- LangSmith 自动上报
- 监控(Prometheus / 飞书报警)

事件类型速查:

| 类型 | 含义 |
| --- | --- |
| `on_chain_start` / `on_chain_end` | 节点进入 / 退出 |
| `on_llm_start` / `on_llm_end` | LLM 调用开始 / 结束 |
| `on_llm_stream` | LLM token |
| `on_tool_start` / `on_tool_end` | 工具调用开始 / 结束 |

## 5. `stream_mode="custom"` — 节点主动推进度

长任务场景需要"AI 正在查 A 接口...查 B 接口...正在生成报告..."的体验:

```python
from langgraph.config import get_stream_writer
import time

def slow_node(state: State):
    # get_stream_writer() 拿到当前流的 writer, 直接写 dict 出去
    writer = get_stream_writer()
    for i in range(5):
        writer({"progress": f"step {i+1}/5"})
        time.sleep(0.05)
    return {"messages": [HumanMessage(content="done")]}

graph = StateGraph(State)
graph.add_node("slow", slow_node)
graph.add_edge(START, "slow")
graph.add_edge("slow", END)
app = graph.compile()

# 节点内主动推 progress
for chunk in app.stream({"messages": []}, stream_mode="custom"):
    print(f"[custom] {chunk}")
```

实战:

| 场景 | 推送内容 |
|---|---|
| 多源 RAG 检索 | "查 KB1...查 KB2...查 KB3..." |
| 多步报告生成 | "正在分析数据...正在生成图表...正在写摘要..." |
| 多模型投票 | "调 GPT-4o...调 Claude...汇总结果..." |

类似 SSE(server-sent events)的前端体验。

## 6. 同时订阅多个 stream_mode(传 list)

前端需要同时拿"步骤进度(updates)"和"token 流(messages)":

```python
updates_count = 0
for mode, chunk in agent.stream(
    {"messages": [HumanMessage("杭州天气?")]},
    config={"configurable": {"thread_id": "stream-multi"}},
    stream_mode=["updates", "messages"],  # 同时订阅
):
    if mode == "updates":
        updates_count += 1
        for node, delta in chunk.items():
            if "messages" in delta:
                print(f"[updates / {node}] {len(delta['messages'])} new msg(s)")
    elif mode == "messages":
        # token 流: 打印到一行
        if hasattr(chunk, "content") and chunk.content:
            print(chunk.content, end="", flush=True)
print(f"\n(updates 事件共 {updates_count} 次)")
```

返回类型变成 `(mode, chunk)` 元组。比开两次 stream 高效(内部共享一次执行)。

实战 SSE 推送:

```python
async def gen():
    async for mode, chunk in app.astream(
        input, config=config,
        stream_mode=["updates", "messages"],
    ):
        if mode == "messages" and hasattr(chunk, "content"):
            yield f"event: token\ndata: {chunk.content}\n\n"
        elif mode == "updates":
            yield f"event: step\ndata: {json.dumps(chunk)}\n\n"
```

前端 EventSource 可以监听不同 event type:

```javascript
source.addEventListener('token', (e) => appendText(e.data));
source.addEventListener('step', (e) => updateProgress(JSON.parse(e.data)));
```

## 7. 异步流(astream)

FastAPI / WebSocket 场景必备:

```python
async for chunk in agent.astream(
    {"messages": [HumanMessage("深圳?")]},
    config={"configurable": {"thread_id": "stream-async"}},
    stream_mode="updates",
):
    for node, delta in chunk.items():
        if "messages" in delta:
            print(f"[async / node={node}] {type(delta['messages'][0]).__name__}")
```

| 方法 | 场景 |
|---|---|
| `.stream()` | 同步,简单的 CLI / 测试 |
| `.astream()` | 异步,FastAPI / WebSocket |
| `.astream_events()` | 详细事件,LangSmith 上报 |

## 实战踩坑

| 坑 | 原因 | 解法 |
|---|---|---|
| `chunk.content` 空字符串 | LLM 正在吐 tool_calls | 业务逻辑 `if chunk.content:` |
| 打字机效果卡顿 | 同步 stream 阻塞 | 切 `astream` + 异步生成器 |
| custom writer 拿不到 | 没用 `get_stream_writer()` | 在节点函数里 `writer = get_stream_writer()` |
| 多模式订阅性能差 | 业务层重复订阅 | 用 `stream_mode=list` 一次订阅 |
| SSE 中文乱码 | FastAPI 默认编码 | response header 加 `charset=utf-8` |
| 前端 EventSource 不关闭 | 后端没发 [DONE] | yield `data: [DONE]\n\n` |

## 生产架构

```python
# FastAPI + SSE 集成
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

@app.post("/chat/{thread_id}")
async def chat(thread_id: str, message: str):
    async def gen():
        async for mode, chunk in agent.astream(
            {"messages": [HumanMessage(message)]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                if hasattr(chunk, "content") and chunk.content:
                    yield f"event: token\ndata: {json.dumps({'token': chunk.content}, ensure_ascii=False)}\n\n"
                elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    # 通知前端 AI 在调工具
                    yield f"event: tool_call\ndata: {json.dumps([tc['name'] for tc in chunk.tool_calls])}\n\n"
            elif mode == "updates":
                # 节点进度(进入 / 退出)
                for node in chunk:
                    yield f"event: step\ndata: {json.dumps({'node': node})}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

前端代码:

```javascript
const source = new EventSource('/chat/thread-001');
const output = document.getElementById('ai-output');

source.addEventListener('token', (e) => {
    output.innerText += JSON.parse(e.data).token;
});

source.addEventListener('tool_call', (e) => {
    showProgress(`AI 正在调用工具: ${JSON.parse(e.data)}`);
});

source.addEventListener('step', (e) => {
    const {node} = JSON.parse(e.data);
    updateStepIndicator(node);
});

source.addEventListener('done', () => source.close());
```

## 小结

- `stream_mode="values"`:完整 state 快照,调试用
- `stream_mode="updates"`:state delta,前端 patch 用
- `stream_mode="messages"`:LLM token 流,打字机效果
- `stream_mode="events"`:详细事件,调试 / 监控用
- `stream_mode="custom"`:节点内主动推进度
- `stream_mode=list`:一次订阅多种模式
- `astream` 异步版本,FastAPI / WebSocket 场景

流式让用户"看得见"Agent 在干嘛。下一步是让 Agent **挂了也能恢复**——L2-10 Durable Execution 见。

## 延伸阅读

- [LangGraph Streaming 官方文档](https://langchain-ai.github.io/langgraph/concepts/streaming/)
- 上一篇:[L2-08 Interrupt HITL](./L2-08_interrupt_hitl.md)
- 下一篇:[L2-10 Durable Execution](./L2-10_durable_execution.md)
- 源码:`02-langgraph-orchestration/09_streaming.py`
