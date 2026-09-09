"""
02_pathlib.py
==============
学完你能回答:
1. Path vs os.path 区别?
2. Path("a") / "b" 怎么拼接?
3. .resolve() 干什么?
4. read_text / write_text 自带编码吗?
5. glob vs rglob 区别?
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_path() -> None:
    banner("1. 基本 Path 操作")

    p = Path("foo/bar/baz.txt")
    print(f"  p = {p}")
    print(f"  p.name   = {p.name}")                    # baz.txt
    print(f"  p.stem   = {p.stem}")                    # baz
    print(f"  p.suffix = {p.suffix}")                  # .txt
    print(f"  p.parent = {p.parent}")                  # foo/bar
    print(f"  p.parts  = {p.parts}")                   # ('foo', 'bar', 'baz.txt')


def demo_concat_and_resolve() -> None:
    banner("2. 拼接 + resolve")

    # / 运算符拼接 (跨平台)
    p1 = Path("base") / "sub" / "file.txt"
    print(f"  拼接: {p1}")

    # __file__ 模式: 当前 .py 文件所在
    this_file = Path(__file__)
    print(f"  __file__              = {this_file}")
    print(f"  .resolve()            = {this_file.resolve()}")
    print(f"  .parent               = {this_file.parent}")
    print(f"  .parent.parent        = {this_file.parent.parent}")

    # 项目 ROOT 模式
    primer_root = Path(__file__).resolve().parent.parent
    print(f"  项目 ROOT = {primer_root.name}")


def demo_io_methods() -> None:
    banner("3. IO: read_text / write_text / stat")

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "test.txt"

        f.write_text("Hello OPC\nLine 2\n中文也行", encoding="utf-8")
        print(f"  写入: {f.name}, 存在={f.exists()}")
        print(f"  大小: {f.stat().st_size} bytes")

        content = f.read_text(encoding="utf-8")
        print(f"  内容: {content!r}")

        # stat 拿到文件元信息
        print(f"  st_mtime: {f.stat().st_mtime:.0f} (epoch)")


def demo_glob() -> None:
    banner("4. glob / rglob")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # 造几个文件
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.md").write_text("")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "d.py").write_text("")

        # 单层 glob
        print("  glob('*.py'):")
        for f in tmp_path.glob("*.py"):
            print(f"    {f.name}")

        # 递归 rglob
        print("  rglob('*.py'):")
        for f in tmp_path.rglob("*.py"):
            print(f"    {f.relative_to(tmp_path)}")


def demo_project_dotenv_pattern() -> None:
    banner("5. 项目 _common.py 的 .env 加载 (01_models.py:15)")

    # 模拟项目: 从 .py 文件位置反推项目根
    primer_root = Path(__file__).resolve().parent.parent
    env_file = primer_root / ".env"
    env_example = primer_root / ".env.example"

    print(f"  项目根: {primer_root}")
    print(f"  .env 存在?       {env_file.exists()}")
    print(f"  .env.example 存在? {env_example.exists()}")

    # 项目惯例
    print("\n  项目惯例:")
    print("    _ROOT = Path(__file__).resolve().parent.parent")
    print("    load_dotenv(_ROOT / '.env', override=False)")
    print("    load_dotenv(_ROOT / '.env.example', override=False)")


if __name__ == "__main__":
    setup()
    demo_basic_path()
    demo_concat_and_resolve()
    demo_io_methods()
    demo_glob()
    demo_project_dotenv_pattern()
    print("\n[L4-02] 全部 demo 跑完。")
