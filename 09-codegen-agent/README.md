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
| 06 | `06_human_review.py` | `HumanInTheLoopMiddleware` + 3 HITL gates | 关键决策点 (plan / 每个文件 / fix) 加人工审批 |
| 07 | `07_incremental_diff.py` | SEARCH/REPLACE 块 + `difflib.SequenceMatcher` 模糊匹配 | review loop 改用增量 diff (省 50%+ token, Cursor/Copilot pattern) |

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
   ↓
06_human_review.py          ← 3 HITL gates (plan / 每个文件 / fix) 加人工审批
   ↓
07_incremental_diff.py      ← review loop 改用增量 diff (省 50%+ token)
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
python 09-codegen-agent/06_human_review.py   # 需交互输入 (a/e/r)
python 09-codegen-agent/07_incremental_diff.py
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
11. 用 `HumanInTheLoopMiddleware` 给危险工具加审批: 3 种决策 (approve/edit/reject) 怎么走 `Command(resume=...)` 恢复 graph?
12. 为什么 HITL middleware 要写工厂函数 (`_hitl()`) 而不是模块级单例? (state_schema 冲突)
13. 怎么从 `state.tasks[0].interrupts` 抽 tool_call 的 name + args? (LangChain 1.x `action_requests[0]` 格式)
14. codegen pipeline 哪几个动作适合加 HITL gate? (plan / 每个文件 / fix — 3 个 trade-off: 安全 vs UX 累)
15. 增量 diff (`SEARCH/REPLACE` 块 + `difflib`) 比全文件 regen 省多少 token? 什么场景应该用哪种?

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

## HITL gates (Demo 6)

Demo 6 把 HumanInTheLoopMiddleware (LangChain 1.x native, 跟 L1 demo 5 一致) 挂到 codegen agent 上,
在 3 个"写盘动作"前暂停等人批:

| Gate | 触发工具 | 审批时看到什么 | 决策选项 |
|------|---------|---------------|---------|
| 1 | `tool_write_plan` | spec 预览 + LLM 生成的 plan 摘要 | `[a]pprove` / `[e]dit` (改 spec) / `[r]eject` |
| 2 | `tool_write_code_file` (每个文件) | file_index + purpose + code 预览 | `[a]pprove` / `[e]dit` (跳到其它 idx) / `[r]eject` |
| 3 | `tool_apply_fix` | code_filename + pytest error 摘要 + LLM 修正 | `[a]pprove` / `[e]dit` / `[r]eject` |

设计要点 (跟 08-cli-assistant 一致):
- **`_hitl()` 工厂函数** — HumanInTheLoopMiddleware 注入额外 state keys, 多个 agent 共享同一实例会冲突
- **`[a]/[e]/[r]` CLI UX** — `e` 走 key=value 交互式编辑 args, EOF/Ctrl-C fallback reject
- **`state.tasks[0].interrupts`** 读 interrupt — 比 `result["__interrupt__"]` 可靠, 跨 LangGraph 版本稳
- **异步 stdin** — `await asyncio.to_thread(input)` 不阻塞事件循环
- **Command(resume=...)** 走同一 thread_id 恢复 graph

## Incremental diff (Demo 7)

Demo 7 把 Demo 4 "全文件 regen" 改成 "只输出 SEARCH/REPLACE 块", 走 Cursor/Copilot/Aider
风格的 diff-based prompting。 1000 行文件 1-line bug, full regen ~1500 字符, incremental ~200 字符,
**约 7.5x token 节省**。

核心组件 (在 `codegen_pipeline.py`):
- **`fix_code_incremental(llm, code, error)`** — 调 LLM, 拿 SEARCH/REPLACE 响应, apply 到原 code
- **`extract_search_replace_blocks(text)`** — regex 抓 `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` 块
- **`apply_search_replace(code, search, replace)`** — 优先 exact match, fallback `difflib.SequenceMatcher`

SEARCH/REPLACE 块格式 (Aider 风格):
```
<<<<<<< SEARCH
def foo(x):
    return x + 1
=======
def foo(x):
    return x + 2
>>>>>>> REPLACE
```

