# 10-rag-deep-dive — Advanced RAG Patterns

L1 (basic semantic retrieval) 之后, 真实 production RAG 必备的进阶技术.

## 为什么需要这个模块

L1 `01-langchain-basics/05_retrieval.py` 讲了 vector store + basic retriever. 但 production RAG 通常还要:

| 进阶能力 | L1 没讲 | 实战必备 |
|---|---|---|
| Hybrid search (BM25 + semantic) | ❌ | ✅ |
| Reranking (cross-encoder / LLM) | ❌ | ✅ |
| Query expansion (HyDE / multi-query) | ❌ | ✅ |
| 高级 chunking (semantic chunker) | ❌ | ✅ |
| 评估 (precision@k / recall@k / faithfulness) | ❌ | ✅ |

本模块 5 个 demo 每个讲一个, 共用 `retrievers.py / rerankers.py / evaluators.py` 三个共享模块.

## 学完你能回答 N 个问题

1. **Hybrid search** — BM25 vs semantic 各自强项? RRF 融合公式? 什么时候 hybrid 赢单模式?
2. **Reranking** — 为什么需要 rerank? Cross-encoder vs bi-encoder 差别? Mock vs 真实 cross-encoder?
3. **Query expansion** — HyDE 是什么? Multi-query 怎么 merge? Expansion + rerank 联合 pipeline?
4. **Chunking** — Recursive vs Semantic 切分逻辑? chunk_size / overlap 经验值? 短 doc vs 长 doc?
5. **Evaluation** — precision@k vs recall@k 公式? Faithfulness 怎么用 LLM judge? 怎么聚合多 query?
6. **整体 pipeline** — 怎么把 hybrid + rerank + expansion 串成 production RAG? 评估在哪个环节介入?

## Demo 表

| Demo | 内容 | 需要 API key | 跑法 |
|---|---|---|---|
| `01_hybrid_search.py` | BM25 vs Semantic vs Hybrid (RRF) 对比 | ❌ (semantic 用 safe embedding) | `python 01_hybrid_search.py` |
| `02_reranking.py` | semantic top-20 → cross-encoder rerank → top-5 (mock + LLM) | LLM rerank 部分需要 | `python 02_reranking.py` |
| `03_query_expansion.py` | HyDE + Multi-query, 配合 expansion + rerank 联合 pipeline | ✅ (需要 LLM) | `python 03_query_expansion.py` |
| `04_chunking.py` | Recursive vs Semantic chunker 切分长 doc + retrieval 对比 | ❌ (semantic chunker 用 safe embedding) | `python 04_chunking.py` |
| `05_evaluation.py` | precision@5 / recall@5 + faithfulness LLM judge + 报告写 output/ | LLM judge 部分需要 | `python 05_evaluation.py` |

## 文件结构

```
10-rag-deep-dive/
├── _common.py             L1 wrapper + sample corpus (10 docs) + eval queries (5)
├── retrievers.py          BM25 + semantic + RRF fusion (3 functions + tokenize)
├── rerankers.py           cross_encoder_mock + llm_rerank (async)
├── evaluators.py          precision@k + recall@k + faithfulness_judge (async)
├── 01_hybrid_search.py    Demo 1: hybrid search 对比
├── 02_reranking.py        Demo 2: rerank pipeline
├── 03_query_expansion.py  Demo 3: HyDE + multi-query + expansion+rerank 联合
├── 04_chunking.py         Demo 4: recursive vs semantic chunking
├── 05_evaluation.py       Demo 5: precision/recall/faithfulness + 报告
├── README.md              本文件
└── .gitignore             output/ + faiss/chroma 缓存
```

## 跑法

```bash
cd D:/work-ai/0401-langchain-langgraph-v1

# 新依赖: rank_bm25
pip install rank-bm25

# 不需要 API key 的 demo
python 10-rag-deep-dive/01_hybrid_search.py
python 10-rag-deep-dive/04_chunking.py

# 部分需要 LLM (cross-encoder mock 不需要)
python 10-rag-deep-dive/02_reranking.py

# 完全依赖 LLM
python 10-rag-deep-dive/03_query_expansion.py
python 10-rag-deep-dive/05_evaluation.py
```

