#!/usr/bin/env python3
"""启动器与后端选择的离线测试。

不访问 HLTV、不启动浏览器，只测那些纯逻辑与本地探测：
后端选择、显示环境判断、CDP 端点探测、端口选择、浏览器定位的优先级。

    python tests/test_launcher.py
"""

from __future__ import annotations

import http.server
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hltv_mcp import client as C  # noqa: E402
from hltv_mcp import launcher as L  # noqa: E402

failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}: 得到 {got!r}，期望 {want!r}")
        failures.append(name)


def _serve_cdp(payload: bytes, status: int = 200):
    """起一个极小的 HTTP 服务当假的 CDP 端点，返回 (url, shutdown)。"""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # 静音
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}", server.shutdown


def main() -> int:
    print("--- 1. 后端选择 ---")
    original = C.BACKEND
    for backend, want in [("auto", True), ("browser", True), ("http", False)]:
        C.BACKEND = backend
        check(f"HLTV_BACKEND={backend} -> 用浏览器={want}", C.wants_browser(), want)
    C.BACKEND = original

    # 未配置时（auto）应默认走浏览器 —— 这是本次改动的核心
    C.BACKEND = "auto"
    fake = C.HltvClient()
    check("auto 模式默认标记为浏览器后端", fake.backend_in_use, "browser")
    C.BACKEND = "http"
    fake = C.HltvClient()
    check("http 模式标记为 HTTP 后端", fake.backend_in_use, "http")
    C.BACKEND = original

    print("\n--- 2. 显示环境判断 ---")
    check("空 DISPLAY 视为无显示", L._display_ok(""), False)
    check("localhost:10 交给远端判断", L._display_ok("localhost:10"), True)
    check("指向不存在的 X socket", L._display_ok(":77"), False)
    # 真造一个 socket 文件，确认能被认出来
    probe_dir = "/tmp/.X11-unix"
    made = None
    if os.path.isdir(probe_dir):
        made = os.path.join(probe_dir, "X77")
        try:
            open(made, "w").close()
            check("X socket 存在则视为有显示", L._display_ok(":77"), True)
        finally:
            try:
                os.unlink(made)
            except OSError:
                pass

    # Termux 把临时目录放在 $TMPDIR 而不是 /tmp，X socket 也跟着在那里。
    # 只查 /tmp 会在真机上把「已经起来的虚拟显示」误判成失败。
    import tempfile  # noqa: PLC0415

    saved_env = {k: os.environ.get(k) for k in ("TMPDIR", "PREFIX")}
    with tempfile.TemporaryDirectory() as tmp:
        sock_dir = os.path.join(tmp, ".X11-unix")
        os.makedirs(sock_dir, exist_ok=True)
        open(os.path.join(sock_dir, "X77"), "w").close()
        os.environ["TMPDIR"] = tmp
        try:
            check("能识别 TMPDIR 下的 X socket",
                  L._x_socket_path(77) is not None, True)
            check("DISPLAY 指向 TMPDIR 下的 socket 时判定可用",
                  L._display_ok(":77"), True)
            check("TMPDIR 参与候选目录",
                  any(str(tmp) in str(d) for d in L._x_socket_dirs()), True)
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    check("候选目录始终含 /tmp/.X11-unix",
          any(str(d) == "/tmp/.X11-unix" for d in L._x_socket_dirs()), True)

    print("\n--- 3. CDP 端点探测 ---")
    url, stop = _serve_cdp(b'{"Browser": "Chrome/999", "webSocketDebuggerUrl": "ws://x"}')
    try:
        info = L.cdp_info(url)
        check("能识别活的 CDP 端点", (info or {}).get("Browser"), "Chrome/999")
    finally:
        stop()

    url, stop = _serve_cdp(b"nope", status=403)
    try:
        check("403 不算 CDP 端点", L.cdp_info(url), None)
    finally:
        stop()

    # 关掉的端口
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    check("关掉的端口返回 None", L.cdp_info(f"http://127.0.0.1:{dead_port}", timeout=0.5), None)

    print("\n--- 4. 端口选择 ---")
    port = L._pick_port()
    check("选出的端口确实是空闲的", L._port_free(port), True)

    # 占住默认端口后，应换一个
    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        holder.bind(("127.0.0.1", L.DEFAULT_PORT))
        holder.listen(1)
        occupied = True
    except OSError:
        occupied = False  # 端口已被别的进程占着，同样算「不空闲」
    if occupied or not L._port_free(L.DEFAULT_PORT):
        check("默认端口被占时会换端口", L._pick_port() != L.DEFAULT_PORT, True)
    holder.close()

    print("\n--- 5. 候选地址顺序 ---")
    launcher = L.ChromeLauncher()
    os.environ.pop("HLTV_BROWSER_CDP", None)
    candidates = launcher._candidates()
    check("默认含 9222", f"http://127.0.0.1:{L.DEFAULT_PORT}" in candidates, True)
    check("默认端口排最前", candidates[0], f"http://127.0.0.1:{L.DEFAULT_PORT}")
    os.environ["HLTV_BROWSER_CDP"] = "http://127.0.0.1:9333"
    candidates = launcher._candidates()
    check("显式配置优先于默认端口", candidates[0], "http://127.0.0.1:9333")
    check("候选地址无重复", len(candidates), len(set(candidates)))
    os.environ.pop("HLTV_BROWSER_CDP", None)

    print("\n--- 6. 浏览器定位 ---")
    binary = L.find_browser()
    check("能在本机找到浏览器（找不到也算通过，只是说明环境无浏览器）",
          binary is None or os.path.exists(binary), True)

    # HLTV_CHROME_BIN 指向不存在的文件时，要报错而不是静默返回 None
    os.environ["HLTV_CHROME_BIN"] = "/nonexistent/chrome-for-test"
    try:
        L.find_browser()
        check("HLTV_CHROME_BIN 无效时应报错", "no-raise", "raise")
    except C.BrowserUnavailable as exc:
        check("HLTV_CHROME_BIN 无效时报 BrowserUnavailable",
              "不存在" in str(exc), True)
    finally:
        os.environ.pop("HLTV_CHROME_BIN", None)

    print("\n--- 7. 错误类型分层（决定 auto 会不会降级）---")
    check("BrowserUnavailable 是 HltvError 的子类",
          issubclass(C.BrowserUnavailable, C.HltvError), True)

    print("\n--- 8. Termux / Android 识别 ---")
    saved = {k: os.environ.get(k) for k in ("TERMUX_VERSION", "PREFIX", "HLTV_CHROME_BIN")}
    try:
        os.environ.pop("TERMUX_VERSION", None)
        os.environ.pop("PREFIX", None)
        check("普通环境不是 Termux", L._is_termux(), False)

        os.environ["TERMUX_VERSION"] = "0.118.0"
        check("有 TERMUX_VERSION 即识别", L._is_termux(), True)
        os.environ.pop("TERMUX_VERSION")

        os.environ["PREFIX"] = "/data/data/com.termux/files/usr"
        check("靠 PREFIX 路径也能识别", L._is_termux(), True)

        check("Termux 浏览器路径含 chromium-browser",
              "/data/data/com.termux/files/usr/bin/chromium-browser" in L._termux_candidates(),
              True)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("\n--- 9. 默认在界面上不可见 ---")
    # 屏蔽真实的 Xvfb 启动，只验计划本身
    saved_start = L._VirtualDisplay.start
    L._VirtualDisplay.start = lambda self: None
    saved_visible = os.environ.pop("HLTV_BROWSER_VISIBLE", None)
    saved_headless = os.environ.pop("HLTV_BROWSER_HEADLESS", None)
    try:
        plans = L.ChromeLauncher()._plan_attempts()
        labels = " | ".join(p["label"] for p in plans)
        check("默认不含「窗口可见」的选项", "窗口可见" not in labels, True)
        check("默认不含无头优先", plans[0]["headless"], False)
        check("首选是有头模式", plans[0]["headless"], False)

        os.environ["HLTV_BROWSER_VISIBLE"] = "1"
        plans = L.ChromeLauncher()._plan_attempts()
        labels = " | ".join(p["label"] for p in plans)
        check("显式要求可见时才允许窗口显示", "窗口可见" in labels, True)
        os.environ.pop("HLTV_BROWSER_VISIBLE")

        os.environ["HLTV_BROWSER_HEADLESS"] = "1"
        plans = L.ChromeLauncher()._plan_attempts()
        check("强制无头时只有无头方案", len(plans), 1)
        check("强制无头为首选", plans[0]["headless"], True)
    finally:
        L._VirtualDisplay.start = saved_start
        os.environ.pop("HLTV_BROWSER_HEADLESS", None)
        if saved_visible is not None:
            os.environ["HLTV_BROWSER_VISIBLE"] = saved_visible
        if saved_headless is not None:
            os.environ["HLTV_BROWSER_HEADLESS"] = saved_headless

    print("\n--- 10. CDP 客户端的地址解析 ---")
    from hltv_mcp import cdp as Cdp  # noqa: PLC0415

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    try:
        Cdp.ws_url_for(f"http://127.0.0.1:{dead_port}", timeout=0.5)
        check("坏地址应抛 CDPError", "no-raise", "raise")
    except Cdp.CDPError:
        check("坏地址抛 CDPError", True, True)

    url, stop = _serve_cdp(b'{"Browser": "x"}')  # 没有 webSocketDebuggerUrl
    try:
        Cdp.ws_url_for(url)
        check("缺 webSocketDebuggerUrl 应抛错", "no-raise", "raise")
    except Cdp.CDPError:
        check("缺 webSocketDebuggerUrl 抛 CDPError", True, True)
    finally:
        stop()

    url, stop = _serve_cdp(b'{"webSocketDebuggerUrl": "ws://127.0.0.1:1/x"}')
    try:
        check("能取出 webSocketDebuggerUrl",
              Cdp.ws_url_for(url), "ws://127.0.0.1:1/x")
    finally:
        stop()

    print("\n--- 11. profile 死锁自愈 ---")
    # 场景：浏览器被 kill -9 之后，profile 里会留下指向「已经不存在的 pid」的
    # SingletonLock，此后 Chrome 每次启动都以退出码 21 秒退，浏览器后端永久
    # 起不来、悄悄降级到 HTTP。这里确认清理逻辑只在进程真的没了时才动手。
    import tempfile as _tempfile  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    saved_profile = L.PROFILE_DIR
    with _tempfile.TemporaryDirectory() as tmp:
        L.PROFILE_DIR = _Path(tmp)
        lock = L.PROFILE_DIR / "SingletonLock"
        cookie = L.PROFILE_DIR / "SingletonCookie"

        check("没有锁时安静返回", L._clear_stale_profile_lock(), None)

        # 活锁：指向当前进程，绝不能删
        lock.symlink_to(f"somehost-{os.getpid()}")
        check("活锁不清理", L._clear_stale_profile_lock(), None)
        check("活锁被保留", lock.is_symlink(), True)

        # 死锁：指向一个肯定不存在的 pid
        lock.unlink()
        lock.symlink_to("somehost-999999")
        cookie.symlink_to("12345")
        note = L._clear_stale_profile_lock()
        check("死锁被清理且说明里带上原 pid", bool(note) and "999999" in str(note), True)
        check("死锁文件已删除", lock.is_symlink(), False)
        check("Cookie 一并清掉", cookie.is_symlink(), False)
    L.PROFILE_DIR = saved_profile

    print()
    if failures:
        print(f"{len(failures)} 项失败：{', '.join(failures)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
