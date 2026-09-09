# 工厂函数 + 闭包 (Factory + Closure)

## 是什么
**工厂函数**: 返回内部函数的函数,用于批量生成相似对象。
**闭包**: 内部函数捕获外部变量,即使外部函数已返回,内部函数仍能访问。

```python
def make_adder(n):
    def adder(x):
        return x + n                   # adder 闭包捕获 n
    return adder

add5 = make_adder(5)
print(add5(10))                         # 15
```

## 为什么要用
- 项目 `14_handoff.py:45` / `15_swarm.py:44` 用工厂函数批量造 handoff 工具
- 每个工具的 `target_agent` 不同, 不能写死
- 比 class 更轻量, 不需要 `__init__`

## 语法骨架

```python
def factory(config):
    def inner(...):
        # 用 config
        ...
    return inner

obj = factory(cfg)                       # obj 闭包持有 cfg
```

## 项目里的真实例子

```python
# 14_handoff.py:45
def make_handoff_tool(target_agent: str, description: str):
    tool_name = f"transfer_to_{target_agent}"

    @tool(tool_name)
    def handoff(reason: str) -> str:
        f"""{description}."""
        return f"[handoff -> {target_agent}] {reason}"

    handoff.name = tool_name
    return handoff

# 用法
refund_tool = make_handoff_tool("refund", "转给退款专员")
tech_tool = make_handoff_tool("tech", "转给技术支持")
```

## 常见坑

1. **循环闭包陷阱**: 在 for 循环里定义闭包, 全部捕获**同一个**循环变量
   - 解决: 用工厂参数包一层, 或 (Python 3 之后) 循环变量本身就是每次新值
2. **闭包不能修改外部 `int/str`**: 要 `nonlocal` 声明
3. **闭包持有引用**: 大对象闭包会阻止 GC, 必要时 `weakref`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 工厂方法 | `static createXxx()` | `func NewXxx()` | `def make_xxx():` |
| 闭包 | lambda + effectively final | `func() int { return n }` | `def inner(): return n` |
| 捕获 | Lambda 捕获 final 变量 | 闭包捕获 | 闭包捕获 (任意变量) |