LLM provider 配置见 `01-langchain-basics/_common.py` 的 `get_llm()` — 优先级 Anthropic > DeepSeek > MiniMax > OpenAI, `.env` 配 key 即可.

## 已知坑 (5 个)

### 1. RRF 的 k_constant 选 60 还是 20?

**现象**: 同一组 hit, RRF k=60 vs k=20 出来的 ranking 差异很大.

**原因**: k 越小, top rank 的权重越大 (1/(k+1) vs 1/(k+60) 差距大). 小 k → 偏向 "某个 list 的 top"; 大 k → 偏向 "多 list 都上榜".

**实战**: 论文推荐 60 (平衡), 我们默认也 60. 想强调某个 retriever → 把它单独 weight 加倍 (e.g. 给 BM25 hit 的 rank 多乘 0.5).

### 2. cross-encoder mock 用词重叠, 跟真实 cross-encoder 排名不一致

**现象**: Demo 2 里 mock cross-encoder 出的 top-5 跟真实 cross-encoder (sentence-transformers/ms-marco) 不一样.

**原因**: 词重叠只能抓 lexical 匹配, 抓不到 semantic relation. e.g. "RAG" 和 "retrieval augmented generation" 在 mock 下不重叠, 但实际是同一个东西.

**实战**: mock 适合 smoke test + 教学演示. production 上真实 cross-encoder (e.g. `sentence-transformers/cross-encoder/ms-marco-MiniLM-L-6-v2`), 或者直接用 LLM rerank.

### 3. LLM reranker 输出格式不稳 — MiniMax M3 经常吐 CoT

**现象**: LLM rerank 时, M3 经常先写一段思考 "I think doc_2 is most relevant because...", 然后才给 `doc_N: score` 行.

**原因**: M3 默认在 content 前吐 chain-of-thought. 我们的 regex `doc_(\d+):\s*(\d+(?:\.\d+)?)` 是行内匹配, 能抓到 CoT 之后的分数行, 但如果 LLM 整段都是 prose, 全部抓不到.

**实战**: rerankers.py 用宽容 regex (大小写无关 / 任意位置), 加 system prompt 强调 "严格按格式输出". 如果 LLM 长期不听话, fallback 到 mock cross-encoder.

### 4. Semantic chunker 在短 doc 上 noop

**现象**: 教学 corpus 是 10 条 1-句 doc, semantic chunker 不会切 — 每条当 1 个 chunk.

**原因**: semantic chunker 计算相邻句子的 embedding 距离, 句间距离突变才切. 短 doc 只有 1 句, 没"相邻"可比较.

**实战**: semantic chunking 只对长 doc (≥ 10 段) 有意义. 短 doc 直接当 chunk. Demo 4 加了一段 6 章长 doc 才让 semantic chunker 有事可干.

### 5. precision@k / recall@k 在小 corpus 上波动大

**现象**: 5 条 ground-truth query, 每条只有 1 个 relevant doc. precision@5 永远是 0/1/0.2/0.4/0.6 五种值, 一查波动极大.

**原因**: relevant 集合基数小 (1), 5 个 doc 中 1 个 relevant → precision 粒度就是 0.2. corpus 再大点 (100 docs) 就稳定.

**实战**: 教学 corpus 故意小, 让 demo 在几秒内跑完. 真实 eval 至少 50-100 queries + 每 query 多个 relevant docs. 用 `eval_queries` 模板扩 ground truth.

## 进阶阅读

- **RRF 原论文**: Cormack et al. 2009, "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods"
- **HyDE 原论文**: Gao et al. 2022, "Precise Zero-Shot Dense Retrieval without Relevance Labels"
- **Cross-encoder vs bi-encoder**: Reimers & Gurevych 2019, "Sentence-BERT"
- **Semantic chunking**: Greg Kamradt 的 [5 Levels of Text Splitting](https://github.com/gkamradt/langchain-tutorials)

## 相关模块

- `01-langchain-basics/05_retrieval.py` — 基础 vector store + retriever (本模块的前置)
- `02-langgraph-orchestration/` — 持久化 / interrupt (RAG agent 接 workflow)
- `06-opc-product/` — L1-L6 全栈 demo, 含 RAG 部分
