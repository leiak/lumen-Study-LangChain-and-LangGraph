# 异常处理 try / except / raise SystemExit

## 是什么
Python 用 `try ... except ... finally ... else` 处理异常,`raise` 主动抛。

```python
try:
    risky_call()
except SpecificError as e:
    handle(e)
except (TypeError, ValueError) as e:    # 多个一起接
    handle(e)
else:
    print("没出错才走")
finally:
    cleanup()                            # 无论是否出错都走
```

## 为什么要用
- LLM 调用大概率超时 / 拒答 / 解析失败,必须 try/except
- 项目所有 demo 入口都用 try 包一层 + `raise SystemExit(1)` 优雅退出
- LangChain 工具用 `ToolException` 让框架把错误转成 ToolMessage 给 LLM

## 语法骨架

```python
# 基础
try:
    ...
except Exception as e:        # e 是异常实例
    ...

# 多个异常
except (ValueError, TypeError) as e:
    ...

# 抛出
raise ValueError("msg")

# 重新抛出 (保留原 traceback)
try:
    ...
except Exception:
    log()
    raise                      # 不带参数 = re-raise 当前异常

# 退出整个程序 (项目惯例)
if not api_key:
    print("缺少 API key")
    raise SystemExit(1)
```

## 项目里的真实例子

```python
# 01_models.py:201
if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")):
    print("请先在 .env 中设置 ANTHROPIC_API_KEY 或 MINIMAX_API_KEY")
    raise SystemExit(1)

# 02_tools.py:285 — 业务异常, 框架接管
from langchain_core.tools import ToolException
@tool
def lookup_order(order_id: str) -> str:
    if not order_id.startswith("ORD"):
        raise ToolException(f"订单号必须以 ORD 开头, 收到 {order_id!r}")
    ...

# 所有 demo 末尾 — 容错循环
for name, fn in [("demo_a", demo_a), ("demo_b", demo_b)]:
    try:
        fn()
    except Exception as e:
        print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")
```

## 常见坑

1. **裸 `except:` 会接 KeyboardInterrupt**: 至少写 `except Exception:`
2. **`except` 顺序**: 子类必须在父类前, 否则永远到不了子类的 handler
3. **`raise X from Y`**: `raise ValueError("...") from original_exc` 保留 cause chain
4. **`else` 不是必须的**: 只有 try 块成功才走 else, finally 始终走

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 抛出 | `throw new X()` | `panic(v)` | `raise X()` |
| 捕获 | `try { } catch (X e)` | `if err != nil` (没 try/catch) | `try: except X as e:` |
| 多异常 | `catch (X \| Y e)` | 多返回值 | `except (X, Y) as e:` |
| 资源释放 | `try-with-resources` | `defer` | `with` / `finally` |
