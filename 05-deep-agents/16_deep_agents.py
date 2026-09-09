"""16_deep_agents.py — Deep Agents 高级 Harness.

Deep Agents = LangGraph 之上的封装, 内置:
- 自动 TODO 管理 (planning)
- 虚拟文件系统 (write/read/ls/edit)
- Subagent 委派 (task 工具)
- Context 自动摘要

学完这个模块你能回答:
 1.  Deep Agents vs create_agent 区别在哪 (为什么需要 deep agents)?
 2.  Deep Agent 内置的 TODO 工具怎么用?
 3.  虚拟文件系统怎么读写 (state.files)?
 4.  怎么定义 subagents 委派子任务?
 5.  Deep Agent 怎么接 HITL?
 6.  Deep Agent 怎么接 middleware?
 7.  Deep Agent 怎么流式输出?
 8.  怎么用 Deep Agent 做"长任务" (数小时研究)?
 9.  Deep Agent 失败 / 重试怎么处理?
10.  生产里 Deep Agent 怎么落地?

跑法:
    pip install deepagents
    python 16_deep_agents.py

如果 deepagents 没装, 会 fallback 演示 LangGraph StateGraph 的等价实现。
"""
from __future__ import annotations

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from _common import banner, get_llm

# ============================================================
# 0. 检查 deepagents 是否可用
# ============================================================
banner("0. 检查 deepagents")
try:
    from deepagents import create_deep_agent  # noqa: F401

    HAS_DEEPAGENTS = True
    print("[OK] deepagents 已安装, 用 create_deep_agent 演示")
except ImportError:
    HAS_DEEPAGENTS = False
    print("[WARN] deepagents 未安装, 用 LangGraph StateGraph 演示等价功能")
print()


# ============================================================
# 1. 最简 Deep Agent
# ============================================================
banner("1. 最简 Deep Agent")


def demo_minimal() -> None:
    """Deep Agent 至少要 model + system_prompt."""
    if HAS_DEEPAGENTS:
        from deepagents import create_deep_agent

        agent = create_deep_agent(
            model=get_llm(),
            system_prompt="你是一个深度研究助手, 回答要全面、有条理。",
        )
        result = agent.invoke(
            {"messages": [HumanMessage("LangChain 1.0 的 3 大核心改进是什么?")]}
        )
        print(">>> 最终回复:", result["messages"][-1].content[:200])
    else:
        from langchain.agents import create_agent

        agent = create_agent(
            model=get_llm(), tools=[],
            system_prompt=(
                "你是深度研究助手。回答时:\n"
                "1. 先列 TODO\n"
                "2. 逐条说明\n"
                "3. 最后总结"
            ),
        )
        result = agent.invoke(
            {"messages": [HumanMessage("LangChain 1.0 的 3 大核心改进?")]}
        )
        print(">>> (fallback create_agent) 回复:", result["messages"][-1].content[:200])

    # 💡 Deep Agent 关键能力 (create_agent 没有的):
    #   - 自动 TODO 规划: write_todos / read_todos
    #   - 虚拟文件系统: write_file / read_file / ls
    #   - Subagent 委派: task(description, subagent_type)
    #   - Context 摘要: token 超限自动压缩历史


# ============================================================
# 2. Deep Agent + 自定义 tools
# ============================================================
banner("2. Deep Agent + 自定义 tools")


def demo_with_tools() -> None:
    @tool
    def search_web(query: str) -> str:
        """(mock) 网络搜索."""
        return f"搜索结果: 关于 {query} 的 3 篇文档..."

    @tool
    def write_file(filename: str, content: str) -> str:
        """(mock) 写入文件."""
        return f"已写入 {filename}, {len(content)} 字"

    if HAS_DEEPAGENTS:
        from deepagents import create_deep_agent

        agent = create_deep_agent(
            model=get_llm(),
            tools=[search_web, write_file],
            system_prompt="研究一个主题, 搜资料, 写成报告文件。",
        )
        result = agent.invoke(
            {"messages": [HumanMessage("研究 AI Agent 的发展史, 写份 500 字报告到 report.md")]}
        )
        print(f">>> messages 数: {len(result['messages'])}")
        if "files" in result:
            print(f">>> 虚拟文件: {list(result['files'].keys())}")
    else:
        from langchain.agents import create_agent

        agent = create_agent(
            model=get_llm(), tools=[search_web, write_file],
            system_prompt="研究 AI Agent 发展史, 用 write_file 写报告。",
        )
        result = agent.invoke({"messages": [HumanMessage("研究 AI Agent 发展史")]})
        print(">>> (fallback) 回复:", result["messages"][-1].content[:150])


