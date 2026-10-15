<div align="center">

# hltv-mcp · Termux 离线安装包
# hltv-mcp · Termux Offline Bundle

**零编译 · 零 PyPI 访问**
**Zero compilation · Zero PyPI access**

</div>

---

## 中文

**零编译。** 解压后一条命令装完，全程不会在手机上编译任何东西。

```bash
tar xzf hltv-mcp-termux-offline.tar.gz
cd hltv-mcp-termux-offline
bash install.sh
```

### 包内有什么

```
hltv-mcp-termux-offline/
├── install.sh          一键安装（补丁已预应用，含 wheel 完整性校验）
├── SHA256SUMS          wheels 目录的校验和
├── wheels/             29 个 wheel —— 全部依赖，无编译
│   ├── *.whl                      27 个纯 Python 运行时依赖（跨平台，与设备无关）
│   ├── setuptools-84.0.0-py3-none-any.whl    构建后端，见下
│   └── pydantic_core-2.50.1-cp314-cp314-android_24_arm64_v8a.whl
├── hltv-mcp/           源码快照（curl_cffi 已降级为可选依赖）
└── BUILDINFO.txt       构建环境与依赖分类明细
```

安装时用 `--no-index` 强制只读本地文件，**完全不访问 PyPI**。

> **为什么包里要带 `setuptools`**：`pip install -e .` 使用 `setuptools.build_meta`
> 作为构建后端，而 Python 3.12+ 的 `ensurepip` 不再随 venv 提供 `setuptools`，
> Termux 的系统 Python 也没有。配合 `--no-build-isolation`（离线环境必须用它，
> 否则 pip 会去下载构建后端），不先装上就会直接报
> `BackendUnavailable: Cannot import 'setuptools.build_meta'`。
>
> 这里**刻意不带 `wheel`**：它依赖 `packaging`（不在本包内），带上反而会连带失败；
> 而 `setuptools >= 70.1` 已内置构建 wheel 的能力，独立的 `wheel` 包并不需要。

### 为什么只需要预编译一个包

对 `mcp>=2.0` 完整依赖树做实际解析：**34 个包，只有 6 个带原生代码**。逐个处置后：

| 包 | 语言/依赖 | 处置 | 依据 |
|---|---|---|---|
| `lxml` | C + libxml2/libxslt | apt `python-lxml` 6.1.3 | Termux main 源已预编译 |
| `cryptography` | Rust | apt `python-cryptography` 50.0.2 | Termux main 源已预编译 |
| `rpds-py` | Rust | apt `python-rpds-py` 2026.9.1 | Termux main 源已预编译 |
| `curl_cffi` | C + BoringSSL | **改为可选依赖** | 默认浏览器后端用不到；原仓库把它误列为硬依赖 |
| `cffi` | C + libffi | **自动消失** | 仅由 `cryptography` 引入，apt 版 cryptography 不依赖它 |
| `pydantic_core` | Rust | `wheels/` 内的 Android wheel | 见下 |

其余 28 个包是纯 Python（`py3-none-any`），本来就无需编译。

### 关于 `pydantic_core`

它是唯一无法回避的 Rust 扩展。关键事实：

