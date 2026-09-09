# `try/except` 容错循环 (demo 入口模式)

## 是什么
项目里所有 demo 文件的入口都用同一个模式:

```python
demos = [
    ("demo_1", demo_1),
    ("demo_2", demo_2),
    ...
]
for name, fn in demos:
    try:
        fn()
    except Exception as e:
        print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")
```

## 为什么要用
- M3 模型经常拒答 / 解析失败, 一个 demo 崩不能影响其他
- LLM 调用本身不稳定, 必须容错
- 用户体验: 看到失败信息继续看下一个 demo, 而不是整个脚本崩

## 语法骨架

```python
for name, fn in demos:
    try:
        fn()
        print(f"  [{name}] ✓")
    except Exception as e:
        # 截短错误信息, 不刷屏
        msg = str(e)[:120]
        print(f"  [{name}] ✗ {type(e).__name__}: {msg}")
```

## 项目里的真实例子

```python
# 所有 demo 入口 (04_multi-agent/14_handoff.py:601)
for name, fn in [
    ("demo_basic", demo_basic),
    ("demo_router", demo_router),
    ("demo_supervisor", demo_supervisor),
]:
    try:
        fn()
    except Exception as e:
        print(f"[{name}] 跳过: {type(e).__name__}: {str(e)[:120]}")
```

## 常见坑

1. **吞掉所有异常风险**: 用 `Exception` 而不是 `BaseException`, 否则连 KeyboardInterrupt 都吞
2. **错误信息截短**: `str(e)[:120]` 防止一行的 stacktrace 刷屏
3. **不要静默**: 至少 print, 否则用户不知道为什么 demo 跳过
4. **累积错误**: 想全跑完看汇总, 把异常存起来后面报告

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 多步骤容错 | try-catch 每个步骤 | err 检查 + log | try/except 每个 demo |
| 错误聚合 | collector | errgroup | list of (name, exception) |
