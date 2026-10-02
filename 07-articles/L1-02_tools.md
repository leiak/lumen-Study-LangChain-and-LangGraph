# L1-02 · 工具系统:把 Python 函数变成 LLM 能调的东西

> Agent 的能力 = 模型推理 + 工具调用。这篇讲透 LangChain 1.x 的工具系统:从最简单的 `@tool` 到 BaseTool 子类、异步工具、错误处理、运行时上下文注入、完整 dispatch 流程。

## 为什么学这个

Agent 能落地,核心靠"让 LLM 决定调哪个函数 + 传什么参数"。LangChain 1.x 的 `@tool` 装饰器一秒钟把 Python 函数变成 LLM 可调的工具,但实战里 80% 的坑都在细节:

- 怎么校验参数?(`args_schema`)
- 怎么调 HTTP / 数据库?(`async def`)
- 业务报错怎么处理?(让 LLM 看到错误再决定)
- 怎么传 user_id / session_id?(LLM 不能填的字段)
- 怎么返回大数据(`artifact` vs `content`)
- 模型一次返回多个工具怎么并行执行?

这篇拆 10 个 demo,从最简到生产全覆盖。

## 学完你能回答 10 个问题

1. `@tool` 装饰器怎么用?(最简形态)
2. 怎么用 `args_schema` 严格定义参数?(Pydantic 校验)
3. 怎么用 `BaseTool` 子类封装有状态工具?
4. 怎么写异步工具?(调 HTTP / 数据库)
5. 工具报错怎么处理?(`ToolException` 让 LLM 看到)
6. 怎么程序化构造工具?(`StructuredTool.from_function`)
7. 怎么返回 artifact?(content 给 LLM,artifact 给程序)
8. 怎么注入运行时上下文?(`InjectedToolArg`,如 user_id)
9. 完整 tool calling 流程是什么?(bind → dispatch → ToolMessage)
10. 模型一次返回多个工具怎么并行?

## 1. `@tool` 最简形态

```python
from langchain_core.tools import tool

@tool
def add(a: int, b: int) -> int:
    """把两个数相加。"""
    return a + b

print(add.name)            # "add"
print(add.description)     # "把两个数相加。"
print(add.args)            # {"a": int, "b": int}
print(add.invoke({"a": 1, "b": 2}))  # 3
```

`@tool` 内部用 `inspect` + `docstring` 推断 schema:

| 来源 | 推断 |
| --- | --- |
| 函数签名 | 参数名 + 类型 |
| docstring | 工具描述 |
| 默认值 | 字段默认值 |

> ⚠️ `invoke` **永远接受 dict**,不是位置参数。LLM 调工具时也是 dict 形式传 args。

## 2. `@tool + args_schema` 严格校验

类型提示够了之后,业务还要范围校验(比如 `top_k` 不能超过 20):

```python
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class SearchInput(BaseModel):
    query: str = Field(description="搜索关键词")
    top_k: int = Field(default=3, ge=1, le=20)  # 范围约束

@tool("web_search", args_schema=SearchInput)
def web_search(query: str, top_k: int = 3) -> list[dict]:
    """(mock) 在网上搜索关键词。"""
    return [{"title": f"结果 {i}"} for i in range(top_k)]

# 正常
web_search.invoke({"query": "LangChain", "top_k": 2})

# 越界 → 抛 Pydantic ValidationError,LangChain 自动转给 LLM
web_search.invoke({"query": "test", "top_k": 999})  # ✗
```

`Field(ge=, le=, description=)` 三个作用:

| 字段 | 用途 |
| --- | --- |
| `description` | 发给 LLM,帮它理解参数含义 |
| `ge` / `le` | 校验,LLM 不会填越界值 |
| `default` | 可选参数默认值 |

> 💡 **实战技巧**: `description` 是给 LLM 看的!写"用户搜索的产品关键词,5-50 字"比写"query"效果好十倍。

## 3. `BaseTool` 子类:有状态工具

工具要带状态(数据库连接 / 缓存 / 配置)时,用子类:

```python
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

class _CalculatorInput(BaseModel):
    expression: str = Field(description="数学表达式,例如 1+2*3")

class CalculatorTool(BaseTool):
    name: str = "calculator"
    description: str = "计算数学表达式,支持四则运算。"
    args_schema: type[BaseModel] = _CalculatorInput
    max_retries: int = 1  # Agent 框架下,工具失败自动重试次数

    def _run(self, expression: str) -> str:
        try:
            return str(eval(expression, {"__builtins__": {}}, {}))
        except Exception as exc:
            raise ToolException(f"无法计算 '{expression}': {exc}")

    async def _arun(self, expression: str) -> str:
        return self._run(expression)
```

`BaseTool` 适用场景:

