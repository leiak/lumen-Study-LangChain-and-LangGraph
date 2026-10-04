"""07_incremental_diff.py — Demo 7: Review loop with incremental diff edits.

对比 Demo 4 全文件重生成 vs Demo 7 增量 diff 编辑:
  - 同样 bug, 同样 retry
  - Token 节省 50%+ (1-line bug 不需要重写 1000-line 文件)
  - SEARCH/REPLACE 块格式 (Aider-style) + fallback 行号格式

学完这个 demo 你能回答:
1.  为什么 incremental diff 比 full regen 省 token? (LLM 输出 size 与 input code 长度无关)
2.  Aider-style SEARCH/REPLACE 块怎么 parse? (regex + difflank fuzzy fallback)
3.  difflib.SequenceMatcher 的 threshold (0.6) 怎么选? 太高太低各有什么问题?
4.  解析失败时为什么用 '保留原 code' 而不是 raise? (避免让破圈破坏 pipeline)
5.  怎么 measure token 节省? (LLM response char count 是 proxy, 跟 tokenizer 接近)
6.  SEARCH/REPLACE 块写得多大合适? (2-5 行 + 上下文, 避免歧义匹配)
7.  incremental diff 跟 full regen 怎么选择? (大文件+小 bug → diff; 小文件+大改 → regen)

跑法:
    python 07_incremental_diff.py

💡 设计要点:
  - SEARCH/REPLACE 块用 <<<< ==== >>>> 分隔, 易 parse
  - 模糊匹配 fallback (difflib.SequenceMatcher): LLM 改个空格也匹配
  - 解析失败 → 保留原 code (defensive, 不破坏)
  - 验证: 故意制造 1-line bug, 对比两种 fix 的 token 成本
"""
from __future__ import annotations

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
from codegen_pipeline import (
    _FIX_INCREMENTAL_PROMPT,
    _FIX_PROMPT,
    apply_search_replace,
    code_to_test,
    extract_search_replace_blocks,
    fix_code_incremental,
    plan_to_code,
)
from plan_schema import spec_to_plan


# ============================================================
# Bug injection — 故意制造 off-by-one 演示
# ============================================================
def inject_off_by_one_bug(code: str) -> str:
    """故意把 'return n' 改成 'return n + 1', 制造 off-by-one bug.

    选择这个 pattern 是因为:
    - FizzBuzz 主函数通常含 'return n'
    - 改 1 个字符演示 7.5x token 节省最有效 (full regen 重写整个函数 / file)
    """
    return code.replace("return n", "return n + 1", 1)


def fake_pytest_error(test_name: str = "test_fizzbuzz.py") -> str:
    """构造一个看起来真实的 pytest 失败信息 (不需要真跑 pytest)."""
    return (
        "============================= test session starts ==============================\n"
        f"collected 4 items\n\n"
        f"{test_name}::test_fizzbuzz_returns_number_for_non_multiples FAILED\n"
        "___________________ test_fizzbuzz_returns_number_for_non_multiples ___________________\n\n"
        "    def test_fizzbuzz_returns_number_for_non_multiples():\n"
        "        assert fizzbuzz(1) == '1'\n"
        "        assert fizzbuzz(2) == '2'\n"
        ">       assert fizzbuzz(4) == '4'\n"
        "E       AssertionError: assert 'Buzz' == '4'\n"
        "\n"
        f"{test_name}:6: AssertionError\n"
        "=========================== short test summary info ============================\n"
        "FAILED test_fizzbuzz.py::test_fizzbuzz_returns_number_for_non_multiples - AssertionError\n"
        "============================== 1 failed in 0.05s ==============================="
    )


# ============================================================
# Token cost measurement — 两种 fix 模式各跑一次, 对比 response size
# ============================================================
def measure_fix_cost(
    llm,
    code: str,
    error: str,
    mode: str,
) -> tuple[str, int]:
    """跑一种 fix 模式, 返回 (llm_response_text, char_count).

    Args:
        mode: "full" → 调 _FIX_PROMPT (Demo 4 风格, 重写整个文件)
              "incremental" → 调 _FIX_INCREMENTAL_PROMPT (Demo 7, 输出 SEARCH/REPLACE)

    Returns:
        (response_text, len(response_text)). 长度是 token 节省的 proxy.
    """
    prompt = _FIX_PROMPT if mode == "full" else _FIX_INCREMENTAL_PROMPT
    response = llm.invoke(prompt.format(code=code, error=error))
    text = response.content if hasattr(response, "content") else str(response)
    return text, len(text)


def apply_incremental_to_code(buggy: str, response: str) -> tuple[str, int]:
    """从 incremental response 抽 SEARCH/REPLACE 块, 应用到 buggy code.

    Returns:
        (fixed_code, num_patches_applied)
    """
    patches = extract_search_replace_blocks(response)
    if not patches:
        return buggy, 0
    result = buggy
    applied = 0
    for search, replace in patches:
        new_result = apply_search_replace(result, search, replace)
        if new_result != result:
            applied += 1
        result = new_result
    return result, applied


