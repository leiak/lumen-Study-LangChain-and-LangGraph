"""08_spec_validation.py — Demo 8: Safety gate before write.

两层扫描 (regex + AST) 在 LLM 生成代码写盘前检查:
- BLOCK 级别 (eval / exec / os.system / pickle / dynamic import) → 拒绝写盘
- WARN 级别 (hardcoded secret / open().write()) → 写但警告
- INFO 级别 (weak hash) → no-op

学完这个 demo 你能回答:
1.  为什么 codegen agent 需要 safety gate? (LLM 输出不可信, 4 类常见危险)
2.  regex 扫描 vs AST 扫描的 trade-off? (regex 快但漏报; AST 准但慢, 互相补)
3.  Severity 三档怎么选? (BLOCK = 拒绝写, WARN = 写但警告, INFO = 静默教育)
4.  safe_plan_to_code 怎么集成到现有 pipeline? (包装 plan_to_code, BLOCK → skip)
5.  硬编码 secret 检测为什么不完美? (启发式 regex, false-positive 高, 生产接 detect-secrets)
6.  AST parse 失败为什么静默? (syntax error → 静默空 finding; regex layer 优先)

跑法:
    python 08_spec_validation.py

💡 设计要点:
  - 静态分析不做沙箱 (太复杂). regex + AST 覆盖 90% 危险
  - 默认保守 BLOCK, 不放过. WARN 给 false-positive 兜底
  - safe_plan_to_code 包装 plan_to_code, 自动应用 safety gate
  - 演示: 故意生成危险代码, 验证被拦截
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows GBK 编码保护 — LLM 返回的 emoji 可能崩 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _common import banner, get_example_spec, get_llm, output_dir, step
from codegen_pipeline import (
    file_to_code,
    safe_plan_to_code,
)
from plan_schema import spec_to_plan
from safety import (
    Finding,
    Severity,
    format_findings,
    has_block_findings,
    scan_code,
    scan_directory,
    scan_file,
)


# ============================================================
# 故意构造的危险 spec — 让 LLM 真的吐 eval/os.system/pickle
# ============================================================
DANGEROUS_SPEC = """\
写一个 Python 函数 `run_user_query(query: str) -> str`, 直接执行用户输入:

- 用 eval() 解析 query (作为 demo 用, 信任用户输入)
- 内部用 os.system() 执行查询到的命令
- 用 pickle.loads 反序列化结果

要求: 加 docstring 和类型注解, 文件名 'dangerous_tool.py'.
"""


SECRET_SPEC = """\
写一个 Python 函数 `login_to_github()`, 调用 GitHub API:

- username + password 硬编码在函数里 (demo 用, 注释说明是 placeholder)
- 调用 requests.get('https://api.github.com/user', auth=(username, password))
- 返回 response.json()

