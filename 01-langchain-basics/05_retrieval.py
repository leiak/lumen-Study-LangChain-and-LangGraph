

"""05_retrieval.py — Retrieval (RAG): 给 Agent 接私有知识库.

学完这个模块你能回答:
1.  怎么从内存 / 文件加载文档?
2.  怎么切块 (chunk_size / chunk_overlap / separators)?
3.  怎么选 embedding (OpenAI / 本地 / 离线 hash)?
4.  怎么用 FAISS 构向量库?
5.  similarity 检索 vs MMR 检索差别在哪?
6.  怎么按 metadata 过滤检索结果?
7.  怎么给相似度设阈值过滤低质结果?
8.  向量库怎么持久化到磁盘 (生产必备)?
9.  怎么把 Retriever 接成 Agent 的 tool (完整 RAG)?

跑法:
    python 05_retrieval.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from langchain_community.embeddings import MiniMaxEmbeddings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_text_splitters import RecursiveCharacterTextSplitter

from _common import banner, get_llm

# ============================================================
# 1. 准备文档 — 内存 + 磁盘两种方式
# ============================================================
banner("1. 准备示例文档 (内存 / 磁盘加载)")


# 真实业务里,文档通常存在 DB / OSS / Confluence,LangChain 有对应的 loader
# 这里先用内存 + 磁盘文件做演示
_SAMPLES = [
    {
        "title": "退订政策",
        "content": (
            "退订政策\n"
            "1. 发车前 24 小时以上退订,全额退款。\n"
            "2. 发车前 2-24 小时退订,扣除票面金额 20%。\n"
            "3. 发车前 2 小时以内退订,扣除票面金额 50%。\n"
            "4. 改签每次收取 10 元手续费。\n"
        ),
    },
    {
        "title": "行李规定",
        "content": (
            "行李规定\n"
            "1. 成人旅客免费托运 20kg,商务座 30kg。\n"
            "2. 随身携带行李不得超过 5kg,体积不超过 20×40×55cm。\n"
            "3. 禁止携带打火机、超过 100ml 液体、刀具等危险品。\n"
        ),
    },
    {
        "title": "客服热线",
        "content": (
            "客服热线\n"
            "- 售前咨询: 400-100-1000\n"
            "- 售后投诉: 400-100-1001\n"
            "- 紧急救援: 400-100-1009\n"
            "- 工作时间: 24 小时全天候\n"
        ),
    },
]


def prepare_in_memory_docs() -> list[Document]:
    """内存里直接构造 Document 列表. 适合测试 / 单元测试."""
    return [
        Document(page_content=d["content"], metadata={"title": d["title"]})
        for d in _SAMPLES
    ]


def prepare_disk_docs(tmp_dir: Path) -> list[Document]:
    """写到磁盘再用 TextLoader 读. 模拟真实文档加载 (DB / OSS 同理)."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for d in _SAMPLES:
        (tmp_dir / f"{d['title']}.txt").write_text(d["content"], encoding="utf-8")

    docs: list[Document] = []
    for txt_file in tmp_dir.glob("*.txt"):
        loaded = TextLoader(str(txt_file), encoding="utf-8").load()
        for d in loaded:
            d.metadata["title"] = txt_file.stem
        docs.extend(loaded)
    return docs


def demo_prepare_docs() -> list[Document]:
    print(">>> 内存直接构造:")
    in_mem = prepare_in_memory_docs()
    print(f"  原始文档数: {in_mem}")
    print(f"  原始文档数2: {in_mem.__len__()}")
    print(f"  文档数: {len(in_mem)}, 元数据metadata: {in_mem[0].metadata}, 元数据page_content: {in_mem[0].page_content}")

    print("\n>>> 磁盘加载 (用 TextLoader):")
    with tempfile.TemporaryDirectory() as tmp:
        on_disk = prepare_disk_docs(Path(tmp))
        print(f"  文档数: {len(on_disk)}, 第一篇来源: {on_disk[0].metadata}")

    return in_mem


# ============================================================
# 2. 切块 — RecursiveCharacterTextSplitter
# ============================================================
banner("2. 切块 — RecursiveCharacterTextSplitter")


