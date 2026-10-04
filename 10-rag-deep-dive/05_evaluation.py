"""05_evaluation.py — Demo 5: RAG Evaluation (precision@k + recall@k + faithfulness).

教学目标: 评估 RAG 系统的三个核心指标 + 端到端 Q&A faithfulness.

学完这个 demo 你能回答:
1.  precision@k vs recall@k 公式? 什么时候一个高一个低?
2.  ground truth 怎么建? 完全人工 vs partial label?
3.  faithfulness (无幻觉) 怎么用 LLM judge?
4.  怎么批量跑 eval + 聚合报告?
5.  怎么把评估结果写到 output/ 持久化?

跑法:
    python 05_evaluation.py

💡 precision/recall 部分不需要 API key (BM25/hybrid 是纯算法).
   faithfulness 部分需要 LLM judge, 失败时该 query 跳过, 不阻塞其它 query.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from langchain_core.documents import Document

from _common import banner, get_eval_queries, get_llm, get_sample_corpus, get_safe_vectorstore, output_dir, step
from evaluators import EvalResult, faithfulness_judge, precision_at_k, recall_at_k
from rerankers import cross_encoder_mock
from retrievers import RetrievalHit, bm25_search, doc_key, reciprocal_rank_fusion, semantic_search


# ============================================================
# Ground truth 工具 — 把 doc id 集合映射成 doc_key 集合 (content-based)
# ============================================================
def build_relevant_set(corpus: list[Document], relevant_ids: set[str]) -> set[tuple]:
    """把 ground-truth doc id 字符串 (e.g. {'d2'}) 转成 doc_key 集合.

    为什么用 doc_key 不用 id(doc)?
    - 我们的 relevance 判断函数 (precision_at_k / recall_at_k) 用 hit.doc_key
    - doc_key 是 content-based (page_content + metadata), 跨 retriever 稳定
    - 而 semantic_search 返回的是 FAISS 反序列化的新对象, id(doc) 不同
    """
    return {doc_key(d) for d in corpus if d.metadata.get("id") in relevant_ids}


# ============================================================
# End-to-end Q&A — hybrid retrieve + LLM generate
# ============================================================
async def answer_question(llm, query: str, retrieved_docs: list[Document]) -> str:
    """用 retrieved docs 作为 context, 让 LLM 生成 answer."""
    context = "\n\n".join(f"[{i+1}] {d.page_content}" for i, d in enumerate(retrieved_docs))
    response = await llm.ainvoke(
        f"基于以下参考资料回答问题. 如果资料里没答案, 就说'资料不足'. 简洁回答.\n\n"
        f"参考资料:\n{context}\n\n问题: {query}\n\n答案:"
    )
    content = response.content if isinstance(response.content, str) else str(response.content)
    return content.strip()


# ============================================================
# Demo
# ============================================================
async def main() -> None:
    banner("Demo 5: RAG Evaluation (precision@k / recall@k / faithfulness)")

    # ---- 构造 corpus + 向量库 ----
    step(1, "构造 corpus + 向量库 + ground truth queries")
    corpus = get_sample_corpus()
    vectorstore = get_safe_vectorstore(corpus)
    eval_queries = get_eval_queries()
    print(f"  corpus: {len(corpus)} docs")
    print(f"  eval queries: {len(eval_queries)} (各带 ground-truth relevant doc id)")

    # ---- Step 2: 跑 hybrid retrieval + 算 precision@k + recall@k ----
    step(2, "Hybrid retrieval (BM25 + Semantic + RRF) → precision@5 + recall@5")

    p_at_5_list: list[EvalResult] = []
    r_at_5_list: list[EvalResult] = []

    print(f"\n  {'Query':<35} {'P@5':>6} {'R@5':>6}  Top-5 doc ids")
    print(f"  {'-'*35} {'-'*6} {'-'*6}  {'-'*30}")

    for eq in eval_queries:
        q = eq["q"]
        relevant_ids = build_relevant_set(corpus, eq["relevant"])

        # Hybrid retrieve top-5
        bm25_hits = bm25_search(corpus, q, k=5)
        sem_hits = semantic_search(vectorstore, q, k=5)
        fused = reciprocal_rank_fusion([bm25_hits, sem_hits], k=60)[:5]

        p = precision_at_k(fused, relevant_ids, k=5)
        r = recall_at_k(fused, relevant_ids, k=5)
        p_at_5_list.append(p)
        r_at_5_list.append(r)

        top5_ids = [h.doc.metadata["id"] for h in fused]
        print(f"  {q:<35} {p.value:>6.2f} {r.value:>6.2f}  {top5_ids}")

    # 聚合
    avg_p = sum(p.value for p in p_at_5_list) / len(p_at_5_list)
    avg_r = sum(r.value for r in r_at_5_list) / len(r_at_5_list)
    print(f"\n  聚合 (avg over {len(eval_queries)} queries):")
    print(f"    avg precision@5 = {avg_p:.3f}")
    print(f"    avg recall@5    = {avg_r:.3f}")

    # ---- Step 3: 端到端 Q&A + faithfulness ----
    step(3, "端到端 RAG: hybrid retrieval (top-3) → LLM 生成 → faithfulness judge")

    faith_results: list[dict] = []
    try:
        llm = get_llm(temperature=0.0)
        have_llm = True
    except Exception as e:
        print(f"  >>> LLM 不可用, faithfulness 跳过 ({type(e).__name__}: {str(e)[:80]})")
        llm = None
        have_llm = False

    if have_llm:
        for eq in eval_queries[:3]:  # 只跑前 3 个 — 节省 cost, 教学够用
            q = eq["q"]

            # Hybrid retrieve top-3
            bm25_hits = bm25_search(corpus, q, k=3)
            sem_hits = semantic_search(vectorstore, q, k=3)
            fused = reciprocal_rank_fusion([bm25_hits, sem_hits], k=60)[:3]
            retrieved_docs = [h.doc for h in fused]

            # Generate
            try:
                answer = await answer_question(llm, q, retrieved_docs)
            except Exception as e:
                print(f"  >>> generate 失败 for '{q}': {type(e).__name__}: {str(e)[:60]}")
                continue

            # Judge
            try:
                faith = await faithfulness_judge(llm, q, answer, retrieved_docs)
            except Exception as e:
                print(f"  >>> judge 失败 for '{q}': {type(e).__name__}: {str(e)[:60]}")
                continue

            print(f"\n  Q: {q}")
            print(f"  Retrieved ids: {[d.metadata['id'] for d in retrieved_docs]}")
            print(f"  Answer: {answer[:100]}{'...' if len(answer) > 100 else ''}")
            print(f"  Faithfulness: {faith.value:.0f} ({faith.details})")

            faith_results.append({
                "q": q,
                "answer_preview": answer[:120],
                "retrieved_ids": [d.metadata["id"] for d in retrieved_docs],
                "faithfulness": faith.value,
                "judge_detail": faith.details,
            })

        if faith_results:
            avg_faith = sum(r["faithfulness"] for r in faith_results) / len(faith_results)
            print(f"\n  聚合 faithfulness: {avg_faith:.2f} ({sum(r['faithfulness'] for r in faith_results):.0f}/{len(faith_results)})")

    # ---- Step 4: rerank pipeline 的 eval (对比 baseline) ----
    step(4, "rerank pipeline 评估 (BM25 + Semantic RRF top-10 → cross-encoder → top-3)")

    rerank_p_list: list[EvalResult] = []
    rerank_r_list: list[EvalResult] = []

    print(f"\n  {'Query':<35} {'P@3':>6} {'R@3':>6}  Top-3 doc ids")
    print(f"  {'-'*35} {'-'*6} {'-'*6}  {'-'*30}")

    for eq in eval_queries:
        q = eq["q"]
        relevant_ids = build_relevant_set(corpus, eq["relevant"])

        # Stage 1: hybrid top-10
        bm25_hits = bm25_search(corpus, q, k=10)
        sem_hits = semantic_search(vectorstore, q, k=10)
        stage1 = reciprocal_rank_fusion([bm25_hits, sem_hits], k=60)[:10]

        # Stage 2: rerank to top-3
        reranked = cross_encoder_mock(q, stage1, top_k=3)

        p = precision_at_k(reranked, relevant_ids, k=3)
        r = recall_at_k(reranked, relevant_ids, k=3)
        rerank_p_list.append(p)
        rerank_r_list.append(r)

        top3_ids = [r2.hit.doc.metadata["id"] for r2 in reranked]
        print(f"  {q:<35} {p.value:>6.2f} {r.value:>6.2f}  {top3_ids}")

    avg_rp = sum(p.value for p in rerank_p_list) / len(rerank_p_list)
    avg_rr = sum(r.value for r in rerank_r_list) / len(rerank_r_list)
    print(f"\n  聚合 (avg over {len(eval_queries)} queries):")
    print(f"    avg precision@3 = {avg_rp:.3f}  (rerank 后)")
    print(f"    avg recall@3    = {avg_rr:.3f}  (rerank 后)")

    # ---- Step 5: 报告写到 output/ ----
    step(5, "把评估报告写到 output/eval_report.json")
    report = {
        "corpus_size": len(corpus),
        "n_eval_queries": len(eval_queries),
        "hybrid_top5": {
            "avg_precision_at_5": round(avg_p, 4),
            "avg_recall_at_5": round(avg_r, 4),
            "per_query": [
                {"q": eq["q"], "p_at_5": p_at_5_list[i].value, "r_at_5": r_at_5_list[i].value}
                for i, eq in enumerate(eval_queries)
            ],
        },
        "rerank_top3": {
            "avg_precision_at_3": round(avg_rp, 4),
            "avg_recall_at_3": round(avg_rr, 4),
            "per_query": [
                {"q": eq["q"], "p_at_3": rerank_p_list[i].value, "r_at_3": rerank_r_list[i].value}
                for i, eq in enumerate(eval_queries)
            ],
        },
        "faithfulness": faith_results,
    }
    out_path = output_dir() / "eval_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  报告写入: {out_path}")
    print(f"  文件大小: {out_path.stat().st_size} 字节")

    # 💡 教学要点:
    # - precision/recall 是 retrieval 的硬指标 — 不需要 LLM judge, 可批量算
    # - faithfulness 是 generation 的软指标 — 需要 LLM judge (主观, 不稳定)
    # - production 通常: (1) 先 precision/recall 看 retrieval 改没改进 (2) 再 faithfulness 看生成质量
    # - 多 query 聚合: avg 是最弱指标 — median / per-query breakdown 更有信息


if __name__ == "__main__":
    asyncio.run(main())
