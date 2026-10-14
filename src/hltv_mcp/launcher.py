"""自动启动并接管一个带远程调试端口的 Chrome。

为什么需要它
------------
本项目的默认后端是「完整浏览器」（`HLTV_BACKEND=auto`），因为只有真实浏览器能
稳定穿过 Cloudflare，也只有它能做点击这类交互（见 `browser.py`）。

但默认后端不能要求用户先手动敲一条 `--remote-debugging-port=9222` 的命令 ——
那等于开箱即坏。所以这里负责把浏览器准备好：

  1. 若用户已经用调试端口开着浏览器（或指定了 `HLTV_BROWSER_CDP`），直接用他的
  2. 否则自己拉起一个 Chrome，等它把 CDP 端点准备好，再交给 `BrowserFetcher`
  3. 进程退出时，**只关掉自己拉起的那个实例**

关键取舍
--------
**用独立的用户数据目录，绝不复用用户日常的 profile。**
原因有两个：一是拿用户 profile 去开调试端口有隐私与安全问题；二是 Chrome 在
同 profile 已有实例运行时，新进程只会把标签页塞进旧实例，调试端口根本不会打开。
独立目录还带来一个好处：它是**持久**的，`cf_clearance` 这类 cookie 会留存在里面，
下次启动时 Cloudflare 的挑战会明显更少。

**有头优先。** 桌面系统上有头浏览器最接近真实用户，判定最宽松。只有在没有图形
显示（无 `DISPLAY` 的 Linux）时才退回 `--headless=new`。
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .client import BrowserUnavailable

# 默认调试端口。若被非 CDP 服务占用，会自动换一个空闲端口。
DEFAULT_PORT = int(os.environ.get("HLTV_BROWSER_PORT", "9222"))

# 启动后等待 CDP 端点就绪的上限（秒）。冷启动（首次建 profile）可能偏慢。
STARTUP_TIMEOUT = float(os.environ.get("HLTV_BROWSER_STARTUP_TIMEOUT", "45"))

# 是否允许自动拉起浏览器。关掉后只复用已经开着的实例。
AUTOLAUNCH = os.environ.get("HLTV_BROWSER_AUTOLAUNCH", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _default_cache_dir() -> Path:
    """按平台惯例给一个缓存目录，用于存放独立的浏览器 profile。"""
    override = os.environ.get("HLTV_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "hltv-mcp"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "hltv-mcp"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "hltv-mcp"


CACHE_DIR = _default_cache_dir()
PROFILE_DIR = Path(
    os.environ.get("HLTV_CHROME_PROFILE") or (CACHE_DIR / "chrome-profile")
).expanduser()
LOG_FILE = CACHE_DIR / "chrome.log"
PORT_FILE = CACHE_DIR / "cdp-port"  # 记下我们自己拉起的那个端口，供后续进程复用


# --------------------------- 浏览器可执行文件定位 ---------------------------

_MAC_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

_WIN_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

_LINUX_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "brave-browser",
]


def _playwright_chromium() -> str | None:
    """Playwright 自带的 Chromium，作为最后的兜底。

    注意：这里只是**拿它的可执行文件**，仍然由我们自己用 subprocess 启动，
    因此不会带上 Playwright 那套自动化标志（那才是被 Cloudflare 识别的根因）。
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
        return path if path and Path(path).exists() else None
    except Exception:  # noqa: BLE001 - 没装或没下载浏览器都只是「不可用」
        return None


