"""04_chunking.py — Demo 4: Chunking Strategies (Recursive vs Semantic).

教学目标: 不同 chunking 对 retrieval quality 的影响.

学完这个 demo 你能回答:
1.  RecursiveCharacterTextSplitter 怎么切? 默认 separators 优先级?
2.  Semantic chunking 跟 recursive 核心差别?
3.  chunk_size / chunk_overlap 怎么选? 大小对 recall/precision 的影响?
4.  短 doc (教学语料) 跟长 doc (真实业务) chunking 策略差异?
5.  怎么对比两种 chunking 的 retrieval 效果 (top-k id 重合率)?

跑法:
    python 04_chunking.py

💡 本 demo 的 sample corpus 是短 doc (1 句), chunking 效果差异不明显.
   教学要点在概念 + 流程, 不在 demo 数据集的胜负.
   真实场景用长 doc (10-50 段) 才能看出 semantic chunking 的价值.
"""
from __future__ import annotations

import asyncio

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_experimental.text_splitter import SemanticChunker

from _common import banner, get_safe_vectorstore, get_sample_corpus, step
from retrievers import RetrievalHit, semantic_search


# ============================================================
# 真实长 doc — 教学用, 让 chunking 有意义
# ============================================================
_LONG_DOC = """
LangChain 1.x 入门指南.

第一章: 为什么需要 LangChain?
直接调 OpenAI / Anthropic API 当然可以, 但生产应用要处理: prompt 模板、tool 调用、
记忆管理、RAG、streaming、多 agent 协作. LangChain 提供统一抽象 (Runnable, LCEL),
让这些都能用 |  串起来. 社区生态丰富 (200+ integration), 文档 / 教程多.

第二章: LangChain 1.x 核心概念.
ChatModel: 统一 chat 模型接口 (Anthropic / OpenAI / DeepSeek 都用同一份代码).
PromptTemplate: 参数化 prompt, 支持 partial 和 ChatPromptTemplate.
OutputParser: 把 LLM 输出解析成 Pydantic / dataclass, structured output 一键搞定.
Tool: @tool 装饰器把 Python 函数变 tool, Agent 自动选 tool 调用.
Memory: 短期 (checkpointer) / 长期 (Store) / 摘要 (SummarizationMiddleware).

第三章: LangGraph — stateful multi-agent orchestration.
LangGraph 把 agent workflow 建模成 StateGraph (node + edge), 支持:
- 持久化 (checkpoint): 中断后能恢复
- Human-in-the-loop (interrupt): 关键决策暂停, 等人审批
- Streaming: token 级流式输出
- Time-travel: 回放历史 state, 做 branch / debug
- Multi-agent: supervisor / handoff / swarm 拓扑

第四章: LangSmith — observability.
所有 LangChain / LangGraph 调用自动 trace 到 LangSmith, 可视化每步 token / latency /
错误. Production 必须开 — 没 trace 等于盲飞.

第五章: 生产最佳实践.
Structured output 双轨 (function_calling + Pydantic fallback) 应对小模型 CoT.
Middleware 处理 PII / retry / rate limit / summarization.
Async (ainvoke / astream) 走 event loop, 别 blocking.
Vector store 选择: FAISS (小) / Chroma (中) / Pinecone (大).
Embedding 选择: OpenAI text-embedding-3 (贵但稳) / 本地 sentence-transformers (免费).

第六章: 常见坑.
- langchain 1.0.2 必须 + langchain-core 同主版本, 混 minor 会 ImportError.
- LCEL pipe (|) 顺序敏感: retriever 在 prompt 前, llm 在 prompt 后.
- Structured output 小模型常 fail → 用 method="function_calling" + 双轨.
- LangSmith 默认开, 没 API key 每次 invoke 403 → .env 关 LANGCHAIN_TRACING_V2.
"""


def get_long_doc() -> Document:
    """返回一条长 doc, 用于演示 chunking 差异."""
    return Document(
        page_content=_LONG_DOC.strip(),
        metadata={"id": "long", "topic": "tutorial"},
    )


