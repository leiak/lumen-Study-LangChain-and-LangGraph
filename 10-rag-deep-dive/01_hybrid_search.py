"""01_hybrid_search.py — Demo 1: Hybrid Search (BM25 + semantic + RRF fusion).

教学目标: 三种 retrieval 模式对比, 看清 RRF 的价值.

学完这个 demo 你能回答:
1.  BM25 vs semantic 各自强项 / 弱项是什么? 什么时候一个赢一个输?
2.  RRF 融合公式是什么? 为什么用 rank 不用 score?
3.  hybrid 在哪些 query 类型上比单模式强?
4.  怎么用 set / dict 算 hit list 的 overlap, 评估融合效果?
5.  怎么给 RAG pipeline 加 hybrid 模式 (retriever 包一层)?

跑法:
    python 01_hybrid_search.py
"""
from __future__ import annotations

import asyncio

from _common import banner, get_sample_corpus, get_safe_vectorstore, step
from retrievers import (
    RetrievalHit,
    bm25_search,
    reciprocal_rank_fusion,
    semantic_search,
)


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 1: Hybrid Search (BM25 + Semantic + RRF)")

    # 构造 corpus + 向量库
    step(1, "构造 sample corpus (10 条) + 向量库")
    corpus = get_sample_corpus()
    print(f"  corpus size: {len(corpus)} docs")
    print(f"  topics: {sorted({d.metadata['topic'] for d in corpus})}")
    vectorstore = get_safe_vectorstore(corpus)
    print(f"  vectorstore ready: {vectorstore.index.ntotal} vectors")

    # 测试 query — 故意选一个 keyword 强 (BM25 友好) + 一个语义强 (semantic 友好)
    queries = [
        ("RAG retrieval augmented", "keyword 强 — 'RAG' 是精确术语"),
        ("how to combine different retrievers", "语义强 — 自然语言, 没 'RRF' 字面"),
    ]

    for q_idx, (query, hint) in enumerate(queries, 1):
        banner(f"Query {q_idx}: '{query}' ({hint})")

        # ---- BM25 ----
        step(1, f"BM25 检索 top-5")
        bm25_hits = bm25_search(corpus, query, k=5)
        for h in bm25_hits:
            print(f"  [{h.rank}] score={h.score:.3f}  id={h.doc.metadata['id']:<4}  {h.doc.page_content[:70]}")

        # ---- Semantic ----
        step(2, f"Semantic 检索 top-5")
        sem_hits = semantic_search(vectorstore, query, k=5)
        for h in sem_hits:
            print(f"  [{h.rank}] score={h.score:.3f}  id={h.doc.metadata['id']:<4}  {h.doc.page_content[:70]}")

        # ---- Hybrid (RRF) ----
        step(3, f"Hybrid (RRF 融合 BM25 + Semantic) top-5")
        hybrid_hits = reciprocal_rank_fusion([bm25_hits, sem_hits], k=60)[:5]
        for h in hybrid_hits:
            print(f"  [{h.rank}] rrf={h.score:.4f}   id={h.doc.metadata['id']:<4}  {h.doc.page_content[:70]}")

        # ---- Overlap 分析 ----
        step(4, f"Overlap 分析 (BM25 vs Semantic vs Hybrid)")
        bm25_ids = {h.doc.metadata["id"] for h in bm25_hits}
        sem_ids = {h.doc.metadata["id"] for h in sem_hits}
        hyb_ids = {h.doc.metadata["id"] for h in hybrid_hits}

        print(f"  BM25 top-5     : {sorted(bm25_ids)}")
        print(f"  Semantic top-5 : {sorted(sem_ids)}")
        print(f"  Hybrid top-5   : {sorted(hyb_ids)}")
        print(f"  BM25 ∩ Semantic: {sorted(bm25_ids & sem_ids)}  ({len(bm25_ids & sem_ids)} docs)")
        print(f"  Hybrid 独有    : {sorted(hyb_ids - bm25_ids - sem_ids)}  ({len(hyb_ids - bm25_ids - sem_ids)} docs)")

        # 💡 关键观察: hybrid 不只是 "两者平均" — RRF 让在两个 list 都 top 的 doc 大幅上升
        # 单独在某个 list top 的 doc 也会保留 (分数低一些)
        # 这是为什么 hybrid 通常 recall 比单模式高 — 同时保留两种信号


if __name__ == "__main__":
    main()