def demo_splitting(docs: list[Document]) -> list[Document]:
    # separators 按优先级尝试: 先 \n\n (段落) → \n (行) → 。 (句子) → 空格 (词)
    # 中文场景建议加 "。" 进 separators
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=100,        # 每块最多 100 字符
        chunk_overlap=20,      # 相邻块重叠 20 字符 (避免上下文切断)
        separators=["\n\n", "\n", "。", " "],
    )
    chunks = splitter.split_documents(docs)
    print(f"原文数: {len(docs)} → 切块后: {len(chunks)}")
    for i, c in enumerate(chunks[:3]):
        print(f"  块 {i} ({len(c.page_content)} 字符): {c.page_content[:60]}...")

    # 💡 切块策略 (实战):
    #   - chunk_size: 太小 → 检索粒度细,但上下文不够; 太大 → 召回噪声多
    #     推荐: 200-500 字符 (中文), 500-1500 token (英文)
    #   - chunk_overlap: 通常 10-20% of chunk_size
    #   - 高级: 按语义切 (MarkdownHeaderTextSplitter / SemanticChunker)
    return chunks


# ============================================================
# 3. Embedding + 向量库 (FAISS)
# ============================================================
banner("3. Embedding + 向量库 (FAISS)")


def get_embeddings():
    """根据可用 API key 选 embedding 实现, 失败时降级到 fake."""

    def _real(k: str | None) -> bool:
        return bool(k) and "your_" not in k.lower() and "..." not in k

    openai_key = os.getenv("OPENAI_API_KEY") if _real(os.getenv("OPENAI_API_KEY")) else None
    minimax_key = os.getenv("MINIMAX_API_KEY") if _real(os.getenv("MINIMAX_API_KEY")) else None

    if openai_key or minimax_key:
        from langchain_openai import OpenAIEmbeddings

        # return OpenAIEmbeddings(
        #     model="embo-01",
        #     api_key=openai_key or minimax_key,
        #     base_url=(
        #         "https://api.minimax.chat/v1/embeddings"
        #     ),
        # )
        return MiniMaxEmbeddings(
            model="embo-01",
            api_key=minimax_key,
            group_id=2046414028250550829,
        )

    # 无 key 时用 DeterministicFakeEmbedding (hash 模拟, 检索质量差但流程可演示)
    from langchain_community.embeddings import DeterministicFakeEmbedding

    print(">>> [提示] 未设真实 API key, 用 DeterministicFakeEmbedding (hash 模拟)")
    return DeterministicFakeEmbedding(size=384)


# 模块级缓存: 第一次探测成功后复用,避免重复探测
_cached_embeddings = None


def get_safe_embeddings():
    """智能选 embedding: 真实能用就用真实,失败则降级到 fake,只探测一次."""
    global _cached_embeddings
    if _cached_embeddings is not None:
        return _cached_embeddings

    candidate = get_embeddings()
    try:
        candidate.embed_query("test")  # 探测
        _cached_embeddings = candidate
        return candidate
    except Exception as e:
        print(f">>> [降级] 真实 embedding 不可用 ({type(e).__name__}: {str(e)[:60]})")
        from langchain_community.embeddings import DeterministicFakeEmbedding
        _cached_embeddings = DeterministicFakeEmbedding(size=384)
        return _cached_embeddings


def safe_vectorstore(chunks: list[Document]) -> FAISS:
    """建向量库, 用探测过的 (可能已降级的) embedding.

    实战: MiniMax M3 不暴露 OpenAI 兼容的 embedding 端点, 直接调会 ValueError。
    这种 provider 特定的坑要降级处理, 不能让一个 embedding 失败阻塞整个 demo。
    """
    embeddings = get_safe_embeddings()
    return FAISS.from_documents(chunks, embeddings)


def demo_vector_store(chunks: list[Document]) -> FAISS:
    vectorstore = safe_vectorstore(chunks)
    print(f"向量库大小: {vectorstore.index.ntotal} 条")

    # 💡 实战 embedding 选型:
    #   - OpenAI text-embedding-3-small: 1536 维, 通用强, $0.02/M token
    #   - Voyage-3: 1024 维, RAG 场景 SOTA
    #   - BGE-M3 / mxbai-embed-large: 开源,本地部署,隐私场景
    #   - 多语言: BGE-M3 / multilingual-e5
    return vectorstore