# ============================================================
# 3. Subagents — 委派子任务
# ============================================================
banner("3. Subagents — 委派子任务")


def demo_subagents() -> None:
    """Deep Agents 可以定义 subagents, 用 task 工具委派子任务."""
    if not HAS_DEEPAGENTS:
        print("[WARN] subagents 是 deepagents 独有特性, 跳过")
        return

    from deepagents import create_deep_agent

    research_agent = {
        "name": "research-agent",
        "description": "负责搜索资料, 适合需要事实查询的任务",
        "system_prompt": "你是研究员, 简明扼要地给关键事实, 不超过 100 字。",
    }
    writer_agent = {
        "name": "writer-agent",
        "description": "负责把素材写成通顺文字",
        "system_prompt": "你是写作者, 把给的素材整理成 50 字短文。",
    }

    main_agent = create_deep_agent(
        model=get_llm(),
        subagents=[research_agent, writer_agent],
        system_prompt=(
            "你是主编。需要研究时调 research-agent, 需要写作时调 writer-agent。"
        ),
    )

    result = main_agent.invoke(
        {"messages": [HumanMessage("写一段关于'量子计算未来 5 年'的短文")]}
    )
    print(">>> 主编最终回复:", result["messages"][-1].content[:200])

    # 💡 Subagent 实战:
    #   - 上下文隔离: subagent 看不到主 agent 的全 history
    #   - 角色分工: 不同 subagent 不同的 system_prompt / tools
    #   - 并行: deepagents 自动并行多个 task 调用
    #   - 节省 token: 简单子任务不污染主上下文


# ============================================================
# 4. 虚拟文件系统
# ============================================================
banner("4. 虚拟文件系统 (FS)")


def demo_filesystem() -> None:
    """Deep Agents 的 state 里自动有 'files' 字段, 等于虚拟 FS."""
    if not HAS_DEEPAGENTS:
        print("[WARN] 虚拟 FS 是 deepagents 独有特性, 跳过")
        return

    from deepagents import create_deep_agent

    agent = create_deep_agent(
        model=get_llm(),
        system_prompt=(
            "你要写一份研究计划:\n"
            "1. 先调 write_todo 工具列 TODO\n"
            "2. 然后逐项执行\n"
            "3. 最后总结到 final.md 文件"
        ),
    )

    result = agent.invoke(
        {"messages": [HumanMessage("研究 LangGraph 1.0 的 5 个核心特性")]}
    )

    files = result.get("files", {})
    print(f">>> 虚拟文件数: {len(files)}")
    for name, content in files.items():
        size = len(content) if isinstance(content, str) else type(content).__name__
        print(f"  - {name}: {size}")

    # 💡 虚拟 FS vs 真实 FS:
    #   - 虚拟 FS: state 里存, 跨 checkpoint 保留, 不写磁盘
    #   - 真实 FS: 落盘, 跨进程保留
    #   - 实战: 大文件 / 二进制用真实 FS, 配置 / 中间结果用虚拟 FS


# ============================================================
# 5. TODO 管理 — 规划能力
# ============================================================
banner("5. TODO 管理 (write_todos)")


