# L1-05 · RAG 入门:给 Agent 接私有知识库

> Agent 默认只能问 LLM "通用知识",但 80% 的业务场景需要"私有知识"(公司政策 / 产品手册 / 工单记录)。RAG(检索增强生成)把"先搜资料 → 再答问题"做成标准 pipeline。这篇从文档加载到向量库到 RAG Agent 完整拆解。

## 为什么学这个

ChatGPT 不知道你公司 2026 年的报销标准,Claude 也回答不了你家的产品定价。LLM 的知识有截止日期,企业内部知识更不可能进训练集。

RAG 思路很简单:

1. 把私有文档切块、向量化,存到向量库
2. 用户提问 → 检索相似文档 → 把 top-k 文档塞给 LLM
3. LLM 基于文档 + 自己的知识回答

这套机制在 LangChain 1.x 里 30 行代码就能跑,但 9 个细节决定召回质量:

- 文档怎么切块?(chunk_size / overlap / separators)
- embedding 怎么选?(OpenAI / 本地 / 离线 hash)
- 检索是相似度还是 MMR?
- 怎么过滤低质量结果?(score threshold)
- 怎么按 metadata 过滤?(多租户隔离)
- 向量库怎么持久化?
- 怎么把 Retriever 接成 Agent 的 tool?

## 学完你能回答 9 个问题

1. 怎么从内存 / 文件加载文档?
2. 怎么切块(chunk_size / chunk_overlap / separators)?
3. 怎么选 embedding(OpenAI / 本地 / 离线 hash)?
4. 怎么用 FAISS 构向量库?
5. similarity 检索 vs MMR 检索差别在哪?
6. 怎么按 metadata 过滤检索结果?
7. 怎么给相似度设阈值过滤低质结果?
8. 向量库怎么持久化到磁盘?
9. 怎么把 Retriever 接成 Agent 的 tool(完整 RAG)?

## 1. 准备文档:内存 + 磁盘

```python
from langchain_core.documents import Document

# 内存直接构造(测试 / 单测)
docs = [
    Document(page_content="退订政策...", metadata={"title": "退订政策"}),
    Document(page_content="行李规定...", metadata={"title": "行李规定"}),
]

# 磁盘用 TextLoader
from langchain_community.document_loaders import TextLoader
loaded = TextLoader("policy.txt", encoding="utf-8").load()
```

生产里文档通常在 DB / OSS / Confluence,LangChain 有对应 loader:

| 来源 | Loader |
| --- | --- |
| 文件系统 | `TextLoader` / `PDFLoader` / `CSVLoader` |
| 数据库 | `SQLDatabaseLoader` |
| Confluence / Notion | `ConfluenceLoader` / `NotionDBLoader` |
| Web | `WebBaseLoader` / `FireCrawlLoader` |

`Document` 结构:

```python
class Document:
    page_content: str           # 文本
    metadata: dict[str, Any]    # 元数据(title / source / date / tenant_id)
```

## 2. 切块:`RecursiveCharacterTextSplitter`

长文档必须切块,否则 embedding 会丢信息:

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=100,         # 每块最多 100 字符
    chunk_overlap=20,       # 相邻块重叠 20 字符
    separators=["\n\n", "\n", "。", " "],  # 中文场景加 "。"
)
chunks = splitter.split_documents(docs)
```

`separators` 按优先级尝试:先 `\n\n`(段落)→ `\n`(行)→ `。`(句子)→ ` `(词)。

切块策略经验:

| chunk_size | 粒度 | 适用 |
| --- | --- | --- |
| 200-500 字符(中文) | 细 | FAQ / 短答 |
| 500-1500 token(英文) | 粗 | 文档 / 报告 |

`chunk_overlap` 通常 10-20% of chunk_size,避免上下文切断。

> 💡 高级:Markdown 文档用 `MarkdownHeaderTextSplitter`(按 ## 标题切),代码用 `CodeTextSplitter`(按函数切)。

## 3. Embedding + 向量库(FAISS)

```python
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = FAISS.from_documents(chunks, embeddings)
print(vectorstore.index.ntotal)  # 向量数
```

### 坑:不是所有 provider 都给 embedding

某些 LLM provider(M3)只暴露 chat 接口,**没有 embedding 端点**。直接 `embed_query()` 会 `ValueError: No embedding data received`。

**解法:`safe_vectorstore` 模式——探测失败自动降级**

```python
from langchain_community.embeddings import DeterministicFakeEmbedding

_cached_embeddings = None

def get_safe_embeddings():
    global _cached_embeddings
    if _cached_embeddings is not None:
        return _cached_embeddings
    candidate = OpenAIEmbeddings(model="text-embedding-3-small")
    try:
        candidate.embed_query("test")  # 探测
        _cached_embeddings = candidate
        return candidate
    except Exception:
        print(">>> 真实 embedding 不可用,降级到 fake")
        _cached_embeddings = DeterministicFakeEmbedding(size=384)
        return _cached_embeddings

