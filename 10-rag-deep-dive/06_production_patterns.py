"""06_production_patterns.py — Demo 6: 生产级 RAG patterns.

教学 4 类 production pattern:
  - Caching: 避免重复 LLM/embedding 调用 (cost + latency)
  - Async batch: 并发多个 retriever (BM25 + semantic + HyDE 同时跑)
  - Observability: cache hit rate + p95 latency
  - Multi-corpus eval: 同 query 在不同 corpus 表现

学完这个 demo 你能回答:
1.  RetrievalCache 为什么要 LRU + key 标准化? 不标准化会怎样?
2.  async.gather 如何并发 3 个 retriever? return_exceptions=True 解决什么?
3.  ObservabilityMetrics 的 cache_hit_rate / p95_latency 怎么算? 生产指标哪些必备?
4.  corpus 变大 (10→20 docs) 时 precision / recall 怎么变?
5.  cache 嵌入 retrieve 流水线: 哪一步放 cache 前/后? cost 模型怎么估?

跑法:
    python 06_production_patterns.py

💡 production.py 4 utility 纯 stdlib (无 LLM 依赖) — 主体不调 API key.
   Demo 7 用 mock async sleep 模拟并行 retriever, 跟 LLM 无关.
"""
from __future__ import annotations

import asyncio

from _common import (
    banner,
    get_eval_queries,
    get_sample_corpus,
    get_safe_vectorstore,
    step,
)
from production import (
    ObservabilityMetrics,
    RetrievalCache,
    gather_with_metrics,
    time_operation,
)
from retrievers import RetrievalHit, bm25_search, semantic_search