| 场景 | 做法 |
| --- | --- |
| 数据库连接 | `conn: Connection` 作 Pydantic 字段 |
| 缓存 | `cache: dict = Field(default_factory=dict)` |
| 限流 / 配额 | `quota_remaining: int` |
| 配置注入 | `api_key: str` |

> 跟 Spring `@Service` / Go struct method 一回事,只是 LLM 能直接调用它。

## 4. 异步工具:asyncio 是必备

调 HTTP / 数据库时必须 `async def`,否则阻塞整个 Agent:

```python
@tool
async def fetch_url(url: str) -> str:
    """(mock) 异步抓取 URL 内容。"""
    await asyncio.sleep(0.1)
    return f"<html>{url}...</html>"

# 异步调用
result = await fetch_url.ainvoke({"url": "https://example.com"})
```

实战里多个独立 IO 必须并发,`asyncio.gather` 救场:

```python
import asyncio

t0 = time.time()
results = await asyncio.gather(
    fetch_url.ainvoke({"url": "https://a.com"}),
    fetch_url.ainvoke({"url": "https://b.com"}),
    fetch_url.ainvoke({"url": "https://c.com"}),
)
# 顺序 0.3s → 并发 0.1s
```

> 💡 LangChain 1.x 里,`create_agent` 会自动用 `asyncio.gather` 并发 dispatch 多个 tool_calls,不用自己写。

## 5. 错误处理:`ToolException` 让 LLM 看到

业务错误(参数错 / 业务规则不满足)要让 LLM 看到,让它决定重试 / 换工具:

```python
@tool
def safe_divide(a: float, b: float) -> float:
    """除法, b 不能为 0。"""
    if b == 0:
        # ToolException 而非 Exception → 框架知道是"业务错",会回给 LLM
        raise ToolException("b 不能为 0, 请换一个非零除数")
    return a / b
```

在 `create_agent` / `bind_tools` 流程里:

```
ToolException → 框架捕获 → ToolMessage(content="错误...") → 回给 LLM
   ↓
LLM 看到错误 → ① 改参数重试 ② 换工具 ③ 直接告诉用户
```

| 异常类型 | 行为 |
| --- | --- |
| `ToolException` | 自动转 `ToolMessage`,LLM 看到错误 |
| 普通 `Exception` | 框架兜底成"工具执行失败",细节可能被屏蔽 |

## 6. `StructuredTool.from_function` 程序化构造

工具函数是动态生成 / 来自三方库,不能直接 `@tool`:

```python
def _lookup_employee_raw(emp_id: str) -> dict:
    """(mock) 查员工信息。"""
    employees = {"E001": {"name": "张三", "dept": "工程"}}
    return employees.get(emp_id, {"error": "not found"})

lookup_employee = StructuredTool.from_function(
    func=_lookup_employee_raw,
    name="lookup_employee",
    description="按员工 ID 查员工信息,返回 {name, dept, level}",
)
```

适用:

- 工具从配置文件 / 注册中心动态加载
- 同一个底层函数包成多个工具(如 `get_user` / `find_user` 共用实现)
- 三方库签名不能改

## 7. 返回 `(content, artifact)`:大数据场景

工具返回大数据时,只想让 LLM 看摘要:

```python
@tool
def query_database(sql: str) -> tuple[str, list[dict]]:
    """跑 SQL, 返回 (LLM 看的摘要, 完整结果集)."""
    rows = [{"id": i, "value": f"row-{i}", "data": "x" * 50} for i in range(5)]
    summary = f"查询返回 {len(rows)} 行, 前 3 行预览: {rows[:3]}"
    return (summary, rows)  # (content, artifact)
```

业务调用:

```python
content, rows = query_database.invoke({"sql": "SELECT * FROM t"})
# content → 给 LLM(摘要)
# rows    → 留给程序(完整数据)
```

适用场景:

| 场景 | content | artifact |
| --- | --- | --- |
| 全文搜索 | top 3 + 计数 | 完整结果 |
| 数据库查询 | 总数 + 前几行 | 完整 DataFrame |
| 文件读取 | "文件 1000 行" | 完整文本 |

> 跟 Java 把 DTO 拆成 `SummaryVO` + `DetailVO` 一个思路。

## 8. `InjectedToolArg`:运行时上下文注入

多用户系统里,工具需要"当前是谁在调",不能让 LLM 自己填:

```python
from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg

@tool
def get_my_orders(
    user_id: Annotated[str, InjectedToolArg],  # ← 无括号!InjectedToolArg 是 marker class
    status: str = "all",
) -> str:
    """查当前用户的订单。user_id 由系统注入, LLM 不需要传。"""
    return f"[用户 {user_id}] {status} 订单: 3 个 (mock)"
```

`Annotated[str, InjectedToolArg]` 告诉 LangChain:**这个参数 LLM 不传,运行时注入**。

