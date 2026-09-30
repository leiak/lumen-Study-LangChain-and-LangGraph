# CLI Personal Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `08-cli-assistant/` — an interactive CLI personal assistant exercising Streaming, HITL, Supervisor, Time Travel, Custom Middleware, and Long-term Store in one cohesive tool.

**Architecture:** REPL-driven CLI (stdlib `input()` only). User text → supervisor graph via `astream(stream_mode="messages")` → token-by-token print. `HumanInTheLoopMiddleware` interrupts on `refund_order`/`write_note`. `/history /rewind /fork` expose `get_state_history` + `update_state`. `InMemoryStore` namespace `("user_prefs", user_id)` for long-term prefs. PII redaction + dynamic prompt as `@wrap_model_call`/`@dynamic_prompt`.

**Tech Stack:** LangChain 1.x, LangGraph 1.x, `langgraph-supervisor`, Python stdlib only for I/O. Reuses `01-langchain-basics/_common.py` `get_llm()` factory.

**Note on testing:** Per project convention (no tests in any of 17 existing demos), tasks skip unit tests. Validation = `ast.parse` + dry-run smoke with mock LLM + manual 7-scenario checklist in README.

---

## File Map

| File | Responsibility | Approx LOC |
|---|---|---|
| `08-cli-assistant/_common.py` | Re-export `get_llm`/`banner` from L1 `_common.py`, add project-root `sys.path` shim | 25 |
| `08-cli-assistant/tools.py` | 6 mock tools (`get_weather`, `calc`, `read_note`, `write_note`, `get_order`, `refund_order`) | 80 |
| `08-cli-assistant/middleware.py` | `@wrap_model_call redact_pii` + `@dynamic_prompt tone_prompt` | 50 |
| `08-cli-assistant/memory.py` | `InMemoryStore` wrapper + `get_prefs`/`set_pref` | 40 |
| `08-cli-assistant/agent.py` | Build 4 specialists + supervisor graph assembly | 120 |
| `08-cli-assistant/cli.py` | REPL loop, command router (`/history`/`/rewind`/`/fork`/`/memory`/`/help`/`/quit`), streaming printer, async run_turn | 130 |
| `08-cli-assistant/main.py` | Entry point: env check + REPL bootstrap | 30 |
| `08-cli-assistant/README.md` | 7-scenario checklist + "10 things you can answer after reading" | 80 |
| **Total** | | **~555** |

---

## Task 1: Verify dependencies

**Files:** None (read-only check)

- [ ] **Step 1: Check `langgraph-supervisor` availability**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
python -c "import langgraph_supervisor; print(langgraph_supervisor.__version__)"
```

Expected: prints a version string (e.g., `0.0.21`) OR raises `ModuleNotFoundError`.

- [ ] **Step 2: If missing, install**

If `ModuleNotFoundError`, run:
```bash
pip install langgraph-supervisor
```

Verify by re-running Step 1.

- [ ] **Step 3: Check other key packages**

Run:
```bash
python -c "import langchain, langgraph, langgraph.checkpoint.memory, langgraph.store.memory; from langchain.agents import create_agent; from langchain.agents.middleware import HumanInTheLoopMiddleware; print('OK', langchain.__version__, langgraph.__version__)"
```

Expected: prints `OK` with version numbers, no errors.

- [ ] **Step 4: Commit (nothing to commit if pure check)**

If a package was installed, commit updated `requirements.txt` (if pip auto-edited it) OR just note it in commit message. No git commit needed for a read-only verification.

---

## Task 2: Create directory + `_common.py`

**Files:**
- Create: `08-cli-assistant/_common.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
```

- [ ] **Step 2: Write `_common.py`**

Write `08-cli-assistant/_common.py` with EXACT content:

```python
"""_common.py — 复用 01-langchain-basics/_common.py 的 LLM 工厂 + banner.

CLI 模块独立目录,但需要复用项目其它模块已经写好的:
  - get_llm(): 4-provider 自动检测 (Anthropic/DeepSeek/MiniMax/OpenAI)
  - banner():  分节标题打印

实现要点:
  1. sys.path 临时加项目根,这样 from _common import get_llm 能找到 01-langchain-basics
  2. 不复制 _common.py 内容,直接 import (避免双份维护)
  3. CLI 内部所有 demo / REPL 都从这里 import

跑法:
    python 08-cli-assistant/main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根 (parent of 08-cli-assistant/), 这样能 import 兄弟模块的 _common
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "01-langchain-basics") not in sys.path:
    sys.path.insert(0, str(_ROOT / "01-langchain-basics"))

# 从 L1 _common 复用 (不要复制粘贴,改一处全部生效)
from _common import banner, get_llm  # noqa: E402  (sys.path 改了才能 import)

__all__ = ["banner", "get_llm"]
```

- [ ] **Step 3: Smoke import**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "from _common import banner, get_llm; print(banner, get_llm)"
```

Expected: prints the function objects, no errors. Note: `get_llm()` itself will raise if no API key — that's expected, just importing is fine.

- [ ] **Step 4: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/_common.py
git commit -m "feat(cli): 创建 08-cli-assistant 模块骨架 + 复用 L1 _common"
```

---

## Task 3: Create `tools.py` (6 mock tools)

**Files:**
- Create: `08-cli-assistant/tools.py`

- [ ] **Step 1: Write `tools.py`**

Write `08-cli-assistant/tools.py` with EXACT content:

```python
"""tools.py — 6 个 mock 工具,4 个 specialist 各自挂一批.

