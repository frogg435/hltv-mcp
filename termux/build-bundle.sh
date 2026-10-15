#!/usr/bin/env bash
# ============================================================
# build-bundle.sh —— 构建 hltv-mcp Termux 离线包（可复现）
# ============================================================
# 在任意一台有网络与 python3 的 Linux/macOS 上运行即可，
# **不需要** Termux 设备，也不需要 Android NDK：
# 唯一的原生产物（pydantic_core）直接取 TUR 的预编译 wheel。
#
# 用法：
#   bash termux/build-bundle.sh [输出目录]
#   # 默认输出到 ./dist/
#
# 产出：
#   dist/hltv-mcp-termux-offline.tar.gz
#   dist/SHA256SUMS
#
# 可复现性：固定 mtime / 属主 / 排序，gzip 不写时间戳，
# 相同输入两次构建的 SHA256 应完全一致。
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$REPO_ROOT/dist}"
BUNDLE_NAME="hltv-mcp-termux-offline"
STAGE="$(mktemp -d)"
PKG_DIR="$STAGE/$BUNDLE_NAME"

# 唯一的原生依赖。版本必须与 requirements-termux.txt 中 pydantic 所锁定的
# pydantic-core 一致，否则安装时会解析失败。
PYDANTIC_CORE_VERSION="2.50.1"
PYDANTIC_CORE_WHEEL="pydantic_core-${PYDANTIC_CORE_VERSION}-cp314-cp314-android_24_arm64_v8a.whl"
PYDANTIC_CORE_URL="https://github.com/tur-pypi-dists/python3.14-pydantic_core/releases/download/v${PYDANTIC_CORE_VERSION}/${PYDANTIC_CORE_WHEEL}"

# 固定时间戳，保证可复现（不能用构建时刻）
MTIME='UTC 2026-01-01'

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$PKG_DIR/wheels" "$OUT_DIR"

# ── 1. 纯 Python wheel ───────────────────────────────────────
say "1/6  下载纯 Python 依赖"
python3 -m pip download --no-deps --only-binary=:all: --quiet \
    -d "$PKG_DIR/wheels" -r "$REPO_ROOT/termux/requirements-termux.txt"

# 交叉校验：这些必须是 py3-none-any，否则说明锁的文件里混进了平台相关的包
bad="$(find "$PKG_DIR/wheels" -name '*.whl' ! -name '*-py3-none-any.whl' ! -name '*-py2.py3-none-any.whl')"
[ -z "$bad" ] || die "requirements-termux.txt 里混入了非纯 Python 包：$(echo "$bad" | tr '\n' ' ')"
echo "    ✅ 全部 $(find "$PKG_DIR/wheels" -name '*.whl' | wc -l) 个均为 py3-none-any"

# ── 2. 原生 wheel ────────────────────────────────────────────
say "2/6  下载 Android ARM64 原生 wheel（pydantic_core）"
echo "    来源：TUR PyPI / tur-pypi-dists"
curl -fsSL "$PYDANTIC_CORE_URL" -o "$PKG_DIR/wheels/$PYDANTIC_CORE_WHEEL" \
    || die "下载失败。注意：github.com 在部分网络下不可达，可改用
        https://api.github.com/repos/tur-pypi-dists/python3.14-pydantic_core/releases/assets/<id>
        并以 Accept: application/octet-stream 取值。"

python3 - "$PKG_DIR/wheels/$PYDANTIC_CORE_WHEEL" <<'PY'
import struct, sys, zipfile
p = sys.argv[1]
z = zipfile.ZipFile(p)
assert z.testzip() is None, "wheel 已损坏"
so = [n for n in z.namelist() if n.endswith(".so")]
assert so, "wheel 里没有原生库"
d = z.read(so[0])
machine = struct.unpack("<H", d[18:20])[0]
assert machine == 0xB7, f"不是 AArch64（e_machine={machine:#x}）"
tag = [l for l in z.read(
    [n for n in z.namelist() if n.endswith("WHEEL")][0]).decode().splitlines()
    if l.startswith("Tag:")]
print(f"    ✅ {so[0]}")
print(f"    ✅ {'；'.join(tag)}")
PY