# ============================================================
# Main demo
# ============================================================
def main() -> None:
    banner("Demo 7: Incremental Diff Review Loop")

    llm = get_llm(temperature=0.0)

    step(1, "复用 Demo 1-3 生成代码 (FizzBuzz)")
    spec = get_example_spec()
    plan = spec_to_plan(llm, spec)
    code_files = plan_to_code(llm, plan)
    code_file = code_files[0]
    test_filename = f"test_{code_file.stem}.py"

    # 演示只跑第一个 code 文件 (跟 Demo 4 一致)
    step(2, f"生成 {test_filename}")
    test_code = code_to_test(llm, code_file)
    write_code_file(test_filename, test_code)
    print(f"  写入 {test_filename} ({len(test_code)} 字符)")

    step(3, "故意制造 bug (off-by-one in 'return n')")
    original_code = code_file.read_text(encoding="utf-8")
    buggy_code = inject_off_by_one_bug(original_code)
    code_file.write_text(buggy_code, encoding="utf-8")
    print(f"  原 code: {len(original_code)} 字符")
    print(f"  buggy code: {len(buggy_code)} 字符 (差 {len(buggy_code) - len(original_code)} 字符)")
    print(f"  改动: 'return n' → 'return n + 1'")

    step(4, "构造 fake pytest 错误信息")
    fake_error = fake_pytest_error(test_filename)
    print(f"  fake error 长度: {len(fake_error)} 字符")

    # === 对比两种 fix 模式 ===
    step(5, "Mode A — 全文件重生成 (Demo 4 风格)")
    print("  prompt: _FIX_PROMPT (重写整个 code)")
    print("  调 LLM...")
    full_response, full_chars = measure_fix_cost(llm, buggy_code, fake_error, mode="full")
    print(f"  LLM response: {full_chars} 字符")
    # 打印前 5 行 + 总行数 (避免刷屏)
    full_preview_lines = full_response.split("\n")[:5]
    full_line_count = len(full_response.split("\n"))
    print(f"  响应预览 (前 5 行 / 共 {full_line_count} 行):")
    for line in full_preview_lines:
        print(f"    {line[:80]}")
    print(f"    ...")

    step(6, "Mode B — 增量 diff (Demo 7 风格, SEARCH/REPLACE)")
    print("  prompt: _FIX_INCREMENTAL_PROMPT (只输出 SEARCH/REPLACE 块)")
    print("  调 LLM...")
    incr_response, incr_chars = measure_fix_cost(llm, buggy_code, fake_error, mode="incremental")
    print(f"  LLM response: {incr_chars} 字符")
    incr_preview_lines = incr_response.split("\n")[:8]
    incr_line_count = len(incr_response.split("\n"))
    print(f"  响应预览 (前 8 行 / 共 {incr_line_count} 行):")
    for line in incr_preview_lines:
        print(f"    {line[:80]}")
    print(f"    ...")

    step(7, "Token 节省对比")
    if full_chars > 0:
        saved_pct = (1 - incr_chars / full_chars) * 100
        print(f"  Mode A (full regen):     {full_chars:>6} 字符")
        print(f"  Mode B (incremental):    {incr_chars:>6} 字符")
        print(f"  节省: {saved_pct:>5.1f}%  ({full_chars - incr_chars} 字符差)")
        if saved_pct >= 50:
            print(f"  >>> 达到 50%+ 节省目标 ✅")
        elif saved_pct > 0:
            print(f"  >>> 有节省但未达 50% (跟 LLM 输出风格有关)")
        else:
            print(f"  >>> 反而更长 (rare — LLM 在 incremental 模式吐了解释)")
    else:
        print(f"  ⚠️ full response 为空, 跳过对比")

    step(8, "解析 Mode B 的 SEARCH/REPLACE 块并 apply")
    patches = extract_search_replace_blocks(incr_response)
    print(f"  解析到 {len(patches)} 个 SEARCH/REPLACE 块")
    for i, (search, replace) in enumerate(patches, 1):
        search_preview = search.replace("\n", "\\n")[:80]
        replace_preview = replace.replace("\n", "\\n")[:80]
        print(f"    [{i}] SEARCH: {search_preview}")
        print(f"        REPLACE: {replace_preview}")

    if patches:
        fixed_code, applied = apply_incremental_to_code(buggy_code, incr_response)
        print(f"  成功 apply {applied}/{len(patches)} 个块")
        print(f"  修复后 code: {len(fixed_code)} 字符 (was {len(buggy_code)})")
        # 验证 bug 是否真的被修了
        if "return n + 1" in buggy_code and "return n + 1" not in fixed_code:
            print(f"  ✅ bug 已修复 (off-by-one 'return n + 1' 被改回)")
        elif "return n + 1" in buggy_code and "return n + 1" in fixed_code:
            print(f"  ⚠️ 'return n + 1' 仍在 — LLM 可能改了别的地方")
        else:
            print(f"  ℹ️ bug pattern 已不在 (修复路径走另一条)")

        # 把 fixed code 写回, demo 完整闭环 (review loop 视角)
        # 注: 这里不真跑 pytest, 因为 LLM 真改也可能影响行为, 演示用
        # write_code_file(code_file.name, fixed_code)
        # print(f"  写回 {code_file.name} (可选)")
    else:
        print(f"  ⚠️ 没解析到 SEARCH/REPLACE 块, 跳过 apply")
        print(f"  → fix_code_incremental 会返回原 code (defensive)")

    step(9, "总结 — incremental diff 的 trade-offs")
    print("  适用:")
    print("    - 大文件 (1000+ 行) + 小 bug (1-3 行)")
    print("    - retry loop 的后续轮 (前面 regen 上下文已建立)")
    print("  不适用:")
    print("    - 第一次生成 (LLM 不知道从哪开始改)")
    print("    - 重构 (改文件结构, 增量会变碎片化)")
    print("  生产建议 (Cursor / Copilot / Aider):")
    print("    - 增量 diff 是默认, 全文件 regen 仅用于 first-pass")


if __name__ == "__main__":
    main()