"""cli.py — REPL 主循环 + 命令路由 + streaming token 打印 + HITL 审批.

REPL 流程:
  1. read() 读一行 stdin
  2. 以 "/" 开头 → await handle_command() (内置命令)
  3. 普通文本   → await run_turn() 异步流式调 supervisor
  4. run_turn 内部: astream(stream_mode="messages") + 逐字 print
  5. 检测到 state.next 非空 + 有 interrupt → handle_hitl()
  6. 用户输入 a/r → Command(resume=...) 恢复

命令:
  /history   列出 checkpoints
  /rewind N  回到第 N 个 checkpoint (不重跑 LLM)
  /fork TXT  在新 thread 续走, 注入 TXT 作为新的人类消息
  /memory    查看/编辑长期偏好
  /help      帮助
  /quit, /exit  退出
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from memory import get_prefs, set_pref

# Supervisor 内部 routing 消息 (langgraph_supervisor 内部 AIMessage, 不该显示给用户)
_SUPERVISOR_NOISE = (
    "Transferring back to supervisor",
    "Successfully transferred back to supervisor",
)


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
│    /history   列出 checkpoints               │
│    /rewind N  回到第 N 个 checkpoint         │
│    /fork TXT  改历史后在新 thread 续走      │
│    /memory    查看/编辑长期偏好              │
│    /mysql     探测 MySQL 连接 + 列表         │
│    /help      帮助                           │
│    /quit, /exit  退出                        │
╰─────────────────────────────────────────────╯
"""


HELP_TEXT = """
命令:
  /history           列出本 thread 所有 checkpoint (index 0=最新)
  /rewind N          回到 history[N] 的状态 (N 是 history 列表索引, 0=最新)
  /fork <text>       在最新 checkpoint 上追加 <text>, 新 thread 续走
  /memory            查看偏好
  /memory <key> <v>  设置偏好 (nickname / city / language / user_*)
  /mysql             探测 MySQL 连接 + 列出所有表 (含列结构)
  /help              本帮助
  /quit, /exit       退出

正常对话:
  - "北京天气?"     → 派 WeatherAgent
  - "123 * 456"     → 派 CalcAgent
  - "查订单 #123"    → 派 OrdersAgent
  - "退款 #123 100"  → OrdersAgent 触发 HITL (输入 a/r 决策)
  - "写笔记 todo ..." → NotesAgent 触发 HITL
  - "北京有几个用户"  → DataAgent (调 list_tables → describe_table → run_sql 触发 HITL)
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

        print(f"未知命令: {cmd}. 输入 /help 查看.")
        return False

    def _cmd_history(self) -> None:
        # ⚠️ 用干净的 config (不带 checkpoint_id) 才能拿到整条时间线;
        # 带 checkpoint_id 时 get_state_history 只返回该 ckpt 及之后, 看不到前面.
        history_cfg = {"configurable": {"thread_id": self.active_thread_id}}
        history = list(self.graph.get_state_history(history_cfg))
        print(f"\n>>> 共 {len(history)} 个 checkpoint (history[0]=最新):")
        for i, snap in enumerate(history):
            ckpt_short = snap.config["configurable"]["checkpoint_id"][:8]
            n_msgs = len(snap.values.get("messages", []))
            next_node = snap.next
            print(f"  [{i:>3}] ckpt={ckpt_short}... | msgs={n_msgs} | next={next_node}")

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
        await self._stream_and_print(
            {"messages": [HumanMessage(content=text)]},
            self.config,
        )

        # 检查是否需要 HITL 审批
        await self._maybe_hitl()

        # ⚠️ rewind 是一次性的: 跑完一个 turn 就清掉, 不然会一直 time-travel
        # 在那个分支上, 后续 /history 也只会看到 rewound 之后的子集.
        self._rewind_ckpt = None

    async def _maybe_hitl(self) -> None:
        """如果 graph 在 interrupt 状态, 走 HITL 流程."""
        state = self.graph.get_state(self.config)
        if not state.next:
            return  # 正常结束, 不需要审批

        # 拿 interrupt 内容 (state.tasks[0].interrupts[0].value)
        if not (state.tasks and state.tasks[0].interrupts):
            print(f"\n>>> 暂停在 {state.next}, 但无 interrupt 内容, 跳过 HITL")
            return

        intr = state.tasks[0].interrupts[0].value
        print(f"\n\n[!]  HITL 中断 (节点 {state.next}):")
        # intr 是 dict, 包含 tool_call / reason
        if isinstance(intr, dict):
            for k, v in intr.items():
                print(f"  {k}: {v}")
        else:
            print(f"  {intr}")

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


# WELCOME / HELP_TEXT 不是 CLI 的 API, 但保留在 __all__ 方便单元测试 import 断言内容.
__all__ = ["CLI", "WELCOME", "HELP_TEXT"]