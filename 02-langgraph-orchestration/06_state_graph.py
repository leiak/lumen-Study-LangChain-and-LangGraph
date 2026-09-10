"""06_state_graph.py — StateGraph: 把 Agent 拆成图.

学完这个模块你能回答:
1.  StateGraph 最少要几步?(定义 State → 节点 → 边 → compile → invoke)
2.  MessagesState 内置了什么?为啥用它最省事?
3.  多节点 pipeline 怎么搭?(analyze → execute → summarize)
4.  条件边 add_conditional_edges 怎么用?(根据 state 选下一个节点)
5.  循环边怎么让 Agent 跑 tool calling 循环?
6.  怎么把多个节点并行起来?(START → [A, B, C] → join)
7.  Send 怎么动态扇出 (e.g. 一个问题拆 N 个并行 worker)?
8.  reducer (add_messages / operator.add) 怎么改 state 合并策略?
9.  怎么把图可视化?(get_graph().draw_mermaid)
10. subgraph 怎么把另一个图作为节点嵌入?

跑法:
    python 06_state_graph.py
"""
from __future__ import annotations

import os
import sys
from operator import add as add_messages_int
from typing import Annotated, Literal, TypedDict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send

from _common import banner, get_llm

# ============================================================
# 0. State 定义 (模块级, Pydantic/TypedDict 在 globals 必须可见)
# ============================================================


class RouterState(TypedDict):
    """demo 4/6 用的状态."""

    query: str
    category: Literal["weather", "order", "general"]
    answer: str


class LoopState(TypedDict):
    """demo 5 用的状态 (Agent tool-calling 循环)."""

    messages: Annotated[list, add_messages]


class ParallelState(TypedDict):
    """demo 6 用的并行状态."""

    topic: str
    # 用 list[str] 收集多个并行节点的输出
    research_results: Annotated[list[str], add_messages_int]


class FanOutState(MessagesState):
    """demo 7 用的 fan-out 状态."""

    topic: str
    # 每个 worker 的结果 (动态数量)
    sections: Annotated[list[str], add_messages_int]


# ============================================================
# 1. 最简 StateGraph — 一个 LLM 节点
# ============================================================
banner("1. 最简 StateGraph — 一个 LLM 节点")


def demo_minimal_graph() -> None:
    llm = get_llm()

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    # 节点函数: 接收 state, 返回 state 的"更新" (只写改了的部分)
    def call_llm(state: State) -> dict:
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    # StateGraph(State): 用 TypedDict 定义 state shape
    graph = StateGraph(State)
    graph.add_node("llm", call_llm)
    graph.add_edge(START, "llm")  # START → llm
    graph.add_edge("llm", END)    # llm → END
    app = graph.compile()

    result = app.invoke({"messages": [HumanMessage("用一句话介绍 LangGraph")]})
    print("回复:", result["messages"][-1].content)

    # 💡 StateGraph 的"五步走":
    #   1) 定义 State (TypedDict / MessagesState / Pydantic)
    #   2) 写节点函数 (state → partial state)
    #   3) add_node + add_edge / add_conditional_edges
    #   4) .compile() → Runnable
    #   5) .invoke() / .stream()
    # 跟 Spring Bean 装配 / Gin route 注册一样 — 声明式 + 图化


# ============================================================
# 2. MessagesState — LangGraph 内置的对话状态
# ============================================================
banner("2. MessagesState — 内置便捷")


def demo_messages_state() -> None:
    # MessagesState = {messages: Annotated[list, add_messages]}
    # 90% 的 chat 场景直接用这个, 不用自己写 State
    llm = get_llm()

    def call_llm(state: MessagesState) -> dict:
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("llm", call_llm)
    graph.add_edge(START, "llm")
    graph.add_edge("llm", END)
    app = graph.compile()

    for q in ["我叫王明", "我叫什么?"]:
        result = app.invoke({"messages": [HumanMessage(q)]})
        print(f"Q: {q}")
        print(f"A: {result['messages'][-1].content[:120]}")
        print()
        # 注意: 多轮要保留 history, 见 07_persistence 用 checkpointer


# ============================================================
# 3. 多节点 pipeline — analyze → execute → summarize
# ============================================================
banner("3. 多节点 pipeline")