# ============================================================
# 4. similarity 检索 — 最基础
# ============================================================
banner("4. similarity 检索 (top-k)")


def demo_similarity(vectorstore: FAISS) -> None:
    # search_type="similarity" (默认): 取 cosine 相似度最高的 k 个
    retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 2})

    print(">>> similarity top-2 检索 (cosine 相似度):")
    for doc in retriever.invoke("退款要扣多少手续费?"):
        print(f"  [{doc.metadata['title']}] {doc.page_content[:80]}")

    # 💡 k 值选多大?
    #   - k=1: 偶尔召回漏,回答不全面
    #   - k=3-5: 多数 RAG 场景的甜点
    #   - k=10+: 给 LLM 太多上下文,可能分散注意力 + 烧 token
    # 实战常配合 reranker (Cohere / BGE-reranker) 用: 先取 k=20, 再 rerank 留 top-5


# ============================================================
# 5. MMR 检索 — 多样性 vs 相似度的平衡
# ============================================================
banner("5. MMR 检索 — 多样性 vs 相似度的平衡")


def demo_mmr(vectorstore: FAISS) -> None:
    # MMR (Maximal Marginal Relevance):
    #   不仅要"和 query 像",还要"和已选结果不太像"
    #   fetch_k=10 → 候选池里取 10 个, 再用 MMR 算法挑 k=3 个多样的
    #   lambda_mult: 0=纯多样, 1=纯相似, 0.5 是常用平衡点
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 3, "fetch_k": 10, "lambda_mult": 0.5},
    )

    print(">>> MMR top-3 (兼顾多样):")
    query = "出行要带什么"
    for i, doc in enumerate(retriever.invoke(query)):
        print(f"  {i+1}. [{doc.metadata['title']}] {doc.page_content[:60]}")

    # 💡 适用场景:
    #   similarity: 用户问精确问题 (e.g. "退款多少"), 要最准的那条
    #   MMR:       用户问开放式问题 (e.g. "推荐点什么"), 要多条不同维度


# ============================================================
# 6. metadata 过滤 — 先筛字段,再向量检索
# ============================================================
banner("6. metadata 过滤 (filter by metadata)")


def demo_metadata_filter(vectorstore: FAISS) -> None:
    # search_kwargs 里传 filter, 只在匹配的 metadata 子集里搜
    # FAISS 支持简单字段等值匹配, Chroma / PGVector 支持更复杂 ($gt / $in / $and)
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": 2,
            "filter": {"title": "退订政策"},  # 只在"退订政策"文档里搜
        },
    )

    print(">>> filter={title:'退订政策'} 后, 只能搜到退订政策的块:")
    for doc in retriever.invoke("我要退票"):
        print(f"  [{doc.metadata['title']}] {doc.page_content[:60]}")

    # 💡 实战:
    #   - 多租户: filter={"tenant_id": "t_001"} 隔离租户数据
    #   - 按时间: filter={"created_at": {"$gt": "2026-01-01"}}
    #   - 按类别: filter={"category": {"$in": ["policy", "faq"]}}
    #   - 配合 query 分类器用: 先 LLM 判意图 → filter metadata → 再检索


# ============================================================
# 7. score threshold — 过滤低相似度结果
# ============================================================
banner("7. score threshold — 过滤低相似度结果")


def demo_score_threshold(vectorstore: FAISS) -> None:
    # similarity_search_with_score 返回 (doc, score), score 越小越相似 (取决于距离度量)
    # FAISS 默认用 L2 距离,score 范围 [0, ∞),越小越好
    # 用 cosine 距离则 score 范围 [-1, 1],越大越好 (1=完全相同)
    print(">>> 带分数的检索 + 阈值过滤:")
    docs_scores = vectorstore.similarity_search_with_score(
        "完全不相关的问题,例如量子纠缠的实验验证",
        k=5,
    )
    for doc, score in docs_scores:
        marker = "✓" if score < 50 else "✗ 噪点"  # 阈值根据 embedding 调整
        print(f"  score={score:.2f} {marker} [{doc.metadata['title']}] {doc.page_content[:40]}")

    # 💡 实战:
    #   阈值太严 → 召回漏 (用户问的没答)
    #   阈值太松 → 召回噪声 (LLM 拿到不相关内容)
    #   套路: 设一个保守阈值 (e.g. score < 30), 过滤后的结果送 LLM;
    #        同时让 LLM 在 system prompt 里 "如果上下文不相关就回答不知道"