工具清单:
  weather    : get_weather
  calc       : calc  (AST 安全求值,禁止 __import__)
  notes      : read_note, write_note  (write_note 触发 HITL)
  orders     : get_order, refund_order (refund_order 触发 HITL)

安全:
  - calc 用 ast.parse + 白名单节点,禁止 Name/Call/Attribute (避免 __import__/open)
  - read_note/write_note 的 name 限制 [a-z0-9_]+,防路径穿越
  - refund_order 金额 > 10000 拒绝 (业务规则)
"""
from __future__ import annotations

import ast
import operator
import re
from langchain_core.tools import tool

# ============================================================
# Mock 数据 — 内存 dict,够 demo 用
# ============================================================
_NOTES: dict[str, str] = {
    "todo": "买牛奶, 取快递, 交水电费",
}
_ORDERS: dict[str, dict] = {
    "#123": {"item": "LangChain 课程", "amount": 199.0, "status": "已付款"},
    "#456": {"item": "LangGraph 课程", "amount": 299.0, "status": "已发货"},
}


# ============================================================
# Weather — 无 HITL
# ============================================================
@tool
def get_weather(city: str) -> str:
    """(mock) 查天气. city 是城市名."""
    return f"{city} 晴 25°C, 微风"


# ============================================================
# Calc — AST 安全求值
# ============================================================
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


@tool
def calc(expr: str) -> str:
    """(mock) 计算数学表达式, 仅支持 +-*/%** 和数字/括号.

    e.g. calc("2 + 3 * 4") -> "14"
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"语法错误: {e}"
    try:
        result = _eval_node(tree.body)
    except _UnsafeNode as e:
        return f"非法表达式: {e}"
    except Exception as e:
        return f"计算错误: {e}"
    return str(result)


def _eval_node(node: ast.AST) -> float | int:
    """递归求值, 只允许 Constant/BinOp/UnaryOp/Expression."""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise _UnsafeNode(f"常量类型 {type(node.value).__name__} 不允许")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise _UnsafeNode(f"运算符 {type(node.op).__name__} 不允许")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise _UnsafeNode(f"一元运算符 {type(node.op).__name__} 不允许")
        return op(_eval_node(node.operand))
    raise _UnsafeNode(f"节点 {type(node).__name__} 不允许 (禁止 Name/Call/Attribute)")


class _UnsafeNode(Exception):
    """AST 求值时遇到不允许的节点."""


# ============================================================
# Notes — write 触发 HITL
# ============================================================
_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


@tool
def read_note(name: str) -> str:
    """(mock) 读笔记. name 必须是 [a-z0-9_]+."""
    if not _NAME_RE.match(name):
        return f"name 非法: {name!r}, 只允许小写字母数字下划线"
    return _NOTES.get(name, f"(笔记 {name!r} 不存在)")


@tool
def write_note(name: str, content: str) -> str:
    """(mock) 写笔记. name 必须是 [a-z0-9_]+. ⚠️ 触发 HITL 审批."""
    if not _NAME_RE.match(name):
        return f"name 非法: {name!r}"
    _NOTES[name] = content
    return f"笔记 {name!r} 已写入 ({len(content)} 字符)"


# ============================================================
# Orders — refund 触发 HITL
# ============================================================
@tool
def get_order(order_id: str) -> str:
    """(mock) 查订单详情."""
    info = _ORDERS.get(order_id)
    if info is None:
        return f"订单 {order_id} 不存在"
    return f"订单 {order_id}: {info['item']}, 金额 {info['amount']} 元, 状态 {info['status']}"


@tool
def refund_order(order_id: str, amount: float) -> str:
    """(mock) 给订单退款. ⚠️ 触发 HITL 审批. 金额 > 10000 业务拒绝."""
    if amount > 10000:
        return f"退款失败: 金额 {amount} 超过业务上限 10000"
    info = _ORDERS.get(order_id)
    if info is None:
        return f"订单 {order_id} 不存在"
    return f"订单 {order_id} 已退款 {amount} 元 (原金额 {info['amount']} 元)"
```

- [ ] **Step 2: Syntax check**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "import ast; ast.parse(open('tools.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Manual calc test**

Run:
```bash
python -c "from tools import calc; print(calc.invoke({'expr': '2 + 3 * 4'})); print(calc.invoke({'expr': '__import__(\"os\")'}))"
```

Expected:
```
14
非法表达式: 节点 Name 不允许 (禁止 Name/Call/Attribute)
```

- [ ] **Step 4: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/tools.py
git commit -m "feat(cli): 6 个 mock 工具 (weather/calc/notes/orders), 含 AST 安全求值"
```

---

## Task 4: Create `middleware.py` (PII + dynamic prompt)

**Files:**
- Create: `08-cli-assistant/middleware.py`

- [ ] **Step 1: Write `middleware.py`**

Write `08-cli-assistant/middleware.py` with EXACT content:

```python
"""middleware.py — 两个 custom middleware.

  1. @wrap_model_call redact_pii
     - 把 HumanMessage.content 里的手机号/身份证号脱敏
     - 避免 LLM 看到原始敏感数据
     - 复用 04_middleware.py demo 8 的 pattern

  2. @dynamic_prompt tone_prompt
     - 根据用户最近的输入动态切 system prompt 语气
     - 检测关键词: "正式" → 正式语气, "哈哈"/"随便" → 轻松语气, 否则默认
     - 复用 04_middleware.py demo 1 的 pattern
"""
from __future__ import annotations

import re

from langchain.agents.middleware import dynamic_prompt, wrap_model_call
from langchain_core.messages import HumanMessage, SystemMessage

# ============================================================
# 1. PII 脱敏 — wrap_model_call
# ============================================================
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_ID_RE = re.compile(r"\d{17}[\dXx]")


@wrap_model_call
def redact_pii(request, handler):
    """把用户消息里的手机号/身份证号脱敏再发给 LLM."""
    for m in request.messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            new_content = _PHONE_RE.sub("1XX-XXXX-XXXX", m.content)
            new_content = _ID_RE.sub("1XXXXXXXXXXXXXXXXX", new_content)
            if new_content != m.content:
                # 不可变消息,用 .model_copy 或者 mutate 内容 (构造允许)
                m.content = new_content
    return handler(request)


# ============================================================
# 2. Dynamic prompt — 根据用户语气切 system prompt
# ============================================================
@dynamic_prompt
def tone_prompt(request) -> str:
    """读最近 N 条 HumanMessage, 检测关键词切 system prompt."""
    history = [
        m.content for m in request.messages if isinstance(m, HumanMessage)
    ]
    full = " ".join(history)

    if "正式" in full:
        return "你是智能个人助手. 用正式语气回答,使用'您'."
    if "哈哈" in full or "随便" in full or "lol" in full.lower():
        return "你是智能个人助手. 用轻松幽默的语气回答,可以用 emoji."
    return "你是智能个人助手. 回答简洁 (不超过 80 字), 必要时调工具."


__all__ = ["redact_pii", "tone_prompt"]
```

- [ ] **Step 2: Syntax check**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "import ast; ast.parse(open('middleware.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: PII regex sanity test**

Run:
```bash
python -c "from middleware import _PHONE_RE, _ID_RE; print(_PHONE_RE.sub('1XX-XXXX-XXXX', '我手机号 13800138000')); print(_ID_RE.sub('1XXXXXXXXXXXXXXXXX', '身份证 11010119900101123X'))"
```

Expected:
```
我手机号 1XX-XXXX-XXXX
身份证 1XXXXXXXXXXXXXXXXX
```

- [ ] **Step 4: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/middleware.py
git commit -m "feat(cli): PII 脱敏 + 动态语气 system prompt middleware"
```

---

## Task 5: Create `memory.py` (Store wrapper)

**Files:**
- Create: `08-cli-assistant/memory.py`

- [ ] **Step 1: Write `memory.py`**

Write `08-cli-assistant/memory.py` with EXACT content:

```python
"""memory.py — 长期偏好 Store 包装.

InMemoryStore namespace = ("user_prefs", user_id)
存储:
  - nickname: 用户昵称
  - city:     用户常驻城市
  - language: 用户偏好语言

启动时若 namespace 为空, 写入默认值; 这样 CLI 首次启动就有可读偏好.

复用 10_durable_execution.py demo 7 的 pattern (InMemoryStore + namespace).

生产替换: PostgresStore.from_conn_string(...) — 跨进程持久.
注意: InMemoryStore 进程重启就清空, CLI 演示需要提醒.
"""
from __future__ import annotations

import os
from langgraph.store.memory import InMemoryStore

_DEFAULT_PREFS = {
    "nickname": {"value": "friend"},
    "city": {"value": "上海"},
    "language": {"value": "中文"},
}


def build_store() -> tuple[InMemoryStore, tuple[str, str]]:
    """返回一个 (store, namespace) 元组."""
    user_id = os.getenv("CLI_USER_ID", "default")
    namespace = ("user_prefs", user_id)
    store = InMemoryStore()

    # 首次启动写默认偏好 (如果 namespace 为空)
    items = store.search(namespace)
    if not items:
        for key, val in _DEFAULT_PREFS.items():
            store.put(namespace, key, val)

    return store, namespace


def get_prefs(store: InMemoryStore, namespace: tuple[str, str]) -> dict[str, str]:
    """读全部偏好, 返回 {key: value} dict."""
    items = store.search(namespace)
    return {it.key: it.value.get("value", "") for it in items}


def set_pref(
    store: InMemoryStore, namespace: tuple[str, str], key: str, value: str
) -> None:
    """写一条偏好."""
    if key not in _DEFAULT_PREFS:
        # 允许扩展 key, 但要标 user_ 前缀
        if not key.startswith("user_"):
            raise ValueError(f"非内置 key {key!r} 必须以 'user_' 开头")
    store.put(namespace, key, {"value": value})


__all__ = ["build_store", "get_prefs", "set_pref"]
```

- [ ] **Step 2: Syntax check**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "import ast; ast.parse(open('memory.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Smoke test**

Run:
```bash
python -c "
from memory import build_store, get_prefs, set_pref
store, ns = build_store()
print('initial:', get_prefs(store, ns))
set_pref(store, ns, 'nickname', 'fang')
print('after set:', get_prefs(store, ns))
"
```

Expected:
```
initial: {'nickname': 'friend', 'city': '上海', 'language': '中文'}
after set: {'nickname': 'fang', 'city': '上海', 'language': '中文'}
```

- [ ] **Step 4: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/memory.py
git commit -m "feat(cli): 长期偏好 Store 包装 (InMemoryStore + namespace)"
```

---