def demo_multi_node() -> None:
    """3 节点流水线: 分析 → 执行 → 总结."""
    llm = get_llm()

    class State(TypedDict):
        user_query: str
        analysis: str
        execution_result: str
        final_answer: str

    def analyze(state: State) -> dict:
        # 节点 1: 分析用户问题
        response = llm.invoke([
            SystemMessage(content="你是分析员, 把用户问题拆成 3 个子任务。"),
            HumanMessage(content=state["user_query"]),
        ])
        return {"analysis": response.content}

    def execute(state: State) -> dict:
        # 节点 2: 执行 (mock)
        return {"execution_result": f"已执行: {state['analysis'][:60]}..."}

    def summarize(state: State) -> dict:
        # 节点 3: 总结
        response = llm.invoke([
            SystemMessage(content="把执行结果总结给用户, 不超过 100 字。"),
            HumanMessage(content=state["execution_result"]),
        ])
        return {"final_answer": response.content}

    graph = StateGraph(State)
    graph.add_node("analyze", analyze)
    graph.add_node("execute", execute)
    graph.add_node("summarize", summarize)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "execute")
    graph.add_edge("execute", "summarize")
    graph.add_edge("summarize", END)

    app = graph.compile()
    result = app.invoke({"user_query": "怎么把产品上线到 100 个国家?"})

    print("分析:    ", result["analysis"][:80])
    print("执行:    ", result["execution_result"][:80])
    print("最终回答: ", result["final_answer"][:120])


# ============================================================
# 4. 条件边 — 根据 state 选下一个节点
# ============================================================
banner("4. 条件边 (routing)")


def demo_conditional_edge() -> None:
    """根据问题类型路由到不同专家."""
    llm = get_llm()

    def classify(state: RouterState) -> dict:
        q = state["query"]
        if "天气" in q:
            return {"category": "weather"}
        if "订单" in q:
            return {"category": "order"}
        return {"category": "general"}

    def weather_expert(state: RouterState) -> dict:
        return {"answer": f"[天气专家] {state['query']} → 晴 25°C"}

    def order_expert(state: RouterState) -> dict:
        return {"answer": f"[订单专家] {state['query']} → 已发货"}

    def general_expert(state: RouterState) -> dict:
        response = llm.invoke(state["query"])
        return {"answer": f"[通用] {response.content[:80]}"}

    # 路由函数: 返回值就是下一个节点的 key
    def route(state: RouterState) -> str:
        return state["category"]

    graph = StateGraph(RouterState)
    graph.add_node("classify", classify)
    graph.add_node("weather", weather_expert)
    graph.add_node("order", order_expert)
    graph.add_node("general", general_expert)

    graph.add_edge(START, "classify")
    # path_map 必须给, langgraph 才能把返回值映射到节点名
    graph.add_conditional_edges(
        "classify", route,
        {"weather": "weather", "order": "order", "general": "general"},
    )
    graph.add_edge("weather", END)
    graph.add_edge("order", END)
    graph.add_edge("general", END)

    app = graph.compile()

    for q in ["北京天气怎么样?", "我的订单 #123 在哪?", "你好吗?"]:
        result = app.invoke({"query": q})
        print(f"Q: {q}")
        print(f"A: {result['answer']}")
        print()


# ============================================================
# 5. 循环边 — Agent 多轮 tool calling
# ============================================================
banner("5. 循环边 (Agent tool calling)")


