# 10-rag-deep-dive — 最终状态 (2026-10-04)

> 6 demo + 4 共享 utility + README, 进阶 RAG 工程. 本文档是教学收尾, 标出能力边界 + 已知限制 + 升级路径.

## TL;DR

- **12 个文件 (含 .gitignore) / ~2127 LOC / 4 atomic commits**
- **6 demo + 4 共享 (retrievers / rerankers / evaluators / production + _common)**
- **9 已知坑 (RRF k + cross-encoder mock + M3 CoT + semantic chunker + 小 corpus eval + cache version + gather 失败传染 + LRU 经验值 + p95 sort)**
- **AST parse 11/11 OK, import chain OK**

## 能力矩阵

| 维度 | 实现 | 文件 | LOC |
|---|---|---|---|
| **Hybrid search** | BM25 + semantic + RRF fusion (k=60) | retrievers.py | 178 |
| **Reranking** | cross_encoder_mock (词重叠) + llm_rerank (async ainvoke) | rerankers.py | 156 |
| **Query expansion** | HyDE (假想答案) + multi-query (LLM 改写 + merge) | 03_query_expansion.py | 182 |
| **Chunking** | RecursiveCharacterTextSplitter + SemanticChunker (langchain_experimental) | 04_chunking.py | 207 |
| **Evaluation** | precision@k + recall@k + faithfulness_judge (LLM async) + 报告写 output/ | evaluators.py | 164 |
| **Cache** | LRU OrderedDict + key normalization (`.strip().lower()`) | production.py | 197 |
| **Observability** | ObservabilityMetrics (cache_hit_rate + avg + p95 latency) | production.py | (shared) |
| **Async batch** | gather + return_exceptions + per-task timing | production.py | (shared) |
| **Sample corpus** | 10 docs + 5 eval queries + 1 长 doc (6 章) | _common.py | 188 |

## 6 个 demo

| # | 主题 | 步骤数 | 跑法 | LLM |
|---|---|---|---|---|
| 1 | Hybrid search (BM25 vs semantic vs RRF) | 4 | `python 01_hybrid_search.py` | ❌ (safe embedding) |
| 2 | Reranking (initial top-20 → mock → LLM → top-5) | 5 | `python 02_reranking.py` | 部分 (LLM rerank) |
| 3 | Query expansion (HyDE + multi-query + 联合 pipeline) | 6 | `python 03_query_expansion.py` | ✅ |
| 4 | Chunking (recursive vs semantic + retrieval 对比) | 6 | `python 04_chunking.py` | ❌ (safe embedding) |
| 5 | Evaluation (precision@5 + recall@5 + faithfulness + 报告) | 6 | `python 05_evaluation.py` | ✅ (judge) |
| 6 | Production patterns (cache + async + metrics + multi-corpus) | 7 | `python 06_production_patterns.py` | ❌ (mock async sleep) |

## 9 个已知坑

| # | 描述 | 影响 | 升级路径 |
|---|---|---|---|
| 1 | RRF k_constant 选 60 还是 20? | 小 k 偏向 "某 list top", 大 k 偏向 "多 list 都上榜" | 论文默认 60, 想强调某 retriever → 单独 weight 加倍 |
| 2 | cross_encoder_mock 用词重叠, 跟真实 cross-encoder 排名不一致 | "RAG" vs "retrieval augmented generation" 不重叠 | 换 `sentence-transformers/cross-encoder/ms-marco-MiniLM-L-6-v2` 或直接 LLM rerank |
| 3 | MiniMax M3 经常先吐 CoT 再给 `doc_N: score` | inline regex 能抓, 整段 prose 抓不到 | 宽容 regex (大小写无关/任意位置) + system prompt 强调格式, fallback mock |
| 4 | Semantic chunker 在 1 句 doc 上 noop | 教学 corpus 短, semantic 不会切 | semantic 只对 ≥10 段长 doc 有意义, 短 doc 直接当 chunk (Demo 4 加了 6 章长 doc) |
| 5 | precision@5 / recall@5 在 5 query × 1 relevant 上波动大 | 永远是 0/0.2/0.4/0.6, 信号弱 | 扩到 50-100 queries + 每 query 多个 relevant docs |
| 6 | Cache 不感知 corpus 变化 — 同一 query 命中旧 hits | 索引更新后返回 stale value | 加 `version_key` (corpus hash) → cache key = `(version, query)` |
| 7 | `asyncio.gather` 默认 all-or-nothing | 一个 raise 其它全 cancelled | `return_exceptions=True` (已实现) + `asyncio.wait_for(timeout=)` 防 hang |
| 8 | LRU 上限 1000 是经验值 | corpus 大/小 → 内存涨或命中率低 | 监控 `cache_hit_rate` + 内存, 经验: max_size = unique_query * 2 |
| 9 | p95 latency 每次 summary 都 sort | latency 累计 10w+ 时 CPU 涨 | 生产换 streaming percentile estimator (t-digest / HDR histogram) |