# ============================================================
# 8. 持久化 — 向量库保存到磁盘
# ============================================================
banner("8. 持久化 — save / load 向量库")


def demo_persistence(vectorstore: FAISS) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        save_dir = Path(tmp) / "faiss_index"

        # 保存: 写两个文件, index.faiss (向量) + index.pkl (文档+元数据)
        vectorstore.save_local(str(save_dir))
        print(f">>> 保存到 {save_dir}:")
        for f in save_dir.iterdir():
            print(f"  {f.name} ({f.stat().st_size} bytes)")

        # 加载: 用同一个 embedding 类 (维度必须一致) — 必须用同一个实例!
        embeddings = get_safe_embeddings()
        loaded = FAISS.load_local(
            str(save_dir),
            embeddings,
            allow_dangerous_deserialization=True,  # FAISS pickle 反序列化需明确允许
        )
        print(f">>> 加载后, 文档数: {loaded.index.ntotal}")

        # 验证: 加载的库能正常检索
        result = loaded.similarity_search("客服热线", k=1)
        print(f"  检索测试: {result[0].metadata['title']}")

    # 💡 实战:
    #   - FAISS: 适合 < 10M 向量, 内存加载 (单机 / 单进程)
    #   - 生产: PGVector / Pinecone / Weaviate / Milvus / Qdrant — 分布式 + 持久化 + filter
    #   - 重建成本高: 文档更新要走 "重建 → 增量 upsert" 的工程化流程


# ============================================================
# 9. RAG Agent — Retriever 接成 Tool
# ============================================================
banner("9. RAG Agent — Retriever 作为 Tool")


def demo_rag_agent(vectorstore: FAISS) -> None:
    from langchain.agents import create_agent

    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    @tool
    def search_knowledge_base(query: str) -> str:
        """搜索内部知识库, 回答退订政策 / 行李规定 / 客服热线等问题。
        返回格式: [来源标题] 内容片段, 多条用空行分隔.
        """
        docs = retriever.invoke(query)
        if not docs:
            return "未找到相关内容, 请告诉用户不知道。"
        return "\n\n".join(
            f"[来源: {d.metadata['title']}]\n{d.page_content}" for d in docs
        )

    llm = get_llm()
    agent = create_agent(
        model=llm,
        tools=[search_knowledge_base],
        system_prompt=(
            "你是客服助手。用户问退订 / 行李 / 客服热线时,必须调用 search_knowledge_base 工具,"
            "然后基于返回内容回答,并引用来源 (e.g. '根据退订政策')。上下文不相关就说不知道。"
        ),
    )

    queries = [
        "发车前 2 小时退票要扣多少?",  # 应该答 50%
        "行李最多能带多少公斤?",         # 应该答 20kg
        "客服电话多少?",                 # 应该答 400-100-1000
    ]
    for q in queries:
        print(f"\n>>> Q: {q}")
        result = agent.invoke({"messages": [HumanMessage(q)]})
        print(f"  A: {result['messages'][-1].content[:200]}")


# ============================================================
# entry point
# ============================================================
if __name__ == "__main__":
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        print("请先在 .env 中设置 ANTHROPIC_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY")
        raise SystemExit(1)

    # 准备文档
    docs = demo_prepare_docs()
    chunks = demo_splitting(docs)
    vectorstore = demo_vector_store(chunks)

    # 检索的 5 种玩法
    # demo_similarity(vectorstore)
    # demo_mmr(vectorstore)
    # demo_metadata_filter(vectorstore)
    # demo_score_threshold(vectorstore)
    # demo_persistence(vectorstore)

    # RAG Agent (LLM 驱动, M3 可能不稳)
    try:
        demo_rag_agent(vectorstore)
    except Exception as e:
        print(f"[demo_rag_agent] 跳过: {type(e).__name__}: {str(e)[:120]}")

    print("\n[OK] 05_retrieval.py 全部 demo 跑完。")
