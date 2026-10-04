"""05_multi_agent_coder.py — Demo 5: 完整 codegen pipeline 用 supervisor.

3 个 specialist: Planner (spec → plan) / Coder (plan → code) / Reviewer (test + fix loop).
Supervisor 编排: 根据当前 phase 调对应 specialist.

💡 设计要点:
  - 复用 plan_schema / codegen_pipeline (DRY)
  - supervisor 不用 middleware (跟 L1 一致)
  - 每个 specialist 只负责自己的 phase, 不跨
  - 状态机显式: planning → coding → testing → reviewing → done

学完这个 demo 你能回答:
1.  怎么用 StateGraph 编排多 Agent pipeline?
2.  怎么给 specialist agent 暴露 tool (@tool 装饰器)?
3.  supervisor 的路由函数怎么根据 phase 决定下一个 node?
4.  review 失败 → 回到 coding node 怎么实现 retry loop?
5.  CoderState TypedDict 的字段设计原则 (phase / retry_count / last_error)?

跑法:
    python 05_multi_agent_coder.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from _common import (
    banner,
    get_example_spec,
    get_llm,
    output_dir,
    step,
    write_code_file,
)
from codegen_pipeline import code_to_test, plan_to_code
from plan_schema import spec_to_plan


# ============================================================
# State — 显式状态机字段
# ============================================================
class CoderState(TypedDict, total=False):
    """Coder pipeline 的状态字典."""

    spec: str
    plan: dict | None  # Plan.model_dump() 的 dict
    code_files: list[str]  # 写入 output/ 的相对路径列表
    test_files: list[str]
    retry_count: int
    phase: Literal["planning", "coding", "testing", "reviewing", "done"]
    last_error: str | None


# ============================================================
# Tools — 供 specialist agent 调
# ============================================================
@tool
def tool_spec_to_plan(spec: str) -> str:
    """把 spec 转成 plan JSON string. (Planner 专用)"""
    llm = get_llm(temperature=0.0)
    plan = spec_to_plan(llm, spec)
    return plan.model_dump_json()


@tool
def tool_write_code(file_path: str, content: str) -> str:
    """写一个代码文件到 output/. (Coder 专用)"""
    p = write_code_file(file_path, content)
    return f"写入 {p.name} ({len(content)} 字符)"


@tool
def tool_run_pytest(test_file: str) -> str:
    """跑 pytest, 返回 stdout+stderr. (Reviewer 专用)"""
    code_dir = output_dir()
    test_path = code_dir / test_file
    if not test_path.exists():
        return f"FAIL: {test_file} 不存在"
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


# ============================================================
# Specialist agents — 用 create_agent (L1 模式)
# ============================================================
def _make_planner_agent():
    """Plan 阶段: spec → plan JSON."""
    from langchain.agents import create_agent

    llm = get_llm(temperature=0.0)
    return create_agent(
        llm,
        tools=[tool_spec_to_plan],
        system_prompt=(
            "你是 Planner. 收到 spec 后调 tool_spec_to_plan 拿到 plan JSON, "
            "不要修改, 直接把 JSON 原样返回给 supervisor."
        ),
    )


def _make_coder_agent():
    """Code 阶段: plan → 写文件."""
    from langchain.agents import create_agent

    llm = get_llm(temperature=0.0)
    return create_agent(
        llm,
        tools=[tool_write_code],
        system_prompt=(
            "你是 Coder. 收到 plan JSON 后, 对每个 file 调 tool_write_code 写入 output/. "
            "一次只写一个文件, 写完直接返回 'done'."
        ),
    )


def _make_reviewer_agent():
    """Review 阶段: 跑 pytest + 报告错误."""
    from langchain.agents import create_agent

    llm = get_llm(temperature=0.0)
    return create_agent(
        llm,
        tools=[tool_run_pytest],
        system_prompt=(
            "你是 Reviewer. 收到 test file 名后调 tool_run_pytest 跑测试, "
            "把结果 (returncode + stderr) 原样返回给 supervisor."
        ),
    )


# ============================================================
# Graph nodes — 每个 node 调对应 specialist agent
# ============================================================
def _parse_plan_json(text: str) -> dict:
    """从 agent 输出里抽 JSON (agent 经常裹 markdown)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"raw": text}


