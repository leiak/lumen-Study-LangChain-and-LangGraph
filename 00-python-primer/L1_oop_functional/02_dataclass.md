# `@dataclass` (PEP 557)

## 是什么
用 `@dataclass` 装饰类,自动生成 `__init__` / `__repr__` / `__eq__`,省去样板代码。

```python
from dataclasses import dataclass

@dataclass
class Point:
    x: float
    y: float

p = Point(1.0, 2.0)
print(p)                # Point(x=1.0, y=2.0)
print(p == Point(1, 2)) # True (自动 __eq__)
```

## 为什么要用
- 项目 `12_langsmith_evaluation.py:413` 用它装"评测汇总"
- 比手写 `__init__` / `__repr__` 简洁 10 倍
- Pydantic BaseModel 是更强的 dataclass (校验 + 序列化), 但 dataclass 更轻

## 语法骨架

```python
from dataclasses import dataclass, field

@dataclass
class User:
    name: str
    age: int = 0                        # 默认值
    tags: list[str] = field(default_factory=list)   # 可变默认值必须用 factory

    def __str__(self):                  # 可以再写 dunder 覆盖
        return f"User({self.name})"
```

## 项目里的真实例子

```python
# 12_langsmith_evaluation.py:413
from dataclasses import dataclass

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

1. **可变默认值不要直接写**: `tags: list = []` 会共享同一个 list → 必须 `field(default_factory=list)`
2. **`frozen=True`**: 变 frozen dataclass, 试图赋值会 FrozenInstanceError
3. **`order=True`**: 自动生成 `__lt__` 等, 但字段都要可比
4. **继承时**: 父类字段顺序决定子类 `__init__` 参数顺序

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| POJO | `class + getter/setter` | `struct` | `@dataclass` |
| 自动构造 | Lombok `@Data` | 字面量 `T{x: 1}` | `@dataclass` |
| 不可变 | `final` 字段 | 无 setter | `@dataclass(frozen=True)` |
| 相等 | 手写 `equals` | 结构相等 (map/struct) | `@dataclass(eq=True)` |
