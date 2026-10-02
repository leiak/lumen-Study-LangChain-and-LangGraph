# L1-01 · 接入任何 LLM,5 分钟跑通第一个 Agent

> LangChain 1.x 入门第一课。一文讲清楚怎么用一行代码切不同 provider、流式输出、结构化 JSON、工具绑定、多轮对话。

## 为什么学这个

如果你 2026 年想做一个 AI Agent,第一步永远是「调通一次 LLM」。LangChain 1.x 把这一步抽象得非常干净:`init_chat_model(model="...")` 一行切 GPT / Claude / DeepSeek / MiniMax / Ollama,业务代码不用改。

这篇文章解决三个最常见问题:

1. **provider 切换**:不同 LLM 怎么用同一套代码调用
2. **结构化输出**:让模型吐 JSON 而不是自然语言
3. **工具调用**:让模型决定"调哪个函数 + 传什么参数"

最后讲一下推理模型的"思考过程"坑——DeepSeek-R1 / Kimi / MiniMax-M3 都会先吐一段 `<think>...</think>` 再回答,直接拿来解析 JSON 会崩。

## 学完你能回答 10 个问题

1. 怎么用 `init_chat_model` 接入任何 provider?
2. `invoke` / `stream` / `ainvoke` 三个方法区别?
3. 怎么让模型流式输出,前端做打字机?
4. 怎么用 Pydantic 让模型返回 JSON?
5. 推理模型的 `<think>` 块怎么剥掉?
6. `with_structured_output` 的 method 怎么选?
7. 怎么用 `bind_tools` 把工具提前绑给模型?
8. 多轮对话怎么手动管理 messages 列表?
9. 推理模型跑 structured output 的双轨策略?
10. LangChain 1.x 的输出对象 `AIMessage` 有哪些字段?

## 1. 最基础的调用:一行切 provider

LangChain 1.x 的工厂函数 `init_chat_model` 通过 `model=` 字符串识别 provider,后端自动路由。

```python
from langchain.chat_models import init_chat_model

# OpenAI
llm = ChatOpenAI(model="gpt-4o-mini", api_key=...)

# Anthropic
llm = init_chat_model("claude-haiku-4-5", api_key=...)

# DeepSeek(走 OpenAI 兼容协议)
llm = init_chat_model("deepseek-chat", base_url="https://api.deepseek.com/v1")

# MiniMax M3(走 OpenAI 兼容协议)
llm = init_chat_model("MiniMax-M3", base_url="https://api.minimax.chat/v1")
```

调用接口统一:

```python
resp = llm.invoke("用一句话介绍 LangChain 1.x")
print(resp.content)              # 字符串
print(resp.response_metadata)    # 包含 model_name / token_usage / finish_reason
```

`response_metadata` 是 LangChain 的"瑞士军刀":生产里计费用 `token_usage`、监控用 `model_name`、判断截断看 `finish_reason`。

> 💡 **实战技巧**:把 provider 选择封装到 `_common.py` 的 `get_llm()` 函数里。.env 配 `ANTHROPIC_API_KEY` 走 Claude,配 `DEEPSEEK_API_KEY` 走 DeepSeek,业务代码 `from _common import get_llm` 永远不变。

## 2. 流式输出:token 一个一个蹦

`stream()` 返回迭代器,每段是一个 `AIMessageChunk`(只有一小段 content)。前端 SSE 推送直接用。

```python
print("打字机效果:")
for chunk in llm.stream("写一首关于 Agent 的七言绝句"):
    print(chunk.content, end="", flush=True)
```

| 模式 | 方法 | 用途 |
| --- | --- | --- |
| 同步流 | `llm.stream()` | CLI / 调试 |
| 异步流 | `async for chunk in llm.astream()` | FastAPI / WebSocket |
| Token 流 | `stream_mode="messages"` | LangGraph Agent 流式 |

