"""cli.py — REPL 主循环 + 命令路由 + streaming token 打印 + HITL 审批 + observability.

REPL 流程:
  1. read() 读一行 stdin
  2. 以 "/" 开头 → await handle_command() (内置命令)
  3. 普通文本   → await run_turn() 异步流式调 supervisor
  4. run_turn 内部: astream(stream_mode="messages") + 逐字 print
  5. 检测到 state.next 非空 + 有 interrupt → handle_hitl()
  6. 用户输入 a/r → Command(resume=...) 恢复
  7. ⭐ 每个 turn 完成后打印 per-turn 指标 (latency/tokens/tools/specialist/cost)

命令:
  /history      列出 checkpoints
  /diff A B     比较两个 checkpoint 差异 (message + tokens + latency)
  /rewind N     回到第 N 个 checkpoint (不重跑 LLM)
  /fork TXT     在新 thread 续走, 注入 TXT 作为新的人类消息
  /memory       查看/编辑长期偏好
  /stats        Session 累计指标 (turns / tokens / latency / 路由 / cost)
  /help         帮助
  /quit, /exit  退出
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
from datetime import datetime
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from memory import get_prefs, set_pref
from metrics import (
    SessionMetrics,
    TurnMetrics,
    count_tool_calls,
    detect_specialist,
    estimate_cost,
    extract_tokens,
)

# Supervisor 内部 routing 消息 (langgraph_supervisor 内部 AIMessage, 不该显示给用户)
_SUPERVISOR_NOISE = (
    "Transferring back to supervisor",
    "Successfully transferred back to supervisor",
)


# ============================================================
# HITL 预览 — 每个工具调用前的"影响预览"
# ============================================================
# 目标: 用户 approve 前看到"将要发生什么", 而不是盲签.
# 三个 HITL 工具 (run_sql / refund_order / write_note) 各自有一个 preview 函数,
# 在 `_maybe_hitl` 决策前打印 3-5 行影响摘要.
_HITL_PREVIEW = ("run_sql", "refund_order", "write_note")


def _preview_run_sql(args: dict) -> list[str]:
    """run_sql 预览: SQL 全文 + EXPLAIN 估算影响行数 + 涉及表/列.

    EXPLAIN 在 audit 后执行, 不计入 hitl approve — 是只读 SHOW query plan.
    走 ThreadPoolExecutor 防止 EXPLAIN 自身 hang (罕见但可能).
    """
    sql = args.get("query", "")
    lines = [f"  SQL: {sql}"]
    # 从 SQL 简单提取表名 (regex \\bFROM\\s+`?(\\w+))
    tables = re.findall(r"\bFROM\s+`?(\w+)", sql, re.IGNORECASE)
    if tables:
        lines.append(f"  表: {', '.join(set(tables))}")
    # 跑 EXPLAIN 估行数 — 走 ThreadPoolExecutor 防 hang
    try:
        import concurrent.futures
        from sqlalchemy import text
        from mysql_db import build_engine, _audit_sql
        engine = build_engine()
        # 走 _audit_sql 保证 EXPLAIN 后面的 SELECT 也是 audit 过的 (防注入)
        explained_sql = f"EXPLAIN {_audit_sql(sql)}"

        def _explain():
            with engine.connect() as conn:
                rows = conn.execute(text(explained_sql)).mappings().all()
                return [dict(r) for r in rows]

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            f = ex.submit(_explain)
            try:
                rows = f.result(timeout=5.0)
            except concurrent.futures.TimeoutError:
                lines.append("  预估行数: ? (EXPLAIN 超时 5s)")
                return lines
        # EXPLAIN 返回字段: table, type, rows (估算), Extra, ...
        total_rows = sum(int(r.get("rows") or 0) for r in rows)
        lines.append(f"  预估影响行数: ~{total_rows} (EXPLAIN 估算)")
        extras = [r.get("Extra", "") for r in rows if r.get("Extra")]
        if extras:
            lines.append(f"  执行计划: {'; '.join(set(extras))[:80]}")
    except RuntimeError:
        # MySQL 未配置 — 跳过 EXPLAIN, 不阻塞 REPL
        lines.append("  预估行数: ? (MySQL 未配置)")
    except Exception as e:
        lines.append(f"  预估行数: ? ({type(e).__name__})")
    return lines


def _preview_refund_order(args: dict) -> list[str]:
    """refund_order 预览: 订单 + 退款金额 + 余额 + 业务上限."""
    from tools import _ORDERS, _norm_order_id
    oid = _norm_order_id(args.get("order_id", ""))
    try:
        amount = float(args.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0
    info = _ORDERS.get(oid)
    lines = [f"  订单: {oid}"]
    if info is None:
        lines.append(f"  ⚠️  订单 {oid} 不存在 (demo 内置 #123 / #456)")
        return lines
    lines.append(f"  当前金额: ¥{info['amount']:.2f} ({info['item']})")
    lines.append(f"  退款: ¥{amount:.2f}")
    if amount > 10000:
        lines.append(f"  ⚠️  超过业务上限 10000, 会被业务拒绝")
    lines.append(f"  退款后余额: ¥{info['amount'] - amount:.2f}")
    return lines


def _preview_write_note(args: dict) -> list[str]:
    """write_note 预览: name + content 预览 + 字节数."""
    name = args.get("name", "")
    content = args.get("content", "")
    preview = content[:50] + ("..." if len(content) > 50 else "")
    return [
        f"  name: {name}",
        f"  content ({len(content)} 字符): {preview}",
    ]


_HITL_PREVIEW_FNS = {
    "run_sql": _preview_run_sql,
    "refund_order": _preview_refund_order,
    "write_note": _preview_write_note,
}


def _format_hitl_preview(tool_name: str, args: dict) -> list[str]:
    """根据 tool_name 路由到对应 preview 函数.

    ⚠️ 不在 _maybe_hitl 主体里 raise — preview 失败只打一行 warning,
    不阻塞 HITL 决策 (用户还是能看到原始 intr dict).
    """
    fn = _HITL_PREVIEW_FNS.get(tool_name)
    if fn is None:
        return [f"  (无预览: {tool_name})"]
    try:
        return fn(args)
    except Exception as e:
        return [f"  [预览失败] {type(e).__name__}: {e}"]


# ============================================================
# /diff 辅助 — 时间戳解析 + message 摘要打印
# ============================================================
def _parse_iso_ms(iso_str: str | None) -> int:
    """ISO 8601 时间戳 → 毫秒 (since epoch). 失败 / None → 0.

    LangGraph 的 StateSnapshot.created_at 是 ISO 8601 字符串 (含 timezone offset).
    Python 3.11+ `fromisoformat` 直接吃 "+HH:MM" 偏移, 但 "Z" 后缀不认 —
    这里手动 replace. 失败 defensive 返回 0, 不阻塞 diff 计算.
    """
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def _print_msg_line(msg, prefix: str) -> None:
    """打印一行 message 摘要: 类型 + (optional name) + 前 50 字符 content.

    用在 /diff 输出里, 把 added/removed message 一行一颗塞进去.
    name 仅当存在时打印 (e.g. AIMessage(name="WeatherAgent")).
    content 是 list 时 (tool_calls 块) 转成 str 避免 repr 爆炸.
    """
    type_name = type(msg).__name__
    name = getattr(msg, "name", None)
    name_part = f" ({name})" if name else ""
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        # tool_calls 之类 content 是 list of dict
        content = str(content)
    if not isinstance(content, str):
        content = str(content)
    preview = content[:50].replace("\n", " ") + ("..." if len(content) > 50 else "")
    print(f"  {prefix}{type_name}{name_part}: {preview!r}")


# ============================================================
# 欢迎语 + 帮助
# ============================================================
WELCOME = """
╭─────────────────────────────────────────────╮
│  智能个人助手 CLI  (08-cli-assistant)       │
│                                             │
│  输入问题 → streaming token 流式输出        │
│  危险操作 (退款/写笔记/SQL) → 自动暂停审批  │
│                                             │
│  内置命令:                                  │
│    /history      列出 checkpoints            │
│    /diff A B     比较两个 checkpoint 差异    │
│    /rewind N     回到第 N 个 checkpoint      │
│    /fork TXT     改历史后在新 thread 续走   │
│    /memory       查看/编辑长期偏好           │
│    /mysql        探测 MySQL 连接 + 列表      │
│    /stats        Session 累计指标            │
│    /help         帮助                        │
│    /quit, /exit  退出                        │
╰─────────────────────────────────────────────╯
"""


HELP_TEXT = """
命令:
  /history           列出本 thread 所有 checkpoint (index 0=最新)
  /diff <a> <b>      比较两个 checkpoint 差异 (message/tokens/latency)
  /rewind N          回到 history[N] 的状态 (N 是 history 列表索引, 0=最新)
  /fork <text>       在最新 checkpoint 上追加 <text>, 新 thread 续走
  /memory            查看偏好
  /memory <key> <v>  设置偏好 (nickname / city / language / user_*)
  /mysql             探测 MySQL 连接 + 列出所有表 (含列结构)
  /stats             Session 累计 (token/延迟/路由/cost)
  /help              本帮助
  /quit, /exit       退出

