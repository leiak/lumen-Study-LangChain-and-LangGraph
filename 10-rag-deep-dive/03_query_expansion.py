"""03_query_expansion.py — Demo 3: Query Expansion (HyDE + Multi-Query).

教学目标: 弥补 short query 的语义稀疏 — 用 LLM 扩写 / 生成假 doc.

学完这个 demo 你能回答:
1.  HyDE (Hypothetical Document Embeddings) 是什么? 为什么能提 recall?
2.  Multi-query vs HyDE 适用场景差异?
3.  怎么用 LLM 生成 hypothetical doc (prompt + parsing)?
4.  怎么 merge 多路 retrieval 结果 (RRF 复用)?
5.  query expansion + rerank 联合使用的 pipeline 长啥样?

跑法:
    python 03_query_expansion.py

💡 HyDE + Multi-query 都需要 LLM, 需要 .env 配 key.
   LLM 失败时整个 demo 报错 — 这是预期行为 (query expansion 本来就需要 LLM).
"""
from __future__ import annotations

import asyncio

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from _common import banner, get_llm, get_sample_corpus, get_safe_vectorstore, step
from rerankers import cross_encoder_mock
from retrievers import (
    RetrievalHit,
    bm25_search,
    reciprocal_rank_fusion,
    semantic_search,
)


# ============================================================
# HyDE helper — LLM 生成 hypothetical doc, 用它的 embedding 检索
# ============================================================
async def hyde_retrieve(
    llm,
    vectorstore,
    query: str,
    k: int = 5,
) -> list[RetrievalHit]:
    """HyDE: 让 LLM 生成一个 hypothetical doc, 用它当 query 检索.

    原理: user query 通常短 + 不像 doc 风格 (e.g. 问句 vs 陈述句).
    LLM 生成的 hypothetical doc 风格接近真实 corpus → embedding 空间里更近.
    """
    step(1, f"HyDE: LLM 生成 hypothetical doc for '{query}'")
    response = await llm.ainvoke([
        SystemMessage(content=(
            "你是一个领域专家. 根据 user 的问题, 写一段 1-2 句的领域文档, "
            "风格接近百科条目 (不要直接回答问题, 而是写可能包含答案的背景知识)."
        )),
        HumanMessage(content=f"Question: {query}\n\n写一段相关的领域文档:"),
    ])
    hyde_doc = response.content if isinstance(response.content, str) else str(response.content)
    print(f"  hypothetical doc: {hyde_doc[:120]}...")

    step(2, "用 hypothetical doc 的 embedding 检索 top-k")
    # similarity_search 用 doc-style query 比 raw question 召回更高
    hits = semantic_search(vectorstore, hyde_doc, k=k)
    return hits


# ============================================================
# Multi-query helper — LLM 生成 N 个 query rewrite, 每条独立检索, RRF 融合
# ============================================================
async def multi_query_retrieve(
    llm,
    vectorstore,
    query: str,
    n_variants: int = 3,
    k_per_variant: int = 5,
) -> list[RetrievalHit]:
    """Multi-query: LLM 把 query 改写成 N 个变体, 每条独立检索, RRF 融合."""
    step(1, f"Multi-query: LLM 生成 {n_variants} 个 query 变体 for '{query}'")
    response = await llm.ainvoke([
        SystemMessage(content=(
            f"你是一个搜索 query 改写器. 把 user 的 query 改写成 {n_variants} 个语义相近但措辞不同的版本, "
            "帮助覆盖更多相关文档. 一行一个, 不要编号."
        )),
        HumanMessage(content=f"Original query: {query}\n\n改写 ({n_variants} 个变体):"),
    ])
    raw = response.content if isinstance(response.content, str) else str(response.content)
    # 简单 split: 每行一个, 去空
    variants = [line.strip("- ").strip() for line in raw.split("\n") if line.strip()]
    variants = [v for v in variants if v and v.lower() != query.lower()][:n_variants]
    # 如果 LLM 改写不够, 用原 query 补
    while len(variants) < n_variants:
        variants.append(query)
    print(f"  variants:")
    for i, v in enumerate(variants, 1):
        print(f"    [{i}] {v}")

    step(2, f"每条 variant 检索 top-{k_per_variant}, 然后 RRF 融合")
    all_hit_lists = []
    for i, v in enumerate(variants, 1):
        hits = semantic_search(vectorstore, v, k=k_per_variant)
        print(f"    variant [{i}] '{v[:40]}...' → top-{len(hits)} ids: {[h.doc.metadata['id'] for h in hits]}")
        all_hit_lists.append(hits)
    fused = reciprocal_rank_fusion(all_hit_lists, k=60)
    return fused[:k_per_variant]


