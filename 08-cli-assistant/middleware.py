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
from langchain_core.messages import HumanMessage

# ============================================================
# 1. PII 脱敏 — wrap_model_call
# ============================================================
# 重要: alternation 顺序 = 长在前 (regex 从左到右尝试, 18-char ID 必须
# 先于 11-char phone, 否则 phone 会把 ID 中间 11 位数字替换掉)
# 之前 _PHONE_RE 先跑会把 18 位身份证号里的 11 位子串当成手机号 mangled,
# 导致身份证号永远无法被识别 (review bug C1)
_PII_RE = re.compile(r"\d{17}[\dXx]|1[3-9]\d{9}")


def _redact_string(content: str) -> str:
    """单 pass 脱敏: 先 ID (18字符), 再 phone (11字符)."""
    for m in _PII_RE.finditer(content):
        s = m.group(0)
        if len(s) == 18:  # 身份证号
            content = content.replace(s, "1XXX-XXXX-XXXX-XXXX-X")
        else:  # 手机号 (11 数字)
            content = content.replace(s, "1XX-XXXX-XXXX")
    return content


@wrap_model_call
def redact_pii(request, handler):
    """把用户消息里的手机号/身份证号脱敏再发给 LLM.

    注意: 不能原地改 m.content, 那会污染 agent state / checkpoint /
    trace. 用 model_copy 构造新消息 + 新 request, 保留原始 messages
    不变 (review bug C2).
    """
    new_messages = []
    changed = False
    for m in request.messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            new_content = _redact_string(m.content)
            if new_content != m.content:
                new_messages.append(m.model_copy(update={"content": new_content}))
                changed = True
                continue
        new_messages.append(m)
    if changed:
        request = request.model_copy(update={"messages": new_messages})
    return handler(request)


# ============================================================
# 2. Dynamic prompt — 根据用户语气切 system prompt
# ============================================================
@dynamic_prompt
def tone_prompt(request) -> str:
    """读全部 HumanMessage, 检测关键词切 system prompt."""
    history = [
        m.content for m in request.messages
        if isinstance(m, HumanMessage) and isinstance(m.content, str)
    ]
    full = " ".join(history)

    if "正式" in full:
        return "你是智能个人助手. 用正式语气回答,使用'您'."
    if "哈哈" in full or "随便" in full or "lol" in full.lower():
        return "你是智能个人助手. 用轻松幽默的语气回答,可以用 emoji."
    return "你是智能个人助手. 回答简洁 (不超过 80 字), 必要时调工具."


__all__ = ["redact_pii", "tone_prompt"]