# ============================================================
# Demo
# ============================================================
def main() -> None:
    banner("Demo 6: Production Patterns — Cache / Async Batch / Observability")

    metrics = ObservabilityMetrics()
    corpus = get_sample_corpus()
    print(f"  corpus: {len(corpus)} docs")

    # --------------------------------------------------------
    # Step 1: RetrievalCache basic — 同一 query 跑 2 次, 看 cache hit
    # --------------------------------------------------------
    step(1, "RetrievalCache basic — 同一 query 跑 2 次, 看 cache hit")
    cache = RetrievalCache(max_size=100)

    # 第一次: miss → 真正检索 → 写 cache
    metrics.total_queries += 1
    with time_operation(metrics):
        hits_v1 = bm25_search(corpus, "What is RAG?", k=5)
    metrics.cache_misses += 1
    cache.put("What is RAG?", hits_v1)
    print(f"  query 1 (miss): {len(hits_v1)} hits, latency recorded")

    # 第二次: hit → 直接从 cache 拿 (无 BM25 计算)
    metrics.total_queries += 1
    with time_operation(metrics):
        cached = cache.get("What is RAG?")
    if cached is not None:
        metrics.cache_hits += 1
        print(f"  query 2 (hit) : {len(cached)} hits — skipped BM25 cost")
    else:
        print(f"  ⛔ cache miss unexpected")

    # 第三次: 新 query (miss again)
    metrics.total_queries += 1
    cached_unknown = cache.get("How does BM25 work?")
    if cached_unknown is None:
        metrics.cache_misses += 1
        print(f"  query 3 (miss): new query — would need fresh retrieval")

    print(f"  metrics so far: {metrics.summary()}")

    # --------------------------------------------------------
    # Step 2: LRU eviction — 填满 N entries 后插入第 N+1 个, 最旧的被淘汰
    # --------------------------------------------------------
    step(2, "LRU eviction — max_size=3, 插 5 个看哪些被淘汰")
    small_cache = RetrievalCache(max_size=3)
    for i in range(5):
        # 用稳定 doc 包装, 避免 RetrievalHit.__post_init__ 跑空 doc_key
        doc = corpus[i % len(corpus)]
        small_cache.put(f"query_{i}", [RetrievalHit(doc=doc, score=0.5, rank=0, source="bm25")])

    print(f"  cache size (max=3, inserted 5): {len(small_cache)}")
    remaining = [k for k in small_cache._cache.keys()]
    print(f"  remaining keys (in order, oldest→newest): {remaining}")
    # query_0, query_1 被淘汰, 留下 query_2, query_3, query_4
    assert "query_0" not in remaining, "query_0 应该被 LRU 淘汰"
    assert "query_1" not in remaining, "query_1 应该被 LRU 淘汰"
    assert "query_4" in remaining, "query_4 最新插入应保留"
    print(f"  ✓ query_0 / query_1 已被 LRU 淘汰, query_4 保留")

    # --------------------------------------------------------
    # Step 3: ObservabilityMetrics — cache hit rate + latency summary
    # --------------------------------------------------------
    step(3, "ObservabilityMetrics — cache hit rate + latency summary")
    print(f"  cache_hit_rate: {metrics.cache_hit_rate:.1%}")
    print(f"  avg_latency   : {metrics.avg_latency:.4f}s")
    print(f"  p95_latency   : {metrics.p95_latency:.4f}s")
    print(f"  full summary  : {metrics.summary()}")

    # --------------------------------------------------------
    # Step 4: Multi-corpus eval — 同 query 在 10-doc vs 20-doc corpus
    # --------------------------------------------------------
    step(4, "Multi-corpus eval — 同 query 在 10-doc vs 20-doc corpus")
    # 扩到 20-doc: 原 10 个 + 10 个 distractor
    extended_corpus = list(corpus) + [
        type(corpus[0])(
            page_content=f"Unrelated noise doc number {i}, not about RAG.",
            metadata={"id": f"d{11+i}", "topic": "noise"},
        )
        for i in range(10)
    ]
    print(f"  10-doc corpus: {len(corpus)} docs")
    print(f"  20-doc corpus: {len(extended_corpus)} docs (10 + 10 distractor)")

    queries = get_eval_queries()
    print(f"  eval queries: {len(queries)} (各带 ground-truth relevant doc id)")

    # 跑两个 corpus, 对比 precision@5
    print(f"\n  {'Query':<35} {'10-doc P@5':>12} {'20-doc P@5':>12}")
    print(f"  {'-'*35} {'-'*12} {'-'*12}")
    for eq in queries:
        q = eq["q"]
        relevant_ids = eq["relevant"]
        # 10-doc
        hits_10 = bm25_search(corpus, q, k=5)
        rel_keys_10 = {h.doc_key for h in hits_10 if h.doc.metadata.get("id") in relevant_ids}
        p_10 = len(rel_keys_10) / 5
        # 20-doc
        hits_20 = bm25_search(extended_corpus, q, k=5)
        rel_keys_20 = {h.doc_key for h in hits_20 if h.doc.metadata.get("id") in relevant_ids}
        p_20 = len(rel_keys_20) / 5
        print(f"  {q:<35} {p_10:>12.2f} {p_20:>12.2f}")
    print(f"  → corpus 变大, precision 通常降 (更多干扰), recapture 不变 (相关 doc 数不变)")

    # --------------------------------------------------------
    # Step 5: cache key normalization — 大小写 / 空格 不影响命中
    # --------------------------------------------------------
    step(5, "Cache key normalization — 大小写 / 空格 不影响命中")
    cache2 = RetrievalCache()
    cache2.put("What is RAG?", ["hit_A", "hit_B"])
    # 不同大小写 + 前后空白
    hit_normalized = cache2.get("  what IS rag?  ")
    print(f"  cache.get('  what IS rag?  ') == hit_normalized ? {hit_normalized is not None}")
    assert hit_normalized is not None, "标准化后应该命中"
    # 另一个变体 — 全大写 + 首尾空白
    hit_upper = cache2.get("WHAT IS RAG?  ")
    print(f"  cache.get('WHAT IS RAG?  ') == hit_upper? {hit_upper is not None}")
    assert hit_upper is not None, "全大写也应该命中"
    print(f"  ✓ key 用 .strip().lower() 标准化 — 大小写 / 首尾空白 都命中")

    # --------------------------------------------------------
    # Step 6: Production pipeline (sync) — cache + retrieve + observe
    # --------------------------------------------------------
    step(6, "Production pipeline (sync) — cache + retrieve + observe")

    def cached_retrieve(query: str, k: int = 5) -> list[RetrievalHit]:
        """Cache-wrapped retrieval pipeline.

        命中 → 返回缓存 (0 计算);
        未命中 → BM25 检索 → 写缓存 → 返回.
        metrics.total_queries 在外层加, 这里只标 hit/miss.
        """
        metrics.total_queries += 1
        cached = cache.get(query)
        if cached is not None:
            metrics.cache_hits += 1
            return cached[:k]
        metrics.cache_misses += 1
        hits = bm25_search(corpus, query, k=20)
        cache.put(query, hits)
        return hits[:k]

    # 跑 5 个 query — 故意混重复 + 新, 看 cache 效果
    queries_to_run = [
        "What is RAG?",          # miss
        "How does BM25 work?",   # miss
        "What is RAG?",          # hit
        "Cross-encoder reranking",  # miss
        "What is RAG?",          # hit
    ]
    for q in queries_to_run:
        with time_operation(metrics):
            hits = cached_retrieve(q, k=5)
        print(f"  {q!r:<32}: {len(hits)} hits")

    print(f"\n  final metrics: {metrics.summary()}")
    print(f"  cache hit rate: {metrics.cache_hit_rate:.1%} (期望 50% — step 6 内 3 hit + 2 miss, 加上 step 1 的 1 hit)")

    # --------------------------------------------------------
    # Step 7: Async batch — 3 retriever 并发 + 各自 latency
    # --------------------------------------------------------
    step(7, "Async batch — 3 retriever 并发 + 各自 latency")
    vectorstore = get_safe_vectorstore(corpus)

    async def async_demo():
        # 3 个 retriever coroutine — 模拟"同时检索同一 query"
        async def bm25_coro() -> tuple[str, list[RetrievalHit]]:
            await asyncio.sleep(0.05)  # 模拟 IO/计算
            return ("bm25", bm25_search(corpus, "hybrid retrieval", k=5))

        async def semantic_coro() -> tuple[str, list[RetrievalHit]]:
            await asyncio.sleep(0.05)
            return ("semantic", semantic_search(vectorstore, "hybrid retrieval", k=5))

        async def hyde_coro() -> tuple[str, list[RetrievalHit]]:
            # 教学 mock: HyDE = 用扩写后的 query 跑 BM25
            # 真实场景会用 LLM 生成 hypothetical doc 再 embed
            await asyncio.sleep(0.05)
            return (
                "hyde",
                bm25_search(corpus, "combining keyword and semantic search together", k=5),
            )

        start = asyncio.get_event_loop().time()
        results = await gather_with_metrics(
            [bm25_coro(), semantic_coro(), hyde_coro()],
            metrics,
        )
        elapsed = asyncio.get_event_loop().time() - start
        return results, elapsed

    results, elapsed = asyncio.run(async_demo())
    print(f"  3 retrievers finished in {elapsed:.3f}s wall-clock (并发, 不串行)")
    for r in results:
        if isinstance(r, Exception):
            print(f"    ⛔ ERROR: {type(r).__name__}: {r}")
        else:
            name, hits = r
            print(f"    {name:<10}: {len(hits)} hits")

    print(f"\n  metrics after parallel: {metrics.summary()}")
    print(f"  💡 串行跑 3 个 ~0.15s, 并发只要 ~0.05s (3 倍 speedup)")

    # 💡 教学要点:
    # - cache 是性价比最高的优化 — 一行代码省 10x cost + 几乎所有 latency
    # - async batch: retriever 通常是 IO bound (LLM/embedding 调用), gather 收益大
    # - observability: 没指标 = 没优化方向, p95 比 avg 更能反映用户感知
    # - multi-corpus eval: corpus 质量回归难发现, 必须有 baseline 对比


if __name__ == "__main__":
    main()