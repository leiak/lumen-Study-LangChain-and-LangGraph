"""codegen_pipeline.py — 共享 pipeline: plan → code → tests → fix.

被 02/03/04/05 demo 共用. 抽出来避免重复.

💡 设计要点:
  - 一次生成一个文件 (避免 LLM 单次输出过大)
  - 用 ```python ... ``` 块提取, 容错强 (LLM 经常吐 markdown 解释)
  - 每个 prompt 强约束 "只输出代码块, 不要解释", 减少噪音
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from _common import extract_python_blocks, step, write_code_file
from plan_schema import FileSpec, FunctionSpec, Plan


# ============================================================
# Prompts
# ============================================================
_FILE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是 Python 实现者. 根据 file spec 生成完整 Python 代码.

要求:
- 用 ```python ... ``` 块包裹代码
- 不要解释, 只输出代码块
- 函数签名必须跟 spec 一致
- docstring 写全 (Google 风格)
- 不要 import 用不到的模块"""),
    ("human", "File: {path}\nPurpose: {purpose}\n\n{functions_text}\n\n输出 Python 代码 (```python 块)."),
])


_TEST_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是 pytest 专家. 根据 Python 代码生成完整 pytest 测试文件.

要求:
- 文件名: test_<filename_without_py>.py
- 用 ```python ... ``` 块包裹
- 每个函数至少 3 个测试 (正常 + 边界 + 异常)
- 用 assert, 不需要 unittest
- import 同目录模块 (from <filename_without_py> import ... )"""),
    ("human", "代码文件: {filename}\n\n```python\n{code}\n```\n\n生成 pytest 测试 (```python 块)."),
])


_FIX_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是 Python 调试专家. 根据 pytest 失败信息修改代码.

要求:
- 用 ```python ... ``` 块包裹完整修正后的代码
- 不要解释
- 修复失败的 assert, 保留其它正确行为
- 不要破坏已通过的测试"""),
    ("human", "原代码:\n```python\n{code}\n```\n\n测试失败:\n{error}\n\n输出修正后的代码."),
])


# ============================================================
# Helpers
# ============================================================
def _format_functions(functions: list[FunctionSpec]) -> str:
    """把 FunctionSpec list 格式化成 prompt 输入."""
    lines = []
    for f in functions:
        lines.append(f"- `{f.signature}`")
        lines.append(f"  Docstring: {f.docstring}")
        if f.test_cases:
            lines.append(f"  Tests: {', '.join(f.test_cases)}")
    return "\n".join(lines)


def _invoke_text(llm, prompt_input: dict, prompt: ChatPromptTemplate) -> str:
    """invoke LLM, 返回 text (兼容 AIMessage / str)."""
    response = llm.invoke(prompt.format(**prompt_input))
    if hasattr(response, "content"):
        return response.content
    return str(response)


# ============================================================
# Pipeline 步骤
# ============================================================
def file_to_code(llm, file_spec: FileSpec) -> str:
    """单 file spec → Python code string."""
    text = _invoke_text(
        llm,
        {
            "path": file_spec.path,
            "purpose": file_spec.purpose,
            "functions_text": _format_functions(file_spec.functions),
        },
        _FILE_PROMPT,
    )
    blocks = extract_python_blocks(text)
    return blocks[0]  # 第一个 python 块就是答案


def code_to_test(llm, code_file: Path) -> str:
    """code 文件 → pytest test code string."""
    code = code_file.read_text(encoding="utf-8")
    text = _invoke_text(
        llm,
        {"filename": code_file.name, "code": code},
        _TEST_PROMPT,
    )
    blocks = extract_python_blocks(text)
    return blocks[0]


def fix_code(llm, code: str, error: str) -> str:
    """code + 错误 → 修正后 code string."""
    text = _invoke_text(
        llm,
        {"code": code, "error": error},
        _FIX_PROMPT,
    )
    blocks = extract_python_blocks(text)
    return blocks[0]


def plan_to_code(llm, plan: Plan) -> list[Path]:
    """Plan → 写 output/, 返回文件路径列表."""
    written: list[Path] = []
    for i, file_spec in enumerate(plan.files, 1):
        step(i, f"生成 {file_spec.path}")
        code = file_to_code(llm, file_spec)
        path = write_code_file(file_spec.path, code)
        print(f"  写入 {path} ({len(code)} 字符)")
        # 打印前 8 行预览
        preview = "\n".join(code.split("\n")[:8])
        print(f"  预览:\n{preview}\n  ...")
        written.append(path)
    return written


__all__ = [
    "plan_to_code",
    "file_to_code",
    "code_to_test",
    "fix_code",
]
