"""cli.py — REPL 主循环 + 命令路由 + streaming token 打印 + HITL 审批.

REPL 流程:
  1. read() 读一行 stdin
  2. 以 "/" 开头 → handle_command() (内置命令)
  3. 普通文本   → run_turn() 异步流式调 supervisor
  4. run_turn 内部: astream(stream_mode="messages") + 逐字 print
  5. 检测到 state.next 非空 + 有 interrupt → handle_hitl()
  6. 用户输入 a/e/r → Command(resume=...) 恢复

命令:
  /history   列出 checkpoints
  /rewind N  回到第 N 个 checkpoint (不重跑 LLM)
  /fork TXT  在新 thread 续走, 注入 TXT 作为新的人类消息
  /memory    查看/编辑长期偏好
  /help      帮助
  /quit      退出
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


# ============================================================
# 欢迎语 + 帮助
# ============================================================
WELCOME = """
╭─────────────────────────────────────────────╮
│  智能个人助手 CLI  (08-cli-assistant)       │
│                                             │
│  输入问题 → streaming token 流式输出        │
│  危险操作 (退款/写笔记) → 自动暂停审批      │
│                                             │
│  内置命令:                                  │
│    /history   列出 checkpoints               │
│    /rewind N  回到第 N 个 checkpoint         │
│    /fork TXT  改历史后在新 thread 续走      │
│    /memory    查看/编辑长期偏好              │
│    /help      帮助                           │
│    /quit      退出                           │
╰─────────────────────────────────────────────╯
"""


HELP_TEXT = """
命令:
  /history           列出本 thread 所有 checkpoint (index 0=最新)
  /rewind N          回到 history[N] 的状态 (N 是 history 列表索引, 0=最新)
  /fork <text>       在最新 checkpoint 上追加 <text>, 新 thread 续走
  /memory            查看偏好
  /memory <key> <v>  设置偏好 (nickname / city / language / user_*)
  /help              本帮助
  /quit              退出

正常对话:
  - "北京天气?"     → 派 WeatherAgent
  - "123 * 456"     → 派 CalcAgent
  - "查订单 #123"    → 派 OrdersAgent
  - "退款 #123 100"  → OrdersAgent 触发 HITL (输入 a/e/r 决策)
  - "写笔记 todo ..." → NotesAgent 触发 HITL
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

        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, input, "你> ")
            except (EOFError, KeyboardInterrupt):
                print("\n再见")
                return

            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                should_exit = self.handle_command(line)
                if should_exit:
                    return
                continue

            # 普通对话
            await self.run_turn(line)

    # --------------------------------------------------------
    # 内置命令
    # --------------------------------------------------------
    def handle_command(self, line: str) -> bool:
        """处理 / 命令. 返回 True = 退出 REPL."""
        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "/quit" or cmd == "/exit":
            print("再见")
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
            if len(parts) < 2:
                print("用法: /fork <text>")
                return False
            self._cmd_fork(parts[1])
            return False

        if cmd == "/memory":
            if len(parts) == 1:
                self._cmd_memory_show()
            elif len(parts) >= 3:
                self._cmd_memory_set(parts[1], parts[2])
            else:
                print("用法: /memory [key value]")
            return False

        print(f"未知命令: {cmd}. 输入 /help 查看.")
        return False

    def _cmd_history(self) -> None:
        history = list(self.graph.get_state_history(self.config))
        print(f"\n>>> 共 {len(history)} 个 checkpoint (history[0]=最新):")
        for i, snap in enumerate(history):
            ckpt_short = snap.config["configurable"]["checkpoint_id"][:8]
            n_msgs = len(snap.values.get("messages", []))
            next_node = snap.next
            print(f"  [{i:>3}] ckpt={ckpt_short}... | msgs={n_msgs} | next={next_node}")

    def _cmd_rewind(self, n: int) -> None:
        history = list(self.graph.get_state_history(self.config))
        if n < 0 or n >= len(history):
            print(f"索引 {n} 越界, 范围 [0, {len(history)-1}]")
            return
        snap = history[n]
        ckpt = snap.config["configurable"]["checkpoint_id"]
        # 把 checkpoint_id 注入 config - 下次 astream 从 history[n] 这个
        # checkpoint 重新走 (LangGraph 1.x time-travel replay 语义).
        self._rewind_ckpt = ckpt
        print(
            f">>> 回到 history[{n}] (ckpt={ckpt[:8]}..., "
            f"{len(snap.values.get('messages', []))} 条消息). "
            f"下次输入会以该 checkpoint 为起点."
        )

    def _cmd_fork(self, text: str) -> None:
        """在最新 checkpoint 上追加 text, 用 update_state 创建新 thread."""
        history = list(self.graph.get_state_history(self.config))
        if not history:
            print(">>> 无历史, 无法 fork. 先跟助手对话几轮.")
            return
        new_config = self.graph.update_state(
            history[0].config,
            {"messages": [HumanMessage(content=text)]},
        )
        new_thread = new_config["configurable"]["thread_id"]
        print(f">>> Fork 到新 thread: {new_thread}")
        print(f">>> 续走中...")
        # 在 sync handle_command 里调 async - 用 asyncio.run 起新 loop
        # (这里没问题, handle_command 不是 async, 不会被嵌套)
        asyncio.run(self._continue_turn(new_config))

    async def _continue_turn(self, config: dict) -> None:
        """fork 后在新 thread 上继续 invoke (流式)."""
        try:
            async for token, _ in self.graph.astream(
                {}, config=config, stream_mode="messages"
            ):
                if hasattr(token, "content") and token.content:
                    print(token.content, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}")

    def _cmd_memory_show(self) -> None:
        prefs = get_prefs(self.store, self.store_ns)
        print("\n>>> 长期偏好:")
        for k, v in prefs.items():
            print(f"  {k}: {v}")
        print(f"  (namespace: {self.store_ns})")

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
        try:
            async for token, _ in self.graph.astream(
                {"messages": [HumanMessage(content=text)]},
                config=self.config,
                stream_mode="messages",
            ):
                if hasattr(token, "content") and token.content:
                    print(token.content, end="", flush=True)
            print()
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"\n[error] {err}")
            return

        # 检查是否需要 HITL 审批
        await self._maybe_hitl()

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

        # 读决策
        try:
            decision_raw = input("\n决策 [a]pprove / [e]dit / [r]eject: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return

        if decision_raw.startswith("a"):
            decision = {"decisions": [{"type": "approve"}]}
        elif decision_raw.startswith("e"):
            # 简化: edit 用原参数 (实战应让用户改具体字段)
            print(">>> edit: 当前实现保留原参数, 实战可让用户改 amount 等")
            decision = {"decisions": [{"type": "approve"}]}
        elif decision_raw.startswith("r"):
            reason = input("拒绝原因: ").strip()
            decision = {"decisions": [{"type": "reject", "reason": reason}]}
        else:
            print(f"未知决策 {decision_raw!r}, 默认 reject")
            decision = {"decisions": [{"type": "reject", "reason": "未知决策"}]}

        # resume
        try:
            async for token, _ in self.graph.astream(
                Command(resume=decision),
                config=self.config,
                stream_mode="messages",
            ):
                if hasattr(token, "content") and token.content:
                    print(token.content, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[error after HITL] {type(e).__name__}: {e}")


__all__ = ["CLI", "WELCOME", "HELP_TEXT"]