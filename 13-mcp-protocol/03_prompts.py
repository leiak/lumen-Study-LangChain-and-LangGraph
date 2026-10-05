"""03_prompts.py — Demo 3: MCP Prompts 模板.

学完这个 demo 你能回答:
1.  @mcp.prompt() 怎么定义模板?
2.  客户端怎么 list prompts + 填参数渲染?
4.  跟 LangChain 的 PromptTemplate 区别? (MCP 是协议, 跨语言)
5.  实战: 把 MCP prompt 注入 LangChain system message

跑法:
    python 03_prompts.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from langchain_core.messages import HumanMessage, SystemMessage

from _common import banner, get_llm, run_async, step
from mcp_helpers import stdio_session

# ============================================================
# MCP Server 实现 (带 Prompts)
# ============================================================


def build_server():
    """构造 FastMCP server (带 2 prompts + 1 tool)."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("prompts-server")

    # ─── Prompt 1: 翻译模板 ───
    @mcp.prompt()
    def translate(text: str, target_lang: str = "English") -> str:
        """翻译 prompt 模板 — 客户端填 text + target_lang.

        Returns:
            完整 system prompt
        """
        return f"""你是一个专业翻译. 请把用户的文本翻译成 {target_lang}.

要求:
- 保留原文语气
- 专业术语用标准翻译
- 不解释, 直接给译文

原文:
{text}"""

    # ─── Prompt 2: 代码 review 模板 ───
    @mcp.prompt()
    def code_review(code: str, language: str = "python") -> str:
        """代码 review prompt — 客户端填 code + language.

        Returns:
            review system prompt
        """
        return f"""你是 {language} 高级工程师, 严格 review 下面的代码.

关注:
1. Bug / 逻辑错误
2. 边界条件 / 异常处理
3. 性能 / 复杂度
4. 可读性 / 命名
5. 安全 / 输入验证

代码:
```
{code}
```

按 [CRITICAL / MAJOR / MINOR / NIT] 4 级分类问题, 给修复建议."""

    # ─── Tool: 简易计算 ───
    @mcp.tool()
    def word_count(text: str) -> int:
        """统计文本字数.

        Args:
            text: 文本

        Returns:
            字数
        """
        return len(text.split())

    return mcp


# ============================================================
# Demo
# ============================================================
# 关键: banner 必须在 if __name__ 内, 否则被 import 当 server 时会污染 stdout (JSON-RPC)
if __name__ == "__main__":
    banner("Demo 3: MCP Prompts (预定义模板)")


# ============================================================
# Step 1: server 暴露 prompts
# ============================================================
async def demo_list_prompts() -> None:
    step(1, "list prompts — server 暴露 2 个 prompt")

    async with stdio_session(__file__) as session:
        # MCP SDK 1.x: 便捷方法 list_prompts (不用 send_request + result_type)
        resp = await session.list_prompts()
        for p in resp.prompts:
            print(f"  Prompt: {p.name}")
            print(f"    描述: {(p.description or '')[:70]}")
            args = p.arguments or []
            if args:
                print(f"    参数 ({len(args)}):")
                for arg in args:
                    req = "必需" if arg.required else "可选"
                    print(f"      - {arg.name} ({req}): {arg.description or ''}")

    # 💡 MCP prompt 设计:
    #    - name: client 调用标识
    #    - description: LLM / 用户看
    #    - arguments: 客户端要填的字段 + 是否必需


# ============================================================
# Step 2: 渲染 prompt — 填参数拿 system prompt
# ============================================================
async def demo_render_prompt() -> None:
    step(2, "渲染 prompt — 客户端填参数")

    async with stdio_session(__file__) as session:
        # 渲染 translate prompt — 便捷方法 get_prompt
        result = await session.get_prompt("translate", {
            "text": "LangChain 1.x 比 0.x 简洁很多",
            "target_lang": "English",
        })

        print(f"  渲染 translate prompt:")
        for msg in result.messages:
            content = msg.content.text if hasattr(msg.content, "text") else str(msg.content)
            print(f"    [{msg.role}] {content[:200]}")

        # 渲染 code_review
        result = await session.get_prompt("code_review", {
            "code": "def add(a, b): return a+b",
            "language": "python",
        })
        print(f"\n  渲染 code_review prompt:")
        for msg in result.messages:
            content = msg.content.text if hasattr(msg.content, "text") else str(msg.content)
            print(f"    [{msg.role}] {content[:150]}...")