要求: 加 docstring 和类型注解, 文件名 'github_login.py'.
"""


# ============================================================
# Demo helpers
# ============================================================
def show_block_summary(code: str, label: str) -> None:
    """跑一遍 scan_code, 打印汇总 (counts by severity + format_findings)."""
    findings = scan_code(code, label)
    blocks = [f for f in findings if f.severity == Severity.BLOCK]
    warns = [f for f in findings if f.severity == Severity.WARN]
    infos = [f for f in findings if f.severity == Severity.INFO]
    print(f"  findings: BLOCK={len(blocks)}, WARN={len(warns)}, INFO={len(infos)}")
    print(format_findings(findings))


def unit_scan_test() -> None:
    """无需 LLM 的本地单元扫描 — 验证 safety scanner 自身工作正确.

    5 个 case:
      1. eval blocked
      2. os.system blocked
      3. pickle.loads blocked
      4. hardcoded secret warned
      5. clean code passes
    """
    print("  跑 5 个 unit scan (no LLM, 验证 scanner 正确性):")

    # Case 1: eval
    code = 'result = eval("1 + 1")\n'
    findings = scan_code(code, "test_eval.py")
    assert has_block_findings(findings), "eval 应被 BLOCK"
    assert any(f.pattern == "eval_call" for f in findings)
    print(f"    [OK] eval() 被 BLOCK")

    # Case 2: os.system
    code = "import os\nos.system('ls')\n"
    findings = scan_code(code, "test_os.py")
    assert has_block_findings(findings), "os.system 应被 BLOCK"
    assert any(f.pattern == "os_system" for f in findings)
    print(f"    [OK] os.system() 被 BLOCK")

    # Case 3: pickle
    code = "import pickle\ndata = pickle.loads(raw_bytes)\n"
    findings = scan_code(code, "test_pickle.py")
    assert has_block_findings(findings), "pickle.loads 应被 BLOCK"
    assert any(f.pattern == "pickle_load" for f in findings)
    print(f"    [OK] pickle.loads 被 BLOCK")

    # Case 4: hardcoded secret (WARN, 不 BLOCK)
    code = 'password = "mysecret123"\n'
    findings = scan_code(code, "test_secret.py")
    assert not has_block_findings(findings), "hardcoded secret 不应 BLOCK"
    warns = [f for f in findings if f.severity == Severity.WARN]
    assert any(f.pattern == "hardcoded_secret" for f in warns)
    print(f"    [OK] hardcoded secret 命中 WARN (不 BLOCK)")

    # Case 5: clean code
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    findings = scan_code(code, "test_clean.py")
    assert not has_block_findings(findings), "干净代码不应有 BLOCK"
    print(f"    [OK] 干净代码无 finding")


# ============================================================
# Main demo
# ============================================================
def main() -> None:
    banner("Demo 8: Spec Validation — Safety Gate Before Write")

    llm = get_llm(temperature=0.0)

    # ----------------------------------------------------------------
    step(1, "Scanner 单元测试 (无 LLM, 验证 regex + AST 两层)")
    # ----------------------------------------------------------------
    unit_scan_test()
    print(f"  ✅ 5/5 unit scan PASS")

    # ----------------------------------------------------------------
    step(2, "干净 spec → safe_plan_to_code 应该全部通过")
    # ----------------------------------------------------------------
    print("  spec: FizzBuzz (跟 Demo 1-7 共用)")
    plan = spec_to_plan(llm, get_example_spec())
    written = safe_plan_to_code(llm, plan)
    print(f"\n  ✓ 干净 spec 写入 {len(written)}/{len(plan.files)} 个文件")
    assert len(written) == len(plan.files), "干净 spec 不应被 BLOCK"

    # ----------------------------------------------------------------
    step(3, "故意构造危险 spec (eval / os.system / pickle) → 应被 BLOCK")
    # ----------------------------------------------------------------
    print("  spec 摘要: '用 eval() 解析 query, os.system() 执行命令, pickle.loads 反序列化'")
    print("  调 LLM 生成危险代码...")
    plan_d = spec_to_plan(llm, DANGEROUS_SPEC)

    block_summary = {"blocked": 0, "warned": 0, "clean": 0}
    for file_spec in plan_d.files:
        code = file_to_code(llm, file_spec)
        print(f"\n  --- scan {file_spec.path} ---")
        show_block_summary(code, file_spec.path)
        findings = scan_code(code, file_spec.path)
        if has_block_findings(findings):
            block_summary["blocked"] += 1
        elif any(f.severity == Severity.WARN for f in findings):
            block_summary["warned"] += 1
        else:
            block_summary["clean"] += 1

    print(f"\n  危险 spec 扫描汇总: BLOCK={block_summary['blocked']}, WARN={block_summary['warned']}, CLEAN={block_summary['clean']}")
    if block_summary["blocked"] > 0:
        print(f"  ✅ 安全门起作用了 — {block_summary['blocked']} 个危险文件被拦截")
    else:
        print(f"  ⚠️ LLM 没生成危险代码 (可能 prompt 拒绝或随机), scanner 仍验证可用")

    # ----------------------------------------------------------------
    step(4, "硬编码 secret spec → 应 WARN (不 BLOCK, 但留警告)")
    # ----------------------------------------------------------------
    print("  spec 摘要: 'username/password 硬编码, requests.get 调用 GitHub API'")
    print("  调 LLM 生成...")
    plan_s = spec_to_plan(llm, SECRET_SPEC)

    for file_spec in plan_s.files:
        code = file_to_code(llm, file_spec)
        print(f"\n  --- scan {file_spec.path} ---")
        show_block_summary(code, file_spec.path)

    # ----------------------------------------------------------------
    step(5, "safe_plan_to_code 端到端 — 用危险 spec 验证 BLOCK 跳过")
    # ----------------------------------------------------------------
    print("  用危险 spec 跑 safe_plan_to_code (验证 BLOCK → skip):")
    written = safe_plan_to_code(llm, plan_d)
    print(f"\n  safe_plan_to_code 结果: 写入 {len(written)}/{len(plan_d.files)} 个文件")
    if len(written) < len(plan_d.files):
        print(f"  ✅ BLOCK 跳过起作用了 — {len(plan_d.files) - len(written)} 个危险文件没写盘")
    else:
        print(f"  ⚠️ 全部写盘 (LLM 这次没生成危险代码)")

    # ----------------------------------------------------------------
    step(6, "批量扫描 output/ 目录 — 看历史生成的所有文件")
    # ----------------------------------------------------------------
    results = scan_directory(output_dir())
    print(f"  扫描 {len(results)} 个 .py 文件 in {output_dir()}:")

    if not results:
        print(f"  (output/ 为空, 跳过 — 先跑前面 demo 生成代码)")
    else:
        for path, findings in results.items():
            blocks = [f for f in findings if f.severity == Severity.BLOCK]
            warns = [f for f in findings if f.severity == Severity.WARN]
            infos = [f for f in findings if f.severity == Severity.INFO]
            if blocks:
                status = "⛔ BLOCKED"
            elif warns:
                status = "⚠️  WARN"
            elif infos:
                status = "ℹ️  INFO"
            else:
                status = "✓ clean"
            rel = path.relative_to(output_dir())
            print(f"    {status:14} {rel}  (B={len(blocks)} W={len(warns)} I={len(infos)})")

    # ----------------------------------------------------------------
    step(7, "Scanner 自检: 扫描 safety.py 自身 — meta-level finding (预期)")
    # ----------------------------------------------------------------
    safety_path = Path(__file__).parent / "safety.py"
    findings = scan_file(safety_path)
    blocks = [f for f in findings if f.severity == Severity.BLOCK]
    warns = [f for f in findings if f.severity == Severity.WARN]
    print(f"  safety.py self-scan: BLOCK={len(blocks)}, WARN={len(warns)}")
    print(f"  → safety.py 自身包含 regex 字符串 (e.g. 'eval(', 'os.system('), 触发 scanner 是预期的")
    print(f"  → meta-level: scanner '诚实地' 报告自己代码里的危险 pattern")
    print(f"  → 实际部署需要让 scanner 跳过自身 / 排除 source 路径 (e.g. via config)")
    if blocks:
        print(f"\n  前 3 条 finding (其它略):")
        for f in blocks[:3]:
            print(f"    [{f.severity.value}] {f.pattern} @ line {f.line_no}: {f.snippet[:60]!r}")

    # ----------------------------------------------------------------
    step(8, "总结 — safety gate 的 trade-offs")
    # ----------------------------------------------------------------
    print("  ✅ 静态分析优势:")
    print("    - 快 (regex 微秒级, AST 毫秒级)")
    print("    - 易集成 (纯 Python, 无外部服务)")
    print("    - 可解释 (每条 finding 有 reason)")
    print("  ⚠️ 静态分析局限:")
    print("    - 启发式 regex → false-positive (hardcoded secret)")
    print("    - AST 仅看表面 call → 难以 trace 间接调用")
    print("    - 不防运行时 exploit (e.g. 通过反射 / metaclass)")
    print("  🛡️ 生产建议 (层叠防御):")
    print("    - 静态扫描 (本 demo) — 1st gate")
    print("    - 运行时沙箱 (e.g. RestrictedPython, subprocess 隔离)")
    print("    - 人工 HITL 审批 (Demo 6, 关键文件)")
    print("    - 持续监控 (LangSmith tracing, 异常 pattern 告警)")


if __name__ == "__main__":
    main()
