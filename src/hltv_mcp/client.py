"""HLTV 抓取客户端（后端可切换）。

两种取页面的方式
----------------
**浏览器后端（默认）** —— 用真实浏览器取页面，见 `browser.py` 与 `launcher.py`。
它是最接近真实用户的方式，因此穿过 Cloudflare 最稳；并且只有它能做点击交互
（`hltv_get_match_stats` 依赖这一点）。代价是慢一些、需要一个本机浏览器。

**HTTP 后端** —— `curl_cffi` 直接请求，用 Safari 的 TLS 指纹。裸 `requests` /
`curl` 会拿到 403 的 "Just a moment..." 挑战页，而实测 Safari 指纹能过、Chrome
指纹会被拦。它快、轻、无需浏览器，适合浏览器装不起来的场景。

`HLTV_BACKEND` 控制选择：`auto`（默认）/ `browser` / `http`。
`auto` 的含义是**优先浏览器**，只有在浏览器根本起不来时才降级到 HTTP ——
「页面被 Cloudflare 拦」不属于这种，那种情况降级只会拿到同样的拦截页。

客户端负责四件事：
  1. 后端选择与降级
  2. 全局限速（HLTV 对高频请求敏感）
  3. TTL 缓存（同一会话内避免重复抓取）
  4. 失败重试 + 会话重建
"""

from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

from curl_cffi import requests as cffi
from bs4 import BeautifulSoup

HLTV_BASE = "https://www.hltv.org"

# 实测在 Cloudflare 面前的行为差异：
#   chrome124 / chrome120 -> 403 Just a moment...
#   safari17_0            -> 200 正常页面
# 换网络环境后表现可能不同，所以做成可配置。
IMPERSONATE = os.environ.get("HLTV_IMPERSONATE", "safari17_0")

DEFAULT_TIMEOUT = int(os.environ.get("HLTV_TIMEOUT", "40"))

# 请求间隔是这里最关键的参数。HLTV 位于 Cloudflare 之后，短时间内的密集请求
# 会让当前 IP 被单独限流（表现为某一路径持续 403，其他路径正常），且恢复需要
# 数分钟到数小时。默认取 3 秒并叠加随机抖动，配合缓存足以支撑对话式查询。
DEFAULT_MIN_INTERVAL = float(os.environ.get("HLTV_MIN_INTERVAL", "3.0"))
JITTER = float(os.environ.get("HLTV_JITTER", "0.8"))

DEFAULT_MAX_RETRIES = int(os.environ.get("HLTV_MAX_RETRIES", "3"))