> ⚠️ `chunk.content` 可能是空字符串(比如只更新 tool_calls)。生产代码先判断 `if chunk.content:`。

## 3. 结构化输出:让模型吐 JSON

业务里 80% 场景需要"模型返回结构化数据"。LangChain 1.x 推荐 `Pydantic` + `with_structured_output`:

```python
from pydantic import BaseModel, Field

class MovieReview(BaseModel):
    title: str = Field(description="电影名")
    rating: float = Field(description="1-5 星评分")
    pros: list[str] = Field(description="优点,3 条以内")
    cons: list[str] = Field(description="缺点,3 条以内")

review = llm.with_structured_output(MovieReview).invoke(
    "评价《流浪地球》,只返回 JSON"
)
print(review.title, review.rating)  # 自动是 str / float
```

`with_structured_output` 底层走两种路径:

| method | 实现 | 适用 |
| --- | --- | --- |
| `"function_calling"` | tool_calls 参数 + 校验 | OpenAI / DeepSeek / 大多数新模型 |
| `"json_schema"` | response_format 严格 JSON | 部分 provider(走原生 JSON schema) |

> 💡 **实战**:method 不写默认走 `"function_calling"`,覆盖率最广。

### 坑:推理模型的 think 块

DeepSeek-R1、Kimi、MiniMax-M3 这类推理模型,默认会在 `message.content` 前面吐思考过程:

```text
<think>用户让我评价流浪地球,我需要从剧情、特效、情感三个维度展开...</think>
{"title": "流浪地球", "rating": 4.5, ...}
```

直接 `with_structured_output` 会因为 content 不是纯 JSON 而解析失败。**双轨策略**搞定:

```python
import re
from langchain_core.output_parsers import PydanticOutputParser, BaseOutputParser

_THINK_RE = re.compile(
    r"<think>.*?</think>|<thinking>.*?</thinking>",
    flags=re.DOTALL,
)

class StripThinkParser(BaseOutputParser):
    """解析前剥掉 <think> 块"""
    inner: BaseOutputParser

    def parse(self, text, **kwargs):
        cleaned = _THINK_RE.sub("", text).strip()
        if not cleaned:
            raise ValueError(f"模型返回为空: {text[:200]}")
        return self.inner.parse(cleaned, **kwargs)

# 备路
chain = llm | StripThinkParser(inner=PydanticOutputParser(pydantic_object=MovieReview))
review = chain.invoke("评价《流浪地球》")
```

实战代码:

```python
review = None
try:
    review = llm.with_structured_output(MovieReview, method="function_calling").invoke(prompt)
except Exception:
    # 备路:剥 CoT + Pydantic 解析
    review = (llm | StripThinkParser(inner=PydanticOutputParser(pydantic_object=MovieReview))).invoke(prompt)
```

> ⚠️ 这个坑所有 2026 年的推理模型都有,务必把 `StripThinkParser` 抄进项目 `_common.py`。

## 4. bind_tools:让模型决定调哪个函数

`bind_tools` 把 Python 函数的 schema(从签名 + docstring 推断)发给模型,模型返回 `tool_calls` 列表,业务代码路由回 Python 函数:

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """查某城市天气"""
    return f"{city} 晴,25°C"

llm_with_tools = llm.bind_tools([get_weather])
resp = llm_with_tools.invoke("北京天气怎么样?")
print(resp.tool_calls)  # [{'name': 'get_weather', 'args': {'city': '北京'}, 'id': '...'}]
```

`tool_calls` 是 `list[dict]`,每个元素有:

| 字段 | 含义 |
| --- | --- |
| `name` | 函数名(对应 `@tool` 装饰的函数) |
| `args` | LLM 填的参数(dict) |
| `id` | 后续回填 `ToolMessage` 时配对 |

拿到 `tool_calls` 后业务逻辑通常这样:

```python
# 1. 路由回 Python 函数
result = get_weather.invoke(resp.tool_calls[0]["args"])