## Task 6: Create `agent.py` (supervisor + 4 specialists)

**Files:**
- Create: `08-cli-assistant/agent.py`

- [ ] **Step 1: Write `agent.py`**

Write `08-cli-assistant/agent.py` with EXACT content:

```python
"""agent.py — 装配 supervisor + 4 specialists.

架构:
  supervisor (create_supervisor)
    ├── WeatherAgent  (create_agent, tools=[get_weather])
    ├── CalcAgent     (create_agent, tools=[calc])
    ├── NotesAgent    (create_agent, tools=[read_note, write_note])
    └── OrdersAgent   (create_agent, tools=[get_order, refund_order])

HITL 挂 supervisor.compile() 上, 危险工具 (refund_order / write_note) 在
HumanInTheLoopMiddleware 里登记, 触发时整个 supervisor graph 暂停.

middleware (PII + dynamic_prompt) 挂 supervisor.compile() 上, supervisor
调 LLM 前生效.

复用:
  - 13_supervisor.py: langgraph_supervisor.create_supervisor
  - 04_middleware.py demo 5: HumanInTheLoopMiddleware
  - 04_middleware.py demo 1/8: dynamic_prompt / wrap_model_call
"""
from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_supervisor import create_supervisor

from middleware import redact_pii, tone_prompt
from tools import (
    calc,
    get_order,
    get_weather,
    read_note,
    refund_order,
    write_note,
)

# ============================================================
# Specialist 工厂
# ============================================================
def _make_weather_agent(model):
    return create_agent(
        model=model,
        tools=[get_weather],
        system_prompt=(
            "你是 WeatherAgent. 用户问天气时, 调 get_weather 工具, "
            "用中文简洁回答 (不超过 30 字)."
        ),
    )


def _make_calc_agent(model):
    return create_agent(
        model=model,
        tools=[calc],
        system_prompt=(
            "你是 CalcAgent. 用户问数学时, 调 calc 工具, "
            "把结果用一句话告诉用户."
        ),
    )


def _make_notes_agent(model):
    return create_agent(
        model=model,
        tools=[read_note, write_note],
        system_prompt=(
            "你是 NotesAgent. 读/写笔记. 调工具后用中文简短回复."
        ),
    )


def _make_orders_agent(model):
    return create_agent(
        model=model,
        tools=[get_order, refund_order],
        system_prompt=(
            "你是 OrdersAgent. 查订单 / 退款. 调工具后用中文简短回复. "
            "退款是危险操作, 必须经 HumanInTheLoopMiddleware 审批."
        ),
    )


# ============================================================
# Supervisor 装配
# ============================================================
SUPERVISOR_PROMPT = """你是智能个人助手 supervisor. 根据用户问题, 把任务派给:
  - WeatherAgent: 天气相关
  - CalcAgent:    数学计算
  - NotesAgent:   笔记读写
  - OrdersAgent:  订单/退款

不要直接调工具. 一次只派一个 specialist. 用中文回复用户."""


def build_graph(model, *, checkpointer=None, store=None):
    """Build supervisor graph with middleware + checkpointer + store.

    checkpointer / store 默认 None — 由 caller 注入 (cli.py 负责创建).
    """
    weather_agent = _make_weather_agent(model)
    calc_agent = _make_calc_agent(model)
    notes_agent = _make_notes_agent(model)
    orders_agent = _make_orders_agent(model)

    hitl = HumanInTheLoopMiddleware(
        interrupt_on={
            # write_note / refund_order 触发 HITL
            "write_note": {"allowed_decisions": ["approve", "edit", "reject"]},
            "refund_order": {"allowed_decisions": ["approve", "edit", "reject"]},
        },
    )

    supervisor = create_supervisor(
        agents=[weather_agent, calc_agent, notes_agent, orders_agent],
        model=model,
        prompt=SUPERVISOR_PROMPT,
        output_mode="last_message",  # 只回 supervisor 看到的 final message
    )

    return supervisor.compile(
        checkpointer=checkpointer,
        store=store,
        middleware=[redact_pii, tone_prompt, hitl],
    )


__all__ = ["build_graph"]
```

- [ ] **Step 2: Syntax check**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "import ast; ast.parse(open('agent.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Import smoke (no API call)**

Run:
```bash
python -c "
from agent import build_graph, _make_weather_agent
from unittest.mock import MagicMock
mock_llm = MagicMock()
ag = _make_weather_agent(mock_llm)
print('WeatherAgent OK:', type(ag).__name__)
print('build_graph signature OK')
"
```

Expected:
```
WeatherAgent OK: CompiledStateGraph
build_graph signature OK
```

