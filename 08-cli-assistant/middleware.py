"""middleware.py — 两个 custom middleware.

  1. @wrap_model_call redact_pii
     - 把 HumanMessage.content 里的手机号/身份证号脱敏
     - 避免 LLM 看到原始敏感数据
     - 复用 04_middleware.py demo 8 的 pattern

  2. @dynamic_prompt tone_prompt
     - 根据用户最近的输入动态切 system prompt 语气
     - 检测关键词: "正式" → 正式语气, "哈哈"/"随便" → 轻松语气, 否则默认
     - 复用 04_middleware.py demo 1 的 pattern
"""
from __future__ import annotations

import re

from langchain.agents.middleware import dynamic_prompt, wrap_model_call
from langchain_core.messages import HumanMessage, SystemMessage

# ============================================================
# 1. PII 脱敏 — wrap_model_call
# ============================================================
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_ID_RE = re.compile(r"\d{17}[\dXx]")


@wrap_model_call
def redact_pii(request, handler):
    """把用户消息里的手机号/身份证号脱敏再发给 LLM."""
    for m in request.messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            new_content = _PHONE_RE.sub("1XX-XXXX-XXXX", m.content)
            new_content = _ID_RE.sub("1XXXXXXXXXXXXXXXXX", new_content)
            if new_content != m.content:
                # 不可变消息,用 .model_copy 或者 mutate 内容 (构造允许)
                m.content = new_content
    return handler(request)


# ============================================================
# 2. Dynamic prompt — 根据用户语气切 system prompt
# ============================================================
@dynamic_prompt
def tone_prompt(request) -> str:
    """读最近 N 条 HumanMessage, 检测关键词切 system prompt."""
    history = [
        m.content for m in request.messages if isinstance(m, HumanMessage)
    ]
    full = " ".join(history)

    if "正式" in full:
        return "你是智能个人助手. 用正式语气回答,使用'您'."
    if "哈哈" in full or "随便" in full or "lol" in full.lower():
        return "你是智能个人助手. 用轻松幽默的语气回答,可以用 emoji."
    return "你是智能个人助手. 回答简洁 (不超过 80 字), 必要时调工具."


__all__ = ["redact_pii", "tone_prompt"]