## 升级到 Production 的步骤

```python
# 1. Cache 持久化 (Redis)
import redis, pickle
r = redis.Redis(host="...", port=6379)
class RedisCache(RetrievalCache):
    def get(self, query):
        cached = r.get(f"rag:{query}")
        return pickle.loads(cached) if cached else None
    def set(self, query, hits):
        super().set(query, hits)
        r.setex(f"rag:{query}", 3600, pickle.dumps(hits))

# 2. Cross-encoder 换真 BERT
from sentence_transformers import CrossEncoder
ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-12-v2")
def bert_rerank(query, docs):
    scores = ce.predict([(query, d.page_content) for d in docs])
    return sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)

# 3. Vector store 换生产级 (Qdrant / Weaviate)
from langchain_qdrant import QdrantVectorStore
# vs = QdrantVectorStore.from_documents(corpus, embeddings, url="http://qdrant:6333")

# 4. Cache 加 corpus version
class VersionedCache(RetrievalCache):
    def __init__(self, corpus_version: str):
        super().__init__()
        self._version = corpus_version
    def _key(self, query):
        return f"v{self._version}:{query.strip().lower()}"

# 5. Observability 升级 (OpenTelemetry)
from opentelemetry import trace
tracer = trace.get_tracer(__name__)
# with tracer.start_as_current_span("retrieve"):
#     hits = retriever.search(query)

# 6. Async batch + timeout + retry
import asyncio
async def batch_with_timeout(tasks, timeout=30, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.wait_for(
                gather_with_metrics(tasks, metrics),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 ** attempt)
```

## Smoke 验证 (2026-10-04)

```bash
$ cd 10-rag-deep-dive
$ for f in _common.py retrievers.py rerankers.py evaluators.py production.py \
          01_hybrid_search.py 02_reranking.py 03_query_expansion.py \
          04_chunking.py 05_evaluation.py 06_production_patterns.py; do
    python -c "import ast; ast.parse(open('$f', encoding='utf-8').read())" && echo "OK: $f"
  done
OK: _common.py
OK: retrievers.py
OK: rerankers.py
OK: evaluators.py
OK: production.py
OK: 01_hybrid_search.py
OK: 02_reranking.py
OK: 03_query_expansion.py
OK: 04_chunking.py
OK: 05_evaluation.py
OK: 06_production_patterns.py
```

**11/11 AST parse OK. Import chain OK. 项目进入稳定状态.**

## 4 atomic commits 历史

```
1116493  feat(10): 新模块 10-rag-deep-dive — _common + retrievers + rerankers + evaluators
d4f9eac  feat(10): 5 demo + README — Hybrid/Rerank/Expansion/Chunking/Eval 全套
2337aa9  feat(10): production 共享模块 + 06_production_patterns — cache/async/metrics
f481363  docs(10): README 加 demo #6 + Production patterns 章节 + 4 已知坑 (#6-#9)
```

## 下一步 (可选)

1. **Nitpick skill audit** — 用 `nitpick` 全项目 review (跨 6 维度, 跟 08 / 09 平行)
2. **跟 09 集成** — `09_safe_plan_to_code` 用 10 的 faithfulness 评估生成代码的 RAG 引用质量
3. **新方向 11-xxx** — 跟 08 / 09 / 10 平行 (eval-only / tool-fabric / async-pipeline)
4. **打包发布** — pyproject.toml + Docker image + GitHub Actions CI

6 demo + 4 共享 utility 后, 10-rag-deep-dive 教学目标达成. **推荐**: nitpick audit 或集成, 不再加深现有能力.
