"""metrics.py — observability: TurnMetrics + SessionMetrics + pricing.

Per-turn: latency / tokens (in/out) / tool calls / specialist name / cost
Cumulative: /stats 命令汇总 session 累计

💡 设计权衡:
  - TurnMetrics 不可变 (dataclass frozen=False 但 record 后不修改), 用 list 累积
  - token 去重按 message.id — LangGraph 有时在 history 里出现同一 message 多次
    (checkpoint replay / supervisor routing 转回), 不去重会 double-count.
  - pricing 表 substring 匹配, 大小写不敏感. 不在表里 → cost 显示 "?"
    而不是抛错 (M3 / 本地 ollama 等都没定价).
  - specialist 检测基于最后一条 AIMessage 的 .name; supervisor 内部 routing
    AIMessage 没 name, 只 specialist final reply 有 — 这正是我们想要的.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from langchain_core.messages import AIMessage, ToolMessage


# ============================================================
# Pricing — model name (substring 匹配) → (input $/1M, output $/1M)
# 不在表里的模型 → cost 显示 "?" 不算金额.
#
# 💡 价格快照 (2026-10, 仅供参考, 实战前请去 provider 官网核对):
#   - Anthropic Claude 5: sonnet $3/$15, opus $15/$75, haiku $0.25/$1.25
#   - DeepSeek V3 / R1: $0.14/$0.28, $0.55/$2.19
#   - OpenAI GPT-5: $5/$15, GPT-4o: $2.5/$10
#   - MiniMax M3: 0/0 (内测免费)
# ============================================================
_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic Claude 5 family
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-5": (15.0, 75.0),
    "claude-haiku-4-5": (0.25, 1.25),
    # DeepSeek
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    # OpenAI
    "gpt-5": (5.0, 15.0),
    "gpt-4o": (2.5, 10.0),
    # MiniMax
    "MiniMax-M3": (0.0, 0.0),  # 内测免费
}


def estimate_cost(model_name: str, in_tok: int, out_tok: int) -> float | None:
    """根据模型名估算 cost (USD). 找不到模型 → None (不显示 cost).

    Args:
        model_name: LLM model 名 (e.g. "claude-sonnet-5-20251001")
        in_tok: input tokens
        out_tok: output tokens

    Returns:
        USD 金额 (float), 或 None 表示模型不在定价表里.
    """
    if not model_name:
        return None
    # substring 匹配 (case-insensitive) — 兼容 "claude-sonnet-5-20251001" 这类带日期的版本号
    for key, (in_price, out_price) in _PRICING.items():
        if key.lower() in model_name.lower():
            return (in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price
    return None


# ============================================================
# State → metrics 提取 (从 graph.get_state(config).values 拿)
# ============================================================
def extract_tokens(state_values: dict) -> tuple[int, int]:
    """从 state.values['messages'] 提取总 input/output tokens.

    去重: 按 message.id 排除同一 message 重复出现 (LangGraph 有时在 history
    里出现同一 message 多次 — checkpoint replay / supervisor 内部 routing
    把 message 转回主图都会导致 history 出现重复).

    Returns:
        (total_input_tokens, total_output_tokens)
    """
    seen: set[str | int] = set()
    total_in, total_out = 0, 0
    for msg in state_values.get("messages", []):
        if not isinstance(msg, AIMessage):
            continue
        msg_id = getattr(msg, "id", None) or id(msg)
        if msg_id in seen:
            continue
        seen.add(msg_id)
        um = getattr(msg, "usage_metadata", None)
        if um:
            total_in += um.get("input_tokens", 0) or 0
            total_out += um.get("output_tokens", 0) or 0
    return total_in, total_out


def detect_specialist(state_values: dict) -> str:
    """最后一条带 name 的 AIMessage 的 name (specialist 路由结果).

    💡 supervisor 内部 routing AIMessage (e.g. "Transferring back to supervisor")
       是 langgraph_supervisor 自己加的 AIMessage, 没有 .name. 而 specialist
       调完工具后的 final reply 由 create_agent 生成, 自带 .name (e.g. "WeatherAgent").
       所以反向遍历找第一个带 name 的 AIMessage = 最终 specialist 输出.

    没识别 → '?'
    """
    for msg in reversed(state_values.get("messages", [])):
        if isinstance(msg, AIMessage):
            name = getattr(msg, "name", None)
            if name:
                return name
    return "?"


def count_tool_calls(state_values: dict) -> int:
    """统计 ToolMessage 数量 = LLM 调用工具的次数.

    注意: 同一 turn 里 specialist 可能调多个工具, 每个工具执行完都有一条
    ToolMessage. 这是真实工具调用次数, 不是 unique tool names.
    """
    return sum(1 for m in state_values.get("messages", []) if isinstance(m, ToolMessage))


# ============================================================
# Turn + Session
# ============================================================
@dataclass
class TurnMetrics:
    """单个 turn 的指标."""
    latency_ms: int
    input_tokens: int
    output_tokens: int
    tool_calls: int
    specialist: str
    cost_usd: float | None = None  # None = 未知模型, 不算金额


@dataclass
class SessionMetrics:
    """整个 session 的累计指标."""
    model_name: str = ""
    turns: list[TurnMetrics] = field(default_factory=list)

    def record(self, tm: TurnMetrics) -> None:
        """追加一个 turn 的指标."""
        self.turns.append(tm)

    # ---- per-turn display ----
    @staticmethod
    def format_turn(tm: TurnMetrics) -> str:
        """单行显示当前 turn 指标 (REPL run_turn 完成后调用).

        格式: `>>> 280ms · in 124 / out 86 · 1 tools · WeatherAgent · ~$0.0001`
        cost 未知 → `$?` (e.g. M3 没接 pricing 也照常显示, 只是 token 数不准)
        """
        cost = f"~${tm.cost_usd:.4f}" if tm.cost_usd is not None else "$?"
        return (
            f">>> {tm.latency_ms}ms · in {tm.input_tokens} / out {tm.output_tokens} "
            f"· {tm.tool_calls} tools · {tm.specialist} · {cost}"
        )

    # ---- cumulative /stats display ----
    def summary(self) -> str:
        """多行显示 session 累计指标 (/stats 命令调用).

        格式示例:
            >>> Session 统计 (12 turns):
               tokens:   in 1,420 / out 980  ·  tools 18
               latency:  avg 245ms · max 1.2s
               routed:   Weather 3 · Calc 2 · Notes 4 · Orders 2 · Data 1 · direct 0
               cost:     ~$0.0042 估算 (model: claude-sonnet-5)
        """
        if not self.turns:
            return ">>> Session 统计: 还没有 turn"

        n = len(self.turns)
        total_in = sum(t.input_tokens for t in self.turns)
        total_out = sum(t.output_tokens for t in self.turns)
        total_tools = sum(t.tool_calls for t in self.turns)
        total_cost = sum(t.cost_usd for t in self.turns if t.cost_usd is not None)
        has_cost = any(t.cost_usd is not None for t in self.turns)
        latencies = [t.latency_ms for t in self.turns]
        avg_lat = sum(latencies) // n
        max_lat = max(latencies)

        # routed 计数 — specialist 名 → 次数, 按名字排序便于对比
        routed: dict[str, int] = {}
        for t in self.turns:
            routed[t.specialist] = routed.get(t.specialist, 0) + 1
        routed_str = " · ".join(f"{k} {v}" for k, v in sorted(routed.items()))

        # max_lat 显示成 "1.2s" 风格 — >1000ms 时换单位
        max_lat_str = f"{max_lat / 1000:.1f}s" if max_lat >= 1000 else f"{max_lat}ms"

        cost_str = (
            f"~${total_cost:.4f} 估算 (model: {self.model_name})"
            if has_cost
            else "? (model 不在 pricing 表)"
        )

        return (
            f">>> Session 统计 ({n} turns):\n"
            f"   tokens:   in {total_in:,} / out {total_out:,}  ·  tools {total_tools}\n"
            f"   latency:  avg {avg_lat}ms · max {max_lat_str}\n"
            f"   routed:   {routed_str}\n"
            f"   cost:     {cost_str}"
        )


__all__ = [
    "TurnMetrics",
    "SessionMetrics",
    "estimate_cost",
    "extract_tokens",
    "detect_specialist",
    "count_tool_calls",
]
