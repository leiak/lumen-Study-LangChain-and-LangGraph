# class 继承 (class inheritance)

## 是什么
Python 用 `class 子类(父类):` 声明继承,支持**多继承**,**方法重写**靠同名函数。

```python
class Animal:
    def speak(self) -> str:
        return "..."

class Dog(Animal):
    def speak(self) -> str:        # 重写
        return "Woof!"
```

## 为什么要用
- LangChain 的所有工具/parser/retriever 都基于 class 继承
- `@tool` 装饰普通函数转成 `BaseTool`,`BaseTool` 是 `Runnable` 子类
- 懂继承才能看懂 LangChain 的类型层级

## 语法骨架

```python
class Parent:
    def __init__(self, x):
        self.x = x

class Child(Parent):
    def __init__(self, x, y):
        super().__init__(x)        # 调用父类 __init__
        self.y = y

c = Child(1, 2)
print(c.x, c.y)                    # 1 2
print(isinstance(c, Parent))       # True
```

## 项目里的真实例子

```python
# 02_tools.py:108 — BaseTool 子类化
from langchain_core.tools import BaseTool
from pydantic import BaseModel

class _CalculatorInput(BaseModel):
    expression: str

class CalculatorTool(BaseTool):
    name: str = "calculator"
    description: str = "算术计算"
    args_schema: type[BaseModel] = _CalculatorInput

    def _run(self, expression: str) -> str:
        return str(eval(expression))    # 演示用, 生产禁止 eval
```

## 常见坑

1. **`super().__init__()` 必须显式调**, 不像 Java 自动调父构造
2. **多继承 MRO**: `class C(A, B):` 按 C3 线性化, 用 `ClassName.__mro__` 看顺序
3. **私有约定**: `_name` 是"别碰", `__name` 是名字改编 (name mangling)
4. **类变量 vs 实例变量**: `self.x = 1` 创建实例属性, 不影响类

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 继承 | `class Dog extends Animal` | 无继承 (用组合 + interface) | `class Dog(Animal):` |
| 调用父 | `super.method()` | 无 | `super().method()` |
| 多继承 | 不支持 (interface 多) | 不支持 | 支持 (C3 MRO) |
| 抽象 | `abstract class` | `interface` | `ABC` + `@abstractmethod` |
