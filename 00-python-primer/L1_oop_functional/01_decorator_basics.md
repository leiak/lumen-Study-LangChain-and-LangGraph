# 装饰器基础 (Decorator + @property)

## 是什么
装饰器是一个**接收函数返回新函数**的可调用对象,用 `@` 语法糖应用。

```python
def my_decorator(func):
    def wrapper(*args, **kwargs):
        print("调用前")
        result = func(*args, **kwargs)
        print("调用后")
        return result
    return wrapper

@my_decorator
def greet(name):
    return f"hi {name}"
```

## 为什么要用
- LangChain 大量装饰器: `@tool`, `@traceable`, `@wrap_model_call`
- 横向切面 (日志 / 重试 / 计时 / 权限) 不污染业务代码
- 装饰器工厂 (带参数的装饰器) 是进阶核心

## 语法骨架

```python
# 1. 函数装饰器
@decorator
def f(): ...

# 2. 带参数的装饰器 (装饰器工厂)
@decorator(arg=1)
def f(): ...

# 3. 类装饰器
@DecoratorClass
def f(): ...

# 4. @property 把方法变属性
class A:
    @property
    def x(self): return self._x

# 5. 多个装饰器从下往上应用
@a
@b
@c
def f(): ...    # 等价 f = a(b(c(f)))
```

## 项目里的真实例子

```python
# 11_langsmith_tracing.py:112 — LangSmith 自动 trace
from langsmith import traceable

@traceable(name="user_login")
def user_login(user_id: str, password: str) -> dict:
    ...

# 02_tools.py — @tool 把函数变工具
@tool
def search(query: str) -> str:
    """搜索关键词"""
    return ...
```

## 常见坑

1. **wrapper 忘了 `*args, **kwargs`**: 导致参数透传失败
2. **忘了 `functools.wraps`**: 被装饰函数的 `__name__` / `__doc__` 丢了
3. **装饰器顺序**: `@a @b def f` → `f = a(b(f))`, 顺序敏感
4. **类实例方法加 @property**: 第一个参数是 self, 不是 self 参数缺

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| AOP | Spring `@Aspect` | 中间件 / 函数包装 | `@decorator` |
| 注解 | `@Override` (纯元数据) | struct tag (元数据) | `@decorator` (真执行) |
| 横切 | 字节码增强 | 手动包装 | 装饰器 / 上下文管理器 |
