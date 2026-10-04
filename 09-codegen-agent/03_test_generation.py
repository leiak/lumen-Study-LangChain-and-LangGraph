"""03_test_generation.py — Demo 3: 给生成的代码写 pytest 测试.

输入: code 文件路径列表 (from Demo 2)
输出: test_<filename_without_py>.py 写到 output/

学完这个 demo 你能回答:
1.  怎么让 LLM 看完整 code 后生成对应 pytest 测试?
2.  怎么给每个 code 文件生成对应的 test_<...>.py?
3.  测试用例的覆盖维度 (正常 + 边界 + 异常) 怎么在 prompt 里约束?
4.  怎么复用 Demo 2 的 plan → code pipeline?
5.  测试代码和主代码为什么要分开生成 (而不是一并生成)?

跑法:
    python 03_test_generation.py
"""
from __future__ import annotations

from pathlib import Path

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
# Helpers
# ============================================================
def test_filename_for(code_file: Path) -> str:
    """fizzbuzz.py → test_fizzbuzz.py"""
    stem = code_file.stem  # 去 .py
    return f"test_{stem}.py"


def generate_tests_for_files(llm, code_files: list[Path]) -> list[Path]:
    """对每个 code 文件生成 test_<filename>.py."""
    written: list[Path] = []
    for i, code_file in enumerate(code_files, 1):
        step(i, f"生成 test_{code_file.name}")
        test_code = code_to_test(llm, code_file)
        test_path = write_code_file(test_filename_for(code_file), test_code)
        print(f"  写入 {test_path} ({len(test_code)} 字符)")
        # 打印前 6 行预览
        preview = "\n".join(test_code.split("\n")[:6])
        print(f"  预览:\n{preview}\n  ...")
        written.append(test_path)
    return written


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 3: Code → Pytest Tests")

    llm = get_llm(temperature=0.0)

    step(1, "复用 Demo 1+2: spec → plan → code")
    spec = get_example_spec()
    plan = spec_to_plan(llm, spec)
    code_files = plan_to_code(llm, plan)
    print(f"  得到 {len(code_files)} 个 code 文件")

    step(len(plan.files) + 2, "逐文件生成 test_<filename>.py")
    test_files = generate_tests_for_files(llm, code_files)

    step(len(plan.files) + len(test_files) + 2, "完成")
    print(f"  output_dir: {output_dir()}")
    print(f"  共生成 {len(test_files)} 个测试文件:")
    for tf in test_files:
        print(f"    - {tf.name}  ({tf.stat().st_size} 字节)")


if __name__ == "__main__":
    main()