vectorstore = FAISS.from_documents(chunks, get_safe_embeddings())
```

`FAISS save/load` **必须用同一个 embedding 实例**(维度一致)!

### Embedding 选型

| 模型 | 维度 | 价格 | 适用 |
| --- | --- | --- | --- |
| OpenAI text-embedding-3-small | 1536 | $0.02/M token | 通用 |
| Voyage-3 | 1024 | - | RAG SOTA |
| BGE-M3 / mxbai-embed-large | 1024 | 免费 | 开源 / 本地 / 隐私 |
| multilingual-e5 | 1024 | 免费 | 多语言 |

## 4. similarity 检索(最基础)

```python
retriever = vectorstore.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 2},
)

for doc in retriever.invoke("退款要扣多少手续费?"):
    print(f"[{doc.metadata['title']}] {doc.page_content[:80]}")
```

`k` 值经验:

| k | 优劣 |
| --- | --- |
| 1 | 偶尔召回漏,回答不全面 |
| 3-5 | 大多数 RAG 甜点 |
| 10+ | 给 LLM 太多上下文,可能分散注意力 + 烧 token |

实战常配合 reranker:先取 k=20,再用 Cohere / BGE-reranker 重排,留 top-5。

## 5. MMR 检索 — 多样性 vs 相似度

```python
retriever = vectorstore.as_retriever(
    search_type="mmr",
    search_kwargs={
        "k": 3,
        "fetch_k": 10,      # 候选池
        "lambda_mult": 0.5,  # 0=纯多样, 1=纯相似
    },
)

for doc in retriever.invoke("出行要带什么"):
    print(f"[{doc.metadata['title']}] {doc.page_content[:60]}")
```

MMR(Maximal Marginal Relevance):**既要"和 query 像",还要"和已选结果不太像"**。

| 检索类型 | 适用场景 |
| --- | --- |
| similarity | 用户问精确问题("退款多少") → 要最准 |
| MMR | 用户问开放式问题("推荐点什么") → 要多样 |

## 6. metadata 过滤

```python
retriever = vectorstore.as_retriever(
    search_type="similarity",
    search_kwargs={
        "k": 2,
        "filter": {"title": "退订政策"},  # 只在"退订政策"文档里搜
    },
)
```

实战场景:

| 场景 | filter |
| --- | --- |
| 多租户隔离 | `{"tenant_id": "t_001"}` |
| 按时间 | `{"created_at": {"$gt": "2026-01-01"}}`(Chroma / PGVector 支持) |
| 按类别 | `{"category": {"$in": ["policy", "faq"]}}` |

> FAISS 只支持简单字段等值匹配。Chroma / PGVector 支持 `$gt` / `$in` / `$and`。

## 7. score threshold 过滤低相似度

```python
docs_scores = vectorstore.similarity_search_with_score(
    "完全不相关的问题,例如量子纠缠",
    k=5,
)
for doc, score in docs_scores:
    marker = "✓" if score < 50 else "✗ 噪点"
    print(f"score={score:.2f} {marker} [{doc.metadata['title']}]")
```

FAISS 默认 L2 距离,score 越小越相似。

实战套路:阈值过严 → 召回漏(用户问的没答);阈值过松 → 召回噪声(LLM 拿不相关内容)。

| 做法 | 效果 |
| --- | --- |
| 阈值保守(20-30) | 过滤后送 LLM,SystemMessage 加"上下文不相关就说不知道" |
| 多档阈值 | 文档类用 30,FAQ 用 50,FAQ 命中率高 |

## 8. 持久化:save / load

```python
from pathlib import Path

# 保存(写两个文件:index.faiss + index.pkl)
vectorstore.save_local("./faiss_index")

# 加载(必须用同一个 embedding)
embeddings = get_safe_embeddings()  # 用过的实例
loaded = FAISS.load_local(
    "./faiss_index",
    embeddings,
    allow_dangerous_deserialization=True,  # FAISS pickle 反序列化需明确允许
)
```

向量库选型:

| 库 | 适用 | 持久化 | 多租户 filter |
| --- | --- | --- | --- |
| FAISS | < 10M 向量,单机 | 本地文件 | ✗ |
| Chroma | 小到中等 | 文件 / DuckDB | ✓ |
| PGVector | 生产 / PG 已用 | PostgreSQL | ✓ |
| Pinecone | SaaS,亿级 | 云 | ✓ |
| Weaviate / Milvus | 大规模 | 分布式 | ✓ |

> 💡 FAISS save/load 必须用同一个 embedding 实例——embedding 维度不同直接报错。

## 9. 完整 RAG Agent

把 Retriever 接成 Agent 的 tool:

```python
from langchain.agents import create_agent