```python
schema_params = list(get_my_orders.args.keys())
# → ['status']  # user_id 被隐藏,LLM 看不到

# 手动调用时必须自己注入
config = {"configurable": {"user_id": "U-Alice"}}
user_id = config["configurable"]["user_id"]
result = get_my_orders.invoke({"user_id": user_id, "status": "pending"})
```

`create_agent` + `context_schema` 自动注入,不用手动。

> ⚠️ **坑**:`InjectedToolArg()` 带括号会报 `TypeError: takes no arguments`。它是不接受任何参数的 marker class,只能 `Annotated[T, InjectedToolArg]`。

## 9. 完整 tool calling 流程

模型不调工具 = 没法用。`create_agent` 内部在做的事,手动展开看:

```python
from langchain_core.messages import HumanMessage, ToolMessage

llm_with_tools = llm.bind_tools([get_weather, get_time])
messages = [HumanMessage(content="北京天气? 现在几点了?")]

# Step 1: 调 LLM,它返回 tool_calls
resp = llm_with_tools.invoke(messages)

# Step 2: dispatch — 手动路由回 Python 函数
def _dispatch_tool_calls(resp, tools):
    tool_map = {t.name: t for t in tools}
    messages = []
    for tc in resp.tool_calls:
        try:
            content = str(tool_map[tc["name"]].invoke(tc["args"]))
        except ToolException as e:
            content = f"工具错误: {e}"
        except Exception as e:
            content = f"工具执行失败: {type(e).__name__}"
        messages.append(ToolMessage(content=content, tool_call_id=tc["id"]))
    return messages

tool_messages = _dispatch_tool_calls(resp, [get_weather, get_time])

# Step 3: 把 AIMessage + ToolMessage 一起喂回 LLM
final = llm_with_tools.invoke([*messages, resp, *tool_messages])
print(final.content)
```

`ToolMessage.tool_call_id` 必须对应 `resp.tool_calls[i].id`,框架才能配对。

> 这套流程是 LangChain tool calling 的"心脏"。`create_agent` 就是这套的封装,自动循环到 LLM 不再调工具为止。

## 10. 并行 tool calls

模型一次返回多个 tool_calls,业务必须并发 dispatch:

```python
resp = llm_with_tools.invoke("推荐几本 Python 书, 再推荐几部科幻电影")
# resp.tool_calls 可能有 2 个:get_books / get_movies

async def _run_parallel(tool_calls):
    async def one(tc):
        fn_map = {"search_books": search_books, "search_movies": search_movies}
        fn = fn_map.get(tc["name"])
        result = await asyncio.to_thread(fn.invoke, tc["args"])  # 同步工具包异步
        return (tc["id"], str(result))
    return await asyncio.gather(*(one(tc) for tc in tool_calls))

results = asyncio.run(_run_parallel(resp.tool_calls))
```

`bind_tools` 默认 `parallel_tool_calls=True`,模型可一次吐多个。

## 实战踩坑

| 坑 | 原因 | 解法 |
| --- | --- | --- |
| `invoke(a, b)` 报错 | invoke 必须传 dict | 改成 `invoke({"a": 1, "b": 2})` |
| `InjectedToolArg()` TypeError | 它是 marker class | `Annotated[T, InjectedToolArg]` |
| 工具报错 LLM 看不到 | 抛了普通 Exception | 改抛 `ToolException` |
| 并行 IO 没提速 | 用同步函数串行 await | `asyncio.gather` 并发 |
| 大数据全塞 content | token 爆炸 | 返回 `(content, artifact)` |
| LLM 填错 user_id | 没标 InjectedToolArg | `Annotated[T, InjectedToolArg]` |

## 生产架构

工具层是 Agent 系统的"手脚",生产里要遵循三个原则:

1. **错误友好**:业务错用 `ToolException`,让 LLM 自己决定
2. **异步必备**:IO 类工具全 `async def`,并发 `gather`
3. **上下文注入**:`user_id` / `session_id` 用 `InjectedToolArg`,LLM 不填
4. **大数据返回**:`(content, artifact)` 元组,LLM 看摘要、程序拿全量

## 小结

- `@tool` 一行变 LLM 可调,docstring 是给 LLM 看的(不是给你看的)
- `args_schema=Pydantic` 严格校验 + 描述
- `BaseTool` 子类封装有状态工具(连接 / 缓存)
- 异步工具 + `asyncio.gather` 并发 dispatch
- `ToolException` 让业务错回给 LLM
- `(content, artifact)` 元组让 LLM 看摘要
- `InjectedToolArg` 注入运行时上下文

工具搞定了,下一步是让 LLM **自动决定**调什么——下一篇 `create_agent` 拆给你看。

## 延伸阅读

- [LangChain Tools 官方文档](https://python.langchain.com/docs/concepts/tools/)
- 上一篇:[L1-01 接入任何 LLM](./L1-01_models.md)
- 下一篇:[L1-03 create_agent 一统天下](./L1-03_agents.md)
- 源码:`01-langchain-basics/02_tools.py`