# 出口 IP 是这套方案唯一真正脆弱的环节。
# Cloudflare 会按 IP 累积信誉：同一 IP 短时间内请求过多，会从「某条路径被拦」
# 逐步升级到「整站 403」，此时换 TLS 指纹、上有头浏览器、带登录态都没有用。
# 唯一可靠的解法是换一个干净的出口，因此这里支持配置代理。
def _proxy_from_env() -> dict[str, str] | None:
    """读取代理配置。

    优先 HLTV_PROXY，其次标准的 HTTPS_PROXY / ALL_PROXY。
    值形如 http://user:pass@host:port 或 socks5://host:port。
    """
    raw = (
        os.environ.get("HLTV_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("ALL_PROXY")
        or os.environ.get("all_proxy")
    )
    if not raw:
        return None
    return {"http": raw, "https": raw}


PROXY = _proxy_from_env()

# 后端选择：
#   auto（默认）—— 优先浏览器；只有浏览器**根本起不来**时才降级到 HTTP。
#                   页面被 Cloudflare 拦不算「起不来」，那种情况降级没意义。
#   browser     —— 强制浏览器。起不来就报错，不做任何降级。
#   http        —— 强制 HTTP。适合装不了浏览器的环境（CI、容器）。
BACKEND = os.environ.get("HLTV_BACKEND", "auto").strip().lower()
if BACKEND not in ("auto", "browser", "http"):
    BACKEND = "auto"

# 显式指定 CDP 地址（复用外部已开着的浏览器）。留空则由 launcher 自动准备。
BROWSER_CDP = os.environ.get("HLTV_BROWSER_CDP", "").strip()


def wants_browser() -> bool:
    """当前配置是否要走浏览器后端。"""
    return BACKEND in ("auto", "browser")


class HltvError(RuntimeError):
    """HLTV 请求失败（网络、拦截或页面不存在）。"""


class BrowserUnavailable(HltvError):
    """浏览器后端起不来（没装浏览器、连不上调试端口等）。

    单独一个类型，是为了让 `auto` 能准确区分「该降级」和「不该降级」：
    只有这种错误才退到 HTTP。
    """


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class HltvClient:
    """线程安全、带缓存与限速的 HLTV 抓取客户端。"""

    def __init__(
        self,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        cache_ttl: dict[str, float] | None = None,
    ) -> None:
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        # 不同页面变化频率不同，缓存 TTL 分开配置（秒）
        self.cache_ttl = cache_ttl or {
            "matches": 60,      # 赛程变动快
            "live": 15,         # 实时比分：够新，又不至于把 HLTV 打爆
            "results": 120,
            "news": 300,
            "ranking": 3600,
            "profile": 1800,    # 选手/战队资料变化慢
            "event": 900,
            "stats": 3600,      # 历史年份的统计不会变，放长一些
            "default": 300,
        }

        self._session: cffi.Session | None = None
        self._lock = threading.RLock()      # 串行化请求，保证限速有效
        self._last_request_at = 0.0
        self._cache: dict[str, _CacheEntry] = {}
        self._warmed_up = False
        # 记录实际生效的后端，供工具回传与诊断脚本读取
        self._backend_in_use: str | None = None
        self._fallback_noted = False

    # ---------- 会话管理 ----------

    def _new_session(self) -> cffi.Session:
        kwargs: dict[str, Any] = {"impersonate": IMPERSONATE}
        if PROXY:
            kwargs["proxies"] = PROXY
        session = cffi.Session(**kwargs)
        # 预热：首页会下发 Cloudflare 相关 cookie，后续请求命中率明显更高
        try:
            session.get(HLTV_BASE + "/", timeout=self.timeout)
        except Exception:  # noqa: BLE001 - 预热失败不致命，交给正式请求重试
            pass
        self._warmed_up = True
        return session

    @property
    def session(self) -> cffi.Session:
        with self._lock:
            if self._session is None:
                self._session = self._new_session()
            return self._session

    def reset_session(self) -> None:
        """丢弃当前会话。403 后调用，用于换一组 cookie 重试。"""
        with self._lock:
            try:
                if self._session is not None:
                    self._session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None
            self._warmed_up = False

    # ---------- 限速 ----------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_interval + random.uniform(0, JITTER) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    # ---------- 缓存 ----------

    @staticmethod
    def _cache_bucket(path: str) -> str:
        p = path.lower()
        if p.startswith("/livescore"):
            return "live"
        if p.startswith("/matches") and "results" not in p:
            return "matches"
        if p.startswith("/results"):
            return "results"
        if p.startswith("/news"):
            return "news"
        if "ranking" in p:
            return "ranking"
        if p.startswith("/player") or p.startswith("/team"):
            return "profile"
        if p.startswith("/events"):
            return "event"
        if p.startswith("/stats"):
            return "stats"
        return "default"

    def _cache_get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            self._cache.pop(key, None)
            return None
        return entry.value

    def _cache_put(self, key: str, value: Any, bucket: str) -> None:
        ttl = self.cache_ttl.get(bucket, self.cache_ttl["default"])
        self._cache[key] = _CacheEntry(value, time.monotonic() + ttl)

    def clear_cache(self) -> None:
        self._cache.clear()

    # ---------- 请求 ----------

    def fetch_html(self, path: str, *, bypass_cache: bool = False) -> str:
        """抓取一个 HLTV 路径，返回 HTML 字符串。

        后端按 `HLTV_BACKEND` 选择（默认 `auto` = 优先浏览器）。
        缓存键带上实际使用的后端，避免降级前后拿到混在一起的结果。
        """
        use_browser = self._should_use_browser()
        cache_key = ("browser:" if use_browser else "") + path
        if not bypass_cache:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        if not use_browser:
            return self._fetch_via_http(path, cache_key)

        try:
            html = self._fetch_via_browser(path)
        except BrowserUnavailable as exc:
            # 只有「浏览器起不来」才降级。页面被 Cloudflare 拦不属于这一类 ——
            # 那种情况 HTTP 后端会拿到同样的拦截，降级只是把错误变得难以理解。
            if BACKEND != "auto":
                raise
            self._note_fallback(exc)
            self._backend_in_use = "http"
            return self._fetch_via_http(path, cache_key)

        self._backend_in_use = "browser"
        self._cache_put(cache_key, html, self._cache_bucket(path))
        return html

    def _should_use_browser(self) -> bool:
        """是否该走浏览器。一旦判定过就不再反复探测。"""
        if not wants_browser():
            self._backend_in_use = "http"
            return False
        if self._backend_in_use == "http":
            # auto 模式下已经确认浏览器不可用，后续请求不再重试，避免每次都白等一次启动超时
            return False
        return True

    def _note_fallback(self, exc: Exception) -> None:
        """降级只提示一次，避免把日志刷满。"""
        if self._fallback_noted:
            return
        self._fallback_noted = True
        import sys

        print(
            f"[hltv-mcp] 浏览器后端不可用，已降级为 HTTP：{exc}",
            file=sys.stderr,
        )

    @property
    def backend_in_use(self) -> str:
        """当前实际在用的后端：`browser` / `http`。"""
        return self._backend_in_use or ("browser" if wants_browser() else "http")

    def _fetch_via_browser(self, path: str) -> str:
        """浏览器后端。延迟导入，避免没装 websocket-client 时影响 HTTP 路径。"""
        from .browser import get_browser_fetcher

        with self._lock:
            self._throttle()
            return get_browser_fetcher().fetch_html(path)

    def _fetch_via_http(self, path: str, cache_key: str) -> str:
        last_error: Exception | None = None
        rate_limited = False

        for attempt in range(self.max_retries):
            with self._lock:
                self._throttle()
                try:
                    resp = self.session.get(HLTV_BASE + path, timeout=self.timeout)
                except Exception as exc:  # noqa: BLE001 - 网络层异常统一转 HltvError
                    last_error = exc
                    self.reset_session()
                    time.sleep(2.0 * (attempt + 1))
                    continue

            if resp.status_code == 200:
                html = resp.text
                # 挑战页会以 200 返回（部分场景），额外判一次
                if "Just a moment" in html[:2000] or "cf-chl" in html[:4000]:
                    last_error = HltvError("被 Cloudflare 挑战页拦截")
                    rate_limited = True
                    time.sleep(4.0 * (attempt + 1))
                    continue
                self._cache_put(cache_key, html, self._cache_bucket(path))
                return html

            if resp.status_code == 404:
                raise HltvError(f"页面不存在：{path}")

            if resp.status_code == 403:
                # 关键：403 多半是「当前 IP 对该路径被临时限流」，不是 cookie 失效。
                # 立刻重建会话反而会丢掉已有的通行 cookie，让情况更糟。
                # 因此先退避重试并沿用同一会话，只在最后一次尝试时才换会话。
                rate_limited = True
                last_error = HltvError("HTTP 403（Cloudflare 限流）")
                time.sleep(4.0 * (attempt + 1))
                if attempt == self.max_retries - 1:
                    self.reset_session()
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = HltvError(f"HTTP {resp.status_code}")
                self.reset_session()
                time.sleep(2.0 * (attempt + 1))
                continue

            raise HltvError(f"HTTP {resp.status_code}：{path}")

        if rate_limited:
            raise HltvError(
                f"HLTV 拒绝了请求（{path}）。当前网络出口 IP 可能被 Cloudflare 临时限流。"
                "建议：稍后重试；或调大 HLTV_MIN_INTERVAL（如 5）降低请求频率；"
                "若长期如此，请更换网络出口。"
            )
        raise HltvError(f"请求失败（重试 {self.max_retries} 次）：{path}｜{last_error}")

    def fetch_soup(self, path: str, *, bypass_cache: bool = False) -> BeautifulSoup:
        return BeautifulSoup(self.fetch_html(path, bypass_cache=bypass_cache), "lxml")

    def close(self) -> None:
        self.reset_session()


# 进程内共享一个客户端，缓存与限速才会生效
_shared: HltvClient | None = None
_shared_lock = threading.Lock()


def get_client() -> HltvClient:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = HltvClient()
        return _shared