正常对话:
  - "北京天气?"     → 派 WeatherAgent
  - "123 * 456"     → 派 CalcAgent
  - "查订单 #123"    → 派 OrdersAgent
  - "退款 #123 100"  → OrdersAgent 触发 HITL (输入 a/r 决策)
  - "写笔记 todo ..." → NotesAgent 触发 HITL
  - "北京有几个用户"  → DataAgent (调 list_tables → describe_table → run_sql 触发 HITL)

每个 turn 完成后会自动打印一行指标:
  >>> 280ms · in 124 / out 86 · 1 tools · WeatherAgent · ~$0.0001

/diff 用法:
  /diff 1 3         列出 1→3 之间新增的 message + token delta + latency delta
  /diff 3 1         反向 diff — 看 "回到 1" 会移除什么 (rewind 决策辅助)
  只读, 不动 state / pending_checkpoint_id
"""


# ============================================================
# REPL 主类
# ============================================================
class CLI:
    """REPL 主循环 + 命令路由 + 流式打印."""

    def __init__(
        self,
        graph,
        checkpointer,
        store,
        store_namespace: tuple[str, str],
        thread_id: str = "cli-session-1",
        session_metrics: SessionMetrics | None = None,
        model_name: str = "",
    ):
        self.graph = graph
        self.checkpointer = checkpointer
        self.store = store
        self.store_ns = store_namespace
        self.thread_id = thread_id
        self.active_thread_id = thread_id  # 主 thread; fork 后会变
        # rewind 用的 checkpoint_id 覆盖 - 设了之后 config() 会带上它,
        # 后续 invoke 会从 history[n] 这个 checkpoint 开始 (走 time-travel replay)
        # ⚠️ 一次性: run_turn 完成后会清掉, 不然会一直卡在分支上
        self._rewind_ckpt: str | None = None
        # ⭐ /diff 用: /history 跑完后填充, [{id, msgs, latency_ms, next}, ...]
        # /diff 通过这里拿 checkpoint_id + latency 字段, 不用再 query history
        self.history_checkpoints: list[dict] = []
        # ⭐ Observability: 默认 None 时创建新的 SessionMetrics, 传入则复用 (测试场景)
        self.metrics = session_metrics or SessionMetrics(model_name=model_name)
        # model_name 单独存一份, 用于新 turn 的 cost 计算
        # (避免 session_metrics 被外面改 model_name 后影响当前 CLI 实例)
        self._model_name = model_name

    @property
    def config(self) -> dict[str, Any]:
        """当前 thread 的 invoke config. rewind 后会带上 checkpoint_id."""
        cfg = {"configurable": {"thread_id": self.active_thread_id}}
        if self._rewind_ckpt:
            # checkpoint_id 注入后, 下次 astream 会从 history[n] 这个点重新走
            # (不重跑 LLM, 直接接续; LangGraph 1.x time-travel 语义)
            cfg["configurable"]["checkpoint_id"] = self._rewind_ckpt
        return cfg

    # --------------------------------------------------------
    # 入口
    # --------------------------------------------------------
    async def run(self) -> None:
        print(WELCOME)
        print(f">>> thread_id: {self.thread_id}")
        print(f">>> user prefs: {get_prefs(self.store, self.store_ns)}")
        print()

        # 3.10+ 用 get_running_loop, 不再 get_event_loop (后者已 deprecate)
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, input, "你> ")
            except (EOFError, KeyboardInterrupt):
                print("\n再见 👋")
                return

            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                should_exit = await self.handle_command(line)
                if should_exit:
                    return
                continue

            # 普通对话
            await self.run_turn(line)

    # --------------------------------------------------------
    # 内置命令 (async, 因为 _cmd_fork 需要 await)
    # --------------------------------------------------------
    async def handle_command(self, line: str) -> bool:
        """处理 / 命令. 返回 True = 退出 REPL.

        async: 让 /fork 之类的子命令能 await 流式输出, 不再 asyncio.run() 嵌套 loop.
        """
        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "/quit" or cmd == "/exit":
            print("再见 👋")
            return True

        if cmd == "/help":
            print(HELP_TEXT)
            return False

        if cmd == "/history":
            self._cmd_history()
            return False

        if cmd == "/diff":
            self._cmd_diff(parts[1:])
            return False

        if cmd == "/rewind":
            if len(parts) < 2:
                print("用法: /rewind N  (N 是 history 列表索引, 0=最新)")
                return False
            try:
                n = int(parts[1])
                self._cmd_rewind(n)
            except ValueError:
                print(f"非法索引: {parts[1]!r}")
            return False

        if cmd == "/fork":
            # parts 用 maxsplit=2, 但 fork text 可能含空格, 直接从原 line 截
            text = line[len("/fork"):].strip()
            if not text:
                print("用法: /fork <text>")
                return False
            await self._cmd_fork(text)
            return False

        if cmd == "/memory":
            if len(parts) == 1:
                self._cmd_memory_show()
            elif len(parts) >= 3:
                self._cmd_memory_set(parts[1], parts[2])
            else:
                print("用法: /memory [key value]")
            return False

        if cmd == "/mysql":
            self._cmd_mysql()
            return False

        if cmd == "/stats":
            # ⭐ Session 累计指标 (turns / tokens / latency / 路由 / cost)
            print(self.metrics.summary())
            return False

        print(f"未知命令: {cmd}. 输入 /help 查看.")
        return False

    def _cmd_history(self) -> None:
        # ⚠️ 用干净的 config (不带 checkpoint_id) 才能拿到整条时间线;
        # 带 checkpoint_id 时 get_state_history 只返回该 ckpt 及之后, 看不到前面.
        history_cfg = {"configurable": {"thread_id": self.active_thread_id}}
        history = list(self.graph.get_state_history(history_cfg))

        # ⭐ 填充 self.history_checkpoints — /diff 命令用它取 checkpoint_id + latency
        # latency_ms: 这个 checkpoint 距上一个的 wall-clock ms (首个 0)
        # 用 created_at 算 — 比 TurnMetrics.latency_ms 更准 (后者是 streaming 时长,
        # 不含 HITL 等待 / 中断暂停)
        self.history_checkpoints = []
        prev_ts_ms: int | None = None
        for snap in history:
            ts_ms = _parse_iso_ms(getattr(snap, "created_at", None))
            latency_ms = (ts_ms - prev_ts_ms) if (prev_ts_ms is not None and ts_ms) else 0
            prev_ts_ms = ts_ms if ts_ms else prev_ts_ms
            self.history_checkpoints.append({
                "id": snap.config["configurable"]["checkpoint_id"],
                "msgs": len(snap.values.get("messages", [])),
                "latency_ms": latency_ms,
                "next": snap.next,
            })

        print(f"\n>>> 共 {len(history)} 个 checkpoint (history[0]=最新):")
        for i, ckpt in enumerate(self.history_checkpoints):
            ckpt_short = ckpt["id"][:8]
            print(
                f"  [{i:>3}] ckpt={ckpt_short}... | msgs={ckpt['msgs']} "
                f"| latency={ckpt['latency_ms']}ms | next={ckpt['next']}"
            )

    def _cmd_rewind(self, n: int) -> None:
        # 同样用干净 config 拿完整 history
        history_cfg = {"configurable": {"thread_id": self.active_thread_id}}
        history = list(self.graph.get_state_history(history_cfg))
        if n < 0 or n >= len(history):
            print(f"索引 {n} 越界, 范围 [0, {len(history)-1}]")
            return
        snap = history[n]
        ckpt = snap.config["configurable"]["checkpoint_id"]
        # 把 checkpoint_id 注入 config - 下次 astream 从 history[n] 这个
        # checkpoint 重新走 (LangGraph 1.x time-travel replay 语义).
        # 一次性: run_turn 完成后会清掉.
        self._rewind_ckpt = ckpt
        print(
            f">>> 回到 history[{n}] (ckpt={ckpt[:8]}..., "
            f"{len(snap.values.get('messages', []))} 条消息). "
            f"下次输入会以该 checkpoint 为起点."
        )

    async def _cmd_fork(self, text: str) -> None:
        """在最新 checkpoint 上追加 text, 用 update_state 创建新 thread."""
        history_cfg = {"configurable": {"thread_id": self.active_thread_id}}
        history = list(self.graph.get_state_history(history_cfg))
        if not history:
            print(">>> 无历史, 无法 fork. 先跟助手对话几轮.")
            return
        new_config = self.graph.update_state(
            history[0].config,
            {"messages": [HumanMessage(content=text)]},
        )
        new_thread = new_config["configurable"]["thread_id"]
        # ⚠️ 切换 active_thread_id 到新 thread — 后续 /history 和 run_turn 都走这条
        # 否则会卡在原 thread, 看 fork 后的续走消息
        self.active_thread_id = new_thread
        self._rewind_ckpt = None
        print(f">>> Fork 到新 thread: {new_thread}")
        print(f">>> 续走中...")
        await self._continue_turn(new_config)

    def _cmd_diff(self, args: list[str]) -> None:
        """比较两个 checkpoint 之间的差异 (message + tokens + latency).

        用法: /diff <a> <b>  (a b 是 /history 里的 1-based 索引, 顺序无关)
              /diff 1 3 → 列出 1→3 之间新增的 message + token delta + latency delta
              /diff 3 1 → 反向: 列出"从 3 回到 1"会移除哪些 message (rewind 决策辅助)

        ⚠️ 只读 — 不动 pending_checkpoint_id, 不调用 invoke / astream.
        /rewind 仍按 history_checkpoints 当前索引走, /diff 纯分析不修改.
        """
        if len(args) != 2:
            print("usage: /diff <a> <b> (checkpoint 索引, 1-based)")
            return
        if not self.history_checkpoints:
            print(">>> 没有 history, 先跑 /history")
            return
        try:
            a_idx = int(args[0]) - 1  # 1-based → 0-based
            b_idx = int(args[1]) - 1
        except ValueError:
            print("usage: /diff <a> <b> (checkpoint 索引, 1-based)")
            return
        if not (0 <= a_idx < len(self.history_checkpoints)
                and 0 <= b_idx < len(self.history_checkpoints)):
            print(
                f">>> checkpoint 索引越界, 跑 /history 看可用索引 "
                f"(1-{len(self.history_checkpoints)})"
            )
            return
        if a_idx == b_idx:
            print(
                f">>> Diff #{a_idx+1} → #{b_idx+1}: 同一 checkpoint, 无变化"
            )
            return

        old_ckpt = self.history_checkpoints[a_idx]
        new_ckpt = self.history_checkpoints[b_idx]

        # ⚠️ 用 self.active_thread_id 而不是 thread_id — fork 后会切换
        # 读的是当前 thread 的 checkpoint, 不是原 thread
        old_state = self.graph.get_state({
            "configurable": {
                "thread_id": self.active_thread_id,
                "checkpoint_id": old_ckpt["id"],
            }
        })
        new_state = self.graph.get_state({
            "configurable": {
                "thread_id": self.active_thread_id,
                "checkpoint_id": new_ckpt["id"],
            }
        })
        old_msgs = old_state.values.get("messages", [])
        new_msgs = new_state.values.get("messages", [])

        # 用 message.id 去重 + 比较 (LangGraph 有时同一 message 多次出现)
        # id() fallback: 跨 checkpoint 比较时, 没 id 的 message 仍能区分
        old_ids = {(m.id or id(m)) for m in old_msgs}
        new_ids = {(m.id or id(m)) for m in new_msgs}
        added = [m for m in new_msgs if (m.id or id(m)) not in old_ids]
        removed = [m for m in old_msgs if (m.id or id(m)) not in new_ids]

        # ⭐ Token delta — 复用 metrics.extract_tokens (不去重重复实现)
        old_in, old_out = extract_tokens(old_state.values)
        new_in, new_out = extract_tokens(new_state.values)
        delta_in = new_in - old_in
        delta_out = new_out - old_out

        # Latency delta — history_checkpoints 已有 latency_ms 字段
        # (wall-clock ms from prev ckpt, /history 时填的)
        delta_latency = new_ckpt.get("latency_ms", 0) - old_ckpt.get("latency_ms", 0)

        direction = "old→new" if a_idx < b_idx else "new→old"
        print(f">>> Diff #{a_idx+1} → #{b_idx+1} ({direction}):")
        print(f"  + {len(added)} added, {len(removed)} removed")
        print(f"  Δ tokens: {delta_in:+d} in / {delta_out:+d} out")
        print(f"  Δ latency: {delta_latency:+d}ms")

        if not added and not removed:
            return  # 空 diff, 只 header 就够

        print()
        for msg in added:
            _print_msg_line(msg, prefix="+ ")
        for msg in removed:
            _print_msg_line(msg, prefix="- ")

    async def _stream_and_print(self, input_data: dict, config: dict) -> None:
        """统一处理 astream + token 打印 + 错误捕获.

        ⚠️ 过滤两类 noise:
        1. ToolMessage — 工具结果, 是数据不是给用户的文本 (LLM 会再复述一遍,
           提前打印会让用户看两遍同一信息)
        2. langgraph_supervisor 内部 routing AIMessage ("Transferring back
           to supervisor" / "Successfully transferred back to supervisor")
           是 framework 内部 chatter, 跟用户问题无关
        """
        try:
            async for token, _ in self.graph.astream(
                input_data, config=config, stream_mode="messages"
            ):
                # 跳过 ToolMessage (工具结果)
                if type(token).__name__ == "ToolMessage":
                    continue
                # 跳过 supervisor 内部 routing chatter
                if isinstance(token.content, str):
                    if any(token.content.startswith(prefix) for prefix in _SUPERVISOR_NOISE):
                        continue
                if token.content:
                    print(token.content, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}")

    async def _continue_turn(self, config: dict) -> None:
        """fork 后在新 thread 上继续 invoke (流式)."""
        await self._stream_and_print({}, config)

    def _cmd_memory_show(self) -> None:
        prefs = get_prefs(self.store, self.store_ns)
        print("\n>>> 长期偏好:")
        for k, v in prefs.items():
            print(f"  {k}: {v}")
        print(f"  (namespace: {self.store_ns})")

    def _cmd_mysql(self) -> None:
        """探测 MySQL 连接 + 列出表结构 (绕过 LLM, 调试用).

        不走 DataAgent / LLM, 直接调 mysql_db 给运维视角的快照:
          - 失败 → 友好提示怎么修
          - 成功 → 列出表 + 每张表的列结构
        """
        try:
            from mysql_db import build_engine, get_schema_summary
            engine = build_engine()
            tables, describe = get_schema_summary(engine)
        except RuntimeError as e:
            print(f"\n[error] MySQL 未配置: {e}")
            print("  在 .env 设置 MYSQL_HOST / MYSQL_PORT / MYSQL_USER / "
                  "MYSQL_PASSWORD / MYSQL_DATABASE")
            return
        except Exception as e:
            print(f"\n[error] MySQL 连接失败: {type(e).__name__}: {e}")
            return

        if not tables:
            print("\n>>> MySQL 连接成功, 但没有表")
            return

        print(f"\n>>> MySQL 连接成功, 共有 {len(tables)} 张表:")
        for t in tables:
            print(f"\n  [{t}]")
            # describe dict 里 value 是多行字符串, 缩进再加一层
            for line in describe.get(t, "").splitlines():
                print(f"    {line}")

    def _cmd_memory_set(self, key: str, value: str) -> None:
        try:
            set_pref(self.store, self.store_ns, key, value)
            print(f">>> 偏好已更新: {key} = {value}")
        except ValueError as e:
            print(f"[error] {e}")

    # --------------------------------------------------------
    # 普通对话 - 流式 + HITL
    # --------------------------------------------------------
    async def run_turn(self, text: str) -> None:
        print()  # 换行
        # ⭐ 计时 — 包裹整个 _stream_and_print (含 astream 流式输出 + 错误捕获)
        t0 = time.perf_counter()
        await self._stream_and_print(
            {"messages": [HumanMessage(content=text)]},
            self.config,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        # 检查是否需要 HITL 审批
        await self._maybe_hitl()

        # ⚠️ rewind 是一次性的: 跑完一个 turn 就清掉, 不然会一直 time-travel
        # 在那个分支上, 后续 /history 也只会看到 rewound 之后的子集.
        self._rewind_ckpt = None

        # ⭐ Observability: 提取并打印 per-turn 指标
        # try/except 包住: metrics 失败不阻塞 REPL (用户继续能对话)
        try:
            state = self.graph.get_state(self.config)
            in_tok, out_tok = extract_tokens(state.values)
            specialist = detect_specialist(state.values)
            tools = count_tool_calls(state.values)
            cost = estimate_cost(self._model_name, in_tok, out_tok)
            tm = TurnMetrics(
                latency_ms=elapsed_ms,
                input_tokens=in_tok,
                output_tokens=out_tok,
                tool_calls=tools,
                specialist=specialist,
                cost_usd=cost,
            )
            self.metrics.record(tm)
            print(self.metrics.format_turn(tm))
        except Exception as e:
            # metrics 失败不阻塞 REPL — 仅打印一行 warning
            print(f">>> [metrics error] {type(e).__name__}: {e}")

    async def _maybe_hitl(self, interrupts: list | None = None) -> None:
        """如果 graph 在 interrupt 状态, 走 HITL 流程.

        interrupts: 生产为 None, 内部从 state 拿 (state.tasks[0].interrupts);
        测试可直接传 Interrupt-like mock 列表, 跳过 state fetch.

        分发:
          0 个 → return
          1 个 → _handle_single_interrupt (现有 UX 保留)
          N 个 → _handle_batch_interrupts (批量预览 + 单决策 prompt)
        """
        # 生产路径: 从 state 拿 interrupts
        if interrupts is None:
            state = self.graph.get_state(self.config)
            if not state.next:
                return  # 正常结束, 不需要审批
            if not (state.tasks and state.tasks[0].interrupts):
                print(f"\n>>> 暂停在 {state.next}, 但无 interrupt 内容, 跳过 HITL")
                return
            interrupts = list(state.tasks[0].interrupts)
        if not interrupts:
            return
        if len(interrupts) == 1:
            await self._handle_single_interrupt(interrupts[0])
        else:
            await self._handle_batch_interrupts(interrupts)

    async def _handle_single_interrupt(self, intr) -> None:
        """单 interrupt 流程 — 现有 UX 保留, 不变.

        prompt 风格保持 `[a]pprove / [r]eject` 不变 (向后兼容).
        """
        state = self.graph.get_state(self.config)
        intr_value = intr.value if hasattr(intr, "value") else intr
        print(f"\n\n[!]  HITL 中断 (节点 {state.next}):")
        # intr 是 dict, 包含 tool_call / reason
        if isinstance(intr_value, dict):
            for k, v in intr_value.items():
                print(f"  {k}: {v}")
            # ⭐ 工具调用预览 — 在决策前显示"将要发生什么"
            # LangGraph HITL 中断的 intr dict 通常含 "tool_calls" list,
            # 每项 {name, args, id}. 我们按 name 路由到对应 preview.
            tool_calls = intr_value.get("tool_calls", []) if isinstance(intr_value, dict) else []
            if tool_calls:
                print()
                for tc in tool_calls:
                    tname = tc.get("name", "?")
                    targs = tc.get("args", {})
                    print(f"  [{tname}] 预览:")
                    for line in _format_hitl_preview(tname, targs):
                        print(line)
                    print()
        else:
            print(f"  {intr_value}")

        # 读决策 — 只暴露 approve / reject 给用户.
        # LangGraph 协议层仍允许 ["approve","edit","reject"] 三种 type, 但 CLI 不提供 edit:
        # 实战中 [e]dit 经常被误按成 approve, UX 上直接砍掉.
        try:
            decision_raw = input("\n决策 [a]pprove / [r]eject: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return

        if decision_raw.startswith("a"):
            decision = {"decisions": [{"type": "approve"}]}
        elif decision_raw.startswith("r"):
            reason = input("拒绝原因: ").strip()
            decision = {"decisions": [{"type": "reject", "reason": reason}]}
        else:
            print(f"未知决策 {decision_raw!r}, 默认 reject")
            decision = {"decisions": [{"type": "reject", "reason": "未知决策"}]}

        # resume - 走同一份 _stream_and_print 辅助
        await self._stream_and_print(Command(resume=decision), self.config)

    async def _handle_batch_interrupts(self, interrupts: list) -> None:
        """批量 interrupt 流程 — N 个工具调用一次预览, 一个决策 prompt.

        ⚠️ HITL middleware 单 interrupt 内 N action_requests 的场景: 实际触发
        batch 时, interrupts 列表里通常是 1 个 Interrupt (HITL middleware 的
        after_model 只调一次 interrupt()). 单 Interrupt 内 action_requests 的
        多个工具调用 → 走单 interrupt 路径内的 _format_hitl_preview 逐个打印.
        跨 interrupt 多次触发 (e.g. 不同 specialist 同时调用) 才进 batch 路径.

        UX:
          >>> HITL 批量审批 — 共 3 个工具调用:
            --- #1/3 ---
            [write_note] 预览: ...
            --- #2/3 ---
            [refund_order] 预览: ...
            --- #3/3 ---
            [run_sql] 预览: ...

          决策: [A]pprove all / [R]eject all / [S]elective (per-tool)? a
        """
        n = len(interrupts)
        print(f"\n\n[!]  HITL 批量审批 — 共 {n} 个工具调用:")
        # 1. 打印每个 interrupt 的预览 (header 标 #i/n 视觉对齐)
        for i, intr in enumerate(interrupts, 1):
            print(f"\n--- #{i}/{n} ---")
            self._print_interrupt_preview(intr)

        # 2. 读单决策 prompt
        raw_input, eof = self._read_batch_decision()

        # 3. 解析为 decisions list (按 interrupt 顺序对齐)
        decisions = self._resolve_batch(raw_input, interrupts, eof=eof)

        # 4. Resume graph (走同一份 _stream_and_print 辅助)
        await self._stream_and_print(
            Command(resume={"decisions": decisions}),
            self.config,
        )

    def _print_interrupt_preview(self, intr) -> None:
        """打印单个 interrupt 的预览 — 支持 HITL middleware action_requests + 普通 tool_calls.

        优先级:
          1. value.action_requests (HITL middleware 1.0 格式, list)
          2. value.tool_calls (自定义 interrupt() 老格式, list)
          3. value.name + value.args (单工具 dict 格式)
          4. fallback: 打印 raw value
        """
        value = intr.value if hasattr(intr, "value") else intr
        if not isinstance(value, dict):
            print(f"  (无预览: {value})")
            return
        # 1. HITL middleware: action_requests
        action_requests = value.get("action_requests")
        if action_requests:
            for j, action in enumerate(action_requests, 1):
                name = action.get("name", "?")
                args = action.get("args", {})
                if len(action_requests) > 1:
                    print(f"  [{j}/{len(action_requests)}] [{name}] 预览:")
                else:
                    print(f"  [{name}] 预览:")
                for line in _format_hitl_preview(name, args):
                    print(line)
                if j < len(action_requests):
                    print()
            return
        # 2. 老格式: tool_calls
        tool_calls = value.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                tname = tc.get("name", "?")
                targs = tc.get("args", {})
                print(f"  [{tname}] 预览:")
                for line in _format_hitl_preview(tname, targs):
                    print(line)
                print()
            return
        # 3. 单工具 dict 格式
        if "name" in value:
            name = value["name"]
            args = value.get("args", {})
            print(f"  [{name}] 预览:")
            for line in _format_hitl_preview(name, args):
                print(line)
            return
        # 4. fallback
        print(f"  (无预览: {value})")

    def _read_batch_decision(self) -> tuple[str, bool]:
        """读 batch 主 prompt. Returns (raw_input, eof_flag).

        EOF / Ctrl-C → eof=True (防御性: 默认 reject all).
        """
        try:
            raw = input(
                "\n决策 [A]pprove all / [R]eject all / [S]elective (per-tool): "
            ).strip().lower()
            return (raw, False)
        except (EOFError, KeyboardInterrupt):
            return ("", True)

    def _resolve_batch(
        self, raw: str, interrupts: list, eof: bool = False
    ) -> list[str]:
        """解析 batch 决策 → list[str] (按 interrupt 顺序对齐).

        行为:
          EOF                → ["reject"] * n     (defensive)
          "" / "a" / "approve" → ["approve"] * n   (默认 approve)
          "r" / "reject"     → ["reject"] * n
          "s" / "selective"  → _read_selective_decisions (per-tool sub-prompt)
          其它 (e.g. "x")    → ["reject"] * n     (default safety)

        ⚠️ 顺序必须严格按 `interrupts` 顺序追加 — middleware 按顺序消费
        decisions list, 错位会错 approve. _read_selective_decisions 同样按
        interrupts 顺序迭代, 不打乱.
        """
        n = len(interrupts)
        if eof:
            print("EOF, 默认 reject all (防御性 — 不留未决决策)")
            return ["reject"] * n
        if not raw or raw == "a" or raw == "approve":
            return ["approve"] * n
        if raw == "r" or raw == "reject":
            return ["reject"] * n
        if raw == "s" or raw == "selective":
            return self._read_selective_decisions(interrupts)
        # 无效输入 → 默认 reject all (defensive)
        print(f"无效输入 {raw!r}, 默认 reject all")
        return ["reject"] * n

    def _read_selective_decisions(self, interrupts: list) -> list[str]:
        """Per-tool sub-prompt — 简单格式 `#N tool_name [a/r]:`.

        ⚠️ Selective 模式不可逆: 一旦 approve 一个工具, 不能撤回. 中途 EOF
        → 剩余全部 reject (defensive, 不留未决决策).
        """
        decisions: list[str] = []
        n = len(interrupts)
        for i, intr in enumerate(interrupts, 1):
            name = self._extract_tool_name_from_interrupt(intr)
            try:
                raw = input(f"  #{i} {name} [a/r]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                # EOF / Ctrl-C 中途 → 剩余全部 reject (defensive)
                print(
                    f"\n  EOF, #{i}-{n} 自动 reject (防御性 — 不留未决决策)"
                )
                decisions.extend(["reject"] * (n - i + 1))
                return decisions
            if not raw or raw.startswith("a"):
                decisions.append("approve")
            else:
                decisions.append("reject")
        return decisions

    def _extract_tool_name_from_interrupt(self, intr) -> str:
        """从 interrupt 提取工具名 (用于 selective mode 显示).

        优先级同 _print_interrupt_preview:
          action_requests > tool_calls > name
        """
        value = intr.value if hasattr(intr, "value") else intr
        if isinstance(value, dict):
            action_requests = value.get("action_requests")
            if action_requests:
                names = [a.get("name", "?") for a in action_requests]
                return ",".join(names) if len(names) > 1 else names[0]
            tool_calls = value.get("tool_calls")
            if tool_calls:
                names = [tc.get("name", "?") for tc in tool_calls]
                return ",".join(names) if len(names) > 1 else names[0]
            if "name" in value:
                return str(value["name"])
        return "?"


# WELCOME / HELP_TEXT 不是 CLI 的 API, 但保留在 __all__ 方便单元测试 import 断言内容.
__all__ = ["CLI", "WELCOME", "HELP_TEXT"]