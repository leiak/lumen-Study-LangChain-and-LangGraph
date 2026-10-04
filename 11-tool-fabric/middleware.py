"""middleware.py — 共享 wrap_tool_call handlers.

教学 tool middleware 3 类:
  - logging: 记录每次 tool call (input + output + latency)
  - PII strip: 输出剥 PII (e.g. 手机号 138****0000)
  - rate limit: 限制单 tool 调用频率

💡 设计要点:
  - 用 @wrap_tool_call 装饰 (LangChain 1.x 标准)
  - handler 返回 ToolMessage 或 Command (handler(request) 真执行; return 是包结果)
  - 可以 chain 多个 middleware (顺序敏感: 第一个声明的最外层)
"""
from __future__ import annotations

import re
import time
from collections import defaultdict

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage


@wrap_tool_call
def logging_middleware(request, handler):
    """记录每次 tool call (input + output + latency).

    用法:
        middleware=[logging_middleware]
    """
    tool_name = request.tool_call["name"]
    tool_input = request.tool_call["args"]
    print(f"  [LOG] tool={tool_name} input={tool_input}")
    start = time.perf_counter()
    result = handler(request)
    elapsed = time.perf_counter() - start
    # ToolMessage 有 .content (handler 返回值); 截断避免刷屏
    output_preview = str(getattr(result, "content", result))[:100]
    print(f"  [LOG] tool={tool_name} output={output_preview} latency={elapsed:.3f}s")
    return result


_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"(\w)\w*@(\w+\.\w+)")


@wrap_tool_call
def pii_strip_middleware(request, handler):
    """输出剥 PII (手机号 → 138****0000, 邮箱 → a***@example.com).

    实战:
        - 聊天记录 / 客服工单常有 PII, 给 LLM 前先 mask 防止 context 泄漏
        - 但: handler 返回 ToolMessage 一定要带 tool_call_id, 框架靠它对应回 AIMessage
    """
    result = handler(request)
    content = str(result.content)

    # 手机号 13800138000 → 138****8000
    content = _PHONE_RE.sub(
        lambda m: m.group(0)[:3] + "****" + m.group(0)[7:],
        content,
    )
    # 邮箱 alice@example.com → a***@example.com
    content = _EMAIL_RE.sub(
        lambda m: m.group(1) + "***@" + m.group(2),
        content,
    )

    # 重建 ToolMessage (content 改了, 必须新建 — 不能直接 setattr, frozen)
    return ToolMessage(content=content, tool_call_id=result.tool_call_id)


# Rate limiter (simple in-memory, per-tool)
_call_counts: dict[str, list[float]] = defaultdict(list)


@wrap_tool_call
def rate_limit_middleware(request, handler, max_per_minute: int = 10):
    """限制单 tool 每分钟调用次数 (in-memory, 教学用).

    Args:
        max_per_minute: 默认 10/min. 超过返回 "rate limit exceeded" 当 ToolMessage.

    实战:
        - production 用 Redis token bucket / sliding window (跨进程共享)
        - demo 简化: 进程内 dict 计数, 60s 滑动窗口
    """
    tool_name = request.tool_call["name"]
    now = time.perf_counter()
    # 清理 60s 前的记录 (滑动窗口)
    _call_counts[tool_name] = [t for t in _call_counts[tool_name] if now - t < 60]
    if len(_call_counts[tool_name]) >= max_per_minute:
        # 拒绝: 返回 ToolMessage, 框架当正常 tool result 回给 LLM
        return ToolMessage(
            content="rate limit exceeded",
            tool_call_id=request.tool_call["id"],
        )
    _call_counts[tool_name].append(now)
    return handler(request)


__all__ = ["logging_middleware", "pii_strip_middleware", "rate_limit_middleware"]