def demo_loop_edge() -> None:
    """手动实现 create_agent 的核心循环: agent ↔ tools."""
    @tool
    def get_weather(city: str) -> str:
        """查天气."""
        return f"{city} 晴 25°C"

    @tool
    def get_time(city: str) -> str:
        """查时间."""
        return f"{city} 当前 14:30"

    tools = [get_weather, get_time]
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = get_llm().bind_tools(tools)

    def call_model(state: LoopState) -> dict:
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    def call_tools(state: LoopState) -> dict:
        last_msg = state["messages"][-1]
        results = []
        for tc in last_msg.tool_calls:
            tool_fn = tools_by_name[tc["name"]]
            output = tool_fn.invoke(tc["args"])
            results.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))
        return {"messages": results}

    # 条件边: 模型说要调工具 → 去 tools, 否则 → END
    def should_continue(state: LoopState) -> Literal["call_tools", END]:
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "call_tools"
        return END

    graph = StateGraph(LoopState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", call_tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"call_tools": "tools", END: END})
    graph.add_edge("tools", "agent")  # 关键: 循环回 agent

    app = graph.compile()

    result = app.invoke({"messages": [HumanMessage("北京天气? 上海时间?")]})
    print(f"messages 数: {len(result['messages'])}")
    for m in result["messages"][-6:]:  # 只打最后几条
        print(f"  [{type(m).__name__}] {(m.content or '')[:80]}")

    # 💡 create_agent 就是这套图的封装 — 自己拼图能看清每一步在干嘛


# ============================================================
# 6. 并行分支 — START → [A, B, C] → join
# ============================================================
banner("6. 并行分支 (fan-out / fan-in)")


def demo_parallel() -> None:
    """一个研究任务拆给 3 个并行 worker (技术 / 市场 / 用户), 合并结果."""
    llm = get_llm()

    def tech_research(state: ParallelState) -> dict:
        r = llm.invoke(f"从技术角度分析: {state['topic']}")
        print(f"技术角度返回的内容 :{r}")
        return {"research_results": [f"[技术] {r.content}"]}

    def market_research(state: ParallelState) -> dict:
        r = llm.invoke(f"从市场角度分析: {state['topic']}")
        return {"research_results": [f"[市场] {r.content}"]}

    def user_research(state: ParallelState) -> dict:
        r = llm.invoke(f"从用户角度分析: {state['topic']}")
        return {"research_results": [f"[用户] {r.content}"]}

    def synthesize(state: ParallelState) -> dict:
        combined = "\n".join(state["research_results"])
        r = llm.invoke(f"基于以下研究, 给出综合结论:\n{combined}")
        # 这里只是 demo, 真实场景可以把 synthesis 结果写到一个 final 字段
        return {"research_results": [f"[综合] {r.content}"]}

    graph = StateGraph(ParallelState)
    graph.add_node("tech", tech_research)
    graph.add_node("market", market_research)
    graph.add_node("user", user_research)
    graph.add_node("synthesize", synthesize)

    # 关键: 3 条边从 START 出发, LangGraph 会等 3 个都完成再往下走
    graph.add_edge(START, "tech")
    graph.add_edge(START, "market")
    graph.add_edge(START, "user")

    # 3 个 worker 都结束后才能进 synthesize
    graph.add_edge("tech", "synthesize")
    graph.add_edge("market", "synthesize")
    graph.add_edge("user", "synthesize")
    graph.add_edge("synthesize", END)

    app = graph.compile()
    result = app.invoke({"topic": "AI Agent 商业化"})

    print(f"\n结果数: {len(result['research_results'])} 条")
    for line in result["research_results"]:
        print(f"  {line[:100]}")

    # 💡 StateGraph 并行原理:
    #   - 多个 add_edge(START, node) 触发并行 (无依赖的节点一起跑)
    #   - LangGraph 用 add_messages_int reducer 自动合并 list 字段
    #   - 适用: 多源 RAG (并行查 3 个库) / 多视角分析 (技术+市场+用户)
    #   - 注意事项: 各 worker 之间**不能**有数据依赖 (否则用条件边串行)


# ============================================================
# 7. Send — 动态扇出 (运行时决定并行数)
# ============================================================
banner("7. Send — 动态 fan-out")


def demo_send_dynamic_fanout() -> None:
    """根据 state 动态决定派几个 worker (e.g. 拆 3 个章节 → 3 个 writer)."""
    llm = get_llm()

    def split_into_sections(state: FanOutState) -> dict:
        # 假装按章节拆, 实际可调 LLM 拆
        return {"sections": ["背景", "方法", "结论"]}

    def writer(state: FanOutState) -> dict:
        # 每个 worker 拿到一个 section, 写一段
        section = state.get("section_name", "?")
        r = llm.invoke(f"写一段关于 '{state['topic']}' 的 '{section}' 部分, 30 字以内。")
        return {"sections": [f"[{section}] {r.content}"]}

    def join(state: FanOutState) -> dict:
        # 把所有 worker 输出合并
        return {}  # state['sections'] 已经通过 reducer 累加

    graph = StateGraph(FanOutState)

    graph.add_node("split", split_into_sections)
    graph.add_node("join", join)

    # writer 节点注册, 但实际不直接 add_edge, 而是用 Send 动态触发
    graph.add_node("writer", writer)

    graph.add_edge(START, "split")

    # 条件边: 从 split 动态派 Send 到 writer
    # Send 接受 (节点名, 节点自己的 state)
    def route_to_writers(state: FanOutState) -> list[Send]:
        # split 节点刚把 sections 写进 state, 但当前 state 还是初始值
        # 实际写法: 从原始 state 决定要派几个 worker
        return [
            Send("writer", {**state, "section_name": section})
            for section in ["背景", "方法", "结论"]
        ]

    graph.add_conditional_edges("split", route_to_writers, ["writer"])
    # 所有 writer 完成后进 join
    graph.add_edge("writer", "join")
    graph.add_edge("join", END)

    app = graph.compile()
    result = app.invoke({"topic": "LangGraph 入门", "messages": []})

    print(f"动态扇出结果 ({len(result['sections'])} 段):")
    for s in result["sections"]:
        print(f"  {s[:100]}")

    # 💡 Send vs 静态并行:
    #   静态 add_edge(START, X): 编译时定几个 worker
    #   Send: 运行时根据 state 决定派几个 worker (Map-Reduce 模式)
    #   实战: 多文档并行总结 / Map-Reduce RAG / 并行实验


# ============================================================
# 8. Reducer — 自定义 state 合并策略
# ============================================================
banner("8. Reducer — state 合并策略")


def demo_reducers() -> None:
    """演示 3 种最常用的 reducer."""

    # (1) add_messages: 专用于 messages 字段, 支持 message id 去重 + overwrite
    class StateA(TypedDict):
        messages: Annotated[list, add_messages]  # 默认累加

    # (2) operator.add: 数值 / 字符串累加
    class StateB(TypedDict):
        turn_count: Annotated[int, add_messages_int]  # 每次 +1

    # (3) 不加 reducer: 整个字段被覆盖
    class StateC(TypedDict):
        # 不写 Annotated, 节点返回时这个字段被整体覆盖
        last_result: str

    print(">>> reducer 三种模式:")
    print("  1. Annotated[list, add_messages]  → messages 累加 (支持 message id)")
    print("  2. Annotated[int, add_messages_int] → 数值累加")
    print("  3. 不写 Annotated                  → 字段整体覆盖")
    print()

    # 演示 StateB 的累加效果
    llm = get_llm()

    def count(state: StateB) -> dict:
        return {"turn_count": 1}  # 每次 invoke, turn_count = 上次 + 1

    g = StateGraph(StateB)
    g.add_node("count", count)
    g.add_edge(START, "count")
    g.add_edge("count", END)
    app = g.compile()

    # 第一次: 默认 0 + 1 = 1
    r1 = app.invoke({"turn_count": 0})
    print(f"第 1 次 invoke, turn_count = {r1['turn_count']}")
    # 第二次: 必须显式传当前 state, 不然框架不知道上次的值
    r2 = app.invoke({"turn_count": r1["turn_count"]})
    print(f"第 2 次 invoke, turn_count = {r2['turn_count']}")

    # 💡 没有 checkpointer 时, 每次 invoke 是独立调用, state 不会自动保留
    # 实战: 配合 checkpointer (07_persistence) 才有真正的"长会话"


# ============================================================
# 9. 图可视化 — 导出 Mermaid
# ============================================================
banner("9. 图可视化 (draw_mermaid)")


def demo_visualize() -> None:
    """导出 Mermaid 图, 看图理解状态流."""
    graph = StateGraph(RouterState)

    def classify(s): return {"category": "weather" if "天气" in s["query"] else "general"}
    def weather(s): return {"answer": "晴 25°C"}
    def general(s): return {"answer": "..."}

    graph.add_node("classify", classify)
    graph.add_node("weather", weather)
    graph.add_node("general", general)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", lambda s: s["category"],
                                {"weather": "weather", "general": "general"})
    graph.add_edge("weather", END)
    graph.add_edge("general", END)

    app = graph.compile()

    # 拿到 mermaid 格式的图定义 (复制到 https://mermaid.live 看图)
    mermaid = app.get_graph().draw_mermaid()
    print("Mermaid 图 (粘贴到 https://mermaid.live 看):")
    print(mermaid[:500] + ("..." if len(mermaid) > 500 else ""))


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

    # 1-5 基础图
    # demo_minimal_graph()
    # demo_messages_state()
    # demo_multi_node()
    # demo_conditional_edge()
    # demo_loop_edge()
    #
    # # 6-7 并行
    demo_parallel()
    # demo_send_dynamic_fanout()
    #
    # # 8-9 进阶
    # demo_reducers()
    # demo_visualize()

    print("\n[OK] 06_state_graph.py 全部 demo 跑完。")