#!/usr/bin/env python3
"""浏览器后端自检。

默认后端就是浏览器，所以这个脚本现在**开箱即可运行** —— 它会把浏览器准备好
（必要时自动拉起），然后依次验证：能不能连上、能不能取到无防护站点、能不能
取到 HLTV。

    python scripts/browser_check.py

排查顺序上，它是 `health.py` 的补充：
  * `health.py`       —— 诊断 HTTP 后端的连通性（IP 级 vs 路径级）
  * `browser_check.py` —— 诊断浏览器后端（本文件）

可选环境变量：
    HLTV_BROWSER_CDP       复用一个已经开着的浏览器，例如 http://127.0.0.1:9222
    HLTV_BROWSER_HEADLESS  置 1 强制无头（注意：无头很可能被 Cloudflare 拦）
    HLTV_CHROME_BIN        指定浏览器可执行文件路径
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hltv_mcp.browser import CHALLENGE_WAIT, get_browser_fetcher  # noqa: E402
from hltv_mcp.client import BACKEND, BrowserUnavailable, HltvError  # noqa: E402
from hltv_mcp.launcher import LOG_FILE, PROFILE_DIR, find_browser, get_launcher  # noqa: E402

# 控制组：一个不带 Cloudflare 防护的站点，用来证明「取页面」这条链路本身是通的
CONTROL_URL = "https://example.com"


def main() -> int:
    ap = argparse.ArgumentParser(description="浏览器后端自检")
    ap.add_argument("--control-only", action="store_true", help="只做连接与控制组测试")
    args = ap.parse_args()

    print(f"配置的后端: {BACKEND}（auto = 优先浏览器，起不来才降级 HTTP）")
    print(f"浏览器 profile: {PROFILE_DIR}")
    print(f"浏览器日志: {LOG_FILE}")
    print(f"挑战等待上限: {CHALLENGE_WAIT:.0f}s\n")

    # ---- 1. 定位浏览器 ----
    try:
        binary = find_browser()
    except HltvError as exc:
        print(f"✗ {exc}")
        return 1
    if not binary:
        print("✗ 找不到 Chrome / Chromium / Edge")
        print("  处理方式：安装 Google Chrome，或用 HLTV_CHROME_BIN 指定路径，")
        print("          或设 HLTV_BACKEND=http 改用 HTTP 后端。")
        return 1
    print(f"浏览器可执行文件: {binary}")

    # ---- 2. 连接（可能触发自动启动）----
    started = time.time()
    try:
        info = get_browser_fetcher().probe()
    except BrowserUnavailable as exc:
        print(f"✗ 浏览器后端不可用：{exc}")
        print(f"\n  详细日志见 {LOG_FILE}")
        return 1
    except HltvError as exc:
        print(f"✗ {exc}")
        return 1

    launcher = get_launcher()
    origin = "本服务自动拉起" if launcher.launched_by_us else "复用已有实例"
    print(f"✓ 已连接：{info.get('browser_version')}（{origin}）")
    if launcher.mode:
        print(f"  启动方式：{launcher.mode}")
    print(f"  CDP 地址：{info.get('cdp_url')}")
    print(f"  上下文数：{info.get('contexts')}（复用第一个，即该 profile 的默认配置）")
    print(f"  连接耗时：{time.time() - started:.1f}s")

    if args.control_only:
        return 0

    # ---- 3. 控制组：证明取页面链路本身通 ----
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    print(f"\n[控制组] 取一个无防护站点（{CONTROL_URL}），验证取页面链路本身正常")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(info["cdp_url"])
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            try:
                page.goto(CONTROL_URL, wait_until="domcontentloaded", timeout=30000)
                print(f"  ✓ {page.title()[:40]} ({len(page.content())}B)")
            finally:
                page.close()
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 取页面失败：{str(exc)[:140]}")
        return 1

    # ---- 4. 目标：取 HLTV ----
    print("\n[目标] 取 HLTV 首页")
    try:
        html = get_browser_fetcher().fetch_html("/")
        print(f"  ✓ 成功，{len(html)}B")
    except HltvError as exc:
        print(f"  ✗ {exc}")
        print("\n  可能原因：")
        print("    · 出口 IP 被 Cloudflare 拦 —— 换网络出口，或设置 HLTV_PROXY")
        print("    · 用的是无头模式 —— 无头容易被拦，试着去掉 HLTV_BROWSER_HEADLESS")
        print("    · 浏览器里还没通过验证 —— 手动打开一次 hltv.org 通过后重试")
        print(f"\n  详细日志见 {LOG_FILE}")
        return 1

    print("\n浏览器后端可用。")
    print("提示：MCP 进程退出时会自动关掉它启动的这个浏览器实例；")
    print("      若你用的是自己开着的实例（HLTV_BROWSER_CDP），则不会被关掉。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