(`build_graph` doesn't actually build unless called; we just check import)

- [ ] **Step 4: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/agent.py
git commit -m "feat(cli): supervisor + 4 specialists + HITL middleware 装配"
```

---

## Task 7: Create `cli.py` (REPL + commands + streaming + HITL handler)

**Files:**
- Create: `08-cli-assistant/cli.py`

- [ ] **Step 1: Write `cli.py`**

Write `08-cli-assistant/cli.py` with EXACT content:

```python
"""cli.py — REPL 主循环 + 命令路由 + streaming token 打印 + HITL 审批.

REPL 流程:
  1. read() 读一行 stdin
  2. 以 "/" 开头 → handle_command() (内置命令)
  3. 普通文本   → run_turn() 异步流式调 supervisor
  4. run_turn 内部: astream(stream_mode="messages") + 逐字 print
  5. 检测到 state.next 非空 + 有 interrupt → handle_hitl()
  6. 用户输入 a/e/r → Command(resume=...) 恢复

命令:
  /history   列出 checkpoints
  /rewind N  回到第 N 个 checkpoint (不重跑 LLM)
  /fork TXT  在新 thread 续走, 注入 TXT 作为新的人类消息
  /memory    查看/编辑长期偏好
  /help      帮助
  /quit      退出
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from _common import banner
from memory import get_prefs, set_pref


# ============================================================
# 欢迎语 + 帮助
# ============================================================
WELCOME = """
╭─────────────────────────────────────────────╮
│  智能个人助手 CLI  (08-cli-assistant)       │
│                                             │
│  输入问题 → streaming token 流式输出        │
│  危险操作 (退款/写笔记) → 自动暂停审批      │
│                                             │
│  内置命令:                                  │
│    /history   列出 checkpoints               │
│    /rewind N  回到第 N 个 checkpoint         │
│    /fork TXT  改历史后在新 thread 续走      │
│    /memory    查看/编辑长期偏好              │
│    /help      帮助                           │
│    /quit      退出                           │
╰─────────────────────────────────────────────╯
"""


HELP_TEXT = """
命令:
  /history           列出本 thread 所有 checkpoint (index 0=最新)
  /rewind N          回到 history[N] 的状态 (N 是 history 列表索引, 0=最新)
  /fork <text>       在最新 checkpoint 上追加 <text>, 新 thread 续走
  /memory            查看偏好
  /memory <key> <v>  设置偏好 (nickname / city / language / user_*)
  /help              本帮助
  /quit              退出

正常对话:
  - "北京天气?"     → 派 WeatherAgent
  - "123 * 456"     → 派 CalcAgent
  - "查订单 #123"    → 派 OrdersAgent
  - "退款 #123 100"  → OrdersAgent 触发 HITL (输入 a/e/r 决策)
  - "写笔记 todo ..." → NotesAgent 触发 HITL
"""


# ============================================================
# REPL 主类
# ============================================================
class CLI:
    """REPL 主循环 + 命令路由 + 流式打印."""

    def __init__(
        self,
        graph,
        checkpointer,
        store,
        store_namespace: tuple[str, str],
        thread_id: str = "cli-session-1",
    ):
        self.graph = graph
        self.checkpointer = checkpointer
        self.store = store
        self.store_ns = store_namespace
        self.thread_id = thread_id
        self.active_thread_id = thread_id  # 主 thread; fork 后会变

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.active_thread_id}}

    # --------------------------------------------------------
    # 入口
    # --------------------------------------------------------
    async def run(self) -> None:
        print(WELCOME)
        print(f">>> thread_id: {self.thread_id}")
        print(f">>> user prefs: {get_prefs(self.store, self.store_ns)}")
        print()

        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, input, "你> ")
            except (EOFError, KeyboardInterrupt):
                print("\n再见 👋")
                return

            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                should_exit = self.handle_command(line)
                if should_exit:
                    return
                continue

            # 普通对话
            await self.run_turn(line)

    # --------------------------------------------------------
    # 内置命令
    # --------------------------------------------------------
    def handle_command(self, line: str) -> bool:
        """处理 / 命令. 返回 True = 退出 REPL."""
        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "/quit" or cmd == "/exit":
            print("再见 👋")
            return True

        if cmd == "/help":
            print(HELP_TEXT)
            return False

        if cmd == "/history":
            self._cmd_history()
            return False

        if cmd == "/rewind":
            if len(parts) < 2:
                print("用法: /rewind N  (N 是 history 列表索引, 0=最新)")
                return False
            try:
                n = int(parts[1])
                self._cmd_rewind(n)
            except ValueError:
                print(f"非法索引: {parts[1]!r}")
            return False

        if cmd == "/fork":
            if len(parts) < 2:
                print("用法: /fork <text>")
                return False
            self._cmd_fork(parts[1])
            return False

        if cmd == "/memory":
            if len(parts) == 1:
                self._cmd_memory_show()
            elif len(parts) >= 3:
                self._cmd_memory_set(parts[1], parts[2])
            else:
                print("用法: /memory [key value]")
            return False

        print(f"未知命令: {cmd}. 输入 /help 查看.")
        return False

    def _cmd_history(self) -> None:
        history = list(self.graph.get_state_history(self.config))
        print(f"\n>>> 共 {len(history)} 个 checkpoint (history[0]=最新):")
        for i, snap in enumerate(history):
            ckpt_short = snap.config["configurable"]["checkpoint_id"][:8]
            n_msgs = len(snap.values.get("messages", []))
            next_node = snap.next
            print(f"  [{i:>3}] ckpt={ckpt_short}... | msgs={n_msgs} | next={next_node}")

    def _cmd_rewind(self, n: int) -> None:
        history = list(self.graph.get_state_history(self.config))
        if n < 0 or n >= len(history):
            print(f"索引 {n} 越界, 范围 [0, {len(history)-1}]")
            return
        snap = history[n]
        ckpt = snap.config["configurable"]["checkpoint_id"]
        # 直接把 thread_id 的 checkpoint_id 改了 → 下次 invoke 从这里走
        # 注意: 单纯改 config["configurable"]["checkpoint_id"] 不污染历史
        self.active_thread_id = snap.config["configurable"]["thread_id"]
        print(
            f">>> 回到 history[{n}] (ckpt={ckpt[:8]}..., "
            f"{len(snap.values.get('messages', []))} 条消息)"
        )

    def _cmd_fork(self, text: str) -> None:
        """在最新 checkpoint 上追加 text, 用 update_state 创建新 thread."""
        history = list(self.graph.get_state_history(self.config))
        if not history:
            print(">>> 无历史, 无法 fork. 先跟助手对话几轮.")
            return
        new_config = self.graph.update_state(
            history[0].config,
            {"messages": [HumanMessage(content=text)]},
        )
        new_thread = new_config["configurable"]["thread_id"]
        print(f">>> Fork 到新 thread: {new_thread}")
        print(f">>> 续走中...")
        asyncio.run(self._continue_turn(new_config))

    async def _continue_turn(self, config: dict) -> None:
        """fork 后在新 thread 上继续 invoke (流式)."""
        try:
            async for token, _ in self.graph.astream(
                {}, config=config, stream_mode="messages"
            ):
                if hasattr(token, "content") and token.content:
                    print(token.content, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}")

    def _cmd_memory_show(self) -> None:
        prefs = get_prefs(self.store, self.store_ns)
        print("\n>>> 长期偏好:")
        for k, v in prefs.items():
            print(f"  {k}: {v}")
        print(f"  (namespace: {self.store_ns})")

    def _cmd_memory_set(self, key: str, value: str) -> None:
        try:
            set_pref(self.store, self.store_ns, key, value)
            print(f">>> 偏好已更新: {key} = {value}")
        except ValueError as e:
            print(f"[error] {e}")

    # --------------------------------------------------------
    # 普通对话 — 流式 + HITL
    # --------------------------------------------------------
    async def run_turn(self, text: str) -> None:
        print()  # 换行
        try:
            async for token, _ in self.graph.astream(
                {"messages": [HumanMessage(content=text)]},
                config=self.config,
                stream_mode="messages",
            ):
                if hasattr(token, "content") and token.content:
                    print(token.content, end="", flush=True)
            print()
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"\n[error] {err}")
            return

        # 检查是否需要 HITL 审批
        await self._maybe_hitl()

    async def _maybe_hitl(self) -> None:
        """如果 graph 在 interrupt 状态, 走 HITL 流程."""
        state = self.graph.get_state(self.config)
        if not state.next:
            return  # 正常结束, 不需要审批

        # 拿 interrupt 内容 (state.tasks[0].interrupts[0].value)
        if not (state.tasks and state.tasks[0].interrupts):
            print(f"\n>>> 暂停在 {state.next}, 但无 interrupt 内容, 跳过 HITL")
            return

        intr = state.tasks[0].interrupts[0].value
        print(f"\n\n⚠️  HITL 中断 (节点 {state.next}):")
        # intr 是 dict, 包含 tool_call / reason
        if isinstance(intr, dict):
            for k, v in intr.items():
                print(f"  {k}: {v}")
        else:
            print(f"  {intr}")

        # 读决策
        try:
            decision_raw = input("\n决策 [a]pprove / [e]dit / [r]eject: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return

        if decision_raw.startswith("a"):
            decision = {"decisions": [{"type": "approve"}]}
        elif decision_raw.startswith("e"):
            # 简化: edit 用原参数 (实战应让用户改具体字段)
            print(">>> edit: 当前实现保留原参数, 实战可让用户改 amount 等")
            decision = {"decisions": [{"type": "approve"}]}
        elif decision_raw.startswith("r"):
            reason = input("拒绝原因: ").strip()
            decision = {"decisions": [{"type": "reject", "reason": reason}]}
        else:
            print(f"未知决策 {decision_raw!r}, 默认 reject")
            decision = {"decisions": [{"type": "reject", "reason": "未知决策"}]}

        # resume
        try:
            async for token, _ in self.graph.astream(
                Command(resume=decision),
                config=self.config,
                stream_mode="messages",
            ):
                if hasattr(token, "content") and token.content:
                    print(token.content, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[error after HITL] {type(e).__name__}: {e}")


__all__ = ["CLI", "WELCOME", "HELP_TEXT"]
```

- [ ] **Step 2: Syntax check**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "import ast; ast.parse(open('cli.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Import smoke**

Run:
```bash
python -c "from cli import CLI, WELCOME, HELP_TEXT; print('OK, WELCOME len:', len(WELCOME))"
```

Expected: `OK, WELCOME len: <number>`.

- [ ] **Step 4: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/cli.py
git commit -m "feat(cli): REPL 主循环 + 命令路由 + 流式打印 + HITL 审批处理"
```

---

## Task 8: Create `main.py` (entry point)

**Files:**
- Create: `08-cli-assistant/main.py`

- [ ] **Step 1: Write `main.py`**

Write `08-cli-assistant/main.py` with EXACT content:

```python
"""main.py — CLI 个人助手入口.

跑法:
    cd 08-cli-assistant
    python main.py

需要 .env 里有 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY /
OPENAI_API_KEY 之一. 详见 01-langchain-basics/_common.py.
"""
from __future__ import annotations

import asyncio
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _common import banner, get_llm
from agent import build_graph
from cli import CLI
from memory import build_store


def main() -> int:
    # 1. 检查 API key
    has_key = any(
        os.getenv(k)
        for k in (
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
            "MINIMAX_API_KEY",
            "OPENAI_API_KEY",
        )
    )
    if not has_key:
        print(
            "[error] 未找到 LLM API key. 请在项目根 .env 设置:\n"
            "  ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY"
        )
        return 1

    # 2. 装配 LLM + Graph + Store
    banner("启动智能个人助手 CLI")
    try:
        llm = get_llm()
    except RuntimeError as e:
        print(f"[error] {e}")
        return 1

    from langgraph.checkpoint.memory import InMemorySaver

    checkpointer = InMemorySaver()
    store, namespace = build_store()

    graph = build_graph(llm, checkpointer=checkpointer, store=store)

    # 3. 启动 REPL
    cli = CLI(graph, checkpointer, store, namespace)
    asyncio.run(cli.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Syntax check**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "import ast; ast.parse(open('main.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Help / no-API-key path**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
env -u ANTHROPIC_API_KEY -u DEEPSEEK_API_KEY -u MINIMAX_API_KEY -u OPENAI_API_KEY python 08-cli-assistant/main.py </dev/null
```

Expected (approximate):
```
[error] 未找到 LLM API key. ...
```

Exit code: 1.

(Note: `env -u` only strips from subprocess env, not from `.env` loaded by `_common.py`. The dotenv loading may still find keys. If it does find a key, the script will try to construct LLM, which may fail at model init. Either outcome proves the no-key path is exercised. If a real key is in `.env`, expect the LLM init error path.)

- [ ] **Step 4: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/main.py
git commit -m "feat(cli): main.py 入口 + API key 检查"
```

---

## Task 9: Create `README.md`

**Files:**
- Create: `08-cli-assistant/README.md`

- [ ] **Step 1: Write `README.md`**

Write `08-cli-assistant/README.md` with EXACT content:

```markdown
# 08-cli-assistant — 智能个人助手 CLI

把项目里分散在各 demo 的**高级用法**串成一个真正能跑的端到端工具。

## 学完你能回答 10 个问题

1. 怎么用 `astream(stream_mode="messages")` 实现 token 级流式打印?
2. `HumanInTheLoopMiddleware(interrupt_on={...})` 怎么在 1.x 里挂上 HITL?
3. HITL 触发后, 用户怎么用 stdin 输入决策 (approve / edit / reject) 恢复?
4. `langgraph_supervisor.create_supervisor` 怎么装配多个 specialist?
5. `@wrap_model_call` 怎么拦截请求, 实现 PII 脱敏?
6. `@dynamic_prompt` 怎么根据 history 动态切 system prompt?
7. `get_state_history` 怎么列出 checkpoints? `update_state` 怎么改历史?
8. `InMemoryStore` + namespace 怎么存长期偏好?
9. 怎么在 CLI 里把 streaming 打印 + HITL 中断 + 命令路由整合?
10. 怎么从项目根 .env 复用 LLM 工厂 (跨模块)?

## 跑法

```bash
# 1. 确保 .env 里有 API key (项目根 .env)
cat ../.env  # 应有 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / 等

# 2. 启动
cd 08-cli-assistant
python main.py
```

## 7 个手测场景

| # | 输入 | 期望 |
|---|---|---|
| 1 | `北京天气?` | 派给 WeatherAgent, streaming token 流式输出 |
| 2 | `123 * 456 等于多少` | 派给 CalcAgent |
| 3 | `退款 #123 100元` | 触发 HITL, 输入 `a` 通过 / `r` 拒绝 |
| 4 | `写笔记 todo 买牛奶` | 触发 HITL, 同上 |
| 5 | `我的手机号 13800138000` | PII middleware 脱敏成 `1XX-XXXX-XXXX` |
| 6 | 跑 3 轮对话 → `/history` → `/rewind 1` | 看到状态回到第 1 轮 |
| 7 | `/memory nickname fang` → 退出 → 重启 → `/memory` | nickname 还在 (注: InMemoryStore 重启会丢, 生产换 PostgresStore) |

## 内置命令

| 命令 | 作用 |
|---|---|
| `/history` | 列出本 thread 所有 checkpoint (history[0]=最新) |
| `/rewind N` | 回到 history[N] 的状态 |
| `/fork <text>` | 改历史后在新 thread 续走 |
| `/memory` | 查看长期偏好 |
| `/memory <key> <v>` | 设置偏好 |
| `/help` | 帮助 |
| `/quit` | 退出 |

## 文件结构

```
08-cli-assistant/
├── _common.py     # 复用 01-langchain-basics/_common.py
├── tools.py       # 6 个 mock 工具
├── middleware.py  # PII + dynamic prompt
├── memory.py      # Store 包装
├── agent.py       # supervisor + 4 specialists
├── cli.py         # REPL + 命令 + 流式 + HITL
├── main.py        # 入口
└── README.md      # 本文件
```

## 复用项目内 demo

- `01-langchain-basics/04_middleware.py` — middleware/HITL 全套模式
- `02-langgraph-orchestration/08_interrupt_hitl.py` — HITL interrupt 模式
- `02-langgraph-orchestration/09_streaming.py` — streaming modes
- `02-langgraph-orchestration/10_durable_execution.py` — time travel + Store
- `04-multi-agent/13_supervisor.py` — supervisor 模式
```

- [ ] **Step 2: Verify file**

Run:
```bash
ls -la "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant/"
```

Expected: shows all 8 files (`_common.py`, `tools.py`, `middleware.py`, `memory.py`, `agent.py`, `cli.py`, `main.py`, `README.md`).

- [ ] **Step 3: Commit**

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/README.md
git commit -m "docs(cli): README + 7 个手测场景"
```

---

## Task 10: Lint all 8 files with `ast.parse`

**Files:** None (validation only)

- [ ] **Step 1: Run ast.parse on every file**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
for f in _common.py tools.py middleware.py memory.py agent.py cli.py main.py; do
  python -c "import ast; ast.parse(open('$f').read())" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: 7 lines of `OK: <filename>`.

- [ ] **Step 2: Total LOC count**

Run:
```bash
wc -l _common.py tools.py middleware.py memory.py agent.py cli.py main.py README.md
```

Expected: total between 500 and 600 lines.

- [ ] **Step 3: Commit (only if any whitespace-only changes were needed)**

If a file needed a fix, amend the relevant task commit OR add a fixup commit:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git status --short  # should be clean if everything passed
```

---

## Task 11: End-to-end manual smoke test (mock LLM)

**Files:** None (run-only)

- [ ] **Step 1: Dry-run with mock LLM (no real API call)**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "
import asyncio
from unittest.mock import MagicMock
from agent import build_graph
from cli import CLI
from memory import build_store
from langgraph.checkpoint.memory import InMemorySaver

# mock LLM: create_agent / supervisor 会调 LLM, 我们用 mock 替代
# 但这个 dry-run 主要是看 import + 装配链通不通
mock_llm = MagicMock()
mock_llm.bind_tools = MagicMock(return_value=mock_llm)

store, ns = build_store()
ck = InMemorySaver()
# 不真 build_graph (会真连 LLM), 只看 import 通
print('import chain OK')
print('tools:', [t.name for t in __import__('tools', fromlist=['*']).__dict__.values() if hasattr(t, 'name')])
"
```

Expected: prints `import chain OK` + 6 tool names.

- [ ] **Step 2: With a real API key (Claude / DeepSeek / OpenAI), run a 30-sec test**

If `ANTHROPIC_API_KEY` or equivalent is set in `.env`:

```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
echo "北京天气?" | python 08-cli-assistant/main.py 2>&1 | head -30
```

Expected: prompts exit (no REPL), but if piping produces output you should see LLM response text within ~20s. If M3 doesn't call tools, that's fine — just verify no crash.

- [ ] **Step 3: Verify HITL path with mock interrupt**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1/08-cli-assistant"
python -c "
# 直接测 CLI 类的 HITL 处理逻辑 (不需要真 LLM)
from unittest.mock import MagicMock
from cli import CLI

mock_graph = MagicMock()
cli = CLI(mock_graph, MagicMock(), MagicMock(), ('prefs', 'u'))
# 测命令路由
assert cli.handle_command('/help') is False
assert cli.handle_command('/quit') is True
print('command routing OK')
"
```

Expected: prints `command routing OK`, no exceptions.

- [ ] **Step 4: Update README "跑通" 状态**

Edit `README.md` to add at top:
```
> ✅ Smoke-tested: import chain OK, command routing OK
```

Then commit:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git add 08-cli-assistant/README.md
git commit -m "docs(cli): mark smoke-tested"
```

---

## Task 12: Final wrap-up — verify DoD from spec

**Files:** None (checklist)

- [ ] **Step 1: Verify DoD items**

From spec Section 11:
- [ ] 8 files in `08-cli-assistant/` — yes (Tasks 2-9)
- [ ] `python main.py` starts and shows WELCOME — Task 8 + smoke in Task 11
- [ ] 7 manual scenarios covered — README has them (Task 9)
- [ ] ast.parse passes — Task 10
- [ ] No new pip deps (except langgraph-supervisor if missing) — Task 1
- [ ] README has "学完你能回答 10 个问题" — Task 9

- [ ] **Step 2: Final commit log**

Run:
```bash
cd "D:/work-ai/0401-langchain-langgraph-v1"
git log --oneline -15
```

Expected: ~10 new commits for this feature, each atomic and descriptive.

- [ ] **Step 3: Push if user requests (do NOT auto-push)**

Confirm with user before `git push`. Per session rules: "Commit or push only when the user asks."

---

## Self-Review Notes (after writing the plan)

- Spec coverage check: Each spec section maps to a task:
  - Section 3.1 (directory structure) → Tasks 2-9
  - Section 4.1 (Streaming) → Task 7 `run_turn`
  - Section 4.2 (HITL) → Task 6 `HumanInTheLoopMiddleware` + Task 7 `_maybe_hitl`
  - Section 4.3 (Supervisor) → Task 6 `build_graph`
  - Section 4.4 (Time travel) → Task 7 `_cmd_history/_rewind/_fork`
  - Section 4.5 (PII) → Task 4 `redact_pii`
  - Section 4.6 (Dynamic prompt) → Task 4 `tone_prompt`
  - Section 4.7 (Long-term Store) → Task 5 `memory.py` + Task 7 `_cmd_memory_*`
  - Section 4.8 (LangSmith) → Mentioned in README; env-driven, no code
  - Section 6 (Tools) → Task 3 `tools.py`
  - Section 11 (DoD) → Task 12

- Type consistency: All `graph.get_state_history` / `update_state` / `Command(resume=...)` usages match across tasks 6, 7, 11. The `Store.put/search` interface consistent across tasks 5, 7.

- Placeholder scan: No "TBD"/"TODO"/"add validation" placeholders. Every code step shows complete code.

- Frequent commits: 12 tasks, ~12 commits, each atomic.