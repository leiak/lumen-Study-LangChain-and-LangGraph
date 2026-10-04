"""retrievers.py — 共享 retrievers: BM25 (keyword), semantic (embedding), hybrid (RRF fusion).

教学 RAG 检索三模式:
  - BM25: 关键词匹配, 强 recall 但弱语义 (e.g. "RAG" 不匹配 "retrieval augmented")
  - semantic: 向量相似度, 弱 keyword 但强语义
  - hybrid: 两者 fused via RRF (Reciprocal Rank Fusion)

💡 设计要点:
  - 用 rank_bm25 (轻量 BM25 实现, ~25 KB 无依赖)
  - semantic 用 L1 safe_vectorstore 模式 (embedding 探测 fallback)
  - RRF fusion 不依赖 score, 只依赖 rank (更鲁棒 — 跨 retriever score 不可比)
  - RetrievalHit 把 doc/score/rank/source 绑一起, 便于在 hybrid pipeline 里来回传
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

# Type-only imports — 避免运行时强依赖 langchain_core.vectorstores (测试时只 import doc OK)
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore


@dataclass
class RetrievalHit:
    """单条检索命中.

    Attributes:
        doc: 命中的 Document
        score: 原始 score — BM25 score / semantic distance / RRF 融合分
               (不同 retriever 单位不同, 跨 retriever 不可比)
        rank: 在该 retriever 内的排名 (0-indexed)
        source: "bm25" / "semantic" / "rrf"
        doc_key: stable content-based key — (page_content, sorted metadata).
                 用于 RRF dedup + precision/recall 评估, 避免跨 retriever 时
                 Python object id() 不同导致去重失效.
    """
    doc: Document
    score: float
    rank: int
    source: str
    doc_key: tuple = ()

    def __post_init__(self) -> None:
        if not self.doc_key:
            self.doc_key = doc_key(self.doc)


def doc_key(doc: Document) -> tuple:
    """Stable content-based key for dedup + evaluation.

    Why not id(doc)?
      semantic_search 返回的是 FAISS 反序列化的新 Document 对象,
      跟原始 corpus 里 doc 的 id() 不同 → RRF dedup 失效, precision/recall 误判.

    Key 组成: (page_content, sorted(metadata.items())) — 教学语料稳定,
    真实场景如有 UUID / doc_id metadata, 那个字段更稳.
    """
    return (doc.page_content, tuple(sorted(doc.metadata.items())))


def tokenize(text: str) -> list[str]:
    """简单 tokenize: lowercase + 按 \\b\\w+\\b 切词, 去标点.

    教学用 — 真实项目可以接 jieba (中文) / spaCy / tiktoken.
    """
    return re.findall(r"\b\w+\b", text.lower())


def bm25_search(
    docs: list[Document],
    query: str,
    k: int = 10,
) -> list[RetrievalHit]:
    """BM25 keyword search.

    Args:
        docs: 候选 doc 集合
        query: 查询字符串
        k: 返回 top-k

    Returns:
        top-k hits sorted by BM25 score desc.

    💡 BM25 公式: 每个 doc 的 score = sum over query terms of
       IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D|/avgdl))
       默认 k1=1.5, b=0.75. 词频饱和 + 文档长度归一化.
    """
    corpus = [tokenize(d.page_content) for d in docs]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query))
    # sorted: (idx, score), desc by score, top-k
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
    return [
        RetrievalHit(doc=docs[i], score=float(s), rank=r, source="bm25")
        for r, (i, s) in enumerate(ranked)
    ]


def semantic_search(
    vectorstore: VectorStore,
    query: str,
    k: int = 10,
) -> list[RetrievalHit]:
    """Semantic search via embedding similarity (cosine / L2).

    Args:
        vectorstore: LangChain VectorStore (已 populate 过 doc)
        query: 查询
        k: top-k

    Returns:
        top-k hits sorted by similarity desc (score 越大越相似 — FAISS 用 L2 时取负).

    💡 FAISS similarity_search_with_score 默认 L2 distance, 越小越相似.
       这里我们不再翻转 score (因为 RRF 只看 rank, 不看 score),
       但下游如果用 score 做阈值过滤要注意方向.
    """
    docs_and_scores = vectorstore.similarity_search_with_score(query, k=k)
    return [
        RetrievalHit(doc=d, score=float(s), rank=r, source="semantic")
        for r, (d, s) in enumerate(docs_and_scores)
    ]


def reciprocal_rank_fusion(
    hit_lists: list[list[RetrievalHit]],
    k: int = 60,
) -> list[RetrievalHit]:
    """RRF 融合多个 ranked list.

    RRF score = sum( 1 / (k_const + rank_i) ) for each list
    - k_const=60 是原论文 (Cormack et al. 2009) 推荐值
    - 不依赖原始 score, 只依赖 rank — 跨 retriever score 不可比时尤其有用
    - 同 doc 出现在多个 list 时, 分数累加 (自然 dedup + 加权)

    Args:
        hit_lists: 多个 ranked hit 列表 (不同 retriever 输出)
        k: RRF 常数 (default 60)

    Returns:
        fused ranked list, score desc.

    💡 Dedup 用 hit.doc_key (content-based) 不是 id(hit.doc),
       因为 cross-retriever 时 doc 是不同 Python 对象 (FAISS 反序列化).
    """
    rrf_scores: dict[tuple, float] = defaultdict(float)
    hit_map: dict[tuple, RetrievalHit] = {}
    for hits in hit_lists:
        for hit in hits:
            key = hit.doc_key
            rrf_scores[key] += 1.0 / (k + hit.rank + 1)  # +1 因为 rank 0-indexed
            if key not in hit_map:
                hit_map[key] = hit
    fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [
        RetrievalHit(
            doc=hit_map[key].doc,
            score=score,
            rank=r,
            source="rrf",
            doc_key=key,
        )
        for r, (key, score) in enumerate(fused)
    ]


__all__ = [
    "RetrievalHit",
    "doc_key",
    "tokenize",
    "bm25_search",
    "semantic_search",
    "reciprocal_rank_fusion",
]
