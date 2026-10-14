"""极简 CDP（Chrome DevTools Protocol）客户端。

为什么不用 Playwright
---------------------
**Playwright 在 Android/Termux 上根本装不起来** —— 官方会直接抛
`Error: Unsupported platform: android`，Python 版在 PyPI 上既没有 Termux 的
wheel，也没有源码包。所以只要还依赖它，这个 MCP 在 Termux 上就是死路。

而 CDP 本身只是个 WebSocket 上的 JSON-RPC 协议，语言无关。自己实现一个够用的
子集，换来三个好处：

1. **能在 Termux 上跑** —— 只用 `websocket-client`，纯 Python，哪都能装
2. **可以开「后台标签页」** —— Playwright 的 `new_page()` 一定会激活新标签页，
   把用户正在看的页面顶掉；CDP 的 `Target.createTarget(background=true)` 不会。
   这是本模块存在的主要理由（用法见 `browser.py`）
3. 依赖更小，启动更快

只实现需要的那部分协议：建标签页、导航、取 HTML、执行 JS、关标签页。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any

try:
    import websocket
except ImportError as exc:  # pragma: no cover - 只在缺依赖时触发
    raise ImportError(
        "缺少依赖 websocket-client。安装：pip install websocket-client"
    ) from exc


class CDPError(RuntimeError):
    """CDP 调用失败（连接断开、协议错误、超时）。"""


DEFAULT_CALL_TIMEOUT = 60.0


class CDPTab:
    """一个标签页（CDP 里的 target）上的操作。"""

    def __init__(self, session: "CDPSession", target_id: str, session_id: str) -> None:
        self._session = session
        self.target_id = target_id
        self.session_id = session_id

    # ---------- 基础 ----------

    def call(self, method: str, params: dict | None = None) -> dict:
        return self._session.call(method, params, session_id=self.session_id)

    def navigate(self, url: str) -> None:
        result = self.call("Page.navigate", {"url": url})
        error = result.get("errorText")
        if error:
            raise CDPError(f"导航失败：{error}（{url}）")

    def wait_for_load(self, timeout: float = 45.0, *, complete: bool = False) -> None:
        """等页面可以用。

        默认等到 `readyState != "loading"`（对应 DOMContentLoaded）就够了 ——
        HLTV 是服务端渲染，DOM 一就绪内容就在了。等 `complete` 要多等一批静态
        资源，实测慢近 10 秒而没有收益；需要 JS 异步渲染的内容由调用方自行
        `wait()` 补足。

        用轮询而非 `Page.loadEventFired`：后者在页面早已加载完才 attach 的场景下
        永远等不到，而轮询没有这个竞态。
        """
        accepted = ("complete",) if complete else ("interactive", "complete")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state = self.evaluate("document.readyState")
            except CDPError:
                time.sleep(0.3)
                continue
            if state in accepted:
                return
            time.sleep(0.15)
        # 超时不抛异常：有的页面（含 Cloudflare 挑战页）可能永远到不了目标状态，
        # 交给调用方按内容判断，比在这里直接失败更有用
        return

    def wait(self, seconds: float) -> None:
        """等待若干秒（给前端渲染留时间）。"""
        time.sleep(seconds)

    # ---------- 取值 ----------

    def evaluate(self, expression: str, timeout: float | None = None) -> Any:
        """执行 JS 并取回值。"""
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            raise CDPError(f"JS 执行出错：{detail.get('text')}")
        return result.get("result", {}).get("value")

    def content(self) -> str:
        """取当前文档的完整 HTML。"""
        html = self.evaluate("document.documentElement.outerHTML")
        return html or ""

    def title(self) -> str:
        try:
            return self.evaluate("document.title") or ""
        except CDPError:
            return ""

    def url(self) -> str:
        try:
            return self.evaluate("location.href") or ""
        except CDPError:
            return ""

    # ---------- 交互 ----------

    def click_by_text(self, selector: str, text: str) -> bool:
        """在匹配 `selector` 的元素里，点击文本包含 `text` 的那个。

        用 JS 的 `el.click()` 而不是派发真实鼠标事件 —— 后者要算坐标、处理
        iframe 和滚动，代码量大很多。实测 HLTV 的地图切换按钮接受 JS 点击。
        """
        expression = """
        (() => {
          const nodes = [...document.querySelectorAll(%s)];
          const target = nodes.find(e => (e.innerText || '').includes(%s));
          if (!target) return false;
          target.click();
          return true;
        })()
        """ % (json.dumps(selector), json.dumps(text))
        return bool(self.evaluate(expression))

    def attribute(self, selector: str, name: str) -> str | None:
        """取第一个匹配元素的属性值。"""
        expression = """
        (() => {
          const el = document.querySelector(%s);
          return el ? el.getAttribute(%s) : null;
        })()
        """ % (json.dumps(selector), json.dumps(name))
        return self.evaluate(expression)

    def texts(self, selector: str) -> list[str]:
        """取所有匹配元素的文本。

        把连续空白压成单个空格 —— `innerText` 会带回换行（地图按钮里是
        "13 - 0\\nDust2"），归一化之后调用方不必再处理。
        """
        expression = """
        [...document.querySelectorAll(%s)].map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim())
        """ % json.dumps(selector)
        return self.evaluate(expression) or []

    # ---------- 关闭 ----------

    def close(self) -> None:
        try:
            self._session.close_target(self.target_id)
        except Exception:  # noqa: BLE001 - 关标签页失败不该影响主流程
            pass


class CDPSession:
    """一个浏览器级的 CDP 连接。线程安全（内部串行化）。"""

    def __init__(self, ws_url: str, timeout: float = DEFAULT_CALL_TIMEOUT) -> None:
        self.ws_url = ws_url
        self.timeout = timeout
        self._lock = threading.RLock()
        self._counter = 0
        try:
            # suppress_origin 是必须的：默认会带 Origin 头，Chrome 会以
            # 403 "Rejected an incoming WebSocket connection" 拒绝。
            self._ws = websocket.create_connection(
                ws_url, timeout=timeout, suppress_origin=True
            )
        except Exception as exc:  # noqa: BLE001
            raise CDPError(f"无法连接 CDP（{ws_url}）：{exc}") from exc

    # ---------- 基础 ----------

    def call(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        """发一条 CDP 命令并等它的响应。期间收到的事件一律丢弃。"""
        with self._lock:
            self._counter += 1
            message_id = self._counter
            payload: dict[str, Any] = {"id": message_id, "method": method, "params": params or {}}
            if session_id:
                payload["sessionId"] = session_id

            try:
                self._ws.send(json.dumps(payload))
            except Exception as exc:  # noqa: BLE001
                raise CDPError(f"CDP 发送失败（{method}）：{exc}") from exc

            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CDPError(f"CDP 调用超时（{method}）")
                self._ws.settimeout(remaining)
                try:
                    raw = self._ws.recv()
                except websocket.WebSocketTimeoutException as exc:
                    raise CDPError(f"CDP 调用超时（{method}）") from exc
                except Exception as exc:  # noqa: BLE001
                    raise CDPError(f"CDP 接收失败（{method}）：{exc}") from exc

                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                if data.get("id") != message_id:
                    continue  # 事件或别人的响应，丢掉
                if "error" in data:
                    raise CDPError(f"{method} 失败：{data['error']}")
                return data.get("result", {})

    # ---------- 标签页 ----------

    def new_page(self, url: str = "about:blank", *, background: bool = True) -> CDPTab:
        """新建一个标签页。

        `background=True`（默认）让它**不抢焦点** —— 用户正在看的页面不会被顶掉。
        这是本客户端的核心价值，Playwright 做不到。
        """
        result = self.call("Target.createTarget", {"url": url, "background": background})
        target_id = result["targetId"]
        attached = self.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = attached["sessionId"]
        tab = CDPTab(self, target_id, session_id)
        # 打开页面事件，才能拿到 loadEventFired 之类；不影响 evaluate
        try:
            tab.call("Page.enable")
            tab.call("Runtime.enable")
        except CDPError:
            pass
        return tab

    def close_target(self, target_id: str) -> None:
        self.call("Target.closeTarget", {"targetId": target_id})

    def targets(self) -> list[dict]:
        return self.call("Target.getTargets").get("targetInfos", [])

    def version(self) -> str:
        """浏览器版本串，例如 "Chrome/144.0.7559.132"。"""
        result = self.call("Browser.getVersion")
        return result.get("product", "")

    def close(self) -> None:
        with self._lock:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass


def ws_url_for(cdp_base: str, timeout: float = 5.0) -> str:
    """从 CDP 的 HTTP 端点拿到 WebSocket 地址。"""
    import urllib.error

    url = cdp_base.rstrip("/") + "/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CDPError(f"无法读取 CDP 版本信息（{url}）：{exc}") from exc
    ws = data.get("webSocketDebuggerUrl")
    if not ws:
        raise CDPError(f"CDP 未提供 webSocketDebuggerUrl：{data}")
    return ws
