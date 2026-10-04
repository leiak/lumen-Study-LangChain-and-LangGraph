"""02_plan_to_code.py — Demo 2: 把 Plan 转成实际代码文件.

复用 Demo 1 的 spec_to_plan, 然后对每个 FileSpec 生成 Python 代码.
最后写入 output/ 目录 (gitignored).

学完这个 demo 你能回答:
1.  怎么用 LLM 把单个 FileSpec → Python code?
2.  怎么从 LLM 输出提取 ```python ... ``` 块?
3.  为什么要"一次一个文件" (避免 LLM 单次输出过大)?
4.  怎么把生成的代码写到 output/ 目录?
5.  Plan 文件 / 函数 / 测试用例的层级关系怎么遍历?

跑法:
    python 02_plan_to_code.py
"""
from __future__ import annotations

from _common import (
    banner,
    get_example_spec,
    get_llm,
    output_dir,
    step,
)
from codegen_pipeline import plan_to_code
from plan_schema import spec_to_plan


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 2: Plan → Generated Code Files")

    llm = get_llm(temperature=0.0)
    spec = get_example_spec()

    step(1, "复用 Demo 1 生成 plan")
    plan = spec_to_plan(llm, spec)
    print(f"  Plan: {plan.summary}")
    print(f"  Files: {len(plan.files)} 个 → {[f.path for f in plan.files]}")

    step(2, "逐文件生成 + 写入 output/")
    paths = plan_to_code(llm, plan)

    step(len(plan.files) + 2, "完成 — 列出所有写入文件")
    print(f"  output_dir: {output_dir()}")
    print(f"  生成 {len(paths)} 文件:")
    for p in paths:
        size = p.stat().st_size
        print(f"    - {p.name}  ({size} 字节)")


if __name__ == "__main__":
    main()
