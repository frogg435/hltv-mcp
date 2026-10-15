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
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    # curl_cffi 只在 HTTP 后端用得到（见 _new_session）。
    # 本模块有 `from __future__ import annotations`，所有注解都是惰性字符串，
    # 因此把它降级为可选依赖后，类型标注依然可用、运行时却不必安装。
    from curl_cffi import requests as cffi

HLTV_BASE = "https://www.hltv.org"


def _env_number(name: str, default, cast=float):
    """读一个数字型环境变量，留空或写错时回落到默认值。

    留空（`HLTV_TIMEOUT=`）在 .env 文件与 CI 变量里很常见，而 `float("")` 会抛
    ValueError 把整个模块炸掉 —— 那意味着服务直接起不来。这里宁可悄悄用默认值：
    配置写错时，用户想要的是「还能用」，不是「启动失败」。
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default

# 实测在 Cloudflare 面前的行为差异：
#   chrome124 / chrome120 -> 403 Just a moment...
#   safari17_0            -> 200 正常页面
# 换网络环境后表现可能不同，所以做成可配置。
IMPERSONATE = os.environ.get("HLTV_IMPERSONATE", "safari17_0")

DEFAULT_TIMEOUT = _env_number("HLTV_TIMEOUT", 40, int)

# 请求间隔是这里最关键的参数。HLTV 位于 Cloudflare 之后，短时间内的密集请求
# 会让当前 IP 被单独限流（表现为某一路径持续 403，其他路径正常），且恢复需要
# 数分钟到数小时。默认取 3 秒并叠加随机抖动，配合缓存足以支撑对话式查询。
#
# 注意这个 3 秒是给 **HTTP 后端**定的：裸 HTTP 请求最像爬虫，也最容易被限流。
DEFAULT_MIN_INTERVAL = _env_number("HLTV_MIN_INTERVAL", 3.0)

# 浏览器后端不需要那么长的间隔，理由有三：
#   1. 它就是「一个真人在翻页」，Cloudflare 对它的判定依据完全不同
#   2. CDP 调用本身已经串行化，天然不存在并发冲击
#   3. 每次取页面前后已经花了 1-3 秒，再叠 3 秒纯粹是自己卡自己
# 实测把这里从 3 秒降到 0.5 秒，单次查询的快路径能省下 1.5-3 秒。
BROWSER_MIN_INTERVAL = _env_number("HLTV_BROWSER_MIN_INTERVAL", 0.5)

# hybrid 模式里那次「探路」HTTP 请求的间隔。比纯 HTTP 后端的 3 秒小得多
# （命中的都是没被拦的常规路径），但也不设成 0 —— 裸 HTTP 请求比浏览器扎眼，
# 该给的礼貌还是要给。
HYBRID_HTTP_MIN_INTERVAL = _env_number("HLTV_HYBRID_MIN_INTERVAL", 1.0)

JITTER = _env_number("HLTV_JITTER", 0.8)

DEFAULT_MAX_RETRIES = _env_number("HLTV_MAX_RETRIES", 3, int)

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
#   hybrid      —— HTTP 优先，被 Cloudflare 拦了才落到浏览器，并记住「哪些路径
#                   必须用浏览器」。拿到的数据与 auto 完全一致（拿不到会自动换
#                   浏览器），但常规页面快好几倍：HTTP 约 0.5-1.2 秒，浏览器
#                   约 1.5-3 秒。想更快的用户可以切到这个。
BACKEND = os.environ.get("HLTV_BACKEND", "auto").strip().lower()
if BACKEND not in ("auto", "browser", "http", "hybrid"):
    BACKEND = "auto"

# 显式指定 CDP 地址（复用外部已开着的浏览器）。留空则由 launcher 自动准备。
BROWSER_CDP = os.environ.get("HLTV_BROWSER_CDP", "").strip()


def wants_browser() -> bool:
    """当前配置是否允许走浏览器后端。"""
    return BACKEND in ("auto", "browser", "hybrid")


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
        # hybrid 专用：已经被证实「HTTP 拿不到、必须走浏览器」的路径前缀。
        # 记住它，后续同类路径直接走浏览器，省掉每次白挨一遍 403。
        self._browser_only_paths: set[str] = set()
        self._hybrid_noted = False
        # 预热让步开关：有真实请求进来就置位，预热线程看到后立刻收工，
        # 把带宽和锁让给用户（详见 warmup 的说明）
        self._warmup_cancel = threading.Event()

    # ---------- 会话管理 ----------

    def _new_session(self) -> cffi.Session:
        try:
            from curl_cffi import requests as _cffi
        except ImportError as exc:  # 没装可选依赖时给一句能自解释的报错
            raise HltvError(
                "HTTP 后端依赖可选包 curl_cffi，当前未安装。"
                "在项目目录内执行 `pip install -e '.[http]'` 即可补上；"
                "或直接使用默认的浏览器后端（HLTV_BACKEND=auto / browser），"
                "它不需要 curl_cffi。"
            ) from exc
        kwargs: dict[str, Any] = {"impersonate": IMPERSONATE}
        if PROXY:
            kwargs["proxies"] = PROXY
        session = _cffi.Session(**kwargs)
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

    def _throttle(self, min_interval: float | None = None) -> None:
        """距上次请求不足 `min_interval` 就补足等待。

        `min_interval` 缺省用 HTTP 后端的保守值；浏览器后端会传一个更小的值，
        因为它的风险模型完全不同（见模块顶部 BROWSER_MIN_INTERVAL 的说明）。
        """
        interval = self.min_interval if min_interval is None else min_interval
        elapsed = time.monotonic() - self._last_request_at
        wait = interval + random.uniform(0, JITTER) - elapsed
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

    def fetch_html(self, path: str, *, bypass_cache: bool = False, warmup: bool = False) -> str:
        """抓取一个 HLTV 路径，返回 HTML 字符串。

        后端按 `HLTV_BACKEND` 选择（默认 `auto` = 优先浏览器）。
        缓存键带上实际使用的后端，避免降级前后拿到混在一起的结果。

        `warmup=True` 表示这是预热线程发的请求，此时**不**触发让步开关 ——
        否则预热会把自己叫停。
        """
        if not warmup:
            # 有真人在查，预热立刻让路（见 warmup）
            self._warmup_cancel.set()

        if BACKEND == "hybrid":
            return self._fetch_hybrid(path, bypass_cache=bypass_cache)

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

    # ---------- hybrid：HTTP 优先，被拦才落浏览器 ----------

    def _fetch_hybrid(self, path: str, *, bypass_cache: bool = False) -> str:
        """HTTP 优先，被 Cloudflare 拦了才落到浏览器。

        这不是 `auto` 的「缩水版」而是「快路径版」：最终拿到的数据完全一样，
        只是把顺序倒过来 —— 先花半秒试一次廉价请求，被拦了才启动浏览器。
        实测 `/stats/*` 这类有独立规则的路径会被拦，其余路径 HTTP 全通，所以
        绝大多数查询走的是快路径（约 0.5-1.2 秒，而浏览器约 1.5-3 秒）。

        被拦过的路径按前缀记住，之后直接走浏览器，不必每次都重挨一遍 403。
        """
        cache_key = "hybrid:" + path
        if not bypass_cache:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        prefix = self._path_prefix(path)
        if prefix not in self._browser_only_paths:
            try:
                # 只试一次，不做退避重试：浏览器就在旁边等着，让用户陪着等完
                # 那 24 秒退避毫无意义。
                html = self._fetch_via_http(
                    path,
                    cache_key,
                    retries=1,
                    min_interval=HYBRID_HTTP_MIN_INTERVAL,
                )
            except HltvError as exc:
                self._browser_only_paths.add(prefix)
                self._note_hybrid_switch(path, exc)
            else:
                self._backend_in_use = "http"
                return html

        html = self._fetch_via_browser(path)
        self._backend_in_use = "browser"
        self._cache_put(cache_key, html, self._cache_bucket(path))
        return html

    @staticmethod
    def _path_prefix(path: str) -> str:
        """把路径归并成「前两段」，用于记住哪类路径必须走浏览器。

        `/stats/players/11816/ropz` -> `/stats/players`，记住一次，该类别下
        所有选手都受益，而不是每个 ID 都重新试一遍 HTTP。
        """
        clean = path.split("?", 1)[0].strip("/")
        parts = [p for p in clean.split("/") if p]
        return "/" + "/".join(parts[:2])

    def _note_hybrid_switch(self, path: str, exc: Exception) -> None:
        """hybrid 首次切到浏览器时提示一次，避免日志被刷满。"""
        if self._hybrid_noted:
            return
        self._hybrid_noted = True
        import sys

        print(
            f"[hltv-mcp] hybrid：{path} 用 HTTP 拿不到（{exc}），已改用浏览器后端；"
            "同一类路径后续都直接用浏览器。",
            file=sys.stderr,
        )

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
            self._throttle(BROWSER_MIN_INTERVAL)
            return get_browser_fetcher().fetch_html(path)

    def _fetch_via_http(
        self,
        path: str,
        cache_key: str,
        *,
        retries: int | None = None,
        min_interval: float | None = None,
    ) -> str:
        """HTTP 后端取页面。

        `retries` 缺省用 `max_retries`（3 次退避，约 24 秒）。hybrid 模式会传 1 ——
        它只是在「探路」，一次不通就换浏览器，不该让用户陪着等完退避。
        `min_interval` 缺省用 HTTP 后端的保守值；hybrid 会传一个更小的数。
        """
        last_error: Exception | None = None
        rate_limited = False
        attempts = self.max_retries if retries is None else max(1, int(retries))

        for attempt in range(attempts):
            with self._lock:
                self._throttle(min_interval)
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
                if attempt == attempts - 1:
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
        raise HltvError(f"请求失败（重试 {attempts} 次）：{path}｜{last_error}")

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


# 预热：开服时就把浏览器和 Cloudflare 通行证备好。
#
# 为什么值得做：冷启动的代价全落在**第一次调用**上 —— 起浏览器、过一次
# Cloudflare 挑战，桌面约 3-6 秒，Termux/手机上一不留神就是十几秒。而这段
# 时间用户其实是在等模型思考，本来就有空档。把它挪到服务启动时（后台线程，
# 不阻塞 MCP 握手），第一次真查询就变成热路径。
WARMUP = os.environ.get("HLTV_WARMUP", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# 预热时依次取这些页面。实测 Cloudflare 对**首访的某些路径**（`/livescore`、
# `/stats/*`）会额外给一次真挑战，耗时 10-25 秒；在启动时把它们走一遍，
# 用户查询时这些路径就都是热的了。
WARMUP_PAGES = tuple(
    p.strip()
    for p in os.environ.get(
        "HLTV_WARMUP_PAGES",
        # /search 不能漏：所有「按名字查」的调用（hltv_get_team/player/event…）
        # 都要先过它，实测它同样会被首访挑战，一次就要多等三十来秒
        "/matches,/livescore,/results,/ranking/teams,/search",
    ).split(",")
    if p.strip()
)

# 预热在继续下一页之前，先等这么久看用户有没有动静。有动静就让路 ——
# 把「可能触发挑战的慢请求」排到用户查询前面，就本末倒置了。
WARMUP_IDLE = _env_number("HLTV_WARMUP_IDLE", 8.0)


def warmup(*, background: bool = True, pages: tuple[str, ...] | None = None) -> None:
    """提前把浏览器与 Cloudflare 通行证准备好。

    第一页立刻取（通常 1-3 秒，只是建立通行证）；后续几页要等一个「安静窗口」，
    一旦有真实请求进来就整个收工，把锁和带宽让给用户。

    设 `HLTV_WARMUP=0` 可关闭；`HLTV_WARMUP_PAGES` 可改要预取的路径。
    """
    if not WARMUP or not wants_browser() or BACKEND == "http":
        return

    targets = pages if pages is not None else WARMUP_PAGES

    def _run() -> None:
        client = get_client()
        cancel = client._warmup_cancel
        try:
            from .browser import get_browser_fetcher

            get_browser_fetcher().cdp_url  # 触发自动拉起浏览器
        except Exception as exc:  # noqa: BLE001 - 预热失败不影响正式请求
            _warmup_log(f"浏览器预热失败（正式请求时会重试）：{exc}")
            return

        for index, path in enumerate(targets):
            if index:
                # 后续页面先等一个安静窗口。等不到（说明用户正在查）就收工，
                # 而不是把慢请求堆到用户前面。
                if cancel.wait(WARMUP_IDLE):
                    _warmup_log("检测到查询请求，预热提前收工（不影响本次查询）")
                    return
            try:
                client.fetch_html(path, warmup=True)
                _warmup_log(f"预热完成：{path}")
            except Exception as exc:  # noqa: BLE001
                _warmup_log(f"预热 {path} 失败（不影响后续请求）：{exc}")

    if background:
        threading.Thread(target=_run, name="hltv-warmup", daemon=True).start()
    else:
        _run()


def _warmup_log(message: str) -> None:
    import sys

    print(f"[hltv-mcp] {message}", file=sys.stderr)
