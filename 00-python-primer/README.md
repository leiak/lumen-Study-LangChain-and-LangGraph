# 00-python-primer — 项目 Python 知识点手册

> 面向 **Java/Go → AI Agent → OPC** 背景工程师,系统梳理 `01-06` 6 层 17 个 .py 文件里**实际用到**的 Python 语言特性。
> 不是通用 Python 教程,每个知识点都配项目里的真实例子。

## 一、为什么做这个目录

- 项目代码全部用 LangChain 1.x + LangGraph 1.x 写成,但里面混了大量 Python 语法糖 (decorator / TypedDict / Annotated / asyncio.gather / Pydantic v2 …)
- 你刚接触 Python,直接读 LangChain 源码会被两层抽象压垮
- 这个目录把**业务无关的 Python 知识点**剥离出来,每个都是 30-80 行的最小可运行 demo

## 二、学习路径 (按难度递进,7 层)

```
L0  基础语法      ← 不用懂 OOP 就能读
L1  OOP + 函数式  ← class / 装饰器 / dataclass / 闭包
L2  异步并发      ← async / await / gather
L3  类型系统进阶  ← TypedDict / Annotated / Literal
L4  标准库        ← os / pathlib / re / json / datetime …
L5  第三方 (非 LC) ← pydantic / python-dotenv
L6  工程实践      ← type:ignore / noqa / 容错循环
```

**建议**:
- 第一次读 → 按 L0 → L6 顺序过,每天 1-2 层
- 写代码卡住 → 直接看右栏的"项目里在哪用",跳到对应位置
- 忘了语法 → 回到对应 .py 文件,30 秒回忆

## 三、完整目录 (47 个知识点)

```
00-python-primer/
├── _common.py                              # banner + setup
├── README.md                               # 本文件
│
├── L0_basics/                              # 基础语法 (8)
│   ├── 00_type_hints_basics.md/py
│   ├── 01_fstring_literals.md/py
│   ├── 02_tuple_unpacking.md/py
│   ├── 03_dict_get_or.md/py
│   ├── 04_string_methods.md/py
│   ├── 05_exception_handling.md/py
│   ├── 06_main_guard.md/py
│   └── 07_bool_none_check.md/py
│
├── L1_oop_functional/                      # OOP + 函数式 (10)
│   ├── 00_class_inheritance.md/py
│   ├── 01_decorator_basics.md/py
│   ├── 02_dataclass.md/py
│   ├── 03_factory_closure.md/py
│   ├── 04_lambda.md/py
│   ├── 05_args_kwargs.md/py
│   ├── 06_comprehension_generator.md/py
│   ├── 07_context_manager.md/py
│   ├── 08_dunder_methods.md/py
│   └── 09_getattr_reflection.md/py
│
├── L2_async/                               # 异步并发 (5)
│   ├── 00_async_await.md/py
│   ├── 01_asyncio_gather.md/py
│   ├── 02_asyncio_run.md/py
│   ├── 03_asyncio_to_thread.md/py
│   └── 04_async_for_streaming.md/py
│
├── L3_type_system/                         # 类型系统 (5)
│   ├── 00_typed_dict.md/py
│   ├── 01_annotated.md/py
│   ├── 02_literal.md/py
│   ├── 03_optional_union.md/py
│   └── 04_future_annotations.md/py
│
├── L4_stdlib/                              # 标准库 (11)
│   ├── 00_os_environ.md/py
│   ├── 01_sys_stdout.md/py
│   ├── 02_pathlib.md/py
│   ├── 03_re_module.md/py
│   ├── 04_json_module.md/py
│   ├── 05_datetime.md/py
│   ├── 06_tempfile.md/py
│   ├── 07_time_sleep.md/py
│   ├── 08_random.md/py
│   ├── 09_operator.md/py
│   └── 10_dict_helpers.md/py
│
├── L5_third_party/                         # 第三方 (3)
│   ├── 00_pydantic_basics.md/py
│   ├── 01_pydantic_advanced.md/py
│   └── 02_python_dotenv.md/py
│
└── L6_engineering/                         # 工程实践 (5)
    ├── 00_type_ignore.md/py
    ├── 01_noqa.md/py
    ├── 02_private_naming.md/py
    ├── 03_module_cache.md/py
    └── 04_try_except_loop.md/py
```

## 四、知识点 → 项目文件映射 (速查)

> 不背语法也能用这个表: 卡在哪行 → 查右侧 → 回到 primer 对应 .md 复习

