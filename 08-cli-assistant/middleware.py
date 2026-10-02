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
#
# 5 类 PII, 顺序敏感 (银行卡必须在 ID/手机之后, 否则 ID 里的 18 位子串的
# 内部 16 位连续数字段会被当成卡号 mangled 错):
#   1. ID (18字符)        → 1XXX-XXXX-XXXX-XXXX-X
#   2. 手机号 (11字符)    → 1XX-XXXX-XXXX
#   3. 银行卡 (16-19位)   → XXXX-XXXX-XXXX-XXXX
#   4. 邮箱               → <email>
#   5. IPv4 (4 段 0-255)  → x.x.x.x
_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")
_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
# 银行卡: 16-19 位连续数字 (银联 Visa MC JCB Diners)
# ⚠️ 必须在 ID/手机之后 (ID 的 18 位子串里可能包含 16-19 位连续数字段)
_BANK_CARD_RE = re.compile(r"\b\d{16,19}\b")
# 邮箱: 标准 email 格式 (简化版, RFC 5322 完整正则太复杂)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# IPv4: 4 段 0-255, 段间 .
_IPV4_RE = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|[01]?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d?\d)){3}\b"
)

# 顺序敏感 — 长/具体在前, 短/通用在后
_PII_PATTERNS = [
    (_ID_RE, "1XXX-XXXX-XXXX-XXXX-X"),       # 1. 身份证 (18字符, 最具体)
    (_PHONE_RE, "1XX-XXXX-XXXX"),            # 2. 手机号 (11字符, 1[3-9]开头)
    (_BANK_CARD_RE, "XXXX-XXXX-XXXX-XXXX"),  # 3. 银行卡 (16-19位纯数字)
    (_EMAIL_RE, "<email>"),                  # 4. 邮箱
    (_IPV4_RE, "x.x.x.x"),                   # 5. IPv4
]


def _redact_string(content: str) -> str:
    """单 pass 脱敏: 按 _PII_PATTERNS 顺序逐个替换.

    ⚠️ 为什么不用一个 giant alternation regex (e.g. `id|phone|bank|email|ipv4`)?
    因为每个 pattern 的 replacement 不同 — giant regex 只能给一个统一 repl.
    所以拆成 list, 顺序 sub (顺序敏感: 长/具体在前).
    """
    for pattern, repl in _PII_PATTERNS:
        content = pattern.sub(repl, content)
    return content


@wrap_model_call
async def redact_pii(request, handler):
    """把用户消息里的手机号/身份证号脱敏再发给 LLM.

    ⚠️ 必须是 `async def` — LangChain 1.x middleware 在 async 上下文 (astream)
    里要求 `awrap_model_call`, sync 版本会抛 `NotImplementedError`.
    实测: 用 astream() 调用 agent 时, sync wrap_model_call 触发的报错:
        "Asynchronous implementation of awrap_model_call is not available"
    解: 整个函数写成 async, handler 也 await. `@wrap_model_call` 装饰器识别
    coroutine function, 自动挂到 awrap_model_call 上 (无需双实现).

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
    return await handler(request)


# ============================================================
# 2. Dynamic prompt — 根据用户语气切 system prompt
# ============================================================
@dynamic_prompt
def tone_prompt(request) -> str:
    """根据用户最近的措辞动态追加语气 modifier (不覆盖 specialist 的 system_prompt).

    ⚠️ `dynamic_prompt` 装饰器执行 `request.system_prompt = prompt` — 它是 setter,
       不是 appender。如果直接返回 "用正式语气...", 会覆盖 create_agent 里传进去
       的 specialist 角色 ("你是 WeatherAgent..."), 导致 specialist 失去 domain role.
       所以这里必须以 request.system_prompt 为 base, 在末尾追加语气行.
    """
    base = request.system_prompt or ""
    history_msgs = [
        m.content for m in request.messages
        if isinstance(m, HumanMessage) and isinstance(m.content, str)
    ]
    last_text = history_msgs[-1] if history_msgs else ""

    if "正式" in last_text:
        return base + "\n\n[语气修饰] 用正式语气回答,使用'您'."
    if "哈哈" in last_text or "随便" in last_text:
        return base + "\n\n[语气修饰] 用轻松幽默的语气回答,可以用 emoji."
    return base


__all__ = ["redact_pii", "tone_prompt"]
