"""
02_tuple_unpacking.py
=====================
学完你能回答:
1. Python 函数怎么返回多个值?
2. (1,) 和 (1) 区别?
3. * 在解构里有什么用?
4. LangChain 工具返回 (content, artifact) 怎么接?
5. 解构数量不匹配会怎样?
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_unpack() -> None:
    banner("1. 基本解构")

    # 函数返回多值 (本质就是 tuple)
    def divide(a: int, b: int) -> tuple[int, int]:
        return a // b, a % b

    q, r = divide(10, 3)
    print(f"10 / 3 = 商 {q}, 余 {r}")     # 商 3, 余 1

    # 元组字面量解构
    x, y, z = (1, 2, 3)
    print(f"x={x}, y={y}, z={z}")


def demo_star_unpack() -> None:
    banner("2. * 收集剩余 (PEP 3132)")

    first, *middle, last = [1, 2, 3, 4, 5]
    print(f"first={first}, middle={middle}, last={last}")

    # 只要首尾
    head, *_, tail = "abcdef"
    print(f"head={head!r}, tail={tail!r}")

    # 函数参数收集
    def log(level: str, *messages: str) -> None:
        print(f"[{level}] " + " | ".join(messages))

    log("INFO", "启动", "加载模型", "开始服务")


def demo_tool_return_pattern() -> None:
    banner("3. LangChain 工具的 (content, artifact) 模式")

    # 模拟项目 02_tools.py:257 的 query_database 工具
    def fake_query_database(sql: str) -> tuple[str, list[dict]]:
        # content: 给 LLM 看的摘要
        # artifact: 真正的全量数据 (Pandas DataFrame / 大列表)
        rows = [{"id": i, "name": f"row_{i}"} for i in range(3)]
        summary = f"返回 {len(rows)} 行 (SQL: {sql})"
        return summary, rows

    content, rows = fake_query_database("SELECT * FROM t")
    print(f"content (给 LLM): {content!r}")
    print(f"rows (程序用):    {rows}")
    print(f"第一条 name = {rows[0]['name']}")


def demo_nested_unpack() -> None:
    banner("4. 嵌套解构")

    # 嵌套 tuple / list 都可以解
    data = ("alice", (30, "engineer"), ["python", "rust"])
    name, (age, job), skills = data
    print(f"{name}, {age}岁, {job}, 技能: {skills}")

    # 配合 for 循环解构非常常见
    pairs = [("a", 1), ("b", 2), ("c", 3)]
    for k, v in pairs:
        print(f"  {k} -> {v}")


if __name__ == "__main__":
    setup()
    demo_basic_unpack()
    demo_star_unpack()
    demo_tool_return_pattern()
    demo_nested_unpack()
    print("\n[L0-02] 全部 demo 跑完。")
