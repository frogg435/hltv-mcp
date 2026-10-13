"""浏览器后端：通过 CDP 复用「你自己的浏览器」。

为什么需要这个后端
------------------
默认的 HTTP 后端（`curl_cffi`）在两种情况下会失败：

1. **出口 IP 被 Cloudflare 拉黑** —— 机房/云主机 IP 尤其容易被拦
2. **某些路径有单独的规则** —— 例如 `/stats/*`（选手逐年 Rating 所在页）

这两种情况换 TLS 指纹、上有头浏览器、带登录态都无效，因为判定依据是 IP 和
浏览器真实度。真正有效的做法是**用用户自己的浏览器取数据**：

* 住宅出口 IP，信誉正常
* 真实的浏览器配置文件（含历史、cookie，以及用户自己的登录态）
* 不需要我们经手任何账号密码 —— 用户在自己的浏览器里正常使用即可

工作方式
--------
用 CDP（Chrome DevTools Protocol）连接到用户**已经打开**的 Chrome，借用它的
网络栈和会话取页面，取完就关掉我们开的标签页。

用户侧只需用远程调试端口启动 Chrome：

    # macOS
    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
        --remote-debugging-port=9222

    # Windows
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222

    # Linux
    google-chrome --remote-debugging-port=9222

然后设置 `HLTV_BROWSER_CDP=http://127.0.0.1:9222`。

安全边界
--------
* **绝不关闭用户的浏览器** —— CDP 连上来的 browser 对象不调用 `close()`，
  只关闭本模块自己 `new_page()` 出来的标签页。
* 不读取、不导出、不落盘用户的 cookie 与登录凭据。
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any

from .client import HLTV_BASE, HltvError

DEFAULT_CDP_URL = os.environ.get("HLTV_BROWSER_CDP", "")

# 挑战页特征
_CHALLENGE_MARKERS = ("Just a moment", "Attention Required", "Checking your browser")

# 等待 Cloudflare 挑战自动通过的最长时间（秒）。
# 真实浏览器 + 正常 IP 通常在 5 秒内通过。
CHALLENGE_WAIT = float(os.environ.get("HLTV_CHALLENGE_WAIT", "25"))

# 页面导航重试次数。实测约十分之一的请求会撞上瞬态 Cloudflare 挑战页，
# 重开一个标签页重试即可恢复，因此不能只试一次。
NAV_RETRIES = int(os.environ.get("HLTV_NAV_RETRIES", "3"))
PAGE_TIMEOUT = int(os.environ.get("HLTV_PAGE_TIMEOUT", "45000"))


def _safe_close(page) -> None:
    """关闭标签页，失败也无所谓 —— 绝不能因为清理动作影响主流程。"""
    try:
        if page is not None and not page.is_closed():
            page.close()
    except Exception:  # noqa: BLE001
        pass


def _looks_like_challenge(title: str, html: str) -> bool:
    if any(marker.lower() in (title or "").lower() for marker in _CHALLENGE_MARKERS):
        return True
    head = html[:4000]
    return "cf-chl" in head or "Just a moment" in head


class BrowserFetcher:
    """通过 CDP 借用用户浏览器抓取页面。"""

    def __init__(self, cdp_url: str | None = None) -> None:
        self.cdp_url = (cdp_url or DEFAULT_CDP_URL).strip()
        if not self.cdp_url:
            raise HltvError(
                "未配置浏览器后端。请设置 HLTV_BROWSER_CDP，"
                "例如 http://127.0.0.1:9222（先用 --remote-debugging-port=9222 启动 Chrome）。"
            )
        # 浏览器操作必须在同一线程使用，且并发开着多个标签页没有意义，这里串行化
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def _connect(self):
        """连接 CDP。延迟导入 playwright，未装也不影响默认后端。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # noqa: BLE001
            raise HltvError(
                "未安装 playwright。浏览器后端需要额外依赖：pip install 'hltv-mcp[browser]'"
            ) from exc
        return sync_playwright

    def fetch_html(self, path: str) -> str:
        """打开一个临时标签页抓取页面，然后关掉它。"""
        with self.page(path) as page:
            return page.content()

    @contextmanager
    def page(self, path: str, wait_until: str = "domcontentloaded"):
        """打开页面并把 Playwright 的 page 交给调用方，退出时自动关闭标签页。

        需要点击、等待渲染这类交互的工具用它 —— 例如比赛详细统计要切换
        「地图」和「阵营」按钮，纯 HTTP 请求做不到。
        """
        url = path if path.startswith("http") else HLTV_BASE + path
        sync_playwright = self._connect()

        with self._lock:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.connect_over_cdp(self.cdp_url)
                except Exception as exc:  # noqa: BLE001
                    raise HltvError(
                        f"无法连接浏览器（{self.cdp_url}）：{exc}。"
                        "请确认 Chrome 已带 --remote-debugging-port=9222 启动。"
                    ) from exc

                # 复用用户的默认上下文 —— 这里带着他的 cookie 和登录态
                contexts = browser.contexts
                context = contexts[0] if contexts else browser.new_context()

                # 先把页面开出来（可能重试），再把控制权交给调用方。
                # 两段分开是有意的：调用方在使用过程中抛出的异常必须原样上抛，
                # 不能被这里的重试逻辑误当成「导航失败」而重来一遍。
                page = None
                last_error: Exception | None = None
                for attempt in range(NAV_RETRIES):
                    candidate = context.new_page()
                    try:
                        candidate.goto(url, wait_until=wait_until, timeout=PAGE_TIMEOUT)
                        if self._await_challenge(candidate):
                            # 实测约十分之一的请求会撞上瞬态挑战页，重开即可恢复
                            last_error = HltvError(f"停留在 Cloudflare 挑战页：{path}")
                            _safe_close(candidate)
                            time.sleep(2.0 * (attempt + 1))
                            continue
                    except Exception as exc:  # noqa: BLE001 - 导航超时等
                        last_error = exc
                        _safe_close(candidate)
                        time.sleep(2.0 * (attempt + 1))
                        continue

                    page = candidate
                    break

                if page is None:
                    raise HltvError(
                        f"浏览器打开页面失败（重试 {NAV_RETRIES} 次）：{path}｜{last_error}。"
                        "若一直在挑战页，请在浏览器里手动打开一次 hltv.org 通过验证。"
                    )

                try:
                    yield page
                finally:
                    # 只关自己开的标签页；绝不 close browser，那是用户的 Chrome
                    _safe_close(page)

    @staticmethod
    def _await_challenge(page) -> bool:
        """等 Cloudflare 挑战自动通过。返回 True 表示仍停在挑战页。"""
        deadline = time.monotonic() + CHALLENGE_WAIT
        html = page.content()
        while _looks_like_challenge(page.title(), html) and time.monotonic() < deadline:
            page.wait_for_timeout(1200)
            html = page.content()
        return _looks_like_challenge(page.title(), html)

    # ------------------------------------------------------------------
    def fetch_match_stats(
        self,
        match_id: int,
        slug: str = "x",
        map_name: str | None = None,
    ) -> dict[str, Any]:
        """取某场比赛的详细统计页（可按地图筛选）。

        这个页面特殊：地图是**前端按钮**，URL 参数无效
        （实测 `?maps=` / `?side=` 返回的内容与不带参数完全一致），所以必须真的点。

        阵营则**不需要**点 —— 实测 DOM 里同时存在 totalstats / ctstats / tstats
        三套表，只有当前选中的那套不带 `hidden` 类。因此这里只点地图，
        三个阵营的数据一次性交给解析器。

        Returns:
            {"stats_url", "available_maps", "map", "html"}
        """
        # 步骤一：比赛页里的 "Detailed stats" 指向另一套 ID，必须先取出来
        stats_href = None
        with self.page(f"/matches/{int(match_id)}/{slug}") as page:
            link = page.query_selector("a[href^='/stats/matches/']")
            if link is not None:
                stats_href = link.get_attribute("href")
        if not stats_href:
            raise HltvError(
                f"比赛 {match_id} 没有详细统计页（比赛可能尚未开始，或数据未生成）。"
            )

        # 步骤二：打开统计页，选地图，再读渲染结果
        with self.page(stats_href, wait_until="load") as page:
            page.wait_for_timeout(4000)

            available_maps = page.evaluate(
                """()=>[...document.querySelectorAll('.stats-match-map')].map(
                    e=>e.innerText.replace(/\\s+/g,' ').trim()).slice(0,20)"""
            )

            if map_name and map_name.lower() != "all":
                try:
                    page.locator(".stats-match-map", has_text=map_name).first.click(timeout=8000)
                    page.wait_for_timeout(3500)
                except Exception as exc:  # noqa: BLE001
                    raise HltvError(
                        f"找不到地图 {map_name!r}。本场比赛可选：{available_maps}"
                    ) from exc

            html = page.content()

        return {
            "stats_url": HLTV_BASE + stats_href if stats_href.startswith("/") else stats_href,
            "available_maps": available_maps,
            "map": map_name or "all",
            "html": html,
        }

    # ------------------------------------------------------------------
    def probe(self) -> dict[str, Any]:
        """连通性自检，供 scripts/browser_check.py 使用。"""
        info: dict[str, Any] = {"cdp_url": self.cdp_url}
        sync_playwright = self._connect()
        with self._lock:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.cdp_url)
                info["browser_version"] = browser.version
                info["contexts"] = len(browser.contexts)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                try:
                    page.goto(HLTV_BASE + "/", wait_until="domcontentloaded", timeout=45000)
                    deadline = time.monotonic() + CHALLENGE_WAIT
                    html = page.content()
                    while _looks_like_challenge(page.title(), html) and time.monotonic() < deadline:
                        page.wait_for_timeout(1200)
                        html = page.content()
                    info["title"] = page.title()
                    info["challenged"] = _looks_like_challenge(page.title(), html)
                    info["html_size"] = len(html)
                finally:
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass
        return info


_fetcher: BrowserFetcher | None = None
_fetcher_lock = threading.Lock()


def get_browser_fetcher() -> BrowserFetcher:
    global _fetcher
    with _fetcher_lock:
        if _fetcher is None:
            _fetcher = BrowserFetcher()
        return _fetcher