@tool
def search_knowledge_base(query: str) -> str:
    """搜索内部知识库,回答退订政策 / 行李规定 / 客服热线等问题。"""
    docs = retriever.invoke(query)
    if not docs:
        return "未找到相关内容,请告诉用户不知道。"
    return "\n\n".join(
        f"[来源: {d.metadata['title']}]\n{d.page_content}" for d in docs
    )

agent = create_agent(
    model=llm,
    tools=[search_knowledge_base],
    system_prompt=(
        "你是客服助手。用户问退订 / 行李 / 客服热线时,"
        "必须调用 search_knowledge_base,基于返回内容回答。"
        "上下文不相关就说不知道。"
    ),
)

# 问几个
for q in ["发车前 2 小时退票要扣多少?", "行李最多能带多少公斤?", "客服电话?"]:
    result = agent.invoke({"messages": [HumanMessage(q)]})
    print(f"Q: {q}\nA: {result['messages'][-1].content[:200]}")
```

完整 RAG 链路:

```
用户提问
   ↓
Agent 决定调 search_knowledge_base
   ↓
Retriever 从向量库 top-k 检索
   ↓
Tool 返回 "[来源] 内容片段..."
   ↓
LLM 基于 Tool 结果 + 自己的知识生成最终答案
   ↓
引用来源("根据退订政策...") → 用户
```

## 实战踩坑

| 坑 | 原因 | 解法 |
| --- | --- | --- |
| embedding `ValueError` | provider 没暴露端点 | `safe_vectorstore` 探测降级 |
| FAISS load 报错 | embedding 维度变了 | 用 save 时的同一个 embedding |
| 召回质量差 | chunk_size 太大 | 200-500 字符 / 500-1500 token |
| 召回质量差 | separator 没"。" | 中文文档必须加 |
| metadata filter 报错 | FAISS 不支持复杂语法 | 切到 Chroma / PGVector |
| RAG 答非所问 | top-k 太少 | k=5,配合 reranker |
| RAG 幻觉 | system prompt 没约束 | "上下文不相关就说不知道" |
| 向量库加载慢 | pickle 大 | 持久化到 PG,启动自动加载 |

## 生产架构

```python
# 1. 文档加载 + 切块
docs = load_documents_from_s3(bucket, prefix)
chunks = splitter.split_documents(docs)

# 2. Embedding + 向量库(选型按规模)
vectorstore = PGVector.from_documents(
    chunks,
    OpenAIEmbeddings(model="text-embedding-3-small"),
    connection_string="postgresql://...",
    collection_name="kb_v1",
)

# 3. Retriever 接 Agent
retriever = vectorstore.as_retriever(
    search_type="mmr",
    search_kwargs={"k": 5, "fetch_k": 20, "lambda_mult": 0.5},
)

@tool
def search_kb(query: str) -> str:
    """内部知识库检索,返回带来源的片段。"""
    docs = retriever.invoke(query)
    if not docs:
        return "知识库无结果"
    return "\n\n".join(
        f"[来源 {d.metadata.get('source')}] {d.page_content}"
        for d in docs
    )

# 4. Agent 强约束
agent = create_agent(
    model=llm,
    tools=[search_kb],
    system_prompt=(
        "你是客服。涉及产品 / 政策 / FAQ 必须调 search_kb,"
        "回答时引用来源。上下文不相关就说不知道。"
    ),
)
```

RAG 三大工程化要点:

1. **chunk 策略**:文档类型选 splitter,固定 chunk_size + overlap
2. **embedding 选型**:数据敏感走 BGE 本地,通用走 OpenAI / Voyage
3. **监控指标**:召回命中率(返回 doc 是否被 LLM 引用)、LLM 拒答率

## 小结

- RAG = 检索 + 生成,核心是"先找资料再让 LLM 答"
- 文档切块 200-500 字符,中文 separator 必须有 "。"
- embedding 选型按数据敏感度(本地 BGE / 通用 OpenAI)
- FAISS save/load 必须用同一个 embedding 实例
- similarity vs MMR:精确问 vs 开放问
- metadata filter 实现多租户隔离
- Retriever 接 Agent 关键:docstring 写"返回格式"让 LLM 会用

RAG 搞定了"私有知识"。下一步是把 Agent **拆成图**,实现条件路由、并行、人工介入——L2 StateGraph 见。

## 延伸阅读

- [LangChain Retrieval 官方文档](https://python.langchain.com/docs/concepts/retrieval/)
- 上一篇:[L1-04 Middleware 横切](./L1-04_middleware.md)
- 下一篇:[L2-06 StateGraph 把 Agent 拆成图](./L2-06_state_graph.md)
- 源码:`01-langchain-basics/05_retrieval.py`