- PyPI 上**没有** Termux 能用的 wheel。Termux 用 bionic libc，PyPI 只有 manylinux（glibc）版本；Termux 维护者在 [termux-packages#25150](https://github.com/termux/termux-packages/issues/25150) 里明确说过 **manylinux wheel 在 Termux 上装不上也跑不起来**。
- 但 Termux 的 Python 3.13+ 起，pip 按 **PEP 738** 额外接受 `android_aarch64` 标签的 wheel。
- **TUR 的 PyPI 索引**（`termux-user-repository.github.io/pypi/`）正好提供了我们需要的那个：

```
pydantic_core-2.50.1-cp314-cp314-android_24_arm64_v8a.whl   1.9 MB
```

版本、Python 版本（cp314）、平台三者与本项目依赖树完全吻合，已下载并校验：

- `Tag: cp314-cp314-android_24_arm64_v8a`
- 内含 `pydantic_core/_pydantic_core.cpython-314-aarch64-linux-android.so`
- ELF 头确认为 **AArch64 / 64-bit**，Generator: maturin 1.12.6

所以**不需要自己编，也不需要 CI 构建**。

### 仍需联网的部分

只有 Termux 系统包，它们本来就是预编译 `.deb`，不涉及编译：

| 包 | 大小 | 说明 |
|---|---|---|
| `chromium` | 约 100MB+ | 浏览器后端必需 |
| `xorg-server-xvfb` | 小 | 提供「界面上看不见」的虚拟显示 |
| `python-lxml` / `python-cryptography` / `python-rpds-py` | 小 | 替代源码编译 |

`chromium` + `xvfb` 是体积大头且**无法绕开**——Termux 上 `curl_cffi` 编不出来，HTTP 后端就用不了，只能走默认浏览器后端。

> 想连这部分也离线，更稳的做法是用 Termux 官方方式做整机快照：
> ```bash
> tar -zcf termux-backup.tar.gz -C /data/data/com.termux/files ./home ./usr
> ```
> 在**同版本 Termux** 的设备上还原即可，这份快照里连装好的 chromium 都在。

### 校验

```bash
sha256sum -c SHA256SUMS          # 校验 wheels 目录
sha256sum hltv-mcp-termux-offline.tar.gz   # 与 Release 页公布的值比对
```

### 注意事项

- ⚠️ **脚本未在真机 Termux 上实测过。** 包名、版本、平台标签、ELF 架构均已逐项核对，但毕竟没跑过真机，首次安装请留意输出。
- ⚠️ **wheel 绑定 Termux 的 Python 版本。** 本包面向 **Termux Python 3.14.x**（`cp314`）。Termux 升级 Python 主版本后需要重新取对应 `cpXY` 的 `pydantic_core` wheel。
- 只适用于 **Android ARM64（aarch64）**。32 位设备需要换 `android_24_armeabi_v7a` 的 wheel。
- 补丁已预应用到包内源码，`install.sh` 里的 `pip install -e .` 会直接用它。若想改回原仓库代码，`patches/` 里有完整改动记录。

### 效果对比

| | 原生 `pip install -e .` | 本离线包 |
|---|---|---|
| 需编译的包 | 6 个（其中 `curl_cffi` 基本必失败） | **0 个** |
| Python 依赖来源 | PyPI 在线解析 | 本地 `wheels/`，`--no-index` |
| 典型失败点 | `ffi.h not found`、BoringSSL 链接失败 | 无 |
| 首次耗时 | 15 分钟起，大概率卡在编译 | 约 2 分钟，主要是下载 chromium |

---

## English

**Zero compilation.** One command after extracting — nothing is ever built on the phone.

```bash
tar xzf hltv-mcp-termux-offline.tar.gz
cd hltv-mcp-termux-offline
bash install.sh
```

### What's inside

```
hltv-mcp-termux-offline/
├── install.sh          One-shot installer (patch pre-applied, verifies wheel integrity)
├── SHA256SUMS          Checksums for the wheels/ directory
├── wheels/             29 wheels — the complete dependency set, zero compilation
│   ├── *.whl                      27 pure-Python runtime dependencies (cross-platform)
│   ├── setuptools-84.0.0-py3-none-any.whl    Build backend, see below
│   └── pydantic_core-2.50.1-cp314-cp314-android_24_arm64_v8a.whl
├── hltv-mcp/           Source snapshot (curl_cffi demoted to an optional dependency)
└── BUILDINFO.txt       Build environment and dependency breakdown
```

Installation runs with `--no-index`, so pip reads **only** local files and never touches PyPI.

> **Why `setuptools` ships inside the bundle**: `pip install -e .` uses
> `setuptools.build_meta` as its build backend, and since Python 3.12 `ensurepip`
> no longer provides `setuptools` in a fresh venv — nor does Termux's system Python.
> Combined with `--no-build-isolation` (mandatory offline, otherwise pip tries to
> download the build backend), missing it fails outright with
> `BackendUnavailable: Cannot import 'setuptools.build_meta'`.
>
> `wheel` is **deliberately excluded**: it depends on `packaging` (not bundled here),
> so including it causes a cascading failure; and `setuptools >= 70.1` already has
> wheel-building support built in, so the standalone `wheel` package isn't needed.

### Why only one package needs a prebuilt wheel

An actual resolution of the full `mcp>=2.0` dependency tree gives **34 packages, only 6 of which contain native code**. Handling them one by one:

| Package | Language / deps | Handling | Rationale |
|---|---|---|---|
| `lxml` | C + libxml2/libxslt | apt `python-lxml` 6.1.3 | Prebuilt in the Termux main repo |
| `cryptography` | Rust | apt `python-cryptography` 50.0.2 | Prebuilt in the Termux main repo |
| `rpds-py` | Rust | apt `python-rpds-py` 2026.9.1 | Prebuilt in the Termux main repo |
| `curl_cffi` | C + BoringSSL | **Demoted to optional** | Unused by the default browser backend; upstream wrongly listed it as a hard dependency |
| `cffi` | C + libffi | **Disappears on its own** | Only pulled in by `cryptography`, and the apt build of cryptography doesn't need it |
| `pydantic_core` | Rust | Android wheel in `wheels/` | See below |

The remaining 28 packages are pure Python (`py3-none-any`) and never needed compiling in the first place.

### About `pydantic_core`

It's the one Rust extension that can't be avoided. The key facts:

- **There is no Termux-compatible wheel on PyPI.** Termux uses bionic libc while PyPI only ships manylinux (glibc) builds. Termux maintainers state plainly in [termux-packages#25150](https://github.com/termux/termux-packages/issues/25150) that **manylinux wheels neither install nor load on Termux**.
- However, since the Python 3.13 series Termux's pip additionally accepts wheels tagged `android_aarch64`, per **PEP 738**.
- The **TUR PyPI index** (`termux-user-repository.github.io/pypi/`) happens to carry exactly the one we need:

```
pydantic_core-2.50.1-cp314-cp314-android_24_arm64_v8a.whl   1.9 MB
```

Version, Python version (cp314) and platform all match this project's resolved dependency tree exactly. Downloaded and verified:

- `Tag: cp314-cp314-android_24_arm64_v8a`
- Contains `pydantic_core/_pydantic_core.cpython-314-aarch64-linux-android.so`
- ELF header confirmed **AArch64 / 64-bit**, Generator: maturin 1.12.6

So there is **no local build and no CI build required**.

### What still needs network access

Only Termux system packages, which are prebuilt `.deb` files and never involve compilation:

| Package | Size | Purpose |
|---|---|---|
| `chromium` | ~100MB+ | Required by the browser backend |
| `xorg-server-xvfb` | small | Provides the invisible virtual display |
| `python-lxml` / `python-cryptography` / `python-rpds-py` | small | Replace source compilation |

`chromium` + `xvfb` account for most of the size and **cannot be avoided** — `curl_cffi` can't be built on Termux, so the HTTP backend is unavailable and the default browser backend is the only option.

> To take even this offline, the more reliable route is a full Termux snapshot:
> ```bash
> tar -zcf termux-backup.tar.gz -C /data/data/com.termux/files ./home ./usr
> ```
> Restore it on a device running the **same Termux version**; the snapshot even includes an installed chromium.

### Verification

```bash
sha256sum -c SHA256SUMS                    # verify the wheels/ directory
sha256sum hltv-mcp-termux-offline.tar.gz   # compare against the value on the Release page
```

### Caveats

- ⚠️ **These scripts have not been tested on a real Termux device.** Package names, versions, platform tags and ELF architecture were all checked individually, but they haven't run on hardware — watch the output on first install.
- ⚠️ **Wheels are bound to Termux's Python version.** This bundle targets **Termux Python 3.14.x** (`cp314`). After a Termux Python major upgrade, fetch the matching `cpXY` `pydantic_core` wheel again.
- **Android ARM64 (aarch64) only.** 32-bit devices need the `android_24_armeabi_v7a` wheel.
- The patch is pre-applied to the bundled source, so `pip install -e .` in `install.sh` uses it directly. `patches/` keeps the full change history if you want to revert to upstream code.

### Before / after

| | Plain `pip install -e .` | This offline bundle |
|---|---|---|
| Packages needing compilation | 6 (of which `curl_cffi` almost always fails) | **0** |
| Python dependency source | Live PyPI resolution | Local `wheels/`, `--no-index` |
| Typical failure mode | `ffi.h not found`, BoringSSL link errors | None |
| First install time | 15+ minutes, usually stuck compiling | ~2 minutes, mostly downloading chromium |
