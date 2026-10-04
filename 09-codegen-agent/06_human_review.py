"""06_human_review.py — Demo 6: Codegen pipeline with HITL pause points.

3 HITL gates (每个写盘操作前暂停等人批):
  1. tool_write_plan        — LLM 生成 plan 后
  2. tool_write_code_file   — 每个 code 文件写入前 (N 个文件 = N 次暂停)
  3. tool_apply_fix         — review loop 失败后, 修正前

复用模式 (跟 08-cli-assistant 一致):
  - HumanInTheLoopMiddleware (L1 native, LangChain 1.x)
  - _hitl() 工厂避免多个 agent 共享 singleton 导致 state_schema 冲突
  - hitl_input() async stdin (to_thread 不阻塞事件循环)
  - [a]pprove / [e]dit / [r]eject 三选一 UX
  - edit 模式: key=value 交互式改 args
  - EOF / Ctrl-C → reject (defensive, 防止 stuck)

学完这个 demo 你能回答:
1.  怎么把 HumanInTheLoopMiddleware 挂到 codegen agent 上?
2.  为什么 _hitl() 要写成工厂函数而不是模块级单例?
3.  怎么从 interrupt value 里抽 tool_call 的 name + args?
4.  approve / edit / reject 三种决策怎么 resume graph?
5.  codegen pipeline 哪几步要 HITL, 哪几步可以自动化?
6.  HITL UX 的 edit 模式怎么实现 key=value 参数编辑?
7.  LangGraph state.tasks[0].interrupts 怎么读 (跟 result.__interrupt__ 不同)?

跑法:
    python 06_human_review.py

⚠️ 跑前需要 LLM API key (跟 01-05 一致, 见 _common.get_llm).

💡 跟 Demo 5 的关键区别:
  - Demo 5: supervisor 状态机自动跑完, 无人介入
  - Demo 6: 3 个写盘动作 (plan / code / fix) 全有人工 gate, 防止 LLM hallucination
  - 真实生产建议: Demo 6 只开 gate 1 (plan) + gate 3 (fix), gate 2 太繁琐
"""
from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from _common import (
    banner,
    get_example_spec,
    get_llm,
    output_dir,
    step,
    write_code_file,
)
from codegen_pipeline import code_to_test, file_to_code, fix_code
from plan_schema import Plan, spec_to_plan


# ============================================================
# HITL input loop — async stdin (复用 08-cli-assistant UX)
# ============================================================
async def hitl_input(prompt: str) -> str:
    """CLI 输入 HITL 决策: a / e / r.

    - to_thread: 不阻塞 event loop (其它 agent tick 还能跑)
    - EOF / Ctrl-C → "r" (defensive, 默认 reject, 防止 graph stuck)
    """
    print(prompt, end="", flush=True)
    try:
        line = await asyncio.to_thread(input)
        return line.strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "r"


def _coerce_value(v: str, target_type: type) -> Any:
    """按 target_type 把 string coerce 成 int/float/bool/str.

    失败 fallback str (避免破坏 tool signature).
    """
    if target_type is bool:
        return v.lower() in ("true", "1", "yes")
    if target_type is int:
        return int(v)
    if target_type is float:
        return float(v)
    return v


