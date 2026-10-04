"""production.py — 共享 production patterns: cache + async batch + observability.

教学 RAG 生产模式:
  - RetrievalCache: in-memory LRU cache (query → hits)
  - time_operation: context manager for latency measurement
  - gather_with_metrics: async.gather + 收集各 task latency
  - ObservabilityMetrics: 累计 cache hit/miss + 延迟 + cost

💡 设计要点:
  - 缓存 key 用 query 字符串 (标准化: strip + lowercase), value 是 hits + 时间戳
  - LRU 用 OrderedDict, 上限 1000 entries
  - time_operation 用 perf_counter
  - async.gather 失败不 abort, 部分失败用 return_exceptions=True
  - 纯 utility (无 LLM 依赖) — 易 unit test
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Awaitable, TypeVar


T = TypeVar("T")


# ============================================================
# ObservabilityMetrics — 累计 cache hit/miss + latency
# ============================================================
@dataclass
class ObservabilityMetrics:
    """累计 metrics.

    Attributes:
        total_queries: 总 query 数 (hit + miss)
        cache_hits: cache 命中数
        cache_misses: cache 未命中数
        latencies_seconds: 每步 wall-clock 耗时 (秒) — 可 append 任何 step
    """
    total_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    latencies_seconds: list[float] = field(default_factory=list)

    @property
    def cache_hit_rate(self) -> float:
        """cache 命中率 = hits / (hits + misses). 无查询时返回 0.0."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    @property
    def avg_latency(self) -> float:
        """平均延迟 (秒). 无样本时返回 0.0."""
        return (
            sum(self.latencies_seconds) / len(self.latencies_seconds)
            if self.latencies_seconds
            else 0.0
        )

    @property
    def p95_latency(self) -> float:
        """p95 延迟 (秒) — sort 后 idx = int(n * 0.95).

        💡 简化实现: 每次 summary 都 sort. 生产用 streaming estimator (t-digest).
        """
        if not self.latencies_seconds:
            return 0.0
        sorted_lat = sorted(self.latencies_seconds)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def summary(self) -> str:
        """一行打印所有关键数字."""
        return (
            f"queries={self.total_queries}, cache_hit={self.cache_hit_rate:.1%}, "
            f"avg_lat={self.avg_latency:.3f}s, p95={self.p95_latency:.3f}s"
        )


# ============================================================
# RetrievalCache — In-memory LRU (OrderedDict)
# ============================================================
class RetrievalCache:
    """In-memory LRU cache for retrieval results.

    Args:
        max_size: 上限 entry 数 (default 1000), 满了用 LRU 淘汰

    💡 Python 3.7+ dict 保插入序, OrderedDict.move_to_end / popitem
       配合实现标准 LRU. key 用 query 字符串 (strip + lowercase 标准化).
    """

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, list] = OrderedDict()
        self._max_size = max_size

    @staticmethod
    def _key(query: str) -> str:
        """标准化 cache key: 去首尾空白 + lowercase."""
        return query.strip().lower()

    def get(self, query: str) -> list | None:
        """Get cached hits. Returns None on miss. LRU update on hit."""
        key = self._key(query)
        if key not in self._cache:
            return None
        # 命中 → move_to_end (标记最近用)
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, query: str, hits: list) -> None:
        """Store hits. Evict LRU if full."""
        key = self._key(query)
        if key in self._cache:
            # 已存在 → 先 move_to_end, 再赋值 (覆盖 value)
            self._cache.move_to_end(key)
        self._cache[key] = hits
        # 满了 → 淘汰最旧的 (last=False → pop first item)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        """清空缓存."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


# ============================================================
# time_operation — context manager 测耗时
# ============================================================
@contextmanager
def time_operation(metrics: ObservabilityMetrics | None = None):
    """Context manager: 测量 wall-clock time, 可选 append 到 metrics.

    Args:
        metrics: optional, 非 None 时把耗时 append 到 metrics.latencies_seconds

    Usage:
        with time_operation(metrics):
            do_work()
    """
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    if metrics is not None:
        metrics.latencies_seconds.append(elapsed)


# ============================================================
# gather_with_metrics — async.gather + 各 task latency 收集
# ============================================================
async def gather_with_metrics(
    tasks: list[Awaitable[T]],
    metrics: ObservabilityMetrics | None = None,
) -> list[T | Exception]:
    """async.gather + 收集各 task latency.

    Args:
        tasks: list of awaitables (e.g. coroutine objects)
        metrics: optional, 非 None 时把每个 task 的耗时 append 到 metrics

    Returns:
        list of results or exceptions (return_exceptions=True, 部分失败不 abort)

    💡 设计选择:
      - return_exceptions=True 让单个 task 失败不阻塞其它 task
      - 每个 task 单独计时 (perf_counter), 不算 gather 总耗时
      - 空 list 短路返回 []
    """
    if not tasks:
        return []

    async def timed(coro: Awaitable[T]) -> T | Exception:
        start = time.perf_counter()
        try:
            result = await coro
            if metrics is not None:
                metrics.latencies_seconds.append(time.perf_counter() - start)
            return result
        except Exception as e:
            # 部分失败 — 仍然记录耗时, 但 value 是 exception 对象
            if metrics is not None:
                metrics.latencies_seconds.append(time.perf_counter() - start)
            return e

    return await asyncio.gather(*[timed(t) for t in tasks], return_exceptions=True)


__all__ = [
    "ObservabilityMetrics",
    "RetrievalCache",
    "time_operation",
    "gather_with_metrics",
]