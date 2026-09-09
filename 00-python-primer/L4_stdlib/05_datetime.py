"""
05_datetime.py
================
学完你能回答:
1. datetime.now() 带时区吗?
2. timedelta 怎么算时间差?
3. naive vs aware datetime 区别?
4. strftime / strptime 怎么用?
5. .total_seconds() 返回什么单位?
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_datetime() -> None:
    banner("1. 基本 datetime 构造与运算")

    now = datetime.now()
    print(f"  now           = {now}")
    print(f"  now.isoformat() = {now.isoformat()}")

    # 加 timedelta
    later = now + timedelta(hours=2, minutes=30)
    print(f"  now + 2h30m    = {later}")

    # 指定时间
    t = datetime(2026, 9, 6, 14, 30, 0)
    print(f"  指定时间       = {t}")

    # 差
    diff = later - now
    print(f"  later - now    = {diff} ({type(diff).__name__})")
    print(f"  total_seconds() = {diff.total_seconds()}")


def demo_timezone() -> None:
    banner("2. naive vs aware (时区)")

    naive = datetime.now()
    aware_utc = datetime.now(timezone.utc)
    aware_local = datetime.now().astimezone()         # 本地时区

    print(f"  naive      = {naive}")
    print(f"  naive tz   = {naive.tzinfo}")             # None
    print(f"  aware UTC  = {aware_utc}")
    print(f"  aware tz   = {aware_utc.tzinfo}")

    # naive - aware 会抛 TypeError
    try:
        naive - aware_utc
    except TypeError as e:
        print(f"  ❌ naive - aware -> TypeError: {e}")
        print("  解决: 都用 aware, 或显式设 tzinfo")


def demo_format_parse() -> None:
    banner("3. strftime 格式化 / strptime 解析")

    now = datetime.now()

    # 格式化
    print(f"  %Y-%m-%d      = {now.strftime('%Y-%m-%d')}")
    print(f"  %H:%M:%S      = {now.strftime('%H:%M:%S')}")
    print(f"  中文格式       = {now.strftime('%Y年%m月%d日 %H时%M分')}")

    # 解析
    parsed = datetime.strptime("2026-09-06 14:30", "%Y-%m-%d %H:%M")
    print(f"  strptime      = {parsed}")


def demo_langsmith_latency() -> None:
    banner("4. LangSmith 算 latency (12_langsmith_evaluation.py:280)")

    class FakeRun:
        start_time: datetime
        end_time: datetime

    run = FakeRun()
    run.start_time = datetime.now()
    sleep(0.05)                                        # 模拟耗时
    run.end_time = datetime.now()

    latency_ms = (run.end_time - run.start_time).total_seconds() * 1000
    print(f"  start_time    = {run.start_time.isoformat()}")
    print(f"  end_time      = {run.end_time.isoformat()}")
    print(f"  latency_ms    = {latency_ms:.2f}")


def demo_timedelta_math() -> None:
    banner("5. timedelta 数学")

    # 构造
    one_day = timedelta(days=1)
    one_hour = timedelta(hours=1)
    combined = timedelta(days=1, hours=2, minutes=3)

    print(f"  1 天 = {one_day.total_seconds()}s")
    print(f"  1 天 + 2 小时 + 3 分 = {combined}")

    # datetime + timedelta
    now = datetime.now()
    print(f"  now + 1 day = {now + one_day}")
    print(f"  now - 1 hour = {now - one_hour}")


if __name__ == "__main__":
    setup()
    demo_basic_datetime()
    demo_timezone()
    demo_format_parse()
    demo_langsmith_latency()
    demo_timedelta_math()
    print("\n[L4-05] 全部 demo 跑完。")
