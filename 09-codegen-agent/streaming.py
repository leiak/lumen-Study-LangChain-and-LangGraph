"""streaming.py — 共享 streaming code gen: astream token accumulation + TTFT.

LLM streaming 关键点:
  - astream(messages) → AsyncIterator[AIMessageChunk]
  - 每个 chunk 有 .content (string 增量)
  - 累积成完整 content 后再处理 (不要每 token 解析, 半截 code 不能 parse)
  - TTFT (time-to-first-token) 是 UX 关键指标

💡 设计要点:
  - async generator pattern (让 caller await / 边收边写)
  - callback `on_token` 给 UI hookup 用 (e.g. print to terminal)
  - 写盘只在累积完成时 (避免半截 code)
  - 累积 buffer 用 list + join (比 str += 快)
  - StreamResult dataclass 装载 content + 计时 + token count
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from plan_schema import FileSpec


# ============================================================
# Result dataclass
# ============================================================
@dataclass
class StreamResult:
    """Streaming 生成结果."""

    content: str           # 完整累积内容
    ttft_seconds: float    # time-to-first-token (秒) — 从 astream 调用到第一个 token
    total_seconds: float   # 总耗时 — 整个 astream 迭代完成
    token_count: int       # 估算 token 数 (按 chunk 数估算, 不是真实 token 数)


# ============================================================
# Core streaming — astream token accumulator
# ============================================================
async def stream_llm_content(
    llm,
    messages: list,
    on_token: Callable[[str], None] | None = None,
) -> StreamResult:
    """异步 streaming LLM 内容累积.

    Args:
        llm: LangChain ChatModel (支持 .astream)
        messages: list of BaseMessage (SystemMessage / HumanMessage / ...)
        on_token: optional callback for each token (for UI hookup).
                  callback 内 raise 会打断 streaming, 调用方负责 try/except.

    Returns:
        StreamResult with content + timings.

    💡 设计要点:
      - buffer list + join (避免 str += 反复分配)
      - TTFT 只在第一个 token 时记录一次 (不要每次都 .perf_counter)
      - token_count 按 chunk 数估算 (LLM 一般 1-3 token/chunk, 偏差可接受)
      - callback 静默: 故意不 try/except, 错误传播让 caller 知道
    """
    buffer: list[str] = []
    token_count = 0
    first_token_time: float | None = None
    start = time.perf_counter()

    async for chunk in llm.astream(messages):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if not token:
            continue
        buffer.append(token)
        token_count += 1
        if first_token_time is None:
            first_token_time = time.perf_counter()
        if on_token is not None:
            on_token(token)

    end = time.perf_counter()
    return StreamResult(
        content="".join(buffer),
        ttft_seconds=(first_token_time - start) if first_token_time is not None else (end - start),
        total_seconds=end - start,
        token_count=token_count,
    )


# ============================================================
# File-aware streaming — 走 streaming 路径生成单个 file
# ============================================================
_FILE_STREAM_PROMPT_SYSTEM = (
    "你是一个 Python 代码生成助手. 输出完整可运行的 Python 代码, "
    "含 docstring + 类型注解. 不要 markdown fence (```python), 直接输出纯代码."
)

_FILE_STREAM_PROMPT_HUMAN_TPL = (
    "生成文件 `{path}`: {purpose}\n\n"
    "需要的函数:\n{functions}\n\n"
    "要求:\n"
    "- 完整类型注解 + Google 风格 docstring\n"
    "- 输出纯 Python 代码, 不要 markdown fence\n"
    "- 不要 import 用不到的模块"
)


def _format_functions_for_prompt(file_spec: FileSpec) -> str:
    """Format FunctionSpec list → prompt-friendly string."""
    if not file_spec.functions:
        return "(无具体函数 — 由你决定)"
    lines = []
    for f in file_spec.functions:
        lines.append(f"- `{f.signature}`")
        lines.append(f"  Docstring: {f.docstring}")
        if f.test_cases:
            lines.append(f"  Tests: {', '.join(f.test_cases)}")
    return "\n".join(lines)


async def stream_file_code(
    llm,
    file_spec: FileSpec,
    on_token: Callable[[str], None] | None = None,
) -> StreamResult:
    """Streaming 生成单个 file 的代码.

    跟 `codegen_pipeline.file_to_code` 区别:
      - file_to_code 走 invoke (一次性拿全部, 等 30s)
      - stream_file_code 走 astream (边收边发, TTFT <1s)

    Args:
        llm: LangChain ChatModel
        file_spec: FileSpec (含 path / purpose / functions)
        on_token: optional callback for UI

    Raises:
        透传 astream 异常 (e.g. 网络 / auth 错)
    """
    functions_text = _format_functions_for_prompt(file_spec)
    messages = [
        SystemMessage(content=_FILE_STREAM_PROMPT_SYSTEM),
        HumanMessage(content=_FILE_STREAM_PROMPT_HUMAN_TPL.format(
            path=file_spec.path,
            purpose=file_spec.purpose,
            functions=functions_text,
        )),
    ]
    return await stream_llm_content(llm, messages, on_token=on_token)


# ============================================================
# Async iterator — yield tokens on demand (e.g. for SSE / WebSocket)
# ============================================================
async def iter_llm_tokens(
    llm,
    messages: list,
) -> AsyncIterator[tuple[str, float]]:
    """AsyncIterator yield (token, elapsed_seconds) tuples.

    比 callback 更灵活: caller 可以 .__aiter__() 边收边处理 (e.g. SSE stream).

    Args:
        llm: LangChain ChatModel
        messages: list of BaseMessage

    Yields:
        (token_string, elapsed_seconds_since_first_token) tuples
        - 第一个 token 的 elapsed=0.0
        - 后续 token 的 elapsed 是相对第一个 token 的秒数

    💡 设计要点:
      - 跟 stream_llm_content 共享同一个 astream iterator 思路
      - TTFT 计时用 first-token 后的 elapsed 表达 (更符合 stream UX)
      - 不累积 content (caller 决定要不要缓存)
    """
    start = time.perf_counter()
    first_token_time: float | None = None

    async for chunk in llm.astream(messages):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if not token:
            continue
        # Track per-token elapsed from the FIRST token onward
        if first_token_time is None:
            first_token_time = time.perf_counter()
            elapsed = 0.0  # first token: 0
        else:
            elapsed = time.perf_counter() - first_token_time  # subsequent: time since first
        yield token, elapsed


__all__ = [
    "StreamResult",
    "stream_llm_content",
    "stream_file_code",
    "iter_llm_tokens",
]