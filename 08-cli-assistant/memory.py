"""memory.py — 长期偏好 Store 包装.

InMemoryStore namespace = ("user_prefs", user_id)
存储:
  - nickname: 用户昵称
  - city:     用户常驻城市
  - language: 用户偏好语言

启动时若 namespace 为空, 写入默认值; 这样 CLI 首次启动就有可读偏好.

复用 10_durable_execution.py demo 7 的 pattern (InMemoryStore + namespace).

生产替换: PostgresStore.from_conn_string(...) — 跨进程持久.
注意: InMemoryStore 进程重启就清空, CLI 演示需要提醒.
"""
from __future__ import annotations

import os
from langgraph.store.memory import InMemoryStore

_DEFAULT_PREFS = {
    "nickname": {"value": "friend"},
    "city": {"value": "上海"},
    "language": {"value": "中文"},
}


def build_store() -> tuple[InMemoryStore, tuple[str, str]]:
    """返回一个 (store, namespace) 元组."""
    user_id = os.getenv("CLI_USER_ID", "default")
    namespace = ("user_prefs", user_id)
    store = InMemoryStore()

    # 首次启动写默认偏好 (如果 namespace 为空)
    items = store.search(namespace)
    if not items:
        for key, val in _DEFAULT_PREFS.items():
            store.put(namespace, key, val)

    return store, namespace


def get_prefs(store: InMemoryStore, namespace: tuple[str, str]) -> dict[str, str]:
    """读全部偏好, 返回 {key: value} dict."""
    items = store.search(namespace)
    return {it.key: it.value.get("value", "") for it in items}


def set_pref(
    store: InMemoryStore, namespace: tuple[str, str], key: str, value: str
) -> None:
    """写一条偏好."""
    if key not in _DEFAULT_PREFS:
        # 允许扩展 key, 但要标 user_ 前缀
        if not key.startswith("user_"):
            raise ValueError(f"非内置 key {key!r} 必须以 'user_' 开头")
    store.put(namespace, key, {"value": value})


__all__ = ["build_store", "get_prefs", "set_pref"]