# ── 3. 源码快照 ──────────────────────────────────────────────
say "3/6  打包源码快照"
# 用 git 归档而非直接拷贝：只纳入已跟踪文件，天然排除 __pycache__ / .git 等
if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
        die "工作区有未提交的改动。离线包只收录 git HEAD 的内容，
        请先提交（或 git stash）再构建，否则产物里的源码和实际版本对不上。"
    fi
    mkdir -p "$PKG_DIR/hltv-mcp"
    git -C "$REPO_ROOT" archive HEAD | tar -x -C "$PKG_DIR/hltv-mcp"
    SRC_REV="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
    echo "    ✅ 源码来自 git HEAD ($SRC_REV)"
else
    die "$REPO_ROOT 不是 git 仓库，无法确定源码版本"
fi

# ── 4. 安装脚本与说明 ────────────────────────────────────────
say "4/6  放入安装脚本与说明"
cp "$REPO_ROOT/termux/install.sh" "$PKG_DIR/install.sh"
chmod 755 "$PKG_DIR/install.sh"
cp "$REPO_ROOT/termux/BUNDLE-README.md" "$PKG_DIR/README.md"

cat > "$PKG_DIR/BUILDINFO.txt" <<EOF
hltv-mcp Termux 离线安装包 —— 构建信息
========================================

源码版本      : $SRC_REV
构建时间      : (刻意不写入，以保持可复现)

目标平台      : Android ARM64 (aarch64), Termux
目标 Python   : 3.14.x  (wheel 标签 cp314)
原生 wheel    : $PYDANTIC_CORE_WHEEL
                来源: TUR PyPI 索引 (termux-user-repository.github.io/pypi/)

依赖分类明细见仓库中的 termux/requirements-termux.txt 与
termux/BUNDLE-README.md。

仍需联网的 apt 包（均为预编译 .deb，不触发编译）
--------------------------------------------------
  python  python-lxml  python-cryptography  python-rpds-py
  tur-repo x11-repo chromium xorg-server-xvfb
  注: chromium 与 xorg-server-xvfb 在 TUR 源，需先 pkg install tur-repo x11-repo
EOF

# ── 5. 规范化权限与校验和 ────────────────────────────────────
say "5/6  规范化权限并生成校验和"
find "$PKG_DIR" -type d -exec chmod 755 {} \;
find "$PKG_DIR" -type f -exec chmod 644 {} \;
chmod 755 "$PKG_DIR/install.sh"

( cd "$PKG_DIR" && find wheels -name '*.whl' | LC_ALL=C sort | xargs sha256sum > SHA256SUMS )
echo "    ✅ SHA256SUMS 共 $(wc -l < "$PKG_DIR/SHA256SUMS") 条"

# ── 6. 可复现打包 ────────────────────────────────────────────
say "6/6  可复现打包"
( cd "$STAGE" && tar --sort=name --owner=0 --group=0 --numeric-owner \
      --mtime="$MTIME" --format=gnu \
      -cf - "$BUNDLE_NAME" | gzip -n -9 > "$OUT_DIR/$BUNDLE_NAME.tar.gz" )

( cd "$OUT_DIR" && sha256sum "$BUNDLE_NAME.tar.gz" > SHA256SUMS )

# 自校验：再打一次，确认字节一致
CHECK="$(mktemp)"
( cd "$STAGE" && tar --sort=name --owner=0 --group=0 --numeric-owner \
      --mtime="$MTIME" --format=gnu \
      -cf - "$BUNDLE_NAME" | gzip -n -9 > "$CHECK" )
if cmp -s "$CHECK" "$OUT_DIR/$BUNDLE_NAME.tar.gz"; then
    echo "    ✅ 两次构建字节一致，可复现"
    rm -f "$CHECK"
else
    rm -f "$CHECK"
    die "两次构建结果不一致，可复现性被破坏"
fi

echo
echo "──────────────────────────────────────────────"
echo "产物:"
ls -lh "$OUT_DIR/$BUNDLE_NAME.tar.gz" | awk '{print "  "$9"  "$5}'
echo "校验:"
cat "$OUT_DIR/SHA256SUMS" | sed 's/^/  /'
echo "──────────────────────────────────────────────"
