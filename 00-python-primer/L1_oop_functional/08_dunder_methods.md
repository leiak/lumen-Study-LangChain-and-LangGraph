# dunder 方法 (`__str__` / `__repr__` / `__init__` / `__eq__`)

## 是什么
**dunder** = double underscore, 前后都带 `__` 的方法, 又叫**魔术方法** / **特殊方法**。
Python 在特定操作时自动调用它们。

| dunder | 何时调 | 项目例子 |
|---|---|---|
| `__init__` | `obj = MyClass(...)` | 几乎所有类 |
| `__str__` | `str(obj) / print(obj)` | `EvalSummary.__str__` |
| `__repr__` | `obj` 在 REPL / `obj!r` | 自动生成 |
| `__eq__` / `__lt__` | `obj == other` | dataclass 自动 |
| `__len__` | `len(obj)` | list / dict 默认 |
| `__iter__` | `for x in obj` | list 默认 |
| `__enter__` / `__exit__` | `with obj:` | context manager |
| `__getattr__` | `obj.attr` 找不到 | 反射 |
| `__call__` | `obj()` | 函数对象 |

## 为什么要用
- 自定义打印 (`__str__`) 让 debug 输出友好
- `__repr__` 应当"无歧义可重建", 即 `eval(repr(obj)) == obj`
- 项目里 dataclass 自动生成大部分, 但 `__str__` 通常手写

## 项目里的真实例子

```python
# 12_langsmith_evaluation.py:413
@dataclass
class EvalSummary:
    n_examples: int
    avg_scores: dict[str, float]
    pass_rate: float

    def __str__(self) -> str:
        lines = [f"  examples: {self.n_examples}", ...]
        return "\n".join(lines)
```

## 常见坑

1. **`__repr__` 应当明确**: 失败也应该返回 `'ClassName(field=value)'`
2. **重写 `__eq__` 必须重写 `__hash__`**: 不然 dict/set 行为错乱
3. **`__str__` 返回用户友好**, `__repr__` 返回开发者友好
4. **dunder 不要自己调**: 写 `obj.__str__()` 而不是 `str(obj)` 是反模式

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| toString | `toString()` | `Stringer` 接口 | `__str__` / `__repr__` |
| equals | `equals()` (要 hashCode) | `==` / reflect.DeepEqual | `__eq__` (+ `__hash__`) |
| 调用 | 接口隐式 | 接口隐式 | dunder 隐式 |
