#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# hltv-mcp 离线安装 —— 零编译、零 PyPI 访问
# ============================================================
# 本目录已经包含运行所需的全部 Python wheel：
#   · 纯 Python wheel（跨平台，与设备无关）
#   · pydantic_core-*-cp314-cp314-android_24_arm64_v8a.whl
#     ← 唯一带原生代码的依赖，Android ARM64 ABI，来自 TUR 预编译
#   · setuptools —— pip install -e . 的构建后端，见步骤 4 的说明
# 因此整个过程不会触发任何本地编译。
#
# 仍需联网的部分只有 Termux 系统包（chromium 等，来自 Termux 官方 apt 源），
# 它们是预编译 .deb，本来就不编译。
#
# 用法：
#   bash install.sh
# 可选环境变量：
#   APP_DIR=/path/to/install   安装位置（默认 $HOME/hltv-mcp）
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${APP_DIR:-$HOME/hltv-mcp}"

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

# Termux 的镜像探测偶发抖动，pkg install 失败一次不代表真失败。
# 但也不宜吞掉错误 —— 重试一次仍失败就交给 set -e 中止。
pkg_install() {
    pkg install -y "$@" && return 0
    warn "pkg install $* 失败，刷新索引后重试一次"
    pkg update -y >/dev/null 2>&1 || true
    pkg install -y "$@"
}

# ── 0 ────────────────────────────────────────────────────────
say "步骤 0/5  校验 wheel 完整性"
if [ -f "$HERE/SHA256SUMS" ] && command -v sha256sum >/dev/null 2>&1; then
    if (cd "$HERE" && sha256sum -c --quiet SHA256SUMS); then
        echo "    ✅ 全部 $(ls "$HERE/wheels"/*.whl | wc -l) 个 wheel 校验通过"
    else
        warn "校验失败：wheel 可能下载不全或已损坏，建议重新获取压缩包"
        warn "（这是防传输损坏，不是防篡改——防篡改请比对 Release 页公布的 tar.gz 校验值）"
        exit 1
    fi
else
    warn "找不到 SHA256SUMS 或系统无 sha256sum，跳过校验"
fi

# ── 1 ────────────────────────────────────────────────────────
say "步骤 1/5  安装系统包（预编译 .deb，不触发编译）"
# pkg update 单独容错：镜像抖动不该让整个安装在第一步就挂掉
pkg update -y || warn "pkg update 失败，继续尝试安装；若后续报错请先执行 termux-change-repo 换镜像"

pkg_install python
# chromium 与 xorg-server-xvfb 在 TUR，需先启用源
pkg_install tur-repo x11-repo
# 启用新源后刷新一次索引，chromium 才能被找到
pkg update -y || warn "刷新索引失败，继续尝试安装 chromium"
# 三个原本要在手机上从源码编译的包，改用官方预编译版：
pkg_install python-lxml python-cryptography python-rpds-py
# 浏览器后端必需。约 150MB，是体积大头，Termux 上无法绕开：
# HTTP 后端要的 curl_cffi 需要编译 curl-impersonate + BoringSSL，基本编不出来。
pkg_install chromium xorg-server-xvfb

# ── 2 ────────────────────────────────────────────────────────
say "步骤 2/5  释放项目代码"
if [ -e "$APP_DIR" ]; then
    warn "$APP_DIR 已存在，跳过复制（保留你已有的改动）"
else
    cp -r "$HERE/hltv-mcp" "$APP_DIR"
    echo "    已复制到 $APP_DIR"
fi

# ── 3 ────────────────────────────────────────────────────────
say "步骤 3/5  创建虚拟环境"
# 关键：--system-site-packages 让 venv 直接复用 apt 装的
# lxml / cryptography / rpds_py，pip 就不会去 PyPI 找它们的源码包编译。
# （顺带：apt 版 cryptography 不依赖 cffi，所以 cffi 也不会被要求安装。）
python -m venv --system-site-packages "$APP_DIR/.venv"
VENV_PY="$APP_DIR/.venv/bin/python"

# ── 4 ────────────────────────────────────────────────────────
say "步骤 4/5  从本地 wheel 安装依赖"
# 构建后端必须单独先装：`pip install -e .` 用 setuptools.build_meta，
# 而 Python 3.12+ 的 ensurepip 不再附带 setuptools，venv 里根本没有它，
# Termux 的系统 Python 也没有。配合下面的 --no-build-isolation，
# 不先装就会报 BackendUnavailable: Cannot import 'setuptools.build_meta'。
#
# 只装 setuptools，不装 wheel：
#   · setuptools 84 自身没有任何运行时依赖（其余 requires 全带 extra 标记）
#   · 而 wheel 依赖 packaging，后者不在本包里，装了反而会连带失败
#   · setuptools >= 70.1 已内置构建 wheel 的能力，不需要独立的 wheel 包
"$VENV_PY" -m pip install --no-index --find-links "$HERE/wheels" \
    --only-binary=:all: setuptools

# --no-index：完全不访问 PyPI，只用本目录的 wheel
# --only-binary：确保不会静默退回「下源码包在手机上编译」
if ! "$VENV_PY" -m pip install --no-index --find-links "$HERE/wheels" \
        --only-binary=:all: \
        "mcp>=2.0" "websocket-client>=1.6" "beautifulsoup4>=4.12"; then
    warn "严格 wheel-only 安装失败，去掉该限制重试"
    "$VENV_PY" -m pip install --no-index --find-links "$HERE/wheels" \
        "mcp>=2.0" "websocket-client>=1.6" "beautifulsoup4>=4.12"
fi

# 项目本体：--no-build-isolation 防止 pip 去下载构建后端（离线环境会失败）
"$VENV_PY" -m pip install --no-index --no-deps --no-build-isolation -e "$APP_DIR"

# ── 5 ────────────────────────────────────────────────────────
say "步骤 5/5  自检"
"$VENV_PY" - <<'PY'
from importlib.metadata import version
for p in ("pydantic-core", "lxml", "cryptography", "rpds-py", "mcp"):
    try:
        print(f"    {p:14s} {version(p)}")
    except Exception:
        print(f"    {p:14s} <缺失>")
PY

if "$VENV_PY" -c "import hltv_mcp.client, hltv_mcp.server" 2>/dev/null; then
    echo "    ✅ 模块导入正常"
    "$VENV_PY" -c "import hltv_mcp.client as c; print('    后端 =', c.BACKEND, '| 需要浏览器 =', c.wants_browser())"
else
    warn "模块导入失败，请贴出上面 pip 的输出以便排查"
fi

cat <<EOF

──────────────────────────────────────────────
安装完成（全程未编译任何东西）。

把下面这段加进你的 MCP 客户端配置：

{
  "mcpServers": {
    "hltv": {
      "command": "$APP_DIR/.venv/bin/python",
      "args": ["-m", "hltv_mcp"],
      "env": {
        "PYTHONPATH": "$APP_DIR/src",
        "HLTV_CHALLENGE_WAIT": "120"
      }
    }
  }
}

关于 HLTV_CHALLENGE_WAIT：部分网络出口首次访问 HLTV 时，
Cloudflare 挑战可能远超默认的 25 秒（实测中国联通出口约需 120 秒）。
调大它可以避免首次查询直接超时；挑战一旦通过、cf_clearance 落盘，
后续启动走热路径就很快了。

验证浏览器后端是否可用：
  cd $APP_DIR && .venv/bin/python scripts/browser_check.py
──────────────────────────────────────────────
EOF