def demo_todo_management() -> None:
    """Deep Agents 内置 write_todos / read_todos 工具."""
    if not HAS_DEEPAGENTS:
        print(
            "[WARN] TODO 工具是 deepagents 独有, fallback 演示:\n"
            "  手动让 LLM 在 prompt 里维护 TODO 列表"
        )
        # Fallback 演示: 用 prompt 让 LLM 维护 TODO
        from langchain.agents import create_agent

        agent = create_agent(
            model=get_llm(), tools=[],
            system_prompt=(
                "你是规划助手。每收到任务, 先在回复里输出 TODO 列表 (1. 2. 3.)\n"
                "然后逐条完成, 每完成一条在前面加 [x]。"
            ),
        )
        r = agent.invoke({"messages": [HumanMessage("写一份 AI Agent 入门指南的 TODO")]})
        print(">>> (fallback) TODO:", r["messages"][-1].content[:300])
        return

    from deepagents import create_deep_agent

    agent = create_deep_agent(
        model=get_llm(),
        system_prompt="先 write_todos 列计划, 再逐项执行",
    )
    result = agent.invoke(
        {"messages": [HumanMessage("3 步搞定市场调研报告")]}
    )
    todos = result.get("todos", [])
    print(f">>> TODO 条数: {len(todos)}")
    for t in todos[:5]:
        print(f"  - [{t.get('status', '?')}] {t.get('content', '')[:60]}")

    # 💡 TODO 实战:
    #   - 长任务: 让 agent 自己拆解步骤, 不会半路跑偏
    #   - 用户可见: 把 todos 显示在 UI 上 ("AI 正在做 3/8")
    #   - 失败恢复: 某个 todo 失败, 可以重跑该 todo


# ============================================================
# 6. Deep Agent + HITL — 关键操作人工审批
# ============================================================
banner("6. Deep Agent + HITL")


def demo_deep_hitl() -> None:
    """Deep Agent 里也支持 interrupt (HITL)."""
    if not HAS_DEEPAGENTS:
        print("[WARN] HITL 演示需要 deepagents 或 create_agent + interrupt")
        return

    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import interrupt

    @tool
    def dangerous_op(payload: str) -> str:
        """(mock) 高风险操作, 需要人工审批."""
        # 关键操作前 interrupt
        decision = interrupt({"op": "dangerous", "payload": payload})
        if decision != "approve":
            return f"已取消: {decision}"
        return f"已执行: {payload}"

    # 创建带 checkpointer 的 deep agent
    # (deepagents 暴露的 compile 接口可能不完全, 这里演示思路)
    print(">>> Deep Agent 的 HITL 思路:")
    print("  1. 在自定义工具里调 interrupt(...)")
    print("  2. agent 编译时带 checkpointer=InMemorySaver / PostgresSaver")
    print("  3. invoke 触发 interrupt 后, 用 app.get_state(config) 看暂停点")
    print("  4. 主管审批 → app.invoke(Command(resume='approve'), config)")


# ============================================================
# 7. Deep Agent + Middleware
# ============================================================
banner("7. Deep Agent + Middleware")


def demo_deep_middleware() -> None:
    """Deep Agent 也支持 middleware (PII 脱敏 / 限流 / 日志)."""
    from langchain.agents.middleware import wrap_model_call

    @wrap_model_call
    def logging_middleware(request, handler):
        """日志中间件: 打印每次 LLM 调用的消息数."""
        n = len(request.messages)
        print(f"  [middleware] LLM 调用, {n} 条消息")
        return handler(request)

    if HAS_DEEPAGENTS:
        from deepagents import create_deep_agent

        # deepagents 的 middleware 参数可能版本不同, 演示用法
        print(">>> Deep Agent + middleware:")
        print("  - 传给 create_deep_agent 的 middleware 参数")
        print("  - 支持 wrap_model_call / wrap_tool_call / before_model / after_model")
        print("  - 用途: PII 脱敏 / 限流 / token 计数 / 日志")
    else:
        from langchain.agents import create_agent

        agent = create_agent(
            model=get_llm(), tools=[],
            system_prompt="你是助手",
            middleware=[logging_middleware],
        )
        agent.invoke({"messages": [HumanMessage("hi")]})
        print(">>> (fallback) 看到 middleware 日志了吗?")


# ============================================================
# 8. Deep Agent 流式输出
# ============================================================
banner("8. Deep Agent 流式输出")


def demo_deep_streaming() -> None:
    """Deep Agent 也支持 stream / astream, 看每步状态变化."""
    if not HAS_DEEPAGENTS:
        print("[WARN] 流式需要 deepagents")
        return

    from deepagents import create_deep_agent

    agent = create_deep_agent(
        model=get_llm(),
        system_prompt="你要研究主题, 先 TODO 规划, 然后用工具搜集",
    )

    print(">>> 流式 updates:")
    for chunk in agent.stream(
        {"messages": [HumanMessage("研究 RAG 的 3 个核心组件")]},
        stream_mode="updates",
    ):
        for node, delta in chunk.items():
            if "messages" in delta:
                print(f"  [step] {node}: {len(delta['messages'])} new msg(s)")


