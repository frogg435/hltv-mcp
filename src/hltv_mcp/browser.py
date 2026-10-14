"""浏览器后端：用真实浏览器取页面、做交互。

为什么这是默认后端
------------------
HTTP 后端（`curl_cffi`）在两种情况下会失败：

1. **出口 IP 被 Cloudflare 拦** —— 机房/云主机 IP 尤其容易被拦
2. **某些路径有单独的规则** —— 例如 `/stats/*`（选手逐年 Rating 所在页）

这两种情况换 TLS 指纹、上有头浏览器、带登录态都无效，因为判定依据是 IP 与
浏览器的真实度。真正有效的做法是**用真实浏览器取数据**：住宅出口 IP、真实的
浏览器配置文件、正常的渲染行为。

另外，有些数据**只有**浏览器能拿到：比赛详细统计页的地图切换是前端按钮，
纯 HTTP 请求无法触发（见 `fetch_match_stats`）。

浏览器从哪来
------------
三种来源，按优先级：

1. `HLTV_BROWSER_CDP` —— 你显式指定的 CDP 地址
2. 已经在跑的、带调试端口的浏览器（默认探测 9222）
3. **由 `launcher.py` 自动拉起一个**（默认行为，用独立的持久化 profile）

所以这个模块开箱即用，不需要你先敲命令启动 Chrome。想关掉自动启动就设
`HLTV_BROWSER_AUTOLAUNCH=0`。

安全边界
--------
* **绝不关闭用户自己的浏览器** —— 只有 `launcher` 主动拉起的实例才会被它关掉；
  连上外部实例时 CDP 的 browser 对象不会被 `close()`。
* 不读取、不导出、不落盘用户的 cookie 与登录凭据。
* 自动拉起的实例使用**独立**的用户数据目录，不碰你日常的 profile。
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any

from .client import BrowserUnavailable, HLTV_BASE, HltvError

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


def _is_autolaunched() -> bool:
    """当前连的浏览器是不是由本服务拉起的（用于自检输出）。"""
    try:
        from .launcher import get_launcher

        return get_launcher().launched_by_us
    except Exception:  # noqa: BLE001
        return False


def _looks_like_challenge(title: str, html: str) -> bool:
    if any(marker.lower() in (title or "").lower() for marker in _CHALLENGE_MARKERS):
        return True
    head = html[:4000]
    return "cf-chl" in head or "Just a moment" in head


class BrowserFetcher:
    """通过 CDP 用真实浏览器抓取页面。"""

    def __init__(self, cdp_url: str | None = None) -> None:
        # 不在这里解析地址 —— 解析可能意味着启动浏览器，很慢。
        # 留到第一次真正要取页面时再做，避免「只查缓存」的请求也被拖慢。
        self._explicit_url = (cdp_url or DEFAULT_CDP_URL).strip()
        # 浏览器操作必须在同一线程使用，且并发开着多个标签页没有意义，这里串行化
        self._lock = threading.RLock()

    @property
    def cdp_url(self) -> str:
        """解析出一个可用的 CDP 地址，必要时拉起浏览器。"""
        if self._explicit_url:
            return self._explicit_url
        from .launcher import get_launcher

        return get_launcher().ensure()

    # ------------------------------------------------------------------
    def _connect(self, cdp_url: str):
        """连接 CDP。延迟导入 playwright，未装也能给出清楚的提示。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # noqa: BLE001
            raise BrowserUnavailable(
                "未安装 playwright，浏览器后端不可用。"
                "安装：pip install playwright（无需再跑 playwright install，"
                "本后端复用本机已有的 Chrome）。"
                "或改用 HTTP 后端：设置 HLTV_BACKEND=http。"
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
        「地图」按钮，纯 HTTP 请求做不到。
        """
        url = path if path.startswith("http") else HLTV_BASE + path
        cdp_url = self.cdp_url  # 可能触发浏览器启动，放在锁外做的话会并发启动
        sync_playwright = self._connect(cdp_url)

        with self._lock:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.connect_over_cdp(cdp_url)
                except Exception as exc:  # noqa: BLE001
                    raise BrowserUnavailable(
                        f"无法连接浏览器（{cdp_url}）：{exc}。"
                        "请确认该地址上有一个带 --remote-debugging-port 的浏览器实例，"
                        "或清空 HLTV_BROWSER_CDP 让本服务自动启动一个。"
                    ) from exc

                # 优先复用默认上下文 —— 它带着真实 profile 的 cookie 与登录态。
                # 实测匿名上下文（new_context）更容易被 Cloudflare 拦。
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
        info: dict[str, Any] = {}
        # 先解析地址（可能触发自动启动），再连
        cdp_url = self.cdp_url
        info["cdp_url"] = cdp_url
        info["autolaunched"] = _is_autolaunched()
        sync_playwright = self._connect(cdp_url)
        with self._lock:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.connect_over_cdp(cdp_url)
                except Exception as exc:  # noqa: BLE001
                    raise BrowserUnavailable(
                        f"无法连接浏览器（{cdp_url}）：{exc}"
                    ) from exc
                info["browser_version"] = browser.version
                info["contexts"] = len(browser.contexts)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                try:
                    page.goto(HLTV_BASE + "/", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                    info["title"] = page.title()
                    info["challenged"] = self._await_challenge(page)
                    info["html_size"] = len(page.content())
                finally:
                    _safe_close(page)
        return info


_fetcher: BrowserFetcher | None = None
_fetcher_lock = threading.Lock()


def get_browser_fetcher() -> BrowserFetcher:
    global _fetcher
    with _fetcher_lock:
        if _fetcher is None:
            _fetcher = BrowserFetcher()
        return _fetcher
