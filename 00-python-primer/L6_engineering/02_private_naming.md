# 私有命名 `_` 前缀约定

## 是什么
Python 没有真正的 `private`, 用**下划线前缀**做"软私有"约定:

| 形式 | 含义 |
|---|---|
| `_name` | "别从外部用" (PEP 8 约定) |
| `__name` | 名字改编 (name mangling), 实际存为 `_ClassName__name` |
| `__name__` | dunder, 系统用, 不要自己定义 |

## 为什么要用
- 项目所有 `_common.py` 用 `_ROOT`, `_is_real_key` 等私有函数
- 模块级单例用 `_cached_embeddings` (项目 `05_retrieval.py:176`)
- 告诉其他开发者"这是内部 API, 不保证稳定"

## 语法骨架

```python
# 1. 单下划线: 软私有 (PEP 8)
def _helper():
    pass

_internal_var = 42

# 2. 双下划线: 名字改编
class MyClass:
    def __init__(self):
        self.__secret = 42             # 实际存为 _MyClass__secret
    def get_secret(self):
        return self.__secret

c = MyClass()
# c.__secret                       # AttributeError
c._MyClass__secret                  # 42 (能访问但不推荐)

# 3. 双下划线前后 (dunder): 系统保留
__init__, __str__, __repr__ 等
```

## 项目里的真实例子

```python
# 所有 _common.py
_ROOT = Path(__file__).resolve().parent.parent
_PLACEHOLDER_VALUES = {"sk-", "", ...}
def _is_real_key(value: str | None) -> bool: ...

# 05_retrieval.py:176
_cached_embeddings = None
def get_safe_embeddings():
    global _cached_embeddings
    if _cached_embeddings is not None:
        return _cached_embeddings
    ...
```

## 常见坑

1. **单下划线外部能用**: `_name` 还是能直接 `from module import _name`
2. **双下划线不影响继承访问**: 子类可以用 `self._Parent__name`
3. **不要用双下划线当私有**: 反而难调试, 单下划线足够
4. **dunder 不要自己造**: `__my_method__` 容易撞系统保留名

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| private | `private` 关键字 | 小写字母开头 | `_` 前缀 (约定) |
| protected | `protected` | (无) | `_` 前缀 (约定) |
| 强制 | 编译时 | 编译时 | 仅约定 |