# ============================================================
# 9. Deep Agent vs create_agent — 选型
# ============================================================
banner("9. Deep Agent vs create_agent — 选型")


def demo_vs_create_agent() -> None:
    print(
        """
    ┌─────────────────┬──────────────────────┬──────────────────────┐
    │                 │ create_agent         │ create_deep_agent    │
    ├─────────────────┼──────────────────────┼──────────────────────┤
    │ 用法            │ LangChain 1.x 内置   │ deepagents 包        │
    │                 │                      │ (LangGraph 之上封装) │
    ├─────────────────┼──────────────────────┼──────────────────────┤
    │ 内置 TODO       │ ✗ 需自己写 prompt    │ ✓ 自动 write_todos   │
    │ 内置 FS         │ ✗ 需自己写工具       │ ✓ write_file/read    │
    │ Subagent        │ ✗ 需自己实现         │ ✓ task 委派          │
    │ Context 摘要    │ ✗ 需 SummarizationMW │ ✓ 内置 token 压缩    │
    │ 适用            │ 单步 / 多步工具调用  │ 长任务 (小时级)       │
    │                 │ 简单 chatbot         │ 深度研究 / 编程       │
    │ 依赖            │ langchain 1.x        │ + deepagents         │
    │ 上手            │ 简单                 │ 中等 (要学新 API)     │
    └─────────────────┴──────────────────────┴──────────────────────┘

    选型:
      - 客服 / 简单 chatbot    → create_agent
      - 长任务 (研究 / 编程)   → create_deep_agent
      - 已有 LangGraph pipeline → 继续用 LangGraph (不强制 deepagents)
    """
    )


# ============================================================
# 10. 生产架构 — Deep Agent 落地
# ============================================================
banner("10. 生产架构 — Deep Agent 落地")


def demo_production_snippet() -> None:
    snippet = """
    # 生产 Deep Agent 标准接法:

    # 1. 必须 checkpointer (因为 Deep Agent 是长任务, 中途可能挂)
    from langgraph.checkpoint.postgres import PostgresSaver
    DB = "postgresql://..."
    with PostgresSaver.from_conn_string(DB) as cp:
        agent = create_deep_agent(
            model=llm,
            tools=[...],
            subagents=[...],
            checkpointer=cp,  # 关键
        )

    # 2. thread_id 设计
    config = {"configurable": {"thread_id": "research-task-001"}}

    # 3. token / 步数限制 (防 LLM 失控)
    config = {
        "configurable": {"thread_id": "..."},
        "recursion_limit": 50,  # 节点最多执行 50 次
    }

    # 4. 异步化 (长任务不要同步等)
    result = await agent.ainvoke(input, config=config)

    # 5. 流式给前端 (用户能看到进度)
    async for chunk in agent.astream(input, stream_mode="updates"):
        yield f"data: {json.dumps(chunk)}\\n\\n"

    # 6. 中间结果存 DB (任务跨进程可恢复)
    #    PostgresSaver 自动做这件事

    # 7. 监控: LangSmith 自动 trace + 自己的 dashboard
    #    - TODO 完成率
    #    - 平均任务时长
    #    - 失败率
    """
    print(snippet)

    # 💡 关键实践:
    #   - 必须持久化 (PostgresSaver), 不能 InMemory
    #   - 任务可恢复 (interrupt + resume)
    #   - 用户能看到进度 (stream TODO 状态)
    #   - 失败重试 (单 TODO 失败 vs 整个 agent 失败)


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
        ("demo_minimal", demo_minimal),
        ("demo_with_tools", demo_with_tools),
        ("demo_subagents", demo_subagents),
        ("demo_filesystem", demo_filesystem),
        ("demo_todo_management", demo_todo_management),
        ("demo_deep_hitl", demo_deep_hitl),
        ("demo_deep_middleware", demo_deep_middleware),
        ("demo_deep_streaming", demo_deep_streaming),
        ("demo_vs_create_agent", demo_vs_create_agent),
        ("demo_production_snippet", demo_production_snippet),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 16_deep_agents.py 全部 demo 跑完。")
