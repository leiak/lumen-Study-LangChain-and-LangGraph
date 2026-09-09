# `from __future__ import annotations` (PEP 563)

## 是什么
把所有类型注解变成**字符串**, 延迟到运行时才求值 (用 `typing.get_type_hints()` 才解析)。

```python
from __future__ import annotations
from typing import List                       # 不需要 import List 给注解

def f(x: list[int]) -> dict[str, int]:        # 注解都是字符串, 不立刻 import 解析
    ...
```

## 为什么要用
- **前向引用**: 类方法返回自己的类型, 不需要引号 `'Self'`
- **性能**: 模块加载时不解析注解, 启动更快
- **避免循环导入**: 类型在另一个模块, import 会循环
- 项目所有 23 个 .py 文件顶部都有这一行

## 语法骨架

```python
from __future__ import annotations

class Node:
    def make(self) -> Node:                   # 直接写 Node, 不用 'Node'
        return Node()

def f() -> "SomeForwardRef":                 # 字符串也可以, 但有了 future 不用
    ...
```

## 项目里的真实例子

```python
# 项目每个文件顶部
from __future__ import annotations

# 02_tools.py
def get_safe_embeddings() -> Embeddings | None: ...
#    ↑ Embeddings 在文件后部 import, 没 future 会 NameError
```

## 常见坑

1. **`get_type_hints()` 才解析**: 运行时访问 `f.__annotations__` 是字符串 dict
2. **dataclass / Pydantic 的字段**: 默认还要求类型 (dataclass 默认会 eval, Pydantic 不会)
3. **PEP 649 (Python 3.13 默认开启)**: future annotations 在 3.13+ 默认就是行为
4. **3.10 之前用 list[int] 不行**: future annotations 解决了, 但运行时 inspect 可能拿到字符串

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 类型注解时机 | 编译时必须 | 编译时必须 | 运行时 (默认) / 延迟 (future) |
| 前向引用 | 直接写 | 直接写 | 默认要引号, future 后直接 |
