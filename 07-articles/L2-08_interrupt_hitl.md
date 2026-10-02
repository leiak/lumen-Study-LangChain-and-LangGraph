# L2-08 · HITL 人工介入:让 Agent 在关键决策前暂停

> Agent 跑自动化很爽,但生产场景 90% 需要"人在回路"——退款要主管审批、调外部 API 要确认、隐私数据要人定夺。LangGraph 的 `interrupt()` + `Command(resume=...)` 是 LangChain 1.x 最 powerful 的 HITL(Human-in-the-Loop)机制。这篇拆 6 种场景 + Pydantic schema 高级用法。

## 为什么学这个

完全自动化的 Agent 在生产里几乎不存在:

- 退款超过 100 元 → 必须主管审批
- 删除用户数据 → 必须二次确认
- 调付费 API → 必须人工授权
- 医疗 / 金融决策 → 必须人定夺

LangGraph 的 `interrupt()` 在节点内暂停,等外部 `Command(resume=...)` 恢复。这套机制的优势:

1. **持久化暂停**:进程挂了重启,interrupt 还在
2. **可序列化决策**:决策可以传 dict,前端渲染表单
3. **可中断恢复**:从中断点继续,不重跑

跟 Java 拦截器 / Gin middleware 一个思路,只不过拦截点换成了 Agent 节点。

## 学完你能回答 7 个问题

1. `interrupt()` 怎么在节点中暂停?
2. 怎么用 `Command(resume=...)` 恢复 Agent?
3. 怎么拦截工具参数(e.g. 金额 > 100 才审批)?
4. 怎么支持 edit 决策(主管改参数后批准)?
5. 怎么在 interrupt 后给 LLM 反馈让它重试?
6. 多轮审批怎么串(主管 → 用户 → 执行)?
7. 怎么把 HITL 集成到 LangGraph Studio / 前端?

## 1. 最简 `interrupt()` — 在节点中暂停

```python
from langgraph.types import interrupt, Command

def human_review_node(state: MessagesState) -> dict:
    # interrupt 暂停图执行, 等外部 Command(resume=...) 恢复
    decision = interrupt({
        "question": "请审批 Agent 当前操作:",
        "messages_preview": [m.content[:60] for m in state["messages"][-3:]],
    })
    return {"messages": [HumanMessage(content=f"[人类审批]: {decision}")]}

# 拼图(略) — 加一个 human_review 节点
app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "hitl-1"}}

# 第 1 次 invoke:触发工具 → human_review 暂停
app.invoke({"messages": [HumanMessage("帮订单 #123 退款 100 元")]}, config=config)

state = app.get_state(config)
if state.next:
    print(f"暂停在: {state.next}")
    if state.tasks and state.tasks[0].interrupts:
        print(f"待审批: {state.tasks[0].interrupts[0].value}")

# 第 2 次 invoke(主管批准 → 恢复)
result = app.invoke(Command(resume="approved"), config=config)
```

`interrupt(value)` 接收任意可序列化对象(给前端展示),"resume=" 接用户输入。

## 2. 工具调用前 interrupt — 按参数阈值拦截

退款 > 100 元才审批:

```python
def call_tools_with_check(state: MessagesState) -> dict:
    last = state["messages"][-1]
    results = []
    for tc in last.tool_calls:
        if tc["name"] == "refund_order":
            amount = tc["args"].get("amount", 0)
            if amount > 100:
                decision = interrupt({
                    "tool_call": tc,
                    "reason": f"退款金额 {amount} > 100, 需要审批",
                })
                if decision != "approve":
                    results.append(ToolMessage(
                        content=f"退款被拒绝: {decision}",
                        tool_call_id=tc["id"],
                    ))
                    continue
        # 通过则执行工具
        results.append(ToolMessage(
            content=str(refund_order.invoke(tc["args"])),
            tool_call_id=tc["id"],
        ))
    return {"messages": results}
```

实战模式:

| 拦截规则 | 做法 |
| --- | --- |
| 金额阈值 | `amount > 100` |
| 黑名单用户 | `user_id in blacklist` |
| 高风险操作 | tool name 在高危列表 |
| 跨租户访问 | `tenant_id != ctx.tenant_id` |

跟 Java 拦截器一个思路,在工具真正执行前加判断。

## 3. Edit 决策 — 主管改参数后批准

主管可以修改工具参数再批准(200 改成 80):