设计要点:
- **SEARCH 块 2-5 行 + 上下文** — 太短可能歧义匹配 (code 里出现多次), 太长 LLM 容易吐不一致的空白
- **difflib fallback threshold 0.6** — exact match 失败时, 模糊匹配最相似的连续 N 行 (ratio > 0.6 才替换)
- **解析失败 → 保留原 code** (defensive) — LLM 偶尔吐 markdown 解释或省略 SEARCH 标记, 不破坏原 code
- **response size 是 token proxy** — `len(llm_response)` 跟真实 token 数高度相关, 不需要 tokenizer

跟 Demo 4 的关键区别:

| 维度 | Demo 4 (full regen) | Demo 7 (incremental) |
|------|--------------------|--------------------|
| LLM 输出大小 | 跟原 code 长度正比 | 跟改动大小正比 (大文件小 bug 也省) |
| 风险 | LLM 可能"顺手优化"无关代码 | 只动指定区域, 副作用小 |
| 适用 | 小文件, 大改, 第一次生成 | 大文件, 小 bug, retry loop |
| 生产参考 | 老式 code completion | Cursor / Copilot / Aider / Continue |

生产建议: full regen 用于 first-pass (没历史上下文), incremental 用于 retry (改 1-3 行)。

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
9. **Demo 6 HITL interrupt API 跨 LangGraph 版本可能变**: 我们读 `state.tasks[0].interrupts[0].value.action_requests[0]`, 这是 LangChain 1.x middleware 格式。 升级到 1.x 更高版本时如果 action_requests 字段名变, 改 `_extract_tool_info_from_interrupt` 即可 (有 4 种格式 fallback, 见 08-cli-assistant/cli.py 同名函数)。
10. **Demo 6 3 gate 全开 UX 累**: 每个文件都触发 gate 2, 5 文件 spec → 7+ 次中断。 真实生产建议只开 gate 1 (plan) + gate 3 (fix), gate 2 (每文件) 太繁琐 — 信任 LLM 写到 output/, 出错用户最后看 diff 就行。
11. **Demo 6 edit 模式简化 UX**: 改 args 走 `key=value` 简单拆分 (shlex), 不支持嵌套 JSON 编辑。 plan_json 这种大字段只展示截断, 编辑会被跳过。 实战更友好是 pop-up 编辑器 / diff 视图。
12. **Demo 7 SEARCH/REPLACE 块分隔符严格匹配**: regex 是 `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` (7 个 `<`, 7 个 `>`)。 LLM 偶尔吐变体 (e.g. `<<<< SEARCH`, `===`, `>>>>`), 解析失败 → 返回原 code (defensive)。 生产可考虑加常见变体 fallback 或要求 LLM "严格按格式"。
13. **Demo 7 difflib threshold 0.6 太低可能误替换**: demo 用 0.6 接受更多匹配, 但 production 应该 0.8+ (e.g. Aider 默认 0.75)。 threshold 越低, 模糊匹配越多, 误替换概率越大。 防御: 同时要求 `n` 至少 2 行 (避免单行歧义)。
14. **Demo 7 解析失败 defensive 不抛错**: LLM 没出 SEARCH/REPLACE 块时, `fix_code_incremental` 返回原 code 而不是 raise。 这避免了"上游 prompt 误导 → 下游 pipeline 全炸", 但也意味着 silent failure — 调用方应该 log + 检查返回值是否真被改了 (e.g. compare len before/after 或 hash)。

## 跟其它模块的关系

- **L1 Models / Tools / Agents**: 复用 `get_llm` + `@tool` + `create_agent` (Demo 5/6)
- **L1 Middleware**: 复用 `HumanInTheLoopMiddleware` (Demo 6, 见 04_middleware.py demo 5)
- **L2 LangGraph**: 复用 `StateGraph` / `TypedDict` / `add_conditional_edges` (Demo 5), `InMemorySaver` / `Command` (Demo 6)
- **L4 Multi-Agent**: supervisor + specialist 模式 (Demo 5)
- **08-cli-assistant**: 复用 HITL `_hitl()` 工厂 + `[a]/[e]/[r]` CLI UX + `state.tasks[0].interrupts` interrupt 读取
- **L6 OPC Product**: 同款"双轨 structured output + fallback"模式
