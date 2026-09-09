# L1 — LangChain 1.x Agent Framework

> 5 个模块覆盖 LangChain 1.x 的全部核心能力。
> 学完这一层,你能写出**单 Agent** 的完整应用。

## 模块清单

| # | 文件 | 关键 API | 一句话目标 |
|---|------|---------|----------|
| 01 | `01_models.py` | `init_chat_model` / `bind_tools` / structured output | 任何 provider 都能装进同一个接口 |
| 02 | `02_tools.py` | `@tool` / `BaseTool` / `args_schema` | 把 Python 函数 / 类 / API 暴露给 LLM |
| 03 | `03_agents.py` | `create_agent` | 1.0 统一 Agent 入口,5+ 轮 tool loop |
| 04 | `04_middleware.py` | `@dynamic_prompt` / `@wrap_model_call` / `HumanInTheLoopMiddleware` | 在 Agent 上插桩 |
| 05 | `05_retrieval.py` | `Embeddings` / `VectorStore` / `Retriever` | 给 Agent 接私有知识库 |

## 推荐阅读顺序

```
01_models.py          ← 先懂"模型是什么"
   ↓
02_tools.py           ← 再懂"工具是什么"
   ↓
03_agents.py          ← 把 model + tool 拼成 Agent
   ↓
04_middleware.py      ← 在 Agent 上加横切逻辑
   ↓
05_retrieval.py       ← 最后接知识库
```

## 跑起来

```bash
# 配置环境变量 (见 .env.example)
export MINIMAX_API_KEY="..."

# 安装依赖
pip install -r ../../requirements.txt

# 跑任一模块
python 01_models.py
python 02_tools.py
python 03_agents.py
python 04_middleware.py
python 05_retrieval.py
```

每个模块都是独立运行的,运行时会打印彩色日志说明发生了什么。

## 学完 L1 你能

1. 用 3 行代码起一个 Agent: `create_agent(model, tools)`
2. 写 `@tool` 把任何 Python 函数暴露给 LLM
3. 用 Pydantic 让 Agent 输出结构化 JSON
4. 写中间件在 LLM 调用前后做日志 / 鉴权 / 重写
5. 把一堆文档做成 Agent 能搜的知识库

## 跳过的内容 (已过时)

- `langchain.chains.LLMChain` → `create_agent`
- `langchain.agents.initialize_agent` → `create_agent`
- `langchain.memory.ConversationBufferMemory` → L2 LangGraph 持久化
- `langchain.text_splitter` → `langchain-text-splitters` 包
- `langchain_community.chat_models` → `langchain-ollama` 包