# ============================================================
# Pipeline tools — 5 个, 3 个触发 HITL
# ============================================================
@tool
def tool_write_plan(spec: str) -> str:
    """HITL gate 1: spec → LLM 生成 plan → 写 output/plan.json.

    返回 plan.model_dump_json() 给后续 tool_write_code_file 用.
    """
    llm = get_llm(temperature=0.0)
    plan = spec_to_plan(llm, spec)
    (output_dir() / "plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"  [HITL gate 1] 生成 plan ({len(plan.files)} 个文件)")
    return plan.model_dump_json()


@tool
def tool_write_code_file(plan_json: str, file_index: int) -> str:
    """HITL gate 2: plan + file_index → LLM 生成 code → 写 output/<path>.

    一次只写一个文件. 多文件时 agent 调多次, 每次都触发 HITL.
    """
    llm = get_llm(temperature=0.0)
    plan = Plan.model_validate_json(plan_json)
    if file_index < 0 or file_index >= len(plan.files):
        return f"ERROR: file_index 越界 (有效范围 0..{len(plan.files) - 1})"
    file_spec = plan.files[file_index]
    code = file_to_code(llm, file_spec)
    p = write_code_file(file_spec.path, code)
    print(f"  [HITL gate 2] 写 {p.name} ({len(code)} 字符)")
    # 打印前 6 行预览 (让人工审批时看内容)
    preview = "\n".join(code.split("\n")[:6])
    print(f"  预览:\n{preview}\n  ...")
    return f"写入 {p.name} ({len(code)} 字符)"


@tool
def tool_write_test_file(code_filename: str) -> str:
    """auto (无 HITL): 给 code 文件生成对应 pytest 测试.

    测试代码是辅助, LLM 妥协测试的风险低 (人审 plan + 审 fix 时能看到 test).
    """
    llm = get_llm(temperature=0.0)
    code_path = output_dir() / code_filename
    if not code_path.exists():
        return f"ERROR: {code_filename} 不存在 (先调 tool_write_code_file)"
    test_code = code_to_test(llm, code_path)
    test_filename = f"test_{code_path.stem}.py"
    write_code_file(test_filename, test_code)
    print(f"  [auto] 写 {test_filename} ({len(test_code)} 字符)")
    return f"写入 {test_filename} ({len(test_code)} 字符)"


@tool
def tool_run_pytest(test_filename: str) -> str:
    """auto (无 HITL): 跑 pytest, 返回 stdout + stderr 摘要.

    失败时返回的 stdout/stderr 直接喂给 tool_apply_fix.
    """
    code_dir = output_dir()
    test_path = code_dir / test_filename
    if not test_path.exists():
        return f"FAIL: {test_filename} 不存在"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-v", "--tb=short"],
            cwd=code_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        snippet = (result.stdout + "\n" + result.stderr).strip()[-1000:]
        return f"returncode={result.returncode}\n{snippet}"
    except subprocess.TimeoutExpired:
        return "FAIL: pytest timeout (>30s)"
    except Exception as e:
        return f"FAIL: {type(e).__name__}: {e}"


@tool
def tool_apply_fix(code_filename: str, pytest_output: str) -> str:
    """HITL gate 3: pytest 失败 → LLM 修正代码 → 写回 output/.

    只修 main code 不修 test code (跟 demo 4 一致, 避免 LLM 妥协测试).
    """
    llm = get_llm(temperature=0.0)
    code_path = output_dir() / code_filename
    if not code_path.exists():
        return f"ERROR: {code_filename} 不存在"
    code = code_path.read_text(encoding="utf-8")
    fixed = fix_code(llm, code, pytest_output)
    p = write_code_file(code_filename, fixed)
    delta = len(fixed) - len(code)
    sign = "+" if delta >= 0 else ""
    print(f"  [HITL gate 3] 修正 {p.name} ({len(fixed)} 字符, {sign}{delta})")
    return f"修正 {p.name} ({len(fixed)} 字符)"


# ============================================================
# HITL middleware factory — 避免 singleton state_schema 冲突
# ============================================================
# ⚠️ 跟 08-cli-assistant/agent.py 同款坑:
#   HumanInTheLoopMiddleware 注入额外 state keys. 多个 agent 共享同一实例
#   会冲突. 所以用工厂函数, 每次 create_agent 调一次拿新实例.
def _hitl() -> HumanInTheLoopMiddleware:
    """HITL 中间件工厂 — 每次 create_agent 调一次."""
    return HumanInTheLoopMiddleware(
        interrupt_on={
            "tool_write_plan": {"allowed_decisions": ["approve", "edit", "reject"]},
            "tool_write_code_file": {"allowed_decisions": ["approve", "edit", "reject"]},
            "tool_apply_fix": {"allowed_decisions": ["approve", "edit", "reject"]},
        }
    )


# ============================================================
# Interrupt 解码 — 抽 tool_name + args
# ============================================================
def _extract_tool_info_from_interrupt(intr: Any) -> tuple[str, dict]:
    """从 LangGraph 1.x interrupt value 抽 tool_name + args.

    LangChain 1.x HumanInTheLoopMiddleware 格式:
        intr.value.action_requests[0] = {"name": ..., "args": ..., "description": ...}
    老 interrupt() 格式:
        intr.value.tool_calls[0] = {"name": ..., "args": ..., "id": ...}
    """
    value = intr.value if hasattr(intr, "value") else intr
    if not isinstance(value, dict):
        return "?", {}
    # HITL middleware 1.0 格式
    action_requests = value.get("action_requests")
    if action_requests:
        ar = action_requests[0]
        return ar.get("name", "?"), dict(ar.get("args", {}))
    # 老 interrupt() 格式
    tool_calls = value.get("tool_calls")
    if tool_calls:
        tc = tool_calls[0]
        return tc.get("name", "?"), dict(tc.get("args", {}))
    return "?", {}


def _format_preview(tool_name: str, args: dict) -> list[str]:
    """工具调用影响预览 (3-5 行) — 让审批时看到关键信息."""
    lines = [f"  工具: {tool_name}"]
    if tool_name == "tool_write_plan":
        spec_preview = (args.get("spec") or "")[:200]
        lines.append(f"  spec 预览 (前 200): {spec_preview}...")
    elif tool_name == "tool_write_code_file":
        idx = args.get("file_index", "?")
        plan_json = args.get("plan_json", "{}")
        try:
            plan = Plan.model_validate_json(plan_json)
            if isinstance(idx, int) and 0 <= idx < len(plan.files):
                lines.append(f"  file_index: {idx} → {plan.files[idx].path}")
                lines.append(f"  purpose: {plan.files[idx].purpose}")
            else:
                lines.append(f"  file_index: {idx} (越界!)")
        except Exception:
            lines.append(f"  file_index: {idx} (plan_json 解析失败)")
    elif tool_name == "tool_apply_fix":
        lines.append(f"  code_filename: {args.get('code_filename', '?')}")
        err_preview = (args.get("pytest_output") or "")[:200]
        lines.append(f"  pytest error (前 200): {err_preview}...")
    else:
        for k, v in args.items():
            v_str = repr(v)
            if len(v_str) > 100:
                v_str = v_str[:100] + f"... <共 {len(v_str)} 字符>"
            lines.append(f"  {k}: {v_str}")
    return lines


# ============================================================
# Edit mode — 交互式改 args (key=value)
# ============================================================
async def _prompt_edit_args(tool_name: str, current: dict) -> dict | None:
    """交互式编辑 HITL 参数.

    Returns:
        new dict — 走 edit decision
        None    — 用户取消, caller 转 reject

    UX (跟 08-cli-assistant 一致):
        --- 当前参数 (tool: tool_write_code_file) ---
          file_index: 0
          plan_json: '{"summary": "..."}'  <共 800 字符, 截断>

        输入新参数 (key=value 空格分隔, 空提交 = 不修改, Ctrl-C 取消):
        > file_index=1
    """
    print(f"\n--- 当前参数 (tool: {tool_name}) ---")
    if not current:
        print("  (无参数)")
    else:
        for k, v in current.items():
            v_str = repr(v)
            if len(v_str) > 100:
                v_str = f"<共 {len(v_str)} 字符, 截断>"
            print(f"  {k}: {v_str}")
    print()
    print("输入新参数 (key=value 空格分隔, 空提交 = 不修改, Ctrl-C 取消):")
    try:
        line = (await asyncio.to_thread(input)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not line:
        return dict(current)  # 无修改 — caller 后续转 approve
    try:
        tokens = shlex.split(line)
    except ValueError as e:
        print(f">>> 解析失败: {e}, 保持原参数")
        return dict(current)
    new = dict(current)
    for tok in tokens:
        if "=" not in tok:
            print(f">>> 跳过非 key=value token: {tok!r}")
            continue
        k, _, v = tok.partition("=")
        k = k.strip()
        if k not in current:
            # 防 typo — 增新 key 会破坏 tool signature, 让 LLM 重发更稳
            print(f">>> 警告: key {k!r} 不在当前参数里, 跳过")
            continue
        try:
            new[k] = _coerce_value(v, type(current[k]))
        except (ValueError, TypeError):
            new[k] = v
    return new


# ============================================================
# HITL handler — 单 interrupt 处理
# ============================================================
async def handle_hitl(agent, config: dict, intr: Any) -> None:
    """处理一个 interrupt: a / e / r 三选一.

    approve → 通过, agent 收到 ToolMessage (正常结果)
    edit    → 改 args, 仍走 approve 路径但用新 args
    reject  → 拒绝, agent 收到 ToolMessage(error), 通常 LLM 会停止或换路
    """
    state = agent.get_state(config)
    tool_name, current_args = _extract_tool_info_from_interrupt(intr)

    print(f"\n\n[!] HITL 中断 (节点 {state.next})")
    print()
    for line in _format_preview(tool_name, current_args):
        print(line)

    decision_raw = await hitl_input(
        "\n决策 [a]pprove / [e]dit / [r]eject (默认 a): "
    )

    if decision_raw.startswith("e"):
        new_args = await _prompt_edit_args(tool_name, current_args)
        if new_args is None:
            print(">>> edit 取消, 转 reject")
            decision = {"decisions": [{"type": "reject", "reason": "edit 取消"}]}
        else:
            # LangGraph 1.x EditDecision 协议
            decision = {
                "decisions": [{
                    "type": "edit",
                    "edited_action": {"name": tool_name, "args": new_args},
                }]
            }
    elif decision_raw.startswith("r"):
        print(">>> reject")
        decision = {"decisions": [{"type": "reject", "reason": "user reject"}]}
    else:
        # approve (默认 for "a" 或空提交)
        print(">>> approve")
        decision = {"decisions": [{"type": "approve"}]}

    # Resume — 用同一份 config (thread_id), graph 从中断点继续
    await agent.ainvoke(Command(resume=decision), config=config)


# ============================================================
# Main pipeline loop
# ============================================================
# MAX_ITERATIONS 防 LLM 死循环 (HITL approve 后 agent 又调同样 tool 又暂停,
# 理论上不会发生, 但兜底).
MAX_ITERATIONS = 20


async def run_codegen_with_hitl() -> None:
    """Codegen pipeline with 3 HITL gates."""
    llm = get_llm(temperature=0.0)
    checkpointer = InMemorySaver()

    agent = create_agent(
        model=llm,
        tools=[
            tool_write_plan,
            tool_write_code_file,
            tool_write_test_file,
            tool_run_pytest,
            tool_apply_fix,
        ],
        system_prompt=(
            "你是 codegen agent. 用户给 spec 后, 严格按顺序:\n"
            "  1. 调 tool_write_plan(spec) 拿到 plan JSON (HITL gate 1).\n"
            "  2. 对 plan.files 里每个文件, 按下标 0, 1, 2... 依次调 "
            "tool_write_code_file(plan_json, idx) (HITL gate 2 per file).\n"
            "  3. 每个 code 文件写完后, 调 tool_write_test_file(filename) 自动生成 test.\n"
            "  4. 调 tool_run_pytest('test_<filename>.py') 看 pass/fail.\n"
            "  5. 失败 → 调 tool_apply_fix(filename, pytest_output) 修正 (HITL gate 3).\n"
            "  6. 修正后再跑 pytest. 仍失败? 再调 tool_apply_fix (最多 2 次).\n"
            "  7. 全 pass → 用中文一句话告诉用户 '完成' + 列出文件.\n"
            "工具内部已经处理了所有 LLM 生成 + 文件写入, 你只负责决策下一步调什么."
        ),
        middleware=[_hitl()],
        checkpointer=checkpointer,
    )

    config = {"configurable": {"thread_id": "hitl-codegen-demo"}}
    spec = get_example_spec()

    step(1, f"启动 codegen agent, spec ({len(spec)} 字符)")
    print(f"  spec 预览: {spec[:80]}...")

    # 主循环: invoke → 检测 interrupt → 处理 → 再次 invoke
    for i in range(1, MAX_ITERATIONS + 1):
        step(f"turn {i}", f"invoke agent (第 {i} 次)")
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": f"生成代码: {spec}"}]},
                config=config,
            )
        except Exception as e:
            print(f"  invoke 异常: {type(e).__name__}: {str(e)[:200]}")
            break

        # 检查 interrupt — state.tasks[0].interrupts 是 LangGraph 1.x 唯一可靠入口
        # (不要信 result.get('__interrupt__'), 跨版本不稳定)
        state = agent.get_state(config)
        if state.next and state.tasks and state.tasks[0].interrupts:
            interrupts = list(state.tasks[0].interrupts)
            for intr in interrupts:
                await handle_hitl(agent, config, intr)
            continue  # 处理完 interrupt 继续下一轮

        # 没有 interrupt → 看是否结束
        if not state.next:
            print("  >>> 流程结束 (无 next 节点)")
            break

        # state.next 非空但无 interrupt → 内部节点切换, 继续
        print(f"  >>> 节点切换至 {state.next}, 继续下一轮")

    # 总结
    step("final", "完成 — 列出 output/ 下的文件")
    out = output_dir()
    if out.exists():
        for p in sorted(out.glob("*.py")):
            size = p.stat().st_size
            print(f"    - {p.name}  ({size} 字节)")


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 6: Codegen with HITL Gates (plan / code file / fix)")
    asyncio.run(run_codegen_with_hitl())


if __name__ == "__main__":
    main()
