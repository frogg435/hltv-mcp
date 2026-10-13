#!/usr/bin/env python3
"""浏览器后端（CDP）自检。

验证能不能连上你自己的 Chrome、能不能取到 HLTV 页面。

前提：Chrome 已带远程调试端口启动，且已设置 HLTV_BROWSER_CDP。

    # 终端 1：启动 Chrome（保持开着）
    #   macOS
    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
    #   Windows
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222
    #   Linux
    google-chrome --remote-debugging-port=9222

    # 终端 2
    export HLTV_BROWSER_CDP=http://127.0.0.1:9222
    python scripts/browser_check.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hltv_mcp.browser import CHALLENGE_WAIT, get_browser_fetcher  # noqa: E402
from hltv_mcp.client import BROWSER_CDP, HltvError  # noqa: E402


# 控制组：一个不带 Cloudflare 防护的站点，用来证明「取页面」这条链路本身是通的
CONTROL_URL = "https://example.com"


def main() -> int:
    ap = argparse.ArgumentParser(description="CDP 浏览器后端自检")
    ap.add_argument("--control-only", action="store_true", help="只做控制组测试")
    args = ap.parse_args()

    if not BROWSER_CDP:
        print("✗ 未设置 HLTV_BROWSER_CDP")
        print("  例：export HLTV_BROWSER_CDP=http://127.0.0.1:9222")
        return 2

    print(f"CDP 地址: {BROWSER_CDP}")
    print(f"挑战等待上限: {CHALLENGE_WAIT:.0f}s\n")

    # ---- 1. 连接与能力探测 ----
    try:
        info = get_browser_fetcher().probe()
        print(f"✓ 已连接浏览器：{info.get('browser_version')}")
        print(f"  上下文数：{info.get('contexts')}（复用第一个，即你的默认配置）")
    except HltvError as exc:
        print(f"✗ {exc}")
        print("\n  请确认 Chrome 带 --remote-debugging-port=9222 启动且仍在运行。")
        return 1

    if args.control_only:
        return 0

    # ---- 2. 控制组：证明取页面链路通 ----
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    print("\n[控制组] 取一个无防护站点，验证取页面链路本身正常")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(BROWSER_CDP)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            try:
                page.goto(CONTROL_URL, wait_until="domcontentloaded", timeout=30000)
                size = len(page.content())
                print(f"  ✓ {CONTROL_URL} -> {page.title()[:40]} ({size}B)")
            finally:
                page.close()
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 取页面失败：{str(exc)[:140]}")
        return 1

    # ---- 3. 目标：取 HLTV ----
    print("\n[目标] 取 HLTV 首页")
    started = time.time()
    try:
        html = get_browser_fetcher().fetch_html("/")
        print(f"  ✓ 成功，{len(html)}B，耗时 {time.time() - started:.1f}s")
        print("\n浏览器后端可用。设置 HLTV_BROWSER_CDP 后，MCP 会自动改用它取数据。")
        return 0
    except HltvError as exc:
        print(f"  ✗ {exc}")
        print("\n  可能原因：")
        print("    · 浏览器里还没通过 Cloudflare 验证 —— 请手动打开一次 hltv.org")
        print("    · 你的网络出口本身访问受限")
        print("  提示：先在浏览器里正常访问一次 hltv.org，通过验证后再重跑本脚本。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
