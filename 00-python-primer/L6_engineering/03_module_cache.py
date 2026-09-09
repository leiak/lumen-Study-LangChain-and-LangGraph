"""
03_module_cache.py
====================
学完你能回答:
1. 模块级 _cached_xxx 怎么写?
2. global 关键字什么时候必须?
3. 多线程下缓存安全吗?
4. 怎么清缓存做测试?
5. 项目里哪些地方用了这种模式?
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


# === 模块级缓存 (项目惯例) ===
_cached_llm = None
_cached_embeddings = None


def demo_basic_module_cache() -> None:
    banner("1. 模块级缓存")

    def get_thing():
        global _cached_llm
        if _cached_llm is None:
            print("  [init] 首次调用, 初始化...")
            time.sleep(0.05)
            _cached_llm = {"model": "MiniMax-M3", "ready": True}
        return _cached_llm

    # 第一次: 慢
    t0 = time.perf_counter()
    a = get_thing()
    t1 = time.perf_counter()

    # 第二次: 快
    b = get_thing()
    t2 = time.perf_counter()

    print(f"  第一次: {(t1-t0)*1000:.2f}ms, 返回 {a}")
    print(f"  第二次: {(t2-t1)*1000:.2f}ms, 返回 {b}")
    print(f"  a is b = {a is b} (同一对象)")


def demo_safe_embeddings_pattern() -> None:
    banner("2. 项目 safe_embeddings 模式 (05_retrieval.py:176)")

    global _cached_embeddings
    _cached_embeddings = None                                    # 重置

    def get_safe_embeddings():
        global _cached_embeddings
        if _cached_embeddings is not None:
            print("  [cache] 命中, 直接返回")
            return _cached_embeddings

        print("  [probe] 探测真实 embedding...")
        try:
            # 假装 M3 没有 embedding 端点
            raise ValueError("No embedding data received")
        except Exception as e:
            print(f"  [fallback] 探测失败: {e}")
            print("  [fallback] 用 DeterministicFakeEmbedding(size=384)")
            _cached_embeddings = {"type": "fake", "size": 384}
            return _cached_embeddings

    # 第一次探测 + fallback
    e1 = get_safe_embeddings()
    # 第二次直接缓存
    e2 = get_safe_embeddings()
    print(f"  e1 is e2 = {e1 is e2}")


def demo_lru_cache_alternative() -> None:
    banner("3. 用 functools.lru_cache 替代 (单参数场景)")

    from functools import lru_cache

    @lru_cache(maxsize=128)
    def expensive_compute(x: int) -> int:
        """自动缓存: 同一 x 多次调只算一次"""
        time.sleep(0.05)
        return x * x

    t0 = time.perf_counter()
    print(f"  expensive_compute(5) = {expensive_compute(5)}")
    print(f"  第一次: {(time.perf_counter()-t0)*1000:.2f}ms")

    t0 = time.perf_counter()
    print(f"  expensive_compute(5) = {expensive_compute(5)} (命中缓存)")
    print(f"  第二次: {(time.perf_counter()-t0)*1000:.2f}ms")

    # 查看缓存信息
    print(f"  cache_info = {expensive_compute.cache_info()}")

    # 清缓存
    expensive_compute.cache_clear()
    print(f"  清后: {expensive_compute.cache_info()}")


def demo_thread_safety_warning() -> None:
    banner("4. 多线程下不安全的反例")

    import threading

    # 反面: 不用锁可能多次 init
    global_counter = {"count": 0}
    _unsafe_cache = None
    _lock = threading.Lock()

    def unsafe_get():
        global _unsafe_cache
        if _unsafe_cache is None:
            time.sleep(0.01)
            global_counter["count"] += 1
            _unsafe_cache = f"init #{global_counter['count']}"
        return _unsafe_cache

    def safe_get():
        global _unsafe_cache
        with _lock:
            if _unsafe_cache is None:
                time.sleep(0.01)
                global_counter["count"] += 1
                _unsafe_cache = f"init #{global_counter['count']}"
        return _unsafe_cache

    # 模拟 5 个线程同时调 (安全版本)
    _unsafe_cache = None
    global_counter["count"] = 0
    threads = [threading.Thread(target=safe_get) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"  带锁: init 次数 = {global_counter['count']} (期望 1)")
    print(f"  最终 cache = {_unsafe_cache}")


def demo_when_to_use() -> None:
    banner("5. 什么时候用模块缓存")

    print("  ✅ 适合:")
    print("    - LLM client (init 昂贵, 反复用)")
    print("    - Embedding model (探测 + 缓存 fallback)")
    print("    - DB connection pool")
    print("    - 配置解析结果 (parse 一次反复用)")
    print()
    print("  ❌ 不适合:")
    print("    - 一次性数据 (请求参数)")
    print("    - 需要每次重新计算 (随机数 / 当前时间)")
    print()
    print("  测试时: 直接赋值 None 清缓存")
    print("    import mymodule; mymodule._cached_xxx = None")


if __name__ == "__main__":
    setup()
    demo_basic_module_cache()
    demo_safe_embeddings_pattern()
    demo_lru_cache_alternative()
    demo_thread_safety_warning()
    demo_when_to_use()
    print("\n[L6-03] 全部 demo 跑完。")
