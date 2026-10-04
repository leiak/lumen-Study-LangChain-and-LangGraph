"""evaluators.py — 共享 RAG 评估: precision@k / recall@k / faithfulness (LLM judge).

教学 RAG eval 关键指标:
  - precision@k: 前 k 个 hit 中, 相关 doc 比例 — 衡量检索准不准
  - recall@k:    所有相关 doc 中, 前 k 个覆盖的比例 — 衡量检索全不全
  - faithfulness: 生成答案是否基于 retrieved docs (无 hallucination) — LLM judge

💡 设计要点:
  - relevance ground truth 来自 sample corpus 标签 (doc.metadata["id"])
  - relevance key 用 doc_key(doc) — content-based, 跨 retriever 稳定
    (semantic_search 返回 FAISS 反序列化的新对象, id(doc) 会变)
  - LLM judge 用 MiniMax M3, prompt 明确 yes/no 输出 — 容忍大小写 / 解释前后缀
  - 不假设完美 label, 加 partial match (precision/recall 都给 0-1)
"""
from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from retrievers import RetrievalHit, doc_key


@dataclass
class EvalResult:
    """Eval 结果.

    Attributes:
        metric: 指标名 (e.g. "precision@5" / "recall@10" / "faithfulness")
        value: 0-1 之间的值
        details: 解释字符串 (用于打印 / 调试)
    """
    metric: str
    value: float
    details: str


def precision_at_k(
    hits: list[RetrievalHit],
    relevant_keys: set[tuple],
    k: int = 5,
) -> EvalResult:
    """precision@k = (top-k 中 relevant 数) / k.

    Args:
        hits: ranked retrieval hits
        relevant_keys: relevant doc 的 doc_key 集合 (从 doc_key(doc) 得来)
        k: 取 top-k

    Returns:
        EvalResult(metric="precision@{k}", value=0-1, details=...)
    """
    top_k = hits[:k]
    relevant_count = sum(1 for h in top_k if h.doc_key in relevant_keys)
    precision = relevant_count / k if k > 0 else 0.0
    return EvalResult(
        metric=f"precision@{k}",
        value=precision,
        details=f"{relevant_count}/{k} top-k hits are relevant",
    )


def recall_at_k(
    hits: list[RetrievalHit],
    relevant_keys: set[tuple],
    k: int = 10,
) -> EvalResult:
    """recall@k = (top-k 中 relevant 数) / (总 relevant 数).

    Args:
        hits: ranked retrieval hits
        relevant_keys: relevant doc 的 doc_key 集合
        k: 取 top-k

    Returns:
        EvalResult(metric="recall@{k}", value=0-1, details=...)

    💡 如果 ground truth 为空 (relevant_keys 空集), 返回 0 + 说明,
       避免 ZeroDivisionError + 隐式 "召回完美".
    """
    top_k = hits[:k]
    retrieved_relevant = {h.doc_key for h in top_k if h.doc_key in relevant_keys}
    if not relevant_keys:
        return EvalResult(metric=f"recall@{k}", value=0.0, details="no ground truth")
    recall = len(retrieved_relevant) / len(relevant_keys)
    return EvalResult(
        metric=f"recall@{k}",
        value=recall,
        details=f"{len(retrieved_relevant)}/{len(relevant_keys)} relevant docs retrieved",
    )


async def faithfulness_judge(
    llm: BaseChatModel,
    question: str,
    answer: str,
    retrieved_docs: list[Document],
) -> EvalResult:
    """LLM judge: answer 是否完全基于 retrieved docs (无 hallucination).

    Args:
        llm: LangChain BaseChatModel (用 ainvoke)
        question: 用户原始问题
        answer: LLM 生成的答案
        retrieved_docs: 检索到的 context docs

    Returns:
        EvalResult(metric="faithfulness", value=1.0 (YES) / 0.0 (NO), details=judge 原文前 50 字符)

    💡 输出约束:
       - 让 LLM 输出 "YES" 或 "NO" 即可, 不要 JSON / 解释 (小模型经常在 JSON 边缘 case 失败)
       - 解析时大小写无关, 同时检查 YES 和 NO — 防 "NO, ... " 误判
    """
    if not retrieved_docs:
        return EvalResult(
            metric="faithfulness",
            value=0.0,
            details="no docs to check",
        )

    context = "\n\n".join(
        f"[Doc {i}] {d.page_content[:200]}" for i, d in enumerate(retrieved_docs)
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "你是 RAG faithfulness 评估员. "
            "判断给定的 answer 是否完全基于提供的 docs (无幻觉 / 无外部知识). "
            "严格只输出 'YES' 或 'NO', 不加任何解释.",
        ),
        (
            "human",
            "Question: {q}\n\nDocs:\n{ctx}\n\nAnswer: {a}\n\n"
            "answer 是否完全基于 docs (无幻觉)? 输出 YES 或 NO:",
        ),
    ])

    response = await llm.ainvoke(
        prompt.format_messages(q=question, ctx=context, a=answer)
    )
    verdict_raw = response.content if isinstance(response.content, str) else str(response.content)
    verdict = verdict_raw.strip().upper()

    # 同时检查 YES 和 NO: 防 "NO, but actually YES" 这种模型嘀咕被误判
    is_yes = verdict.startswith("YES")
    is_no = verdict.startswith("NO")
    is_faithful = bool(is_yes) and not is_no

    return EvalResult(
        metric="faithfulness",
        value=1.0 if is_faithful else 0.0,
        details=f"judge: {verdict_raw[:50]!r}",
    )


__all__ = [
    "EvalResult",
    "precision_at_k",
    "recall_at_k",
    "faithfulness_judge",
]