# 2. 包成 ToolMessage 喂回去
from langchain_core.messages import ToolMessage
tm = ToolMessage(content=str(result), tool_call_id=resp.tool_calls[0]["id"])

# 3. 调一次 LLM 让它基于工具结果生成最终回复
final = llm_with_tools.invoke([user_msg, resp, tm])
```

> 这一套「bind → dispatch → 回填」的完整逻辑,LangChain 内部的 `create_agent` 都帮你做了。下一篇「Tools」展开讲。

## 5. 多轮对话:手动管理 messages

LangChain 没有强制"会话对象",messages 就是 `list[BaseMessage]`,自己 append 就行:

```python
from langchain_core.messages import SystemMessage, HumanMessage

messages = [
    SystemMessage(content="你是一个简短的助手,每句不超过 20 字。"),
    HumanMessage(content="我叫王明。"),
]

resp1 = llm.invoke(messages)
messages.append(resp1)  # AIMessage 进历史

messages.append(HumanMessage(content="我叫什么?"))
resp2 = llm.invoke(messages)
print(resp2.content)  # 应该答: 你叫王明
```

四类基础 message:

| 类 | 角色 | 用途 |
| --- | --- | --- |
| `SystemMessage` | system | 角色 / 行为约束 |
| `HumanMessage` | user | 用户输入 |
| `AIMessage` | assistant | 模型回复(含 tool_calls) |
| `ToolMessage` | tool | 工具结果回填 |

> ⚠️ **实战提醒**:生产环境不要自己 append,要用 LangGraph 的 `checkpointer`(L2-07 那篇讲),支持持久化 + 多设备。

## 实战踩坑

| 坑 | 原因 | 解法 |
| --- | --- | --- |
| M3 / DeepSeek-R1 解析 JSON 失败 | 推理模型先吐 think 块 | `StripThinkParser` |
| MiniMax M3 没 embedding 端点 | 协议只暴露 chat | 走 `OpenAIEmbeddings` 或 `DeterministicFakeEmbedding` |
| `invoke` 抛 `BadRequestError` | API key 没设 / 过期 | `.env` 检查 `*_API_KEY` |
| `chunk.content` 为空 | LLM 正在吐 tool_calls | 业务逻辑里 `if chunk.content:` 跳过 |
| Windows GBK 编码崩 | emoji 编码失败 | 文件顶部加 `sys.stdout.reconfigure(encoding="utf-8")` |

## 生产架构

```python
# _common.py — 统一 LLM 工厂
def get_llm():
    if os.getenv("ANTHROPIC_API_KEY"):
        return init_chat_model("claude-haiku-4-5", temperature=0)
    if os.getenv("DEEPSEEK_API_KEY"):
        return init_chat_model("deepseek-chat", base_url="https://api.deepseek.com/v1")
    if os.getenv("MINIMAX_API_KEY"):
        return init_chat_model("MiniMax-M3", base_url="https://api.minimax.chat/v1")
    if os.getenv("OPENAI_API_KEY"):
        return init_chat_model("gpt-4o-mini")
    raise RuntimeError("未配置任何 LLM API key")
```

业务代码永远 `from _common import get_llm`,切 provider 不动业务。

## 小结

- `init_chat_model` 是 LangChain 1.x 统一入口,provider 切换零成本
- `with_structured_output` + Pydantic 是结构化输出标配
- 推理模型必加 `StripThinkParser` 处理 `<think>` 块
- `bind_tools` 是 Agent 的基础,但完整调用循环在 `create_agent` 里(下一篇讲)

## 延伸阅读

- [LangChain Models 官方文档](https://python.langchain.com/docs/concepts/models/)
- 下一篇:[L1-02 Tools:把 Python 函数变成 LLM 能调的东西](./L1-02_tools.md)
- 源码:`01-langchain-basics/01_models.py`
