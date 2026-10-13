#!/usr/bin/env python3
"""连通性诊断。

当某个工具报 403 时，先跑这个脚本，它会区分两种情况：

  * **IP 级封锁** —— 首页也 403。说明出口 IP 信誉已被 Cloudflare 拉黑，
    换 TLS 指纹、上有头浏览器、带登录态都没用，只能换出口或等恢复。
  * **路径级拦截** —— 首页正常、个别路径 403。这类是 Cloudflare 对该路径
    的规则（本项目中 `/stats/*` 长期如此），与请求频率无关。

    python scripts/health.py
    python scripts/health.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from curl_cffi import requests as cr  # noqa: E402

from hltv_mcp.client import HLTV_BASE, IMPERSONATE, PROXY, DEFAULT_TIMEOUT  # noqa: E402

# 按功能分组的探测路径
PROBES: list[tuple[str, str]] = [
    ("首页", "/"),
    ("赛程", "/matches"),
    ("赛果", "/results?offset=0"),
    ("世界排名", "/ranking/teams"),
    ("赛事日历", "/events"),
    ("新闻", "/news/archive"),
    ("选手资料", "/player/11816/ropz"),
    ("战队资料", "/team/6667/faze"),
    ("搜索", "/search?query=vitality"),
    ("选手年度统计（已知被拦）", "/stats/players/11816/ropz"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="HLTV 连通性诊断")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    kwargs = {"impersonate": IMPERSONATE, "timeout": DEFAULT_TIMEOUT}
    if PROXY:
        kwargs["proxies"] = PROXY
    session = cr.Session(**kwargs)

    results: list[dict] = []
    for label, path in PROBES:
        try:
            resp = session.get(HLTV_BASE + path)
            code = resp.status_code
            blocked = "Just a moment" in resp.text[:2000]
        except Exception as exc:  # noqa: BLE001
            code, blocked = 0, False
            results.append({"label": label, "path": path, "status": 0, "error": str(exc)[:80]})
            continue
        results.append({"label": label, "path": path, "status": code, "challenge": blocked})

    if args.json:
        print(json.dumps({"impersonate": IMPERSONATE, "proxy": bool(PROXY), "probes": results},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"TLS 指纹: {IMPERSONATE} | 代理: {'已配置' if PROXY else '未配置'}\n")
    for r in results:
        if r.get("error"):
            print(f"  ?? {r['label']:24s} 请求异常：{r['error']}")
        else:
            mark = "✓" if r["status"] == 200 else "✗"
            extra = "（Cloudflare 挑战页）" if r.get("challenge") else ""
            print(f"  {mark} {r['status']} {r['label']:24s} {r['path']}{extra}")

    home_ok = next((r for r in results if r["path"] == "/"), {}).get("status") == 200
    blocked = [r["label"] for r in results if r.get("status") not in (200, 0)]

    print()
    if not blocked:
        print("全部可达，状态正常。")
        return 0

    if not home_ok:
        print("诊断：**IP 级封锁**。首页即被拒，说明当前出口 IP 已被 Cloudflare 拉黑。")
        print("      换 TLS 指纹 / 有头浏览器 / 登录态都无效，因为判定依据是 IP 而非客户端。")
        print("      处理方式：")
        print("        1. 设置 HLTV_PROXY（或 HTTPS_PROXY）走一个干净的出口，这是最可靠的解法")
        print("        2. 或等待 IP 信誉恢复（数小时到数天）")
    else:
        print(f"诊断：**路径级拦截**。首页正常，以下路径被单独拦：{', '.join(blocked)}")
        print("      这类是 Cloudflare 对该路径的固定规则，降低频率无法解决。")

    return 1


if __name__ == "__main__":
    sys.exit(main())
