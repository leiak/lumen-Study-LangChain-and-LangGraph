"""
06_tempfile.py
===============
学完你能回答:
1. TemporaryDirectory 退出 with 会怎样?
2. NamedTemporaryFile delete=False 行为?
3. 怎么拿到临时目录里的文件路径?
4. 跨平台临时目录位置?
5. 项目里为什么用 tempfile 存 SqliteSaver?
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_tempdir() -> None:
    banner("1. TemporaryDirectory 自动清理")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        f = tmp_path / "demo.txt"
        f.write_text("hello", encoding="utf-8")
        print(f"  with 内: tmp = {tmp_path}")
        print(f"  with 内: 文件存在? {f.exists()}")
    # with 退出, 自动清理
    print(f"  with 外: 文件存在? {f.exists()}")          # False


def demo_named_tempfile() -> None:
    banner("2. NamedTemporaryFile")

    # delete=False: with 退出后文件保留
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("持久内容")
        path = f.name

    p = Path(path)
    print(f"  文件路径: {p}")
    print(f"  with 后存在? {p.exists()}")
    print(f"  内容: {p.read_text(encoding='utf-8')!r}")
    p.unlink()                                        # 手动清理

    # delete=True (默认): with 退出删
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=True) as f:
        path = f.name
    print(f"\n  delete=True, with 后存在? {Path(path).exists()}")  # False


def demo_mkdtemp_manual() -> None:
    banner("3. mkdtemp (不自动清理)")

    tmp = tempfile.mkdtemp(prefix="myapp_")
    print(f"  创建: {tmp}")
    Path(tmp, "data.txt").write_text("test")
    print(f"  数据文件存在? {Path(tmp, 'data.txt').exists()}")

    # 手动清理
    import shutil
    shutil.rmtree(tmp)
    print(f"  rmtree 后存在? {Path(tmp).exists()}")


def demo_langgraph_sqlite_pattern() -> None:
    banner("4. LangGraph SqliteSaver 临时 db (07_persistence.py:235)")

    # 模拟 SqliteSaver 的 with 模式
    class FakeSqliteSaver:
        def __init__(self, path):
            self.path = path
            self.connected = False

        @classmethod
        def from_conn_string(cls, path):
            return cls(path)

        def __enter__(self):
            print(f"  [sqlite] 连接 {self.path}")
            self.connected = True
            return self

        def __exit__(self, *exc):
            print(f"  [sqlite] 关闭")
            self.connected = False
            # 真实实现还会删文件
            return False

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "state.db")
        with FakeSqliteSaver.from_conn_string(db_path) as cp:
            print(f"  agent 用 checkpointer 创建, 连接状态={cp.connected}")

    print("  [退出两层 with] temp 目录 + state.db 都被清理")


def demo_gettempdir() -> None:
    banner("5. 临时目录的实际位置")

    print(f"  tempfile.gettempdir() = {tempfile.gettempdir()}")
    print(f"  系统临时目录 = {tempfile.gettempdir()}")
    # Linux: /tmp
    # macOS: /var/folders/xx/.../T/
    # Windows: C:\\Users\\<user>\\AppData\\Local\\Temp


if __name__ == "__main__":
    setup()
    demo_basic_tempdir()
    demo_named_tempfile()
    demo_mkdtemp_manual()
    demo_langgraph_sqlite_pattern()
    demo_gettempdir()
    print("\n[L4-06] 全部 demo 跑完。")