def planning_node(state: CoderState) -> dict:
    """Planner: spec → plan dict."""
    planner = _make_planner_agent()
    result = planner.invoke(
        {"messages": [{"role": "user", "content": state["spec"]}]}
    )
    plan_json_text = result["messages"][-1].content
    plan_dict = _parse_plan_json(plan_json_text)
    return {"plan": plan_dict, "phase": "coding"}


def coding_node(state: CoderState) -> dict:
    """Coder: plan → 写 output/.

    简化: 直接复用 codegen_pipeline.plan_to_code (agent 调 tool 太慢).
    实际项目可以让 agent 决策.
    """
    from plan_schema import Plan as PlanSchema  # noqa: N813 — 别名避免覆盖下方局部 Plan

    plan = PlanSchema.model_validate(state["plan"])
    llm = get_llm(temperature=0.0)
    code_paths = plan_to_code(llm, plan)
    return {
        "code_files": [p.name for p in code_paths],
        "phase": "testing",
    }


def testing_node(state: CoderState) -> dict:
    """Testing: 给每个 code 文件生成 test_<filename>.py."""
    llm = get_llm(temperature=0.0)
    out_dir = output_dir()
    test_files: list[str] = []
    for code_name in state.get("code_files", []):
        code_path = out_dir / code_name
        if not code_path.exists():
            continue
        test_code = code_to_test(llm, code_path)
        test_filename = f"test_{code_path.stem}.py"
        write_code_file(test_filename, test_code)
        test_files.append(test_filename)
    return {"test_files": test_files, "phase": "reviewing"}


def reviewing_node(state: CoderState) -> dict:
    """Reviewing: 跑所有 test, 失败则 phase=coding 触发 retry."""
    out_dir = output_dir()
    retry_count = state.get("retry_count", 0)

    for test_name in state.get("test_files", []):
        test_path = out_dir / test_name
        if not test_path.exists():
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-v", "--tb=short"],
            cwd=out_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            snippet = (result.stdout + "\n" + result.stderr).strip()[-500:]
            return {
                "last_error": snippet,
                "retry_count": retry_count + 1,
                "phase": "coding",  # 失败 → 回 coding 重写
            }

    return {"phase": "done"}


# ============================================================
# Supervisor — 路由函数
# ============================================================
def _route(state: CoderState) -> str:
    """根据 phase 路由下一个 node."""
    return state.get("phase", "planning")


# ============================================================
# Build graph
# ============================================================
def build_graph():
    """3 specialist + supervisor state machine."""
    workflow = StateGraph(CoderState)

    workflow.add_node("planning", planning_node)
    workflow.add_node("coding", coding_node)
    workflow.add_node("testing", testing_node)
    workflow.add_node("reviewing", reviewing_node)

    # 起点: planning
    workflow.add_edge(START, "planning")

    # 每个 phase 节点 → 根据 route 决定下一个 phase
    workflow.add_conditional_edges(
        "planning",
        _route,
        {"coding": "coding", "done": END},
    )
    workflow.add_conditional_edges(
        "coding",
        _route,
        {"testing": "testing", "done": END},
    )
    workflow.add_conditional_edges(
        "testing",
        _route,
        {"reviewing": "reviewing", "done": END},
    )
    workflow.add_conditional_edges(
        "reviewing",
        _route,
        {"coding": "coding", "done": END},  # 失败 → 回 coding 触发 retry
    )

    return workflow.compile()


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 5: Multi-Agent Coder Pipeline (StateGraph)")

    spec = get_example_spec()
    initial: CoderState = {
        "spec": spec,
        "plan": None,
        "code_files": [],
        "test_files": [],
        "retry_count": 0,
        "phase": "planning",
        "last_error": None,
    }

    step(1, "build_graph + invoke")
    print(f"  spec 长度: {len(spec)} 字符")
    graph = build_graph()
    final = graph.invoke(initial)

    step(2, "完成 — final state 摘要")
    print(f"  phase: {final.get('phase')}")
    print(f"  code files: {final.get('code_files', [])}")
    print(f"  test files: {final.get('test_files', [])}")
    print(f"  retry count: {final.get('retry_count', 0)}")
    if final.get("last_error"):
        print(f"  last error (前 200 字符): {final['last_error'][:200]}")


if __name__ == "__main__":
    main()