# ============================================================
# 两种 chunking 策略
# ============================================================
def chunk_recursive(doc: Document, chunk_size: int = 200, overlap: int = 30) -> list[Document]:
    """Recursive character text splitter — LangChain 默认策略.

    按 separators 优先级递归切: ["\\n\\n", "\\n", " ", ""].
    chunk_size: 每块最大字符数
    chunk_overlap: 相邻块重叠字符数 (边界信息保留)
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
        is_separator_regex=False,
    )
    chunks = splitter.split_documents([doc])
    # 给每块加 chunk_id metadata, 方便追踪
    for i, c in enumerate(chunks):
        c.metadata = {**c.metadata, "chunk_id": f"r{i}", "strategy": "recursive"}
    return chunks


def chunk_semantic(doc: Document, embeddings) -> list[Document]:
    """Semantic chunker — 按 embedding 相似度断句.

    原理: 计算相邻句子 embedding 的 cosine distance,
    distance 突变处切 (即语义转换点).
    依赖: embedding 模型 (这里用 safe_vectorstore 同款 — 已探测 fallback).

    缺点: 慢 (每句要 embed), 且 chunk 长度不可控 (可能一段很长).
    """
    splitter = SemanticChunker(
        embeddings=embeddings,
        breakpoint_threshold_type="percentile",  # 用 percentile 找断点
        breakpoint_threshold_amount=70,  # 前 30% 距离突变点切
    )
    chunks = splitter.split_documents([doc])
    for i, c in enumerate(chunks):
        c.metadata = {**c.metadata, "chunk_id": f"s{i}", "strategy": "semantic"}
    return chunks


# ============================================================
# Demo
# ============================================================
async def main() -> None:
    banner("Demo 4: Chunking Strategies (Recursive vs Semantic)")

    # 短 doc 演示 (教学语料)
    step(1, "短 doc 演示: 10 条 1-句 corpus, chunking 差异不明显")
    short_corpus = get_sample_corpus()
    print(f"  短 corpus: {len(short_corpus)} docs, 平均字符 {sum(len(d.page_content) for d in short_corpus) // len(short_corpus)}")
    print(f"  >> 短 doc 场景: chunking 几乎 noop, 直接拿原文检索即可")

    # 长 doc 演示 — chunking 真正发挥价值的场景
    step(2, "长 doc 演示: 6 章 LangChain 教程 (一段)")
    long_doc = get_long_doc()
    print(f"  长 doc 长度: {len(long_doc.page_content)} 字符")
    print(f"  章节数: {long_doc.page_content.count('第')} (粗略)")

    # ---- Recursive ----
    step(3, "Recursive chunking (chunk_size=200, overlap=30)")
    rec_chunks = chunk_recursive(long_doc, chunk_size=200, overlap=30)
    print(f"  生成 {len(rec_chunks)} chunks:")
    for c in rec_chunks[:5]:
        preview = c.page_content.replace("\n", " ")[:80]
        print(f"    [{c.metadata['chunk_id']}] len={len(c.page_content):>3}  {preview}...")
    if len(rec_chunks) > 5:
        print(f"    ... (剩余 {len(rec_chunks) - 5} chunks)")

    # ---- Semantic ----
    step(4, "Semantic chunking (percentile=70 breakpoint)")
    # 需要 embeddings — 用 get_safe_vectorstore 内部的探测逻辑
    # 偷个懒: 先 build 一个空 vectorstore 拿到 embeddings
    probe_vs = get_safe_vectorstore([long_doc])
    embeddings = probe_vs.embeddings  # type: ignore[attr-defined]
    sem_chunks = chunk_semantic(long_doc, embeddings)
    print(f"  生成 {len(sem_chunks)} chunks:")
    for c in sem_chunks[:5]:
        preview = c.page_content.replace("\n", " ")[:80]
        print(f"    [{c.metadata['chunk_id']}] len={len(c.page_content):>3}  {preview}...")
    if len(sem_chunks) > 5:
        print(f"    ... (剩余 {len(sem_chunks) - 5} chunks)")

    # ---- Retrieval 对比 ----
    step(5, "Retrieval 对比: 同样 query, 两种 chunking 各检索 top-3")
    query = "LangGraph 持久化 和 human-in-the-loop"
    print(f"  query: '{query}'")

    rec_vs = get_safe_vectorstore(rec_chunks)
    sem_vs = get_safe_vectorstore(sem_chunks)

    rec_hits = semantic_search(rec_vs, query, k=3)
    sem_hits = semantic_search(sem_vs, query, k=3)

    print(f"\n  Recursive top-3:")
    for h in rec_hits:
        preview = h.doc.page_content.replace("\n", " ")[:60]
        print(f"    [{h.rank}] score={h.score:.3f}  {h.doc.metadata['chunk_id']}  {preview}...")

    print(f"\n  Semantic top-3:")
    for h in sem_hits:
        preview = h.doc.page_content.replace("\n", " ")[:60]
        print(f"    [{h.rank}] score={h.score:.3f}  {h.doc.metadata['chunk_id']}  {preview}...")

    # ---- 评估 (用 chunk_id 重合率) ----
    step(6, "Top-3 chunk_id 重合率 (越高 → 两种策略越一致)")
    rec_ids = {h.doc.metadata["chunk_id"] for h in rec_hits}
    sem_ids = {h.doc.metadata["chunk_id"] for h in sem_hits}
    overlap = rec_ids & sem_ids
    print(f"  Recursive chunk_ids: {sorted(rec_ids)}")
    print(f"  Semantic   chunk_ids: {sorted(sem_ids)}")
    print(f"  重合: {sorted(overlap)} ({len(overlap)}/3)")

    # 💡 教学要点:
    # - Recursive: 快, 稳定, chunk 长度可控 — 80% 场景默认用这个
    # - Semantic: 准 (语义对齐), 慢, chunk 长度不可控 — 长 doc + 高质量需求时用
    # - 真实 production: 短 doc (FAQ / Q&A) → 不切; 长 doc (book / docs) → semantic
    # - chunk_size 经验值: 200-500 字符 (中文 100-300 字), overlap 10-20%


if __name__ == "__main__":
    asyncio.run(main())
