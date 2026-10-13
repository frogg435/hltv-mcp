#!/usr/bin/env python3
"""结构探查工具。

HLTV 会改版。当某个解析器抽不到数据时，用这个脚本 dump 页面的类名分布，
定位新的选择器。

    python scripts/hltv_inspect.py /matches
    python scripts/hltv_inspect.py /team/6667/x --selector .profile-team-stat
"""
import argparse
import collections
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hltv_mcp.client import get_client  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="dump HLTV 页面结构")
    ap.add_argument("path", help="HLTV 路径，例如 /matches")
    ap.add_argument("--selector", help="只打印该选择器命中的元素 HTML")
    ap.add_argument("--top", type=int, default=40, help="打印前 N 个类名")
    ap.add_argument("--filter", default="", help="只显示匹配该正则的类名")
    args = ap.parse_args()

    soup = get_client().fetch_soup(args.path)

    if args.selector:
        nodes = soup.select(args.selector)
        print(f"{args.selector} -> {len(nodes)} 个")
        for node in nodes[:3]:
            print(re.sub(r"\s+", " ", str(node))[:600])
        return

    counter: collections.Counter = collections.Counter()
    for el in soup.find_all(True):
        for cls in el.get("class", []):
            counter[cls] += 1

    items = counter.most_common()
    if args.filter:
        pattern = re.compile(args.filter, re.I)
        items = [(k, v) for k, v in items if pattern.search(k)]

    print(f"{args.path}: {len(soup.find_all(True))} 个节点，{len(counter)} 个类名")
    for name, count in items[: args.top]:
        print(f"  {name:44s} {count}")


if __name__ == "__main__":
    main()