```python
def call_tools_with_edit(state: MessagesState) -> dict:
    last = state["messages"][-1]
    results = []
    for tc in last.tool_calls:
        if tc["name"] == "refund_order":
            amount = tc["args"].get("amount", 0)
            if amount > 100:
                decision = interrupt({
                    "tool_call": tc,
                    "options": ["approve", "edit", "reject"],
                })
                if isinstance(decision, dict):
                    if decision.get("type") == "reject":
                        results.append(ToolMessage(
                            content="退款被拒绝",
                            tool_call_id=tc["id"],
                        ))
                        continue
                    elif decision.get("type") == "edit":
                        # 主管改了参数, 用新参数调
                        new_args = decision.get("args", tc["args"])
                        results.append(ToolMessage(
                            content=str(refund_order.invoke(new_args)),
                            tool_call_id=tc["id"],
                        ))
                        continue
        # 默认 approve
        results.append(ToolMessage(
            content=str(refund_order.invoke(tc["args"])),
            tool_call_id=tc["id"],
        ))
    return {"messages": results}

# 主管 edit
edited = {"type": "edit", "args": {"order_id": "#789", "amount": 80.0}}
result = app.invoke(Command(resume=edited), config=config)
```

三种决策:

| type | 含义 |
| --- | --- |
| `approve` | 通过,执行原参数 |
| `edit` | 修改参数后通过(`args` 字段给新值) |
| `reject` | 拒绝,告诉用户失败 |

> LangChain 1.x 内置的 `HumanInTheLoopMiddleware`(L1-04 讲过)也支持这三种决策,只是配置方式不同。

## 4. Reject + 反馈 — 让 LLM 重试

拒绝退款时,把原因当 ToolMessage 喂给 LLM,让它重答:

```python
def call_tools_with_feedback(state: MessagesState) -> dict:
    last = state["messages"][-1]
    results = []
    for tc in last.tool_calls:
        if tc["name"] == "refund_order":
            decision = interrupt({"tool_call": tc, "reason": "需要审批"})
            if decision == "approve":
                results.append(ToolMessage(
                    content=str(refund_order.invoke(tc["args"])),
                    tool_call_id=tc["id"],
                ))
            else:
                # 把拒绝原因当 ToolMessage 返回, LLM 看到后会重新回答
                results.append(ToolMessage(
                    content=f"操作被拒绝 (原因: {decision})。请告诉用户无法执行此操作。",
                    tool_call_id=tc["id"],
                ))
    return {"messages": results}

result = app.invoke(Command(resume="reject: 金额异常, 怀疑欺诈"), config=config)
print(f"最终 LLM 回复: {result['messages'][-1].content[:150]}")
# → "抱歉,您的退款申请因金额异常被拒绝,建议联系客服..."
```

**关键**:把拒绝原因当 ToolMessage 回传,LLM 会读 tool result → 重新生成"告诉用户被拒"的回答。

## 5. 多轮审批 — 主管 → 用户 → 执行

多轮串行审批(主管批准 → 用户确认 → 才执行):

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]
    approved: bool
    confirmed: bool

def step1_propose(state): return {"messages": [HumanMessage("[系统] 准备退款 200 元")]}

def step2_manager_review(state):
    decision = interrupt({"stage": "manager", "msg": "主管审批?"})
    return {"approved": decision == "approve"}

def step3_user_confirm(state):
    decision = interrupt({"stage": "user", "msg": "用户确认?"})
    return {"confirmed": decision == "confirm"}

def step4_execute(state): return {"messages": [HumanMessage("已退款 200 元")]}

def route_after_step2(s): return "step3" if s.get("approved") else END
def route_after_step3(s): return "step4" if s.get("confirmed") else END

graph = StateGraph(State)
graph.add_node("step1", step1_propose)
graph.add_node("step2", step2_manager_review)
graph.add_node("step3", step3_user_confirm)
graph.add_node("step4", step4_execute)
graph.add_edge(START, "step1")
graph.add_edge("step1", "step2")
graph.add_conditional_edges("step2", route_after_step2, ["step3", END])
graph.add_conditional_edges("step3", route_after_step3, ["step4", END])
graph.add_edge("step4", END)

app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "multi-hitl"}}

# 第 1 次 invoke(停在 step2)
app.invoke({"messages": [], "approved": False, "confirmed": False}, config=config)
state = app.get_state(config)
print(f"暂停点: {state.next}")  # ('step3',)

# 主管批准 → 现在停在 step3
app.invoke(Command(resume="approve"), config=config)

# 用户确认 → END
r = app.invoke(Command(resume="confirm"), config=config)
```

实战多轮审批:

| 场景 | 步骤 |
| --- | --- |
| 内部审批流 | 提交 → 主管 → 总监 → CEO |
| 跨系统 | 我方 → 对方 API → 我方确认 |
| 合规流程 | 自动审核 → 人工复核 → 风控 |

## 6. Pydantic schema 的 interrupt — 前端自动渲染

```python
from pydantic import BaseModel, Field
from typing import Literal

