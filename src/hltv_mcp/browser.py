"""浏览器后端：用真实浏览器取页面、做交互。

为什么这是默认后端
------------------
HTTP 后端（`curl_cffi`）在两种情况下会失败：

1. **出口 IP 被 Cloudflare 拦** —— 机房/云主机 IP 尤其容易被拦
2. **某些路径有单独的规则** —— 例如 `/stats/*`（选手逐年 Rating 所在页）

这两种情况换 TLS 指纹、上有头浏览器、带登录态都无效，因为判定依据是 IP 与
浏览器的真实度。真正有效的做法是**用真实浏览器取数据**。

另外，有些数据**只有**浏览器能拿到：比赛详细统计页的地图切换是前端按钮，
纯 HTTP 请求无法触发（见 `fetch_match_stats`）。

**绝不打扰用户**
----------------
标签页一律以 `background=True` 创建，因此不会抢焦点、不会把你正在看的页面顶掉。
这不是「尽量」而是硬约束 —— Playwright 的 `new_page()` 一定会激活新标签页，
所以这里不用它，改用自研的 CDP 客户端（见 `cdp.py`）。

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
* **绝不关闭用户自己的浏览器** —— 只有 `launcher` 主动拉起的实例才会被它关掉
* 只关自己开的标签页，不动别的标签页
* 不读取、不导出、不落盘用户的 cookie 与登录凭据
* 自动拉起的实例使用**独立**的用户数据目录，不碰你日常的 profile
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

from .cdp import CDPError, CDPSession, CDPTab, ws_url_for
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
PAGE_TIMEOUT = int(os.environ.get("HLTV_PAGE_TIMEOUT", "45"))


def _looks_like_challenge(title: str, html: str) -> bool:
    if any(marker.lower() in (title or "").lower() for marker in _CHALLENGE_MARKERS):
        return True
    head = html[:4000]
    return "cf-chl" in head or "Just a moment" in head


def _looks_suspicious(title: str, html: str) -> bool:
    """既不是正常页面，也不像标准的挑战页。

    实测偶发过：`/matches` 返回 25KB 的中间页（正常是 1.1MB），标题也不对，
    既不触发挑战页特征、也不是错误码，解析出来就是「0 场比赛」——静默给错结果。
    HLTV 的正常页面标题里一定带 "HLTV"，据此识别。

    只用来**多试一次**，不作为失败依据：万一哪天站点改了标题格式，
    顶多多重试一轮，不会整个失效。
    """
    if "HLTV" in (title or ""):
        return False
    return True


def _is_autolaunched() -> bool:
    """当前连的浏览器是不是由本服务拉起的（用于自检输出）。"""
    try:
        from .launcher import get_launcher

        return get_launcher().launched_by_us
    except Exception:  # noqa: BLE001
        return False


class BrowserFetcher:
    """通过 CDP 用真实浏览器抓取页面。"""

    def __init__(self, cdp_url: str | None = None) -> None:
        # 不在这里解析地址 —— 解析可能意味着启动浏览器，很慢。
        # 留到第一次真正要取页面时再做。
        self._explicit_url = (cdp_url or DEFAULT_CDP_URL).strip()
        self._session: CDPSession | None = None
        # CDP 连接不能跨线程并发使用，且并发开多个标签页没有意义，这里串行化
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    @property
    def cdp_url(self) -> str:
        """解析出一个可用的 CDP 地址，必要时拉起浏览器。"""
        if self._explicit_url:
            return self._explicit_url
        from .launcher import get_launcher

        return get_launcher().ensure()

    def _connect(self, cdp_base: str) -> CDPSession:
        """连上 CDP，失败时给出可操作的提示。"""
        if self._session is not None:
            return self._session
        try:
            self._session = CDPSession(ws_url_for(cdp_base))
        except CDPError as exc:
            raise BrowserUnavailable(
                f"无法连接浏览器（{cdp_base}）：{exc}。"
                "请确认该地址上有一个带 --remote-debugging-port 的浏览器实例，"
                "或清空 HLTV_BROWSER_CDP 让本服务自动启动一个。"
            ) from exc
        return self._session

    def _drop_session(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    def fetch_html(self, path: str) -> str:
        """抓一个页面并返回 HTML。标签页在后台打开，不影响用户正在看的页面。"""
        tab, html = self.open(path)
        tab.close()
        return html

    def open(self, path: str, *, wait_after: float = 0.0) -> tuple[CDPTab, str]:
        """打开页面（含重试），返回 (标签页, HTML)。

        标签页始终在**后台**创建 —— 不抢焦点，用户当前的页面不受影响。
        调用方用完必须 `tab.close()`（用 `page()` 更省心）。
        """
        url = path if path.startswith("http") else HLTV_BASE + path
        cdp_base = self.cdp_url
        last_error: Exception | None = None

        for attempt in range(NAV_RETRIES):
            session = self._connect(cdp_base)
            tab: CDPTab | None = None
            try:
                tab = session.new_page("about:blank", background=True)
                tab.navigate(url)
                tab.wait_for_load(timeout=PAGE_TIMEOUT)
                if wait_after:
                    tab.wait(wait_after)

                # 关键：挑战通常几秒内会自己通过，先等一等再判定。
                # 少了这一步会把「正在通过验证」误判成「被拦」，白白重试三次。
                if self._await_challenge(tab):
                    # 实测约十分之一的请求会撞上瞬态挑战页，重开即可恢复
                    last_error = HltvError(f"停留在 Cloudflare 挑战页：{path}")
                    tab.close()
                    # 挑战失败后的实例往往已经半残，重连一次更干净
                    self._drop_session()
                    time.sleep(2.0 * (attempt + 1))
                    continue

                # 挑战通过后页面已重渲染，内容要重新取
                html = tab.content()

                # 拿到的东西不像 HLTV 页面（偶发的中间页），再试一次。
                # 最后一次无论如何都接受 —— 见 _looks_suspicious 的说明。
                if attempt < NAV_RETRIES - 1 and _looks_suspicious(tab.title(), html):
                    last_error = HltvError(
                        f"响应不像 HLTV 页面（{len(html)}B，标题 {tab.title()[:40]!r}）"
                    )
                    tab.close()
                    self._drop_session()
                    time.sleep(1.5)
                    continue

                return tab, html
            except CDPError as exc:
                last_error = exc
                if tab is not None:
                    tab.close()
                # 连接级错误必须重连，否则后续调用会一直挂在坏连接上
                self._drop_session()
                time.sleep(2.0 * (attempt + 1))
                continue

        raise HltvError(
            f"浏览器打开页面失败（重试 {NAV_RETRIES} 次）：{path}｜{last_error}。"
            "若一直在挑战页，请在浏览器里手动打开一次 hltv.org 通过验证。"
        )

    @contextmanager
    def page(self, path: str, *, wait_after: float = 0.0):
        """打开页面并把标签页交给调用方，退出时自动关闭。

        需要点击、等待渲染这类交互的工具用它 —— 例如比赛详细统计要切换
        「地图」按钮，纯 HTTP 请求做不到。
        """
        tab, _html = self.open(path, wait_after=wait_after)
        try:
            yield tab
        finally:
            tab.close()

    # ------------------------------------------------------------------
    @staticmethod
    def _await_challenge(tab: CDPTab) -> bool:
        """等 Cloudflare 挑战自动通过。返回 True 表示仍停在挑战页。"""
        deadline = time.monotonic() + CHALLENGE_WAIT
        html = tab.content()
        while _looks_like_challenge(tab.title(), html) and time.monotonic() < deadline:
            tab.wait(1.2)
            html = tab.content()
        return _looks_like_challenge(tab.title(), html)

    # ------------------------------------------------------------------
    def fetch_match_stats(
        self,
        match_id: int,
        slug: str = "x",
        map_name: str | None = None,
    ) -> dict:
        """取某场比赛的详细统计页（可按地图筛选）。

        这个页面特殊：地图是**前端按钮**，URL 参数无效
        （实测 `?maps=` / `?side=` 返回的内容与不带参数完全一致），所以必须真的点。

        阵营则**不需要**点 —— 实测 DOM 里同时存在 totalstats / ctstats / tstats
        三套表，只有当前选中的那套不带 `hidden` 类。因此这里只点地图，
        三个阵营的数据一次性交给解析器。

        Returns:
            {"stats_url", "available_maps", "map", "html"}
        """
        # 步骤一：比赛页里的 "Detailed stats" 指向另一套 ID，必须先取出来。
        #
        # 注意页面上有**多个**这类链接，且含义不同：
        #   /stats/matches/mapstatsid/241574/...   ← 单张地图的统计
        #   /stats/matches/131941/...              ← 整场比赛的统计（要的是这个）
        # 实测直接取第一个会拿到 mapstatsid 形式，那样地图切换器虽有，但语义上被
        # 限定在某一张图上。所以优先挑不含 mapstatsid 的那个。
        stats_href = None
        with self.page(f"/matches/{int(match_id)}/{slug}") as tab:
            stats_href = tab.evaluate(
                """
                (() => {
                  const links = [...document.querySelectorAll("a[href^='/stats/matches/']")]
                      .map(a => a.getAttribute('href'));
                  return links.find(h => !h.includes('mapstatsid')) || links[0] || null;
                })()
                """
            )
        if not stats_href:
            raise HltvError(
                f"比赛 {match_id} 没有详细统计页（比赛可能尚未开始，或数据未生成）。"
            )

        # 步骤二：打开统计页，点地图，再读渲染结果
        with self.page(stats_href, wait_after=3.5) as tab:
            available_maps = [text for text in tab.texts(".stats-match-map") if text]

            if map_name and map_name.lower() != "all":
                if not tab.click_by_text(".stats-match-map", map_name):
                    raise HltvError(
                        f"找不到地图 {map_name!r}。本场比赛可选：{available_maps}"
                    )
                tab.wait(3.0)

            html = tab.content()

        return {
            "stats_url": HLTV_BASE + stats_href if stats_href.startswith("/") else stats_href,
            "available_maps": available_maps,
            "map": map_name or "all",
            "html": html,
        }

    # ------------------------------------------------------------------
    def probe(self) -> dict:
        """连通性自检，供 scripts/browser_check.py 使用。"""
        cdp_base = self.cdp_url
        info: dict = {
            "cdp_url": cdp_base,
            "autolaunched": _is_autolaunched(),
            "browser_connected": True,
        }
        session = self._connect(cdp_base)
        try:
            info["browser_version"] = session.version()
        except CDPError:
            info["browser_version"] = None

        tab = session.new_page("about:blank", background=True)
        try:
            tab.navigate(HLTV_BASE + "/")
            tab.wait_for_load(timeout=PAGE_TIMEOUT)
            info["title"] = tab.title()
            info["challenged"] = self._await_challenge(tab)
            info["html_size"] = len(tab.content())
        finally:
            tab.close()
        return info

    def close(self) -> None:
        self._drop_session()


_fetcher: BrowserFetcher | None = None
_fetcher_lock = threading.Lock()


def get_browser_fetcher() -> BrowserFetcher:
    global _fetcher
    with _fetcher_lock:
        if _fetcher is None:
            _fetcher = BrowserFetcher()
        return _fetcher
