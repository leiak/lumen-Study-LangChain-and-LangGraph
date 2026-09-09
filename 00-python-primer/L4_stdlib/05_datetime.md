# `datetime` / `timedelta`

## 是什么
- `datetime.now()`: 当前时间 (带时区信息用 `datetime.now(tz=...)`)
- `timedelta(days=, hours=, ...)`: 时间差
- `datetime` - `datetime` = `timedelta`

```python
from datetime import datetime, timedelta

t0 = datetime.now()
# ... 干点啥 ...
elapsed: timedelta = datetime.now() - t0
print(elapsed.total_seconds())
```

## 为什么要用
- 项目 `12_langsmith_evaluation.py:280` 用 `datetime.now()` 和 `timedelta` 算 latency
- 日志 / 监控几乎必用
- LangSmith API 也用 datetime

## 语法骨架

```python
from datetime import datetime, timedelta, timezone

now = datetime.now()                              # 本地时间
now_utc = datetime.now(timezone.utc)              # UTC 带 tz
t = datetime(2026, 9, 6, 14, 30, 0)               # 指定时间

# 加减
later = now + timedelta(hours=2, minutes=30)
diff = later - now                                # timedelta

# 格式化
print(now.strftime("%Y-%m-%d %H:%M:%S"))
print(now.isoformat())                            # 2026-09-06T14:30:00

# 解析
parsed = datetime.strptime("2026-09-06", "%Y-%m-%d")
```

## 项目里的真实例子

```python
# 12_langsmith_evaluation.py:280
from datetime import datetime, timedelta
run.start_time = datetime.now()
run.end_time = run.start_time + timedelta(seconds=2)
latency_ms = (run.end_time - run.start_time).total_seconds() * 1000
```

## 常见坑

1. **naive vs aware**: `datetime.now()` 没时区, 跨时区运算会错
2. **时区**: 用 `datetime.now(timezone.utc)` 而不是 naive
3. **`total_seconds()`**: timedelta 转 float 秒数
4. **格式化**: `%Y` 年, `%m` 月, `%d` 日, `%H` 时, `%M` 分, `%S` 秒
5. **`fromtimestamp` 在不同 OS 行为不同**: 慎用

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 当前时间 | `LocalDateTime.now()` | `time.Now()` | `datetime.now()` |
| 时区 | `ZoneId.systemDefault()` | `time.UTC` | `timezone.utc` |
| 时间差 | `Duration.between(a, b)` | `t2.Sub(t1)` | `b - a` |
| 格式化 | `DateTimeFormatter` | `t.Format(...)` | `strftime` |
