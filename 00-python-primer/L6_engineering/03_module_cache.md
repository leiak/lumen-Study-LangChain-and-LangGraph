# 模块级 global 缓存 (单例模式)

## 是什么
在模块顶层声明 `_cached_xxx = None`, 函数内 `global _cached_xxx` 修改, 实现**懒加载 + 缓存**。

```python
_cached_llm = None

def get_llm():
    global _cached_llm
    if _cached_llm is None:
        _cached_llm = init_chat_model(...)
    return _cached_llm
```

## 为什么要用
- 项目 `05_retrieval.py:176` `_cached_embeddings` 缓存探测结果
- 项目所有 `_common.py` 都有 `_is_real_key()` 等私有模块状态
- 避免重复初始化 LLM / embedding (昂贵)

## 语法骨架

```python
# 模块级
_cached = None

def get_thing():
    global _cached                          # 声明要修改
    if _cached is None:
        _cached = expensive_init()
    return _cached
```

## 项目里的真实例子

```python
# 05_retrieval.py:176
_cached_embeddings = None

def get_safe_embeddings() -> Embeddings:
    global _cached_embeddings
    if _cached_embeddings is not None:
        return _cached_embeddings
    candidate = get_embeddings()
    try:
        candidate.embed_query("test")
        _cached_embeddings = candidate
        return candidate
    except Exception:
        from langchain_community.embeddings import DeterministicFakeEmbedding
        _cached_embeddings = DeterministicFakeEmbedding(size=384)
        return _cached_embeddings
```

## 常见坑

1. **`global` 只在函数内需要**: 模块顶层直接赋值不需要 global
2. **可变类型不要 cache 用 is None**: `_cache = {}; if _cache is None:` 错 (空 dict 也是 falsy 但 is not None)
3. **线程不安全**: 多线程同时首次调用可能建多个, 必要时加 lock
4. **测试时难 reset**: `_cached = None` 才能清

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 单例 | `Singleton` class | `sync.Once` | 模块级变量 + global |
| 缓存 | `ConcurrentHashMap` | `sync.Map` | dict / lru_cache |
| 懒加载 | holder pattern | `sync.OnceValue` (1.21+) | global + None check |
