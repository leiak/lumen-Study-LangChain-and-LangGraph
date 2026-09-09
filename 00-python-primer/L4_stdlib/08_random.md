# `random` 模块

## 是什么
- `random.random()`: [0.0, 1.0) 的 float
- `random.randint(a, b)`: [a, b] 的 int (含两端)
- `random.choice(seq)`: 从序列随机选一个
- `random.sample(population, k)`: 不重复抽 k 个
- `random.shuffle(list)`: 原地洗牌

## 为什么要用
- 项目 `11_langsmith_tracing.py:388` 用 `random.random() < 0.1` 做 10% 采样上报
- 测试数据生成 / 随机选择
- A/B 实验分组

## 语法骨架

```python
import random

v = random.random()                    # [0, 1)
n = random.randint(1, 100)             # [1, 100]
x = random.choice(["a", "b", "c"])     # 选一个
sample = random.sample(range(100), 5)  # 抽 5 个不重复
random.shuffle(my_list)                # 原地洗牌

# 设置种子 (可复现)
random.seed(42)
```

## 项目里的真实例子

```python
# 11_langsmith_tracing.py:388 — 10% 概率上报 trace
if random.random() < 0.1:
    high_volume_call(i)
    sent += 1
```

## 常见坑

1. **不加密**: `random` 是 Mersenne Twister, 不能用于安全场景 (用 `secrets`)
2. **`randint` 含两端**, `randrange` 不含右端
3. **`shuffle` 原地改 list, 返回 None**: 别写 `random.shuffle(x)` 然后用 x
4. **种子**: 测试时设 seed 保证可复现

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 随机 | `Math.random()` | `rand.Float64()` | `random.random()` |
| 整数 | `ThreadLocalRandom.current().nextInt(a, b)` | `rand.Intn(n)` | `random.randint(a, b)` |
| 种子 | `new Random(seed)` | `rand.Seed(s)` | `random.seed(s)` |
| 安全 | `SecureRandom` | `crypto/rand` | `secrets` |