# ============================================================
# Demo
# ============================================================
async def main() -> None:
    banner("Demo 3: Query Expansion (HyDE + Multi-Query)")

    # 构造 corpus + 向量库
    step(0, "构造 corpus + 向量库")
    corpus = get_sample_corpus()
    vectorstore = get_safe_vectorstore(corpus)
    print(f"  corpus: {len(corpus)} docs")

    # 用一个 query 走三路对比
    query = "how to improve RAG retrieval accuracy"

    # ---- Step A: baseline (no expansion) ----
    banner("A. Baseline (无 expansion)")
    baseline_hits = semantic_search(vectorstore, query, k=5)
    for h in baseline_hits:
        print(f"  [{h.rank}] score={h.score:.3f}  id={h.doc.metadata['id']:<4}  {h.doc.page_content[:60]}")

    # ---- Step B: HyDE ----
    banner("B. HyDE (生成 hypothetical doc → 检索)")
    try:
        llm = get_llm(temperature=0.0)
        hyde_hits = await hyde_retrieve(llm, vectorstore, query, k=5)
        print(f"  HyDE top-{len(hyde_hits)}:")
        for h in hyde_hits:
            print(f"    [{h.rank}] score={h.score:.3f}  id={h.doc.metadata['id']:<4}  {h.doc.page_content[:60]}")
    except Exception as e:
        print(f"  >>> HyDE 失败 ({type(e).__name__}: {str(e)[:80]})")
        hyde_hits = []

    # ---- Step C: Multi-query ----
    banner("C. Multi-query (改写 query → 多路检索 → RRF 融合)")
    try:
        if not hyde_hits and "llm" not in locals():
            llm = get_llm(temperature=0.0)
        mq_hits = await multi_query_retrieve(llm, vectorstore, query, n_variants=3, k_per_variant=5)
        print(f"  Multi-query top-{len(mq_hits)}:")
        for h in mq_hits:
            print(f"    [{h.rank}] rrf={h.score:.4f}   id={h.doc.metadata['id']:<4}  {h.doc.page_content[:60]}")
    except Exception as e:
        print(f"  >>> Multi-query 失败 ({type(e).__name__}: {str(e)[:80]})")
        mq_hits = []

    # ---- Step D: expansion + rerank 联合 ----
    banner("D. Expansion (BM25 + Multi-query) + Rerank 联合 pipeline")
    try:
        if "llm" not in locals():
            llm = get_llm(temperature=0.0)
        # Stage 1: BM25 + Multi-query semantic → RRF 融合 → top-10
        bm25_hits = bm25_search(corpus, query, k=10)
        mq_input_hits = await multi_query_retrieve(llm, vectorstore, query, n_variants=3, k_per_variant=5)
        stage1_hits = reciprocal_rank_fusion([bm25_hits, mq_input_hits], k=60)[:10]
        print(f"\n  Stage 1 (BM25 + Multi-query RRF): top-{len(stage1_hits)}")
        for h in stage1_hits:
            print(f"    [{h.rank}] rrf={h.score:.4f}   id={h.doc.metadata['id']:<4}  {h.doc.page_content[:50]}")

        # Stage 2: Cross-encoder rerank → top-5
        step(99, "Stage 2: Cross-encoder rerank → top-5")
        reranked = cross_encoder_mock(query, stage1_hits, top_k=5)
        print(f"  Final top-{len(reranked)}:")
        for r in reranked:
            print(f"    [{r.rank}] score={r.rerank_score:.3f}  was [{r.hit.rank}]  id={r.hit.doc.metadata['id']:<4}  {r.hit.doc.page_content[:50]}")
    except Exception as e:
        print(f"  >>> Pipeline 失败 ({type(e).__name__}: {str(e)[:80]})")

    # 💡 教学要点:
    # - HyDE: 适合 query 短 / 抽象 / 跟 corpus 风格不匹配
    # - Multi-query: 适合 query 模糊 / 可能有多种语义
    # - 两者都贵 (LLM forward), 但 recall 显著提 — 上游 recall 提了, 下游 rerank 才好做
    # - production 里通常只选一个 (cost / latency 限制), 用 eval 决定


if __name__ == "__main__":
    asyncio.run(main())
