"""rerankers.py — 共享 rerankers: cross-encoder (mock) + LLM-based.

教学 RAG rerank pipeline:
  - 初检索 top-50 (recall 高, precision 低)
  - rerank 缩到 top-5 (precision 高)
  - cross-encoder: query + doc 一起 encode (准, 但慢) — 教学用 mock
  - LLM-based: 让 LLM 打分 (灵活, 但贵, 慢)

💡 设计要点:
  - Cross-encoder mock: deterministic (词重叠) — 不依赖外部模型, smoke test 也能跑
  - LLM reranker: async (ainvoke), MiniMax M3 prompt 明确打分格式 "doc_N: score"
  - 真实 cross-encoder: sentence-transformers CrossEncoder(model_name) — 教学不引入重型依赖
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from retrievers import RetrievalHit, tokenize


@dataclass
class RerankResult:
    """Rerank 结果.

    Attributes:
        hit: 原始 RetrievalHit (保留 doc + 原始 score 便于追溯)
        rerank_score: reranker 给的分数 (0-1)
        rank: rerank 后排名 (0-indexed)
        doc_key: 透传自 hit.doc_key — 让 RerankResult 也能直接喂给
                 precision_at_k / recall_at_k (不用 .hit.doc_key 绕一圈)
    """
    hit: RetrievalHit
    rerank_score: float
    rank: int
    doc_key: tuple = ()

    def __post_init__(self) -> None:
        if not self.doc_key:
            self.doc_key = self.hit.doc_key


def cross_encoder_mock(
    query: str,
    hits: list[RetrievalHit],
    top_k: int = 5,
) -> list[RerankResult]:
    """Mock cross-encoder: query-doc token overlap ratio (Jaccard-style).

    真实 cross-encoder (e.g. sentence-transformers/cross-encoder/ms-marco-MiniLM-L-6-v2)
    把 (query, doc) 拼起来过 BERT, 取 [CLS] embedding 过分类头. 准, 但 GPU 依赖.

    这里用词重叠做 deterministic mock — 优点:
      - 无外部依赖, smoke test 可跑
      - 行为可预测, 教学一致
      - 对短 doc (教学语料) 接近真实 cross-encoder 的 ranking

    Args:
        query: 搜索 query
        hits: 初检索 hits (e.g. semantic_search top-20)
        top_k: 返回 top-k (default 5)

    Returns:
        top-k RerankResult sorted by overlap score desc.
    """
    q_tokens = set(tokenize(query))
    if not q_tokens:
        return []
    scored = []
    for hit in hits:
        d_tokens = set(tokenize(hit.doc.page_content))
        # 重叠率 = |交集| / |query tokens| (按 query 长度归一化, 不被 doc 长度稀释)
        overlap = len(q_tokens & d_tokens) / len(q_tokens)
        scored.append((hit, overlap))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [
        RerankResult(hit=h, rerank_score=s, rank=r)
        for r, (h, s) in enumerate(scored[:top_k])
    ]


# MiniMax M3 (跟其它小模型一样) 偶尔吐 CoT 或额外解释, regex 严格抓 "doc_N: score" 行
_RERANK_LINE_RE = re.compile(r"doc_(\d+)\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


async def llm_rerank(
    llm: BaseChatModel,
    query: str,
    hits: list[RetrievalHit],
    top_k: int = 5,
) -> list[RerankResult]:
    """LLM-based rerank: 让 LLM 对每个 doc 打分 (0-10), 归一化到 0-1.

    适合 doc 长 / 语义复杂 / 没有 cross-encoder 模型的场景.
    代价: N 次 LLM forward (此处一次性给所有 doc 让它一次性打分, 省 round-trip).

    Args:
        llm: LangChain BaseChatModel (用 ainvoke, 不要 invoke)
        query: 搜索 query
        hits: 初检索 hits
        top_k: 返回 top-k (default 5)

    Returns:
        top-k RerankResult sorted by rerank score desc.
    """
    if not hits:
        return []

    # 截 doc 到 300 字符 — 控制 token + 教学一致
    docs_text = "\n\n".join(
        f"doc_{i}: {hit.doc.page_content[:300]}" for i, hit in enumerate(hits)
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "你是搜索相关性评分员. 根据 query 对每个 doc 打 0-10 分 "
            "(10=完美匹配, 0=完全不相关). "
            "严格按格式 'doc_N: score' 每行一个, 不要其它解释.",
        ),
        (
            "human",
            "Query: {query}\n\nDocs:\n{docs}\n\n评分 (一行一个 doc_N: score):",
        ),
    ])

    response = await llm.ainvoke(prompt.format_messages(query=query, docs=docs_text))
    content = response.content if isinstance(response.content, str) else str(response.content)

    # Parse "doc_N: score" lines — 容忍大小写 / 空白
    scores: dict[int, float] = {}
    for line in content.split("\n"):
        m = _RERANK_LINE_RE.search(line)
        if m:
            idx = int(m.group(1))
            score = float(m.group(2)) / 10.0  # 归一化 0-1
            scores[idx] = score

    # 按 score desc, 取 top_k. 没解析到的 doc 跳过 (LLM 漏打分 → 不进 rerank)
    reranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [
        RerankResult(hit=hits[i], rerank_score=score, rank=r)
        for r, (i, score) in enumerate(reranked)
        if 0 <= i < len(hits)
    ]


__all__ = [
    "RerankResult",
    "cross_encoder_mock",
    "llm_rerank",
]
