"""02_reranking.py — Demo 2: Reranking pipeline (initial top-20 → rerank to top-5).

教学目标: 两阶段 retrieval — 初检索 recall 高, rerank precision 高.

学完这个 demo 你能回答:
1.  为什么需要 rerank? 直接 semantic top-5 不行吗?
2.  Cross-encoder vs bi-encoder 差别? 为什么 rerank 用 cross-encoder?
3.  Mock cross-encoder (词重叠) vs 真实 cross-encoder (BERT) 差距在哪?
4.  LLM-based rerank 适用场景 + 成本权衡?
5.  怎么评估 rerank 效果 (e.g. top-5 doc id 变化)?

跑法:
    python 02_reranking.py

💡 不需要真实 API key 也能跑 cross-encoder mock 路径.
   LLM reranker 部分会调 LLM, 需要 .env 里至少一个 provider 有 key.
"""
from __future__ import annotations

import asyncio

from _common import banner, get_llm, get_sample_corpus, get_safe_vectorstore, step
from rerankers import RerankResult, cross_encoder_mock, llm_rerank
from retrievers import RetrievalHit, semantic_search


# ============================================================
# Demo
# ============================================================
async def main() -> None:
    banner("Demo 2: Reranking (top-20 → rerank to top-5)")

    # 构造 corpus + 向量库
    step(1, "构造 corpus + 向量库")
    corpus = get_sample_corpus()
    vectorstore = get_safe_vectorstore(corpus)
    print(f"  vectorstore ready: {vectorstore.index.ntotal} vectors")

    query = "how to combine keyword and embedding retrieval"
    print(f"  query: '{query}'")

    # ---- Step 2: 初检索 top-20 (semantic) ----
    step(2, "初检索 top-20 (semantic — recall 高 precision 低)")
    initial_hits = semantic_search(vectorstore, query, k=20)
    print(f"  retrieved: {len(initial_hits)} hits")
    print(f"  top-5 (no rerank):")
    for h in initial_hits[:5]:
        print(f"    [{h.rank}] score={h.score:.3f}  id={h.doc.metadata['id']:<4}  {h.doc.page_content[:60]}")

    # ---- Step 3: Mock cross-encoder rerank ----
    step(3, "Mock cross-encoder rerank → top-5 (词重叠)")
    mock_reranked = cross_encoder_mock(query, initial_hits, top_k=5)
    print("  reranked (mock cross-encoder):")
    for r in mock_reranked:
        print(f"    [{r.rank}] score={r.rerank_score:.3f}  was [{r.hit.rank}]  id={r.hit.doc.metadata['id']:<4}  {r.hit.doc.page_content[:60]}")

    # ---- Step 4: LLM rerank ----
    step(4, "LLM rerank → top-5 (需要 API key, 失败则降级)")
    try:
        llm = get_llm(temperature=0.0)
        # 给 LLM 喂 top-10 (太多 → 浪费 token + prompt 超长; 太少 → 没意义)
        llm_input = initial_hits[:10]
        llm_reranked = await llm_rerank(llm, query, llm_input, top_k=5)
        print(f"  LLM reranked {len(llm_input)} → top-{len(llm_reranked)}:")
        for r in llm_reranked:
            print(f"    [{r.rank}] score={r.rerank_score:.3f}  id={r.hit.doc.metadata['id']:<4}  {r.hit.doc.page_content[:60]}")
    except Exception as e:
        print(f"  >>> LLM rerank 跳过 ({type(e).__name__}: {str(e)[:80]})")
        print(f"  >>> Mock 路径已展示核心流程, LLM 路径需 .env 里配 API key")
        llm_reranked = []

    # ---- Step 5: 对比 ----
    step(5, "对比 mock vs LLM rerank 结果")
    mock_ids = [r.hit.doc.metadata["id"] for r in mock_reranked]
    llm_ids = [r.hit.doc.metadata["id"] for r in llm_reranked]
    initial_top5_ids = [h.doc.metadata["id"] for h in initial_hits[:5]]

    print(f"  Initial top-5     : {initial_top5_ids}")
    print(f"  Mock rerank top-5 : {mock_ids}")
    if llm_reranked:
        print(f"  LLM rerank top-5  : {llm_ids}")
        # Rerank 跟初检索的差异 — 看哪些 doc 被换上来 / 换下去
        mock_moved = set(mock_ids) - set(initial_top5_ids)
        llm_moved = set(llm_ids) - set(initial_top5_ids)
        print(f"  Mock 比 initial 多: {sorted(mock_moved) or '(无)'}")
        print(f"  LLM  比 initial 多: {sorted(llm_moved) or '(无)'}")

    # 💡 教学要点:
    # - rerank 解决了 bi-encoder 的 "approx nearest neighbor 不是真正的相关" 问题
    # - cross-encoder 用 (query, doc) 联合 attention → 准, 但 N 倍开销
    # - 所以 pipeline: cheap bi-encoder 召回 top-50, 然后 cross-encoder rerank 到 top-5
    # - LLM rerank 是 cross-encoder 没有部署 / 想要更灵活 prompt 时的 fallback


if __name__ == "__main__":
    asyncio.run(main())
