# L9 — Code Generation Agent

> 从 spec → 生成代码 + tests → review loop 的端到端 codegen workflow。
> 复用 L1-L4 的所有能力 (Models / Tools / Agents / Middleware / LangGraph)。

## 模块清单

| # | 文件 | 关键 API | 一句话目标 |
|---|------|---------|----------|
| 共享 | `_common.py` | L1 `get_llm` + `banner` via `importlib.util` | 复用 L1 provider 切换, 加 spec loader / output writer |
| 共享 | `plan_schema.py` | `Pydantic BaseModel` + `with_structured_output` | Plan / FileSpec / FunctionSpec schema + 双轨 `spec_to_plan` |
| 共享 | `codegen_pipeline.py` | `ChatPromptTemplate` + `extract_python_blocks` | 共享 `plan_to_code` / `code_to_test` / `fix_code` |
| 01 | `01_spec_to_plan.py` | `spec_to_plan` (双轨 function_calling + Pydantic fallback) | spec → 结构化 Plan JSON |
| 02 | `02_plan_to_code.py` | `plan_to_code` + `write_code_file` | Plan → 逐文件生成代码 → 写到 `output/` |
| 03 | `03_test_generation.py` | `code_to_test` | code → pytest tests → `output/test_<filename>.py` |
| 04 | `04_review_loop.py` | `subprocess` + `fix_code` | 跑 pytest → 失败 LLM 修 → 重跑直到 pass (max_retries=3) |
| 05 | `05_multi_agent_coder.py` | `StateGraph` + `create_agent` + `@tool` | 3 specialist (Planner / Coder / Reviewer) + supervisor 状态机 |

## 推荐阅读顺序

```
_common.py          ← 先懂"我们怎么复用 L1"
   ↓
plan_schema.py      ← 再懂"Plan 长什么样 + 怎么从 spec 解析出来"
   ↓
codegen_pipeline.py ← 再懂"从 plan 到 code 到 test 的 pipeline"
   ↓
01_spec_to_plan.py          ← spec → Plan (用 example_spec 演示)
   ↓
02_plan_to_code.py          ← Plan → 实际代码文件
   ↓
03_test_generation.py       ← code → pytest tests
   ↓
04_review_loop.py           ← test 失败 → LLM 修 → 重跑
   ↓
05_multi_agent_coder.py     ← supervisor 编排 3 specialist 跑完整 pipeline
```

## 跑起来

```bash
# 配置环境变量 (见 .env.example)
export MINIMAX_API_KEY="..."   # 或 DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY

# 跑任一 demo (按顺序)
python 09-codegen-agent/01_spec_to_plan.py
python 09-codegen-agent/02_plan_to_code.py
python 09-codegen-agent/03_test_generation.py
python 09-codegen-agent/04_review_loop.py
python 09-codegen-agent/05_multi_agent_coder.py
```

每个 demo 都独立运行,运行时把生成的代码写到 `09-codegen-agent/output/` (gitignored)。
输出文件名跟 spec 里 LLM 决定的文件名一致,常见产物:
- `fizzbuzz.py` — 主代码
- `test_fizzbuzz.py` — pytest 测试

## 学完 L9 你能

1.  用 Pydantic `BaseModel` 定义 LLM 输出的 schema, 让 LLM 吐结构化 JSON
2.  写双轨 fallback: `method="function_calling"` 主路失败时切 `PydanticOutputParser` 备路
3.  从 LLM 输出里用正则提取 `````python ... ````` 块, 容错 markdown 噪音
4.  把生成的代码写到磁盘 (`Path.write_text`), 隔离好 `output/` 工作区
5.  用 `subprocess.run` 跑 pytest 拿 stdout/stderr, 用 returncode 判断 pass/fail
6.  写 review loop: 失败 → 喂 stderr 给 LLM 修代码 → 重跑, 直到 pass 或 max_retries
7.  用 LangGraph `StateGraph` 编排多 Agent pipeline (Planner / Coder / Reviewer)
8.  用 `@tool` 装饰器把 Python 函数暴露给 specialist agent
9.  设计 supervisor 路由函数: 根据 state.phase 决定下一个 node
10. 复用一个 L1 `_common.py` 到别的模块: `importlib.util.spec_from_file_location` 模式

## 复用 L1 的方式 (DRY)

```python
# 09-codegen-agent/_common.py
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_L1_COMMON_PATH = _ROOT / "01-langchain-basics" / "_common.py"

_spec = importlib.util.spec_from_file_location("_l1_common", _L1_COMMON_PATH)
_l1_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_l1_common)

banner = _l1_common.banner
get_llm = _l1_common.get_llm
```

为什么不直接 `from _common import ...`?
- 当前目录已经在 sys.path[0], 本地的 `_common.py` 会优先被加载
- 本地的 `_common.py` 正在执行时, `sys.modules['_common']` 已经有 partial 状态
- `from _common import` 会拿到 partial 本地模块 → ImportError

`importlib.util` 用独立 module name `_l1_common` 隔离, 避免循环引用。
同款 pattern 见 `08-cli-assistant/_common.py`。

## 已知坑

1. **MiniMax M3 CoT 干扰**: `with_structured_output` 主路失败时, 切备路 `_strip_think` + `PydanticOutputParser`。
   - 主路 print: `(主路 function_calling OK)`
   - 备路 print: `(主路失败: <ExceptionType>: <msg>, 切备路)`
2. **LLM 经常吐 markdown 解释**: 用 `extract_python_blocks` 正则提取 ```` ```python ```` 块, 没匹配到时 fallback 用整段。
3. **pytest 在 demo 4/5 跑**: 用 `subprocess.run` 隔离进程, `cwd=output_dir()` 让 pytest 能找到 import 的同目录模块。
4. **max_retries=3**: 防 LLM 死循环改代码改坏。 超过上限报告人类, 不硬撑。
5. **review loop 只修 main code 不修 test code**: 避免 LLM 妥协测试让代码通过 (测试本身是契约)。
6. **生成代码不要 commit**: `output/` 已加 `.gitignore`, 跑 demo 产物不入库。
7. **5 demo 默认用 FizzBuzz spec**: 想测别的 spec, `load_spec("path/to/spec.md")` 或直接传字符串。
8. **Demo 5 supervisor 简化**: coding_node 直接调 `plan_to_code`, 没让 Coder agent 自己决策。 真实项目可以让 agent 决定写几个文件 / 怎么拆。

## 跟其它模块的关系

- **L1 Models / Tools / Agents**: 复用 `get_llm` + `@tool` + `create_agent` (Demo 5)
- **L2 LangGraph**: 复用 `StateGraph` / `TypedDict` / `add_conditional_edges` (Demo 5)
- **L4 Multi-Agent**: supervisor + specialist 模式 (Demo 5)
- **L6 OPC Product**: 同款"双轨 structured output + fallback"模式