| 知识点 | 项目里在哪用 |
|---|---|
| 类型注解基础 | `01_models.py:42` `dict[str, Any]` |
| f-string | `07_persistence.py:267` 多行打印 banner |
| tuple 解构 | `02_tools.py:257` `content, rows = query_database.invoke(...)` |
| dict .get / or | `08_interrupt_hitl.py:136` `tc["args"].get("amount", 0)` |
| 字符串方法 | `14_handoff.py:132` `tc["name"].startswith("transfer_to_")` |
| 异常处理 | `01_models.py:201` `raise SystemExit(1)` |
| `__name__` 入口 | 所有 17 个模块文件底部 |
| bool / None 判定 | `08_interrupt_hitl.py:88` `getattr(last, "tool_calls", None)` |
| class 继承 | `02_tools.py:108` `CalculatorTool(BaseTool)` |
| 装饰器基础 | `11_langsmith_tracing.py:112` `@traceable` |
| @dataclass | `12_langsmith_evaluation.py:413` `EvalSummary` |
| 工厂 + 闭包 | `14_handoff.py:45` `make_handoff_tool(...)` |
| lambda | `06_state_graph.py:495` `add_conditional_edges(..., lambda s: ...)` |
| `*args` / `**kwargs` | `02_tools.py:423` `asyncio.gather(*(one(tc) for tc in ...))` |
| 推导式 / 生成器 | `13_supervisor.py:398` `sum(1 for m in ra["messages"] ...)` |
| with 上下文 | `07_persistence.py:239` `with SqliteSaver.from_conn_string(...)` |
| dunder 方法 | `12_langsmith_evaluation.py:421` `__str__` |
| getattr 反射 | `08_interrupt_hitl.py:88` `getattr(last, "tool_calls", None)` |
| async / await | `02_tools.py:157` `async def fetch_url` |
| asyncio.gather | `02_tools.py:165` 并发抓 URL |
| asyncio.run | `02_tools.py:425` 同步入口跑异步 |
| asyncio.to_thread | `02_tools.py:420` 同步工具桥接到 async |
| async for | `09_streaming.py:221` `async for chunk in agent.astream(...)` |
| TypedDict | `06_state_graph.py:41` `class RouterState(TypedDict)` |
| Annotated | `08_interrupt_hitl.py:334` `Annotated[list, add_messages]` |
| Literal | `06_state_graph.py:45` `Literal["weather", "order", ...]` |
| Optional / Union | `02_tools.py:293` `Embeddings | None` |
| `from __future__` | 所有文件顶部 |
| os.getenv | `11_langsmith_tracing.py:46` |
| sys.stdout.reconfigure | `02_tools.py:26` Windows GBK 修复 |
| pathlib.Path | `_common.py:15` `_ROOT = Path(__file__).resolve().parent.parent` |
| re.compile + DOTALL | `01_models.py:24` 剥 `<think>` 标签 |
| json.dumps/loads | `07_persistence.py:209` 序列化 messages |
| datetime | `12_langsmith_evaluation.py:280` 算 latency |
| tempfile | `07_persistence.py:235` 临时 SQLite |
| time.sleep | `04_middleware.py:64` 模拟慢 IO |
| random.random | `11_langsmith_tracing.py:388` 10% 采样上报 |
| operator.add | `03_agents.py:22` `from operator import add as add_int` |
| dict.setdefault | `10_durable_execution.py:264` 计数器 |
| pydantic BaseModel + Field | `02_tools.py:69` `SearchInput` |
| pydantic 进阶 | `01_models.py:41` `model_config` / `model_rebuild()` |
| python-dotenv | 所有 `_common.py:15` `load_dotenv(...)` |
| type: ignore | `01_models.py:118` 抑制类型检查 |
| noqa: F401 | `16_deep_agents.py:45` 抑制未使用 import |
| 私有命名 _ | 所有 `_common.py` 模块私有函数 |
| 模块缓存 + global | `05_retrieval.py:176` `_cached_embeddings` |
| 容错循环 | 所有 entry point `for name, fn in [...]: try: ...` |

## 五、怎么跑

每个 .py 文件都**独立可运行**,自带 `if __name__ == "__main__":` 入口。

```bash
# 单文件
python 00-python-primer/L0_basics/00_type_hints_basics.py

# 一层全部 (Windows)
for %f in (00-python-primer/L0_basics/*.py) do python "%f"

# 一层全部 (bash / git bash)
for f in 00-python-primer/L0_basics/*.py; do python "$f"; done
```

## 六、风格约定 (和项目其它文件保持一致)

- 中文注释 / docstring
- 顶部 docstring 列 "学完你能回答 N 个问题"
- 每个 demo 用 `banner("...")` 分块
- Windows UTF-8 reconfigure 防 GBK 崩
- `try/except` 包住每个 demo,失败优雅跳过
- 不用 emoji (项目惯例)

## 七、建议复习节奏

| 阶段 | 读什么 | 重点 |
|---|---|---|
| 第 1 天 | L0 + L1 全部 | 语法打底,看得懂项目代码 |
| 第 2 天 | L2 + L3 全部 | 异步 + 类型,看懂 LangGraph state |
| 第 3 天 | L4 + L5 全部 | 标准库 + pydantic,看懂 RAG/parser |
| 第 4 天 | L6 + 项目代码 | 工程模式,开始改 demo |
