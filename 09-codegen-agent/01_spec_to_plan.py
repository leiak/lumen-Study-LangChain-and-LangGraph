"""01_spec_to_plan.py — Demo 1: 把 spec 解析成结构化 plan.

用 with_structured_output (Pydantic schema) 让 LLM 输出 Plan dict.
Plan: files[] (path + purpose), functions[] (name + signature + tests[]).

学完这个 demo 你能回答:
1.  怎么用 Pydantic BaseModel 定义 LLM 输出的 schema?
2.  怎么用 method="function_calling" 让 LLM 吐结构化 JSON?
3.  MiniMax M3 默认吐 CoT, structured output 失败时怎么 fallback?
4.  Plan schema 应该多严格? 太死 → LLM 没空间; 太松 → 解析失败
5.  怎么用 json.dumps(plan.model_dump(), indent=2) 漂亮地打印 Plan?

跑法:
    python 01_spec_to_plan.py
"""
from __future__ import annotations

import json

from _common import banner, get_example_spec, get_llm, load_spec, preview_spec, step
from plan_schema import Plan, spec_to_plan


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 1: Spec → Structured Plan")

    llm = get_llm(temperature=0.0)
    spec = load_spec(get_example_spec())

    step(1, "Spec 预览 (截断 300 字符)")
    print(preview_spec(spec))

    step(2, "LLM 生成 plan (双轨: function_calling → Pydantic fallback)")
    plan = spec_to_plan(llm, spec)

    step(3, "Plan 输出 (漂亮打印 JSON)")
    print(json.dumps(plan.model_dump(), ensure_ascii=False, indent=2))

    step(4, "Plan 摘要")
    assert isinstance(plan, Plan), f"expected Plan, got {type(plan)}"
    print(f"  summary: {plan.summary}")
    print(f"  files: {len(plan.files)} 个 ({[f.path for f in plan.files]})")
    print(f"  dependencies: {plan.dependencies}")
    print(f"  assumptions: {plan.assumptions}")
    total_funcs = sum(len(f.functions) for f in plan.files)
    total_tests = sum(len(func.test_cases) for f in plan.files for func in f.functions)
    print(f"  functions: {total_funcs} 个, test_cases: {total_tests} 个")


if __name__ == "__main__":
    main()