class ApprovalRequest(BaseModel):
    """前端表单: 主管审批问卷。"""
    action: Literal["approve", "reject"] = Field(description="审批决定")
    reason: str = Field(default="", description="备注, 拒绝时必填")
    new_amount: float | None = Field(default=None, description="如改金额, 填这里")

def call_tools(state: MessagesState) -> dict:
    last = state["messages"][-1]
    results = []
    for tc in last.tool_calls:
        if tc["name"] == "refund_order":
            # interrupt 用 schema 描述, 前端自动渲染表单
            decision: ApprovalRequest = interrupt(ApprovalRequest(
                action="approve", reason="", new_amount=None
            ).model_dump())

            if decision["action"] == "reject":
                results.append(ToolMessage(
                    content=f"被拒: {decision['reason']}",
                    tool_call_id=tc["id"],
                ))
            else:
                args = dict(tc["args"])
                if decision.get("new_amount"):
                    args["amount"] = decision["new_amount"]  # 主管改的金额
                results.append(ToolMessage(
                    content=str(refund_order.invoke(args)),
                    tool_call_id=tc["id"],
                ))
    return {"messages": results}

# 主管 approve 并改成 100
decision = {"action": "approve", "reason": "金额过大,砍到 100", "new_amount": 100}
result = app.invoke(Command(resume=decision), config=config)
```

实战前端集成:

```javascript
// 后端返回 interrupt schema
POST /chat/thread-001
→ {"interrupt": {"action": "approve", "reason": "", "new_amount": null}}

// 前端用 schema 生成表单
const form = generateFormFromSchema(interrupt.schema)
// 用户填完 → POST /resume/thread-001
fetch(`/resume/${thread_id}`, {body: {action, reason, new_amount}})
```

实战架构:

```
FastAPI 后端返回 interrupt value (含 schema)
   ↓
前端用 schema 自动生成 React 表单
   ↓
用户填完 → POST 到 /resume 端点
   ↓
后端 Command(resume=用户填的内容)
   ↓
Agent 继续走
```

## 实战踩坑

| 坑 | 原因 | 解法 |
| --- | --- | --- |
| `result["__interrupt__"]` 不存在 | LangChain 1.x 改了 | 用 `state.tasks[0].interrupts` |
| 小模型不调工具 → interrupt 不触发 | 模型决定不调 | prompt 强约束 + 检查 state.tasks |
| `Command(resume=None)` 挂死 | 没真 interrupt | 先 `check state.tasks` 再 resume |
| interrupt value 不可序列化 | 含 LLM 对象 / 文件句柄 | 只传 dict / str / 基础类型 |
| 主管 edit 后参数不生效 | 没合并 args | `args = {**tc["args"], **decision["args"]}` |
| 多轮审批状态错乱 | 没用 checkpointer | 必须配 `checkpointer=InMemorySaver()` |

## 生产架构

```python
# 1. 工具内 interrupt + checkpointer
def refund_order_with_approval(order_id, amount):
    decision = interrupt({"op": "refund", "amount": amount, ...})
    if decision != "approve":
        return f"已取消: {decision}"
    return do_refund(order_id, amount)

# 2. graph 编译
app = graph.compile(
    checkpointer=PostgresSaver(...),  # 跨进程
    interrupt_before=["refund_order"],  # 工具前审批(可选)
)

# 3. FastAPI 端点
@app.post("/chat/{thread_id}")
async def chat(thread_id: str, message: str):
    config = {"configurable": {"thread_id": thread_id}}
    result = await app.ainvoke(
        {"messages": [HumanMessage(message)]},
        config=config,
    )
    if result.get("__interrupt__"):
        return {"needs_approval": True, "schema": ...}
    return {"messages": [...]}

@app.post("/resume/{thread_id}")
async def resume(thread_id: str, decision: dict):
    config = {"configurable": {"thread_id": thread_id}}
    result = await app.ainvoke(Command(resume=decision), config=config)
    return {"messages": [...]}
```

## 小结

- `interrupt()` 在节点内暂停,`Command(resume=...)` 恢复
- 工具内按规则拦截(金额 / 风险用户 / 高危操作)
- 三种决策:`approve` / `edit` / `reject`
- 拒绝时把原因当 ToolMessage 喂回 LLM 让它重答
- 多轮审批:state 加 `approved` / `confirmed` 字段做条件路由
- Pydantic schema 让前端自动生成表单

HITL 让 Agent "可控"。下一步是让 Agent 输出 **实时可见**——L2-09 Streaming 见。

## 延伸阅读

- [LangGraph HITL 官方文档](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)
- 上一篇:[L2-07 Persistence 持久化](./L2-07_persistence.md)
- 下一篇:[L2-09 Streaming 流式输出](./L2-09_streaming.md)
- 源码:`02-langgraph-orchestration/08_interrupt_hitl.py`
