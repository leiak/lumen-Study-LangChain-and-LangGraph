"""main.py — CLI 个人助手入口.

跑法:
    cd 08-cli-assistant
    python main.py

需要 .env 里有 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY /
OPENAI_API_KEY 之一. 详见 01-langchain-basics/_common.py.
"""
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _common import banner, get_llm
from agent import build_graph
from cli import CLI
from memory import build_store
from metrics import SessionMetrics


def main() -> int:
    """入口: 检查 API key → 装配 LLM+Graph+Store → 启动 REPL.

    Returns 0 on success, 1 on error.
    """
    # 1. 检查 API key (env 已 load, 这里再兜一道)
    has_key = any(
        os.getenv(k)
        for k in (
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
            "MINIMAX_API_KEY",
            "OPENAI_API_KEY",
        )
    )
    if not has_key:
        print(
            "[error] 未找到 LLM API key. 请在项目根 .env 设置:\n"
            "  ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY\n"
            "(LLM_PROVIDER 强制选择 + .env.example 详见 01-langchain-basics/_common.py)"
        )
        return 1

    # 2. 装配 LLM + Graph + Store
    banner("启动智能个人助手 CLI")
    try:
        llm = get_llm()
    except RuntimeError as e:
        print(f"[error] {e}")
        return 1

    from langgraph.checkpoint.memory import InMemorySaver

    checkpointer = InMemorySaver()
    store, namespace = build_store()

    # 2.5 MySQL 连接探测 (可选 — 没配置也不阻塞 CLI, DataAgent 会优雅提示)
    # 复用 mysql_db.build_engine (RuntimeError = env 缺失; sqlalchemy.exc.* = 网络/auth 错)
    try:
        from mysql_db import build_engine
        engine = build_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1")).fetchone()
        print(">>> MySQL: connected")
    except RuntimeError as e:
        print(f">>> MySQL: 未配置 ({e}); DataAgent 将无法使用")
    except Exception as e:
        print(f">>> MySQL: 连接失败 ({type(e).__name__}: {e}); DataAgent 将无法使用")

    try:
        graph = build_graph(llm, checkpointer=checkpointer, store=store)
    except Exception as e:
        print(f"[error] 装配 graph 失败: {type(e).__name__}: {e}")
        return 1

    # 2.7 ⭐ Observability: 取 model_name 喂给 SessionMetrics (用于 cost 估算)
    # LangChain ChatModel 都有 .model_name 属性; 取不到 → "" (cost 显示 "?")
    model_name = getattr(llm, "model_name", "") or ""
    session_metrics = SessionMetrics(model_name=model_name)

    # 3. 启动 REPL
    cli = CLI(
        graph, checkpointer, store, namespace,
        session_metrics=session_metrics,
        model_name=model_name,
    )
    try:
        asyncio.run(cli.run())
    except KeyboardInterrupt:
        print("\n再见 👋")
    return 0


if __name__ == "__main__":
    sys.exit(main())