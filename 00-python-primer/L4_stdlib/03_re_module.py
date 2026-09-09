"""
03_re_module.py
================
学完你能回答:
1. re.compile 和 re.search 区别?
2. .* 和 .*? 区别?
3. re.DOTALL 干什么?
4. search 找不到返回什么?
5. raw string r"..." 为什么用?
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import banner, setup


def demo_basic_match() -> None:
    banner("1. 基本 match / search / findall")

    pattern = re.compile(r"\d+")

    # match: 从开头匹配
    print(f"  match('123 abc') = {pattern.match('123 abc').group()}")

    # search: 找第一个
    print(f"  search('abc 456') = {pattern.search('abc 456').group()}")

    # findall: 全部
    print(f"  findall('a1 b2 c3') = {pattern.findall('a1 b2 c3')}")

    # 没匹配
    print(f"  search('abc') = {pattern.search('abc')}")    # None


def demo_dotall_flag() -> None:
    banner("2. re.DOTALL 让 . 匹配换行")

    text = "<think>\n跨多行的思考过程\n步骤 1\n步骤 2\n</think>\n最终答案"

    # 不带 DOTALL: . 不匹配 \n, 匹配不到
    no_dotall = re.search(r"<think>.*?</think>", text)
    print(f"  不带 DOTALL: {no_dotall}")

    # 带 DOTALL: 跨行匹配
    with_dotall = re.search(r"<think>.*?</think>", text, flags=re.DOTALL)
    if with_dotall:
        print(f"  带 DOTALL: 匹配到, 长度 {len(with_dotall.group())}")


def demo_greedy_vs_lazy() -> None:
    banner("3. 贪婪 vs 非贪婪")

    text = "<b>bold1</b> normal <b>bold2</b>"

    # 贪婪: 尽量多匹配
    greedy = re.findall(r"<b>.*</b>", text)
    print(f"  贪婪 (.*):   {greedy}")

    # 非贪婪: 尽量少匹配
    lazy = re.findall(r"<b>.*?</b>", text)
    print(f"  非贪婪 (.*?): {lazy}")


def demo_groups_and_named() -> None:
    banner("4. 分组 + 命名分组")

    text = "退款金额 500 元, 订单号 ORD-001"

    # 普通分组
    m = re.search(r"(\d+)\s*元", text)
    if m:
        print(f"  普通分组 group(1) = {m.group(1)}")

    # 命名分组 (?P<name>...)
    m = re.search(r"订单号\s+(?P<order_id>\w+)", text)
    if m:
        print(f"  命名分组 group('order_id') = {m.group('order_id')}")
        print(f"  groupdict() = {m.groupdict()}")


def demo_strip_think_pattern() -> None:
    banner("5. 项目 01_models.py:24 剥 <think> 标签")

    # 模拟 M3 模型返回
    raw = """<think>
The user is asking about weather. Let me think step by step.
Step 1: parse the city.
Step 2: look up weather API.
</think>
北京今天晴, 28°C, 微风。"""

    # 多个标签都用 | 列举
    THINK_RE = re.compile(
        r"<think>.*?</think>"
        r"|<thinking>.*?</thinking>"
        r"|<reflection>.*?</reflection>",
        flags=re.DOTALL,
    )
    cleaned = THINK_RE.sub("", raw).strip()
    print(f"  原始长度: {len(raw)}")
    print(f"  剥后长度: {len(cleaned)}")
    print(f"  剥后内容: {cleaned!r}")

    # 等价但不推荐的写法 (每次现编译)
    cleaned_v2 = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    print(f"  等价: {cleaned_v2 == cleaned}")


if __name__ == "__main__":
    setup()
    demo_basic_match()
    demo_dotall_flag()
    demo_greedy_vs_lazy()
    demo_groups_and_named()
    demo_strip_think_pattern()
    print("\n[L4-03] 全部 demo 跑完。")