def find_browser() -> str | None:
    """定位一个可用的 Chrome / Chromium / Edge。"""
    explicit = os.environ.get("HLTV_CHROME_BIN")
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return str(path)
        raise BrowserUnavailable(f"HLTV_CHROME_BIN 指向的文件不存在：{path}")

    if sys.platform == "darwin":
        for candidate in _MAC_CANDIDATES:
            if Path(candidate).exists():
                return candidate
    elif os.name == "nt":
        win_candidates = list(_WIN_CANDIDATES)
        local = os.environ.get("LOCALAPPDATA")
        if local:
            win_candidates.insert(0, str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"))
        for candidate in win_candidates:
            if Path(candidate).exists():
                return candidate
    else:
        import shutil

        for name in _LINUX_CANDIDATES:
            found = shutil.which(name)
            if found:
                return found

    return _playwright_chromium()


# --------------------------- CDP 端点探测 ---------------------------

def cdp_info(url: str, timeout: float = 2.0) -> dict | None:
    """探测一个地址是否是活的 CDP 端点。是则返回 /json/version 的内容。"""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _port_free(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_port() -> int:
    """选一个既空闲、又不是「被别的服务占着」的端口。"""
    if _port_free(DEFAULT_PORT):
        return DEFAULT_PORT
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _task_spawn(args, **kwargs):
    """统一的进程启动入口，便于集中处理平台差异。"""
    return subprocess.Popen(args, **kwargs)  # noqa: S603 - 路径来自本机探测或用户显式指定


def _display_ok(display: str) -> bool:
    """`DISPLAY` 里写的那个显示是否真的可用。

    不能只看变量有没有值：容器、SSH 转发残留、CI 里这个变量经常存在，
    但对应的 X 服务早就没了。这种情况下有头启动会立刻失败。
    """
    if not display:
        return False
    if display.startswith(":") and display[1:].split(".")[0].isdigit():
        return Path(f"/tmp/.X11-unix/X{display[1:].split('.')[0]}").exists()
    if display.startswith("localhost:") or display[0].isdigit():
        # 远程 X（host:0）无法用文件判断，交给启动失败重试兜底
        return True
    return False


# --------------------------- 虚拟显示（Xvfb） ---------------------------

class _VirtualDisplay:
    """在没有图形显示的机器上，用 Xvfb 造一个。

    为什么需要它：**无头浏览器会被 Cloudflare 拦**。实测同一环境、同一 IP、
    同一份代码，`--headless=new` 全部停在挑战页，改为有头（哪怕是 Xvfb 造的
    虚拟显示）则三个页面全部 200，包含 964KB 的逐年统计页。

    所以「没有显示器」不能直接退化成无头 —— 那等于静默失效。正确做法是补一个
    虚拟显示，让浏览器仍以有头模式运行。
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self.display: str | None = None

    @staticmethod
    def available() -> str | None:
        import shutil

        return shutil.which("Xvfb")

    def start(self) -> str | None:
        """拉起 Xvfb 并返回它的 `DISPLAY` 值；没有 Xvfb 则返回 None。"""
        binary = self.available()
        if not binary:
            return None

        for number in range(99, 120):
            display = f":{number}"
            if Path(f"/tmp/.X11-unix/X{number}").exists():
                continue
            proc = _task_spawn(
                [binary, display, "-screen", "0", "1440x900x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            # 等 socket 出现，最多 10 秒
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if Path(f"/tmp/.X11-unix/X{number}").exists():
                    self._process = proc
                    self.display = display
                    return display
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return None

    def stop(self) -> None:
        proc = self._process
        self._process = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


# --------------------------- 启动器 ---------------------------

class ChromeLauncher:
    """保证「有一个可用的 CDP 端点」，必要时自己拉起浏览器。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._url: str | None = None
        self._process: subprocess.Popen | None = None
        self._virtual_display: _VirtualDisplay | None = None
        self._launched_by_us = False
        self._mode: str | None = None
        self._registered = False

    # ---------- 对外 ----------

    def ensure(self) -> str:
        """返回一个可用的 CDP 地址，必要时把浏览器拉起来。"""
        with self._lock:
            if self._url and cdp_info(self._url):
                return self._url

            for url in self._candidates():
                if cdp_info(url):
                    self._url = url
                    self._launched_by_us = False
                    return url

            if not AUTOLAUNCH:
                raise BrowserUnavailable(
                    "没有检测到带调试端口的浏览器，且已禁用自动启动"
                    "（HLTV_BROWSER_AUTOLAUNCH=0）。请手动用 "
                    f"--remote-debugging-port={DEFAULT_PORT} 启动 Chrome，"
                    "或设置 HLTV_BROWSER_CDP 指向已有实例。"
                )

            self._url = self._launch()
            return self._url

    def shutdown(self) -> None:
        """关掉自己拉起的浏览器与虚拟显示。用户自己的实例绝不动。"""
        with self._lock:
            proc = self._process
            self._process = None
            self._url = None
            self._mode = None

            if proc is not None and self._launched_by_us and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=8)
                except Exception:  # noqa: BLE001 - 收尾失败不值得影响退出
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass

            self._launched_by_us = False

            # 虚拟显示是我们造的，跟着一起收掉
            if self._virtual_display is not None:
                self._virtual_display.stop()
                self._virtual_display = None

    @property
    def launched_by_us(self) -> bool:
        return self._launched_by_us

    # ---------- 内部 ----------

    def _candidates(self) -> list[str]:
        """可能已经在跑的 CDP 地址，按优先级排。"""
        urls: list[str] = []
        explicit = os.environ.get("HLTV_BROWSER_CDP", "").strip()
        if explicit:
            urls.append(explicit)
        urls.append(f"http://127.0.0.1:{DEFAULT_PORT}")

        # 自己上次拉起的端口（换个进程再跑时能直接复用，避免又开一个窗口）
        try:
            remembered = PORT_FILE.read_text(encoding="utf-8").strip()
            if remembered:
                urls.append(f"http://127.0.0.1:{remembered}")
        except OSError:
            pass

        seen: set[str] = set()
        return [u for u in urls if not (u in seen or seen.add(u))]

    def _launch(self) -> str:
        binary = find_browser()
        if not binary:
            raise BrowserUnavailable(
                "找不到 Chrome / Chromium / Edge。请安装其中之一，或用 "
                "HLTV_CHROME_BIN 指定可执行文件路径；也可以设置 HLTV_BROWSER_CDP "
                "复用一个已经开着的浏览器。"
            )

        errors: list[str] = []
        for attempt in self._plan_attempts():
            try:
                return self._spawn(binary, **attempt)
            except BrowserUnavailable as exc:
                errors.append(f"{attempt['label']}：{exc}")
                # 换下一次尝试前，先把这个显示环境收掉，避免留下孤儿 Xvfb
                if self._virtual_display is not None and attempt.get("display") == self._virtual_display.display:
                    self._virtual_display.stop()
                    self._virtual_display = None

        raise BrowserUnavailable(
            "浏览器启动失败。\n  " + "\n  ".join(errors) + f"\n  完整日志：{LOG_FILE}"
        )

    def _plan_attempts(self) -> list[dict]:
        """准备若干种启动方案，按优先级排列。

        有头优先，因为**无头会被 Cloudflare 拦**（实测：同环境同 IP，无头全部停在
        挑战页，有头全部 200）。所以「没有显示器」时先造一个虚拟显示，而不是
        直接退化成无头 —— 那等于静默失效。
        """
        forced = os.environ.get("HLTV_BROWSER_HEADLESS")
        if forced is not None and forced.strip().lower() in ("1", "true", "yes", "on"):
            return [{"headless": True, "display": None, "label": "无头模式（由 HLTV_BROWSER_HEADLESS 指定）"}]

        attempts: list[dict] = []

        # 1. 现成的显示环境
        current = os.environ.get("DISPLAY", "").strip()
        if _display_ok(current):
            attempts.append({"headless": False, "display": None, "label": "有头模式"})

        # 2. 自己造一个虚拟显示（Linux 且装了 Xvfb）
        if sys.platform.startswith("linux"):
            if self._virtual_display is None:
                self._virtual_display = _VirtualDisplay()
            display = self._virtual_display.start()
            if display:
                attempts.append(
                    {
                        "headless": False,
                        "display": display,
                        "label": f"有头模式 + 虚拟显示（Xvfb {display}）",
                    }
                )

        # 3. 最后才考虑无头。它很可能被 Cloudflare 拦，但至少能连上 CDP；
        #    在某些网络环境下无头也能过，所以不作为首选但保留。
        attempts.append({"headless": True, "display": None, "label": "无头模式（可能被 Cloudflare 拦截）"})
        return attempts

    def _spawn(self, binary: str, *, headless: bool, display: str | None, label: str) -> str:
        port = _pick_port()
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        args = [
            binary,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-translate",
            "--window-size=1440,900",
        ]
        if headless:
            args.append("--headless=new")
        if os.name == "nt" or sys.platform == "darwin":
            # 独立 profile 在桌面系统上会弹钥匙串相关提示，用 mock 更安静
            args.append("--use-mock-keychain")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            # 容器 / 沙箱里以 root 跑时必须关掉沙箱，否则 Chrome 起不来
            args.append("--no-sandbox")
        if Path("/.dockerenv").exists():
            # 容器内 /dev/shm 通常很小，不关掉容易崩
            args.append("--disable-dev-shm-usage")

        env = None
        if display:
            env = {**os.environ, "DISPLAY": display}

        log = open(LOG_FILE, "ab")  # noqa: SIM115 - 生命周期与子进程一致，交给 subprocess 持有
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

        try:
            proc = _task_spawn(
                args,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
                creationflags=creationflags,
                env=env,
            )
        except OSError as exc:
            raise BrowserUnavailable(f"无法执行 {binary}：{exc}") from exc

        self._process = proc
        self._launched_by_us = True
        self._mode = label
        self._register_cleanup()

        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if cdp_info(url, timeout=1.0):
                try:
                    PORT_FILE.write_text(str(port), encoding="utf-8")
                except OSError:
                    pass
                return url
            if proc.poll() is not None:
                raise BrowserUnavailable(f"启动后立刻退出（退出码 {proc.returncode}）")
            time.sleep(0.4)

        raise BrowserUnavailable(f"等待调试端口超时（{STARTUP_TIMEOUT:.0f}s，端口 {port}）")

    @property
    def mode(self) -> str | None:
        """实际生效的启动方式描述，供自检脚本显示。"""
        return self._mode

    def _register_cleanup(self) -> None:
        if self._registered:
            return
        atexit.register(self.shutdown)
        self._registered = True


_launcher: ChromeLauncher | None = None
_launcher_lock = threading.Lock()


def get_launcher() -> ChromeLauncher:
    global _launcher
    with _launcher_lock:
        if _launcher is None:
            _launcher = ChromeLauncher()
        return _launcher
