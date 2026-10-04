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
| 共享 | `safety.py` | regex + `ast` 两层扫描 | 静态安全扫描: BLOCK/WARN/INFO 三档, 默认规则覆盖 eval/exec/shell/pickle/dynamic-import |
| 08 | `08_spec_validation.py` | `safe_plan_to_code` + 故意危险 spec | LLM 生成代码写盘前拦截危险模式 (eval/exec/secret), 演示 3 类 spec |
| 共享 | `dep_graph.py` | `extract_imports` (regex) + `topological_sort` (Kahn's) + `detect_cycles` (DFS) | 跨文件依赖图工具: import 提取 + 拓扑排序 + 循环检测 + forward decl |
| 09 | `09_cross_file_deps.py` | `build_dep_graph` + `topological_sort` + `plan_to_code_with_deps` | 多文件 codegen 按依赖顺序生成, 循环依赖 raise 不 silent, 演示 6 个步骤 (3 算法 + 3 LLM 集成) |
| 共享 | `streaming.py` | `llm.astream` + `llm.astream_events` + `time.perf_counter` | 共享 streaming 累积: `stream_llm_content` (basic) + `stream_file_code` (file-aware) + `StreamResult` dataclass + `iter_llm_tokens` async generator |
| 10 | `10_streaming_codegen.py` | `plan_to_code_streaming` + TTFT + `astream_events` v2 | LLM token streaming codegen, 边写边预览, TTFT 测量, 5 个步骤 (3 streaming 机制 + 2 集成 + 1 bonus async-iter) |

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
   ↓
safety.py + 08_spec_validation.py  ← safety gate 拦截危险代码 (eval/exec/secret)
   ↓
dep_graph.py + 09_cross_file_deps.py  ← 多文件 dep graph + 拓扑排序 + cycle detection
   ↓
streaming.py + 10_streaming_codegen.py  ← LLM token streaming + TTFT + UI hookup
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
python 09-codegen-agent/08_spec_validation.py
python 09-codegen-agent/09_cross_file_deps.py
python 09-codegen-agent/10_streaming_codegen.py
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
16. 为什么 LLM 生成的代码需要 safety gate? (eval/exec/secret/dynamic-import 4 类常见危险)
17. 静态分析 (regex + AST) 跟运行时沙箱的 trade-off? (静态快但漏报, 沙箱准但重)
18. Severity 三档 (BLOCK/WARN/INFO) 怎么选? (默认保守 BLOCK, WARN 给 false-positive 兜底)

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

## Spec validation (Demo 8)

Demo 8 在 `plan_to_code` 写盘前加 safety gate, 拦截 LLM 生成的危险代码。 在 `04_review_loop`
和 `06_human_review` 只检查 "测试 pass" 的基础上, 加一层 "代码安全" 防御。

**两层扫描架构** (在 `safety.py`):
- **Layer 1 (regex)**: 全文件字符串扫描, 快 + 易读。 覆盖 `eval(`/`exec(`/`os.system(` 等明显模式
- **Layer 2 (AST)**: `ast.parse` + 递归 walk, 准 + 处理结构化场景。 覆盖 `Call(func=Name('eval'))` 等

**Severity 三档**:
| 档位 | 行为 | 示例 |
|------|------|------|
| `BLOCK` | 拒绝写盘, 打印 finding | `eval(` / `exec(` / `os.system(` / `pickle.loads` / `__import__(` / `shell=True` |
| `WARN`  | 写盘但打印警告 | hardcoded secret (`password = "..."`) / `open().write()` |
| `INFO`  | 静默, 仅学习 | `hashlib.md5` / `hashlib.sha1` (不安全 hash) |

**默认 BLOCK 规则** (12 条):
```python
# 直接执行任意代码
eval(exec(compile(...                       # 表达式 / 代码注入
# shell 注入
os.system( shell=True                       # shell 命令注入
# 反序列化
pickle.loads( marshal.loads(                # 反序列化 RCE
# 动态 import 绕过审查
__import__( importlib.import_module(        # 绕过静态审查
```

**默认 WARN 规则** (2 条):
- `hardcoded_secret` — `(?i)(password|secret|api_key|token)\s*=\s*['"][^'\"]{4,}['"]`
- `open_write` — `open(...).write(` 链式调用

**集成方式** (`codegen_pipeline.py`):
```python
from codegen_pipeline import safe_plan_to_code

# 替换 plan_to_code: 自动应用 safety gate
written = safe_plan_to_code(llm, plan)
# BLOCK 文件被跳过, 返回写入成功的路径列表
```

跟 Demo 6 HITL 的关系:
- HITL 是 "人类审批" — 慢但权威
- Safety scan 是 "机器审批" — 快但粗糙
- 生产建议: 两者结合, 扫描先过 (cheap rejection), HITL 兜底 (humans 看 ambiguous case)

跟其它扫描工具对比:
| 工具 | 类型 | 优劣 |
|------|------|------|
| `safety.py` (本 demo) | regex + AST 静态 | 快 / 易集成 / 启发式 |
| `bandit` | AST + taint | 全 Python 安全规则, 误报低 |
| `detect-secrets` | regex + entropy | secret 检测专业, false-positive 低 |
| `RestrictedPython` | 运行时沙箱 | 准但需重构代码 |

生产推荐: 静态扫描 + bandit + detect-secrets + RestrictedPython 组合, 不要单押一种。

## Cross-file deps (Demo 9)

Demo 9 解决多文件 codegen 的 import 顺序问题:
LLM 生成 `app.py` 时如果 `from utils import helper`, 但 `utils.py` 还没生成
(或后生成), Python 解释器报 `ModuleNotFoundError`。 Demo 9 用 dep graph +
topo sort 保证依赖先生成, 同时检测循环依赖 (raise 不 silent)。

**核心工具** (在 `dep_graph.py`):

| 函数 | 算法 | 教学目的 |
|------|------|---------|
| `extract_imports(code)` | regex | 从 source 抓 `from X import Y` / `import X` 的 root module |
| `build_dep_graph(files)` | 启发式 path→module | 构建 file_path → set of deps 的有向图, 忽略 stdlib |
| `topological_sort(graph)` | Kahn's (BFS) | in-degree=0 优先处理, 同 in-degree 按名字排 (deterministic) |
| `detect_cycles(graph)` | Tarjan-like DFS | 返回所有环, normalized dedup |
| `add_forward_decls(content, mod, symbols)` | string prepend | `TYPE_CHECKING` forward declaration |
| `CycleError(cycles)` | exception | raise 不 silent (跟 spec validation 风格一致) |

**集成方式** (在 `codegen_pipeline.py`):
```python
from codegen_pipeline import plan_to_code_with_deps

# 替换 plan_to_code / safe_plan_to_code: 自动按 dep 顺序写盘
written = plan_to_code_with_deps(llm, plan, output_dir=out)
# BLOCK finding → skip 写盘
# 循环依赖 → raise CycleError (caller 处理, 可选 forward decl 重试)
```

**3 阶段设计**:
1. **Phase 1**: 按 plan 顺序生成所有 file content (LLM 调用确定性)
2. **Phase 2**: 用真实 content 构建 graph → topo sort
3. **Phase 3**: 按 dep 顺序写盘 + safety scan

为什么不一步到位? Phase 1 必须按 plan 顺序生成 (LLM 调用顺序不好改);
topo sort 用于"写盘顺序"而非"生成顺序", 这样 graph 反映真实 content。

**Demo 9 流程** (6 steps):
1. **算法演示** (no LLM): linear chain → topo order 验证
2. **算法演示**: a ↔ b cycle → `CycleError` 抛出
3. **算法演示**: DFS `detect_cycles` 返回所有环
4. **LLM 集成**: 3-file spec (User / Repository / app) → 生成 + graph 构建
5. **LLM 集成**: cyclic spec → cycle 检测 + `add_forward_decls` 演示
6. **端到端**: `plan_to_code_with_deps` on linear spec + import 验证

跟其它扫描工具对比:

| 工具 | 类型 | 适用 |
|------|------|-----|
| `dep_graph.py` (本 demo) | regex import + topo sort | 多文件 codegen 顺序保证 |
| `pydeps` / `pyan` | AST + 完整 call graph | 静态分析文档生成 |
| `ruff --select F401` | AST unused imports | 单文件 lint |
| `importtime` (stdlib) | runtime profile | 性能分析, 不解决顺序 |

生产推荐: dep_graph (静态) + 真实 pytest import collection (动态) 组合。

## Streaming code gen (Demo 10)

Demo 10 解决 codegen 的**感知延迟问题**: 用户提交 spec → 30s 沉默 → 整段代码一次性出现,
体验像"卡死"了。 Streaming 让代码逐字浮现, 500ms 内第一个字符就出现, 像 Cursor / Copilot。

**核心组件** (在 `streaming.py`):
- **`stream_llm_content(llm, messages, on_token=None)`** — basic astream 累积: buffer list+join,
  TTFT = `time.perf_counter()` 在第一个 chunk 时记录
- **`stream_file_code(llm, file_spec, on_token=None)`** — file-aware: 用专用 prompt 让 LLM 输出纯代码
  (不包 markdown fence), 走 streaming 路径
- **`StreamResult`** dataclass — 4 fields: `content` / `ttft_seconds` / `total_seconds` / `token_count`
- **`iter_llm_tokens(llm, messages)`** — async generator: `async for token, elapsed in ...`,
  适合 SSE / WebSocket / 异步 pipeline

**集成方式** (在 `codegen_pipeline.py`):
```python
from codegen_pipeline import plan_to_code_streaming

# 替换 plan_to_code / safe_plan_to_code: 自动 streaming + safety
written, results = plan_to_code_streaming(llm, plan, output_dir=out, on_token=print)
# written: list[Path] — 写盘成功的文件 (BLOCK 跳过)
# results: list[StreamResult] — 每个文件的 timing 数据
```

**两个 streaming API 区别**:
| API | 粒度 | 用途 |
|-----|------|------|
| `llm.astream(messages)` | token-level (`AIMessageChunk.content`) | 简单 UI (SSE / print / 进度条) |
| `llm.astream_events(messages, version="v2")` | event-level (`on_chat_model_start` / `on_llm_new_token` / `on_chat_model_end` / chain / tool / retriever) | 复杂 UI (LangSmith trace / 多 node 监控 / chain 中断) |

**Demo 10 流程** (6 steps):
1. **basic astream**: 看 token 增量, 确认 TTFT < 1s
2. **streaming 单文件**: code char-by-char (每 20 token 一个 dot 替代纯字符-避免 terminal 乱)
3. **TTFT 对比**: streaming vs non-streaming (感知延迟 speedup)
4. **多文件 streaming**: `plan_to_code_streaming` 端到端 (greeter.py + main.py)
5. **astream_events v2**: 细粒度事件流 (start / new_token / end)
6. **iter_llm_tokens bonus**: async iterator 模式 (SSE / WebSocket 友好)

**生产 UX 类比**:
- **Cursor / Copilot inline**: streaming codegen + 实时 diff = demo 10 思路
- **ChatGPT web**: astream_events + typing animation = step 5 思路
- **OpenAI Playground**: async iterator + WebSocket = `iter_llm_tokens` 思路

跟其它 streaming 工具对比:
| 工具 | 类型 | 适用 |
|------|------|------|
| `streaming.py` (本 demo) | astream + 累积 + TTFT | LangChain 1.x standard, 教学够用 |
| `langchain.callbacks.streaming.StdOutCallbackHandler` | callback 自动 print | 调试时方便, 没 timing |
| `vllm` / `text-generation-inference` | LLM server side | 自部署 LLM 时用 |
| OpenAI `stream=True` (raw) | HTTP SSE | 直接调 API, 不走 LangChain |

生产推荐: LangChain `astream` (跨 provider 兼容) + 累积 buffer + 自己的 UI layer。

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
15. **Demo 8 AST 解析失败静默**: `scan_ast` 遇到 SyntaxError 返回空 `[]`, 不抛错。 设计: regex layer 已 catch 表面错误 (e.g. eval), AST 解析失败说明代码本身畸形, 不强行扫。 局限: 复杂但语法错误的代码可能漏检, 生产可以加 `try/except` log 异常让扫描失败可见。
16. **Demo 8 hardcoded secret 检测不完美**: 启发式 regex `(?i)(password|secret|api_key|token)\s*=\s*['"][^'\"]{4,}['"]` 会误报:
    - 注释里 `password = "my_var_name"` (e.g. 注释解释 placeholder)
    - 测试 fixture 里 `password = "test123"` (合法 fixture)
    - 默认值 `password = ""` 会被 regex 漏掉 (`{4,}` 排除短字符串)
    生产推荐接 `detect-secrets` (基于 entropy + 上下文) 而非自造 regex。
17. **Demo 8 `subprocess shell=True` regex 太宽**: 当前 regex `shell\s*=\s*True` 不区分 `shell=False` 注释 / 文档字符串。 实测中 docstring 写 "shell=False is safer" 会触发 BLOCK。 AST layer 应该 parse kwarg 验证, 未来可以增强为: `Call(func=subprocess...) and any(kw.arg=='shell' and kw.value.value is True)` 才 BLOCK。
18. **Demo 8 scanner 自扫会 meta-level 命中**: `safety.py` 自身包含 `re.compile(r"\beval\s*\(")` 等字面量, scanner 扫自己 → 命中 19 BLOCK findings。 这是预期 (meta-level), scanner "诚实" 报告自身代码里的危险 pattern。 部署时: 配置 scanner 跳过自身 source path, 或把规则定义放到独立 JSON / YAML 文件, 让 scanner 代码不含字面量 pattern。 Demo 8 step 7 演示这点。
19. **Demo 8 multiline `open().write()` 漏报已修复 (R13 fix)**: 之前 regex `open\s*\(\s*[^)]*\)\s*\.write\s*\(` 的 `[^)]*` 不跨行, 只能抓单行 `open("x").write(...)`; 多行 `f = open("x.txt")\nf.write("hello")` 漏报。 R13 修复: AST layer 加 open_vars 跟踪, `f = open(...)` 把 `f` 加进集合, 后续 `f.write(...)` 触发 `open_write` WARN。 新增 inline smoke assert #7 验证多行 pattern 被捕获。 局限: open_vars 不区分函数作用域, 跨 scope 复用变量名会有少量 false positive (acceptable trade-off)。
20. **Demo 9 topological_sort 算法细节**: Kahn's algorithm 关键在"in-degree 怎么算"。 我们 graph[n] = n 依赖谁 (出边 from n → dep), 所以 in-degree(n) = len(graph[n]) = n 依赖多少个 graph 里的 node。 处理 n 时, 让所有 m where n ∈ graph[m] 的 m 的 in-degree 减 1。 同 in-degree 节点按名字 sort 保证 deterministic (同样输入总得到同样顺序, 易测试)。 第一次实现时把方向搞反过, 导致 topo 顺序颠倒, inline smoke 暴露。 ⚠️ 教学要点: 在 deps-on graph 上做 topo sort, in-degree = "我依赖多少", 不是 "多少人依赖我"。
21. **Demo 9 module name heuristic 不完美**: `_path_to_module("foo/bar/utils.py") → "utils"` 简单取文件名去 `.py`。 不支持 nested packages (e.g. `pkg/sub/utils.py` 应是 `pkg.sub.utils`)。 不看 `__init__.py` 判断包结构。 教学够用, 生产应解析实际 Python import 系统 (`astroid`, `importlib`)。 inline smoke assert #2-#7 覆盖基本场景。
22. **Demo 9 cycle detection 返回所有环**: Tarjan-style DFS + normalized dedup (最小节点开头 + tuple hash)。 局限: 重复环可能 O(n²) (e.g. 3-node 完全图有 6 个不同 ring 都描述同一个 SCC)。 生产应该用 Tarjan SCC (强连通分量) 找唯一的 cycle 群。 demo 简单版够教学。
23. **Demo 9 forward decl 不解决所有问题**: `add_forward_decls` 插 `TYPE_CHECKING` import, 只让 type checker 知道符号存在 (annotation 用), 运行时不在 → 解决 type-only cycle。 不解决 runtime cycle: `a.foo()` → `b.bar()` → `a.foo()` 仍会 ImportError / NameError (因为运行时 a 还没定义完)。 demo step 5 演示 forward decl 工具, 但 case 6 的端到端 pipeline 用 linear spec 避免 runtime cycle (LLM 不一定每次都生成 runtime-safe code)。 生产建议: dep-aware + 真实 pytest import collection + 必要时 lazy import (`def foo(): from b import x`) 兜底。
24. **Demo 9 FileSpec 加 `extra='allow'`**: 让 `FileSpec(..., content='...')` 可以注入生成代码做 dep 分析。 LLM structured output 不会吐 `content` (content 是 file_to_code 之后产物), 所以 `model_dump()` 仍干净 (没多余字段)。 `getattr(f, "content", "")` 兜底没 content 的 FileSpec 视为空字符串。 局限: `model_dump()` 会包含 `content` 字段 (如果注入过), 生产应考虑 expose `content` 为正式字段 (with description), 或用 wrapper class。
25. **Demo 10 写盘只在累积完成时**: 半截 code 不能 parse (`ast.parse` 抛 `SyntaxError`), 不能 extract (`extract_python_blocks` 正则匹配需要闭合 fence), 不能 write (写半截 = 让用户看错误代码)。 教学要点是 buffer 模式: 每个 chunk append 到 list, **迭代结束** 才 `"".join(buffer)` 走下一步。 `plan_to_code_streaming` 已经强制这个时序 (写盘只在 `await stream_file_code(...)` 返回后)。
26. **Demo 10 `astream_events` version 必须 "v2"**: LangChain 1.x deprecated `version="v1"`, 默认值也会警告。 必须显式传 `version="v2"` 才能拿到 `on_chat_model_start` / `on_llm_new_token` / `on_chat_model_end` 等新事件。 `v1` 的 `on_llm_start` / `on_llm_token` 仍能跑, 但官方文档明确推荐迁移。 demo step 5 已显式传 `"v2"`, 跑会看到 deprecation warning 如果你忘了。
27. **Demo 10 TTFT 受网络影响大, 不一定代表 UX 改进**: 局域网 TTFT < 100ms, 跨洲 500ms+, 但**后续 token 也要算**。 如果 total 是 5s, TTFT 0.3s, 用户感知是"5s 里前 0.3s 安静, 后 4.7s 一字写"。 跟 5s 一次性显示对比, 感知延迟改进 = 0.3s vs 5s (16x speedup)。 但如果 total 是 0.5s, TTFT 0.3s, 改进只有 0.2s, 用户感觉不明显。 教学: 看 speedup ratio + 看 absolute TTFT, 两个都要。 demo step 3 直接 print 这两个值, 让用户判断。
28. **Demo 10 callback 不能 raise, UI 渲染要静默**: `on_token` 在 astream 循环里同步调, 抛错会打断 streaming → 后续 chunk 拿不到 → 用户卡死。 防御: `plan_to_code_streaming` 内 `_safe_on_token` wrapper 用 try/except 吞异常 (UI 渲染错不影响 codegen)。 教学: 生产 streaming UI layer 必须包 try/except, 终端 print 也要 flush (`print(t, end="", flush=True)`), 不然 buffer 卡住看起来不流畅。

## 跟其它模块的关系

## 跟其它模块的关系

- **L1 Models / Tools / Agents**: 复用 `get_llm` + `@tool` + `create_agent` (Demo 5/6)
- **L1 Middleware**: 复用 `HumanInTheLoopMiddleware` (Demo 6, 见 04_middleware.py demo 5)
- **L2 LangGraph**: 复用 `StateGraph` / `TypedDict` / `add_conditional_edges` (Demo 5), `InMemorySaver` / `Command` (Demo 6)
- **L4 Multi-Agent**: supervisor + specialist 模式 (Demo 5)
- **08-cli-assistant**: 复用 HITL `_hitl()` 工厂 + `[a]/[e]/[r]` CLI UX + `state.tasks[0].interrupts` interrupt 读取
- **L6 OPC Product**: 同款"双轨 structured output + fallback"模式
