"""04_review_loop.py — Demo 4: 测试失败 → LLM 修正 → 重跑, 直到 pass.

完整 review loop:
  - 跑 pytest (subprocess, 隔离进程)
  - 失败 → 把 stderr 喂给 LLM 修代码
  - 重跑 → 再次失败? 再修 (最多 max_retries 次)
  - max_retries 用完还失败 → 跳出, 报告人类

学完这个 demo 你能回答:
1.  怎么用 subprocess.run 跑 pytest 拿 stderr?
2.  怎么把 pytest 失败的 stderr 喂给 LLM 让它修代码?
3.  怎么设 max_retries 防无限循环?
4.  review loop 的终止条件 (pass / max_retries) 怎么设计?
5.  为什么不修 test code? (避免 LLM 妥协测试, 改成让代码通过)
6.  怎么把生成的代码 + test 真跑起来 (subprocess cwd)?

跑法:
    python 04_review_loop.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import (
    banner,
    get_example_spec,
    get_llm,
    output_dir,
    step,
    write_code_file,
)
from codegen_pipeline import code_to_test, fix_code, plan_to_code
from plan_schema import spec_to_plan


MAX_RETRIES = 3


# ============================================================
# pytest runner
# ============================================================
def run_pytest(test_file: Path, code_dir: Path) -> tuple[bool, str]:
    """跑 pytest, 返回 (passed, error_msg).

    Returns:
        (True, "") — 全部通过
        (False, stderr) — 有失败, 含 stdout+stderr 详情
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short"],
            cwd=code_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stdout + "\n" + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "pytest timeout (>30s)"
    except Exception as e:
        return False, f"pytest failed to start: {type(e).__name__}: {e}"


def _truncate(text: str, max_lines: int = 30) -> str:
    """截断 error 输出前 max_lines 行 (避免刷屏)."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n... [共 {len(lines)} 行, 截断]"


# ============================================================
# review loop
# ============================================================
def review_loop(llm, code_file: Path, test_file: Path, max_retries: int = MAX_RETRIES) -> int:
    """跑 test → 失败 → 修 → 重跑.

    Returns:
        retry 次数. 0 = 一次就过; max_retries+1 = 达到上限
    """
    code_dir = output_dir()

    for attempt in range(max_retries + 1):
        step(f"run {attempt}", f"跑 pytest (attempt {attempt + 1}/{max_retries + 1})")
        passed, error = run_pytest(test_file, code_dir)

        if passed:
            print(f"  PASS — 无需修改")
            return attempt

        print(f"  FAIL (重试 {attempt}/{max_retries})")
        print(f"  错误预览:\n{_truncate(error)}\n  ...")

        if attempt >= max_retries:
            print(f"  达到 max_retries={max_retries}, 放弃")
            return attempt + 1

        step(f"fix {attempt}", f"LLM 修正 {code_file.name}")
        code = code_file.read_text(encoding="utf-8")
        fixed = fix_code(llm, code, error)
        code_file.write_text(fixed, encoding="utf-8")
        delta = len(fixed) - len(code)
        sign = "+" if delta >= 0 else ""
        print(f"  修正后 {len(fixed)} 字符 (was {len(code)}, {sign}{delta})")

    return max_retries + 1


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 4: Review Loop — Fix Until Pass")

    llm = get_llm(temperature=0.0)

    step(1, "复用 spec → plan → code → test")
    spec = get_example_spec()
    plan = spec_to_plan(llm, spec)
    code_files = plan_to_code(llm, plan)

    # 演示: 只 review 第一个 code 文件 (简化, 实际项目可对每个跑一遍)
    code_file = code_files[0]
    test_filename = f"test_{code_file.stem}.py"
    test_path = output_dir() / test_filename

    step(2, f"生成 {test_filename}")
    test_code = code_to_test(llm, code_file)
    write_code_file(test_filename, test_code)
    print(f"  写入 {test_path} ({len(test_code)} 字符)")

    step(3, f"review loop (max_retries={MAX_RETRIES})")
    retries = review_loop(llm, code_file, test_path)

    step(4, "总结")
    if retries <= MAX_RETRIES:
        print(f"  PASS — 在 {retries} 次重试内通过")
        print(f"  最终代码: {code_file}")
    else:
        print(f"  FAIL — {MAX_RETRIES} 次重试后仍失败")
        print(f"  代码留在 {code_file}, 需人工介入")


if __name__ == "__main__":
    main()
