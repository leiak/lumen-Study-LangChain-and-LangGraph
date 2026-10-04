"""plan_schema.py — 共享的 Plan Pydantic schema + spec_to_plan 双轨实现.

被 01-05 demo 共用. 抽出来避免重复.

💡 设计要点:
  - 双轨: 主路 method="function_calling" + 备路 llm | StripThinkParser | PydanticOutputParser
    (MiniMax M3 默认吐 CoT, structured output 解析失败)
  - Plan schema 不要太死: 让 LLM 加额外字段 (e.g. dependencies / assumptions)
"""
from __future__ import annotations

import re

from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# Pydantic schemas
# ============================================================
class FunctionSpec(BaseModel):
    """单个函数的规格."""

    name: str = Field(description="函数名, e.g. 'fizzbuzz'")
    signature: str = Field(description="完整签名, e.g. 'def fizzbuzz(n: int) -> str'")
    docstring: str = Field(description="Google 风格 docstring")
    test_cases: list[str] = Field(description="pytest 测试用例描述")


class FileSpec(BaseModel):
    """单个文件的规格.

    💡 model_config extra='allow':
      LLM 不会吐 content (content 是 file_to_code 之后产物).
      但 dep_graph.py 需要 `f.content` 来分析 import 关系,
      通过 `getattr(f, "content", "")` 兜底, 没 content 时视为空.
      允许 extras 让 demo 9 可以 `FileSpec(..., content='...')` 注入生成代码.
    """

    model_config = ConfigDict(extra="allow")

    path: str = Field(description="相对路径, e.g. 'fizzbuzz.py'")
    purpose: str = Field(description="文件用途, 一句话")
    functions: list[FunctionSpec] = Field(default_factory=list)


class Plan(BaseModel):
    """完整的实现 plan."""

    summary: str = Field(description="一句话总结要做什么")
    files: list[FileSpec] = Field(description="要创建的文件列表")
    dependencies: list[str] = Field(default_factory=list, description="外部依赖, e.g. ['pytest']")
    assumptions: list[str] = Field(default_factory=list, description="实现假设")


# ============================================================
# Prompts
# ============================================================
PLAN_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是一个严谨的 Python 架构师. 根据用户 spec, 设计一个清晰的实现 plan.

要求:
1. 拆分成 1-3 个文件 (不要过度拆分)
2. 每个函数给完整签名 + docstring + 至少 3 个测试用例
3. 列出依赖 (e.g. pytest / pydantic)
4. 列出关键假设

⚠️ 只输出 JSON, 不要解释. JSON 必须符合 schema."""),
    ("human", "Spec:\n\n{spec}\n\n输出 Plan JSON."),
])


# ============================================================
# 双轨: function_calling → Pydantic fallback
# ============================================================
# 兼容各种 CoT 标签: DeepSeek-R1 / Kimi / MiniMax M3 / Qwen3 等
_THINK_RE = re.compile(
    r".*?"
    r"|<thinking>.*?</thinking>"
    r"|<reflection>.*?</reflection>",
    flags=re.DOTALL,
)


def _strip_think(text: str) -> str:
    """剥 ... / <thinking>...</thinking> 块 (推理模型 CoT)."""
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned


def spec_to_plan_structured(llm, spec: str) -> Plan:
    """主路: function_calling (大部分 provider 稳)."""
    return llm.with_structured_output(Plan, method="function_calling").invoke(
        PLAN_PROMPT.format(spec=spec)
    )


def spec_to_plan_fallback(llm, spec: str) -> Plan:
    """备路: text → 剥 think → PydanticOutputParser."""
    parser = PydanticOutputParser(pydantic_object=Plan)
    chain = PLAN_PROMPT | llm | StrOutputParser() | RunnableLambda(_strip_think) | parser
    return chain.invoke({"spec": spec})


def spec_to_plan(llm, spec: str) -> Plan:
    """双轨: 主路失败 → 备路."""
    try:
        plan = spec_to_plan_structured(llm, spec)
        print("  (主路 function_calling OK)")
        return plan
    except Exception as e:
        print(f"  (主路失败: {type(e).__name__}: {str(e)[:80]}, 切备路)")
        return spec_to_plan_fallback(llm, spec)


__all__ = [
    "Plan", "FileSpec", "FunctionSpec",
    "PLAN_PROMPT",
    "spec_to_plan_structured", "spec_to_plan_fallback", "spec_to_plan",
]
