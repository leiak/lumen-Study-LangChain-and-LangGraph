# dict 工具方法 (setdefault / Counter / 排序)

## 是什么
Python dict 的进阶用法, 项目里用来做**计数器**和**分组**。

```python
# 累加
counts[k] = counts.get(k, 0) + 1
counts[k] = counts.setdefault(k, 0) + 1

# 排序
sorted(d.items(), key=lambda kv: kv[1])        # 按 value 排
```

## 为什么要用
- 项目 `10_durable_execution.py:264` 用 dict.get 做计数器
- 项目 `13_supervisor.py:398` 用 setdefault 做分组
- `collections.Counter` 是更高阶的计数器

## 语法骨架

```python
# 1. 累加器 (3 种写法)
counts[k] = counts.get(k, 0) + 1
counts[k] = counts.setdefault(k, 0) + 1
counts = Counter(items)                          # Counter 一行搞定

# 2. 默认值
d.setdefault("key", []).append(x)                # 缺 key 自动建空 list

# 3. 排序
sorted(d.items())                                # 按 key
sorted(d.items(), key=lambda kv: kv[1])          # 按 value
sorted(d.items(), key=lambda kv: -kv[1])         # 降序

# 4. 反转 (key<->value)
inv = {v: k for k, v in d.items()}               # dict comprehension
```

## 项目里的真实例子

```python
# 10_durable_execution.py:264
counts: dict[str, int] = {}
counts[kind] = counts.get(kind, 0) + 1

# 11_langsmith_tracing.py 类似
```

## 常见坑

1. **`setdefault` 永远返回值**: 即使 key 存在也返回当前值
2. **`Counter` 不存在的 key 返回 0**: 而不是 KeyError
3. **dict 排序返回 list of tuples**: 不是 dict
4. **`{}.get(k, [])` 返回同一个空 list 引用**: 可变默认值陷阱 (但这场景没问题)

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 计数器 | `Map.merge(k, 1, Integer::sum)` | 手动 map | `Counter` / `setdefault` |
| 默认值 | `map.getOrDefault(k, d)` | `m[k]` | `d.get(k, d)` |
| 排序 | Stream API | 手动 sort | `sorted(d.items())` |
