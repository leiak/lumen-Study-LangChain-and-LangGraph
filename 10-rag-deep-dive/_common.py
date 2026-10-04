"""10-rag-deep-dive 共享辅助: 复用 L1 _common + sample corpus + eval ground truth.

复用 L1: banner + get_llm (via importlib.util 按路径加载, 跟 09-codegen-agent 一致).
  - 不用 sys.path hack, 避免 import _common 时拿到自己 (circular)
  - 用唯一 module name '_l1_common' 隔离
新增:
  - get_sample_corpus(): 10 个 LangChain/RAG 教学 doc
  - get_eval_queries(): 5 个 ground-truth queries (q + relevant doc ids)
  - get_safe_vectorstore(corpus): L1 safe_vectorstore 模式 (embedding 探测 fallback)
  - step(): 跟 09 同风格, 输出 "--- Step N: title ---"
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Windows GBK: LLM 返回 emoji/中文 → 默认 cp936 崩. 提前 reconfigure.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.documents import Document

# ============================================================
# 复用 L1 _common — 不要重复 provider 切换代码
# ============================================================
_ROOT = Path(__file__).resolve().parent.parent
_L1_COMMON_PATH = _ROOT / "01-langchain-basics" / "_common.py"

_spec = importlib.util.spec_from_file_location("_l1_common", _L1_COMMON_PATH)
_l1_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_l1_common)

# 暴露 L1 的两个公开符号
banner = _l1_common.banner
get_llm = _l1_common.get_llm

# safe_vectorstore 在 L1 05_retrieval.py 里 (不是 _common.py) — 也通过 importlib 加载
# 用唯一 module name '_l1_retrieval' 隔离, 避免跟未来其它模块冲突
_L1_RETRIEVAL_PATH = _ROOT / "01-langchain-basics" / "05_retrieval.py"
_spec_r = importlib.util.spec_from_file_location("_l1_retrieval", _L1_RETRIEVAL_PATH)
_l1_retrieval = importlib.util.module_from_spec(_spec_r)
_spec_r.loader.exec_module(_l1_retrieval)
safe_vectorstore = _l1_retrieval.safe_vectorstore


# ============================================================
# Sample corpus — 10 个 LangChain/RAG 教学 doc
# ============================================================
# 每条都标 metadata.id (ground truth 用) + topic (教学分组).
# 内容故意短 (1 句) — 教学演示, 不需要真实长文档.
_SAMPLES = [
    {
        "id": "d1",
        "topic": "langchain",
        "content": (
            "LangChain is a framework for building applications with large language models (LLMs)."
        ),
    },
    {
        "id": "d2",
        "topic": "rag",
        "content": (
            "Retrieval-Augmented Generation (RAG) combines retrieval with generation to reduce hallucination."
        ),
    },
    {
        "id": "d3",
        "topic": "vectorstore",
        "content": (
            "Vector stores like FAISS, Chroma, and Pinecone enable semantic similarity search."
        ),
    },
    {
        "id": "d4",
        "topic": "bm25",
        "content": (
            "BM25 is a bag-of-words retrieval algorithm that ranks documents based on term frequency."
        ),
    },
    {
        "id": "d5",
        "topic": "rerank",
        "content": (
            "Cross-encoders rerank documents using query-document interaction, more accurate than bi-encoders."
        ),
    },
    {
        "id": "d6",
        "topic": "rrf",
        "content": (
            "Reciprocal Rank Fusion (RRF) combines multiple ranked lists without needing score calibration."
        ),
    },
    {
        "id": "d7",
        "topic": "hyde",
        "content": (
            "Hypothetical Document Embeddings (HyDE) generates a fake document to improve retrieval recall."
        ),
    },
    {
        "id": "d8",
        "topic": "multi-query",
        "content": (
            "Multi-query retrieval rewrites the original query into multiple variants to increase coverage."
        ),
    },
    {
        "id": "d9",
        "topic": "chunking",
        "content": (
            "Semantic chunking splits text based on embedding similarity, preserving semantic boundaries."
        ),
    },
    {
        "id": "d10",
        "topic": "eval",
        "content": (
            "Faithfulness evaluation checks whether an LLM answer is grounded in retrieved context."
        ),
    },
]


def get_sample_corpus() -> list[Document]:
    """返回 10 条 LangChain/RAG 教学 doc.

    metadata 含 id (eval ground truth 用) + topic (教学分组用).
    """
    return [
        Document(page_content=s["content"], metadata={"id": s["id"], "topic": s["topic"]})
        for s in _SAMPLES
    ]


# ============================================================
# Ground truth — 5 个 query + 对应 relevant doc id
# ============================================================
# 评估 precision@k / recall@k 时, 用这 5 条当 label.
def get_eval_queries() -> list[dict]:
    """5 个 ground-truth query. relevant 是 doc id 集合 (匹配 _SAMPLES 的 metadata.id)."""
    return [
        {"q": "What is RAG?", "relevant": {"d2"}},
        {"q": "How does BM25 work?", "relevant": {"d4"}},
        {"q": "Cross-encoder reranking", "relevant": {"d5"}},
        {"q": "Hybrid retrieval fusion", "relevant": {"d6"}},
        {"q": "Query expansion with HyDE", "relevant": {"d7"}},
    ]


# ============================================================
# Vectorstore — 复用 L1 safe_vectorstore 模式 (embedding 探测 fallback)
# ============================================================
def get_safe_vectorstore(docs: list[Document]):
    """建 FAISS 向量库, embedding 不可用时降级到 DeterministicFakeEmbedding.

    复用 L1 safe_vectorstore: 真实 embedding 探测一次, 失败降级, 缓存复用.
    """
    return safe_vectorstore(docs)


# ============================================================
# 进度显示 — 跟 09 同风格
# ============================================================
def step(n: int, title: str) -> None:
    """打印步骤: --- Step N: title ---."""
    print(f"\n--- Step {n}: {title} ---")


# ============================================================
# output/ 目录 (demo 5 评估报告写这里)
# ============================================================
_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def output_dir() -> Path:
    """返回 output/ 目录, 不存在则创建."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


__all__ = [
    "banner", "get_llm",
    "get_sample_corpus", "get_eval_queries",
    "get_safe_vectorstore",
    "step", "output_dir",
]