# ============================================================
# Step 3: 把 MCP prompt 注入 LangChain
# ============================================================
async def demo_mcp_prompt_to_langchain() -> None:
    step(3, "MCP prompt → LangChain system message")

    from langchain_mcp_adapters.tools import load_mcp_tools

    async with stdio_session(__file__) as session:
        # 1. 拉 prompt 模板 — 便捷方法 get_prompt
        result = await session.get_prompt("code_review", {
            "code": "def foo(x):\n  return x * 2",
            "language": "python",
        })
        system_prompt = result.messages[0].content.text

        # 2. 拉 tool
        tools = await load_mcp_tools(session)

        # 3. 用 LangChain agent + 渲染的 prompt
        from langchain.agents import create_agent

        agent = create_agent(
            model=get_llm(),
            tools=tools,
        )

        try:
            r = await agent.ainvoke({
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content="帮我 review 一下"),
                ],
            })
            last = r["messages"][-1]
            print(f"  Agent 最终回复 (用 MCP prompt 当 system):")
            print(f"    {getattr(last, 'content', '')[:200]}")
        except Exception as e:
            print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 实战: MCP prompt + LangChain system 注入
    #    - 模板放 MCP server (跨语言 / 跨进程 / 可独立更新)
    #    - 客户端拉模板 + 填参数 + 注入 LangChain
    #    - 跟 LangChain PromptTemplate 比: MCP prompt 是协议, 跨语言
    #    - PromptTemplate 是 Python 库, 只能在 Python 端用


# ============================================================
# Step 4: 同时用 MCP prompt + MCP tool
# ============================================================
async def demo_prompt_and_tool() -> None:
    step(4, "MCP prompt + tool 组合 — 完整 workflow")

    from langchain.agents import create_agent
    from langchain_mcp_adapters.tools import load_mcp_tools

    async with stdio_session(__file__) as session:
        # 拉翻译 prompt — 便捷方法
        result = await session.get_prompt("translate", {
            "text": "RAG = Retrieval Augmented Generation",
            "target_lang": "中文",
        })
        system_prompt = result.messages[0].content.text

        # 拉 tool
        tools = await load_mcp_tools(session)

        agent = create_agent(model=get_llm(), tools=tools)

        try:
            r = await agent.ainvoke({
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage("翻译并统计字数"),
                ],
            })
            last = r["messages"][-1]
            content = getattr(last, "content", "")

            # 检查 LLM 是否调了 word_count
            msgs = r["messages"]
            tool_calls = sum(1 for m in msgs if hasattr(m, "tool_calls") and m.tool_calls)
            print(f"  LLM 调了 {tool_calls} 次 tool")
            print(f"  最终回复: {content[:200]}")
        except Exception as e:
            print(f"  [跳过] {type(e).__name__}: {str(e)[:100]}")

    # 💡 MCP prompt 实战:
    #    - 复杂 prompt 模板从代码剥离到 MCP server (便于复用 + 跨语言)
    #    - 实战: prompt 版本管理 (Git / DB 存) + 团队共享
    #    - Claude Desktop / Cursor 等客户端可自动加载 MCP prompt


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    # 检测是否被 stdio client 当 subprocess 调
    is_subprocess = not sys.stdin.isatty()

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        print("[server] starting prompts MCP server...", file=sys.stderr)
        build_server().run(transport="stdio")
        sys.exit(0)
    elif is_subprocess:
        # 被 client 当 MCP server 起 — 自动跑 server
        build_server().run(transport="stdio")
        sys.exit(0)

    banner("Demo 3: MCP Prompts (预定义模板)")
    has_key = any(
        os.getenv(k)
        for k in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    )

    run_async(demo_list_prompts())
    run_async(demo_render_prompt())

    if has_key:
        run_async(demo_mcp_prompt_to_langchain())
        run_async(demo_prompt_and_tool())
        print("\n[OK] 03_prompts.py 全部 demo 跑完。")
    else:
        print("\n[OK] 03_prompts.py — Step 3/4 跳过 (需 API key)。")
        print("[i]   真起 server: python 03_prompts.py serve")