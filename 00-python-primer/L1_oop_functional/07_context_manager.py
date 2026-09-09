"""
07_context_manager.py
=====================
学完你能回答:
1. with 语句为什么能自动 close?
2. __enter__ 和 __exit__ 什么时候调?
3. @contextmanager 怎么写?
4. with open() 为何不会泄漏文件句柄?
5. 项目里 LangGraph checkpointer 怎么用 with?
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_builtin_with() -> None:
    banner("1. 内置 with: open / tempfile")

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        f = tmp_path / "demo.txt"
        f.write_text("hello OPC", encoding="utf-8")
        print(f"写入: {f}, 存在 = {f.exists()}")
    # 退出 with, 临时目录自动删除
    print(f"退出 with 后, 目录还存在吗? {tmp_path.exists()}")


def demo_class_based_cm() -> None:
    banner("2. 自己写 context manager (类实现)")

    class Timer:
        def __init__(self, label: str):
            self.label = label
            self.elapsed_ms: float = 0.0
            import time
            self._t0 = 0.0

        def __enter__(self):
            import time
            self._t0 = time.perf_counter()
            print(f"  [Timer {self.label}] start")
            return self                     # with ... as t 接到这个

        def __exit__(self, exc_type, exc_val, exc_tb):
            import time
            self.elapsed_ms = (time.perf_counter() - self._t0) * 1000
            print(f"  [Timer {self.label}] end, 耗时 {self.elapsed_ms:.2f}ms")
            return False                   # 不吞异常

    with Timer("demo") as t:
        total = sum(range(100_000))
    print(f"  with 外访问 elapsed = {t.elapsed_ms:.2f}ms")


def demo_contextmanager_decorator() -> None:
    banner("3. @contextmanager 装饰器写法")

    @contextmanager
    def db_session(url: str):
        """模拟一个数据库 session: 进入连接, 退出提交/回滚"""
        print(f"  [db] 连接 {url}")
        session = {"url": url, "tx": []}
        try:
            yield session                  # with ... as s 接这里
            print("  [db] commit")
        except Exception as e:
            print(f"  [db] rollback 因为 {e}")
            raise

    with db_session("sqlite:///test.db") as s:
        s["tx"].append("INSERT ...")
        s["tx"].append("UPDATE ...")
        print(f"  tx = {s['tx']}")


def demo_multiple_with() -> None:
    banner("4. 多个 with + suppress")

    from contextlib import suppress

    # 多个 with (Python 3.10+ 还能用括号分组)
    with (
        suppress(FileNotFoundError),       # 抑制特定异常
    ):
        Path("/non/existent").read_text()
    print("  FileNotFoundError 被 suppress 吞掉了")

    # suppress 等价
    try:
        Path("/non/existent").read_text()
    except FileNotFoundError:
        pass


def demo_langgraph_pattern() -> None:
    banner("5. LangGraph checkpointer 模式 (07_persistence.py:239)")

    # 模拟 SqliteSaver 的 with 模式
    class FakeCheckpointer:
        def __init__(self, path):
            self.path = path
            self.connected = False

        def __enter__(self):
            print(f"  [checkpointer] 连接 {self.path}")
            self.connected = True
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            print(f"  [checkpointer] 断开 {self.path}")
            self.connected = False
            return False

    with FakeCheckpointer("state.db") as cp:
        print(f"  agent 创建中, checkpointer 连接状态 = {cp.connected}")
    print(f"  with 外, 连接状态 = {cp.connected}")


if __name__ == "__main__":
    setup()
    demo_builtin_with()
    demo_class_based_cm()
    demo_contextmanager_decorator()
    demo_multiple_with()
    demo_langgraph_pattern()
    print("\n[L1-07] 全部 demo 跑完。")
