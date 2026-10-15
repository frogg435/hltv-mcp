<div align="center">

# hltv-mcp

**让 AI 直接查询 HLTV.org 的 Counter-Strike 赛事数据**
**Let AI query HLTV.org for Counter-Strike match data**

赛程 · 赛果 · 实时比分 · 世界排名 · 战队 · 选手 · 赛事 · 新闻
Matches · Results · Live scores · Rankings · Teams · Players · Events · News

[**简体中文**](#简体中文) · [**English**](#english)

</div>

---

<div align="center">

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Android-informational)
![Tools](https://img.shields.io/badge/MCP%20tools-18-orange)

</div>

---

<a id="简体中文"></a>

## 简体中文

让 AI 直接查询 **HLTV.org** 的 Counter-Strike 赛事数据 —— 赛程、赛果、世界排名、战队、选手、新闻、赛事日历。

默认用**真实浏览器**取数据：**后台运行、界面上完全看不见**，也不会打扰你正在浏览的页面。
支持 Windows / macOS / Linux，以及 **Android Termux**。

### 它能回答什么

| 提问 | 调用的工具 |
|---|---|
| 今天有哪些比赛？ | `hltv_get_matches` |
| 现在正在打的有哪些？ | `hltv_get_matches(live_only=True)` |
| **现在比分多少？** | **`hltv_get_live_scores()`** |
| Vitality 最近战绩如何？ | `hltv_get_results(team="Vitality")` |
| 现在世界排名前 30 是谁？ | `hltv_get_team_ranking` |
| ZywOo 的 Rating 和生涯荣誉？ | `hltv_get_player(name="ZywOo")` |
| **ZywOo 历年表现怎么样？** | **`hltv_get_player_career(name="ZywOo")`** |
| **ropz 每年 Rating 多少？** | **`hltv_get_player_year_stats(name="ropz")`** |
| **这场比赛 Inferno 上 CT 方谁打得好？** | **`hltv_get_match_stats(match_id, map="Inferno", side="ct")`** |
| 这届 Major 奖金多少？谁参加？ | `hltv_get_event(name="...")` |
| FaZe 最近战绩如何？ | `hltv_get_team_matches(name="FaZe")` |
| FaZe 和 Vitality 历史交手谁强？ | `hltv_get_head_to_head("FaZe", "Vitality")` |
| FaZe 现在阵容都有谁？ | `hltv_get_team(name="FaZe")` |
| 最近有什么新闻？ | `hltv_get_news` |
| 接下来有哪些大赛？ | `hltv_get_events` |

**所有工具都接受 ID 或名称** —— 直接写 `name="Vitality"` 就行，服务端会自动解析成 ID，不需要模型先查一遍搜索。

> 只想**飞快地看一眼当前比分**？仓库里带了 `python scripts/hltv-live` —— 不经浏览器直连 HLTV，
> 1~2 秒出结果，见下文「[极速实时比分](#极速实时比分scripts-hltv-live)」。

### 安装

```bash
git clone <repo> && cd hltv-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

依赖里**没有 Playwright** —— 浏览器控制由自带的原生 CDP 客户端完成，只有一个纯 Python
的 `websocket-client` 依赖。这么设计有两个原因：Playwright 在 Termux/Android 上装不起来，
而且它创建标签页时一定会抢焦点（见下文「不打扰你的浏览」）。

前提是本机装了 Chrome / Chromium / Edge 之一（三选一即可）。Linux 上还建议装 `Xvfb`，
用来提供「界面上看不见」的虚拟显示。装不了浏览器（比如 CI）就改用 HTTP 后端：
`pip install -e ".[http]"` 并设置 `HLTV_BACKEND=http`。

> **`curl_cffi` 是可选依赖。** 只有 HTTP 后端需要它，默认的浏览器后端用不到。
> 它需要编译 curl-impersonate + BoringSSL，在 Android 等平台上很难装成功，因此**不要**
> 把它加回 `dependencies`。

#### Android / Termux 离线安装（零编译）

Termux 上装 Python 依赖最痛的一环是现场编译原生扩展（`lxml`、`cryptography`、`pydantic_core`…）。
本仓库提供一个**预编译好的离线包**，解压后一条命令装完，**全程不编译任何东西**：

```bash
tar xzf hltv-mcp-termux-offline.tar.gz
cd hltv-mcp-termux-offline
bash install.sh
```

包里已经放了全部 30 个 wheel（含 Android ARM64 版的 `pydantic_core`），安装时用
`--no-index` 强制只读本地文件，**完全不访问 PyPI**。详见
[Releases](https://github.com/frogg435/hltv-mcp/releases) 页面的离线包说明。

### 接入 MCP 客户端

在客户端的 MCP 配置里加上：

```json
{
  "mcpServers": {
    "hltv": {
      "command": "/绝对路径/hltv-mcp/.venv/bin/python",
      "args": ["-m", "hltv_mcp"],
      "env": {
        "PYTHONPATH": "/绝对路径/hltv-mcp/src"
      }
    }
  }
}
```

用 `pip install -e .` 装过之后，也可以直接用命令入口：

```json
{
  "mcpServers": {
    "hltv": { "command": "/绝对路径/hltv-mcp/.venv/bin/hltv-mcp" }
  }
}
```

**不需要任何环境变量。** 服务启动时会在后台**预热**：拉起浏览器，并把赛程、实时比分、
赛果、排名这几个常用页各取一遍。实测 Cloudflare 对**首访的某些路径**会额外给一次真挑战
（10–25 秒），这样做等于把这些代价提前到启动时消化掉，**第一次查询就已经是热的**。

预热会**让路**：第一页之后，每一页都要先等 8 秒确认你没在查询，一旦有请求进来就立刻收工，
不会把慢请求堆在你前面。之后复用同一个浏览器实例，MCP 退出时自动关掉它。

几个可选的调优项：

```json
{
  "env": {
    "HLTV_BACKEND": "auto",
    "HLTV_BROWSER_VISIBLE": "0"
  }
}
```

### 工具清单

| 工具 | 说明 |
|---|---|
| `hltv_search` | 搜索选手/战队/赛事/新闻，名称 → ID |
| `hltv_get_matches` | 赛程（即将开始 + 进行中），支持按队伍/赛事过滤、只看直播 |
| `hltv_get_live_scores` | **实时比分快照**：正在进行的比赛、当前地图回合数、已赢地图数（轮询获取进展）|
| `hltv_get_results` | 赛果，含比分与胜方，支持分页 |
| `hltv_get_match` | 单场详情：地图比分 + **逐地图分队伍的选手数据**（昵称、选手 ID、国籍、K-D、ADR、KAST、Rating、Swing）|
| `hltv_get_team_ranking` | 世界战队排名（含积分） |
| `hltv_get_team` | 战队资料：排名、教练、阵容 |
| `hltv_get_player` | 选手资料：Rating 3.0、能力评分、生涯荣誉汇总 |
| `hltv_get_player_career` | **选手逐年生涯**：历年在哪支队、历年 Top20 排名、奖项、冠军、MVP |
| `hltv_get_player_year_stats` | **选手逐年 Rating 与详细数据**：Rating、K/D、ADR、地图数、对 Top5/10/20 对手的 Rating |
| `hltv_get_match_stats` | **单场比赛逐地图、分阵营（CT/T）的选手数据**：Op.K-D、多杀、KAST、1vX、爆头、ADR、Rating |
| `hltv_get_event` | 赛事详情：奖金池、日期、地点、VRS 权重、参赛队、名次与奖金分配 |
| `hltv_get_team_matches` | 战队近期战绩：日期、对手、比分、胜负 |
| `hltv_get_head_to_head` | 两队交手记录：逐地图明细 + 按地图聚合胜率 |
| `hltv_get_news` | 新闻列表 |
| `hltv_get_news_article` | 新闻正文 |
| `hltv_get_events` | 赛事日历 |
| `hltv_backend_status` | 当前用哪种后端、浏览器是否可用；排查「查不到数据」时先调它 |

全部只读，没有任何写操作。

### 工作原理与已知限制

#### 取页面的三种后端

| 后端 | 怎么用 | 特点 |
|---|---|---|
| **浏览器**（默认） | 用真实浏览器取页面 | 过 Cloudflare 最稳；唯一能做点击交互；需要本机有浏览器 |
| **HTTP** | `curl_cffi` + Safari TLS 指纹 | 快、轻、无需浏览器；但过不了 Cloudflare 的路径级规则 |
| **hybrid** | 先试 HTTP，被拦了自动改用浏览器 | 两种能力都有；代价是每次先花半秒探一次路 |

`HLTV_BACKEND=auto`（默认）/ `browser` / `http` / `hybrid` 控制选择，见下文「后端选择」。

#### Cloudflare

HLTV 在 Cloudflare 之后。实测（**在出口 IP 干净的前提下**）：

| 方式 | 结果 |
|---|---|
| 裸 `requests` / `curl` | ❌ 403 Just a moment... |
| `got-scraping`（Chrome TLS 指纹） | ❌ 403 |
| `curl_cffi` + Chrome / Firefox / Edge 指纹 | ❌ 403 |
| **`curl_cffi` + Safari 指纹** | ✅ **200，正常页面** |
| **真实浏览器** | ✅ **200，含 /stats/\*** |

HTTP 后端用 `curl_cffi` 且 `impersonate="safari17_0"`。换网络环境后最优指纹可能不同，可用 `HLTV_IMPERSONATE` 覆盖。

#### 后端：默认用真实浏览器

Cloudflare 按 **IP 累积信誉**，封禁会逐级升级：

```
干净 IP  →  某条路径被拦（如 /stats/*）  →  整站 403（首页也进不去）
```

进了第二、三阶段后，**换客户端伪装是没用的** —— 我们实测过：

| 尝试 | 结果 |
|---|---|
| 换 7 种 TLS 指纹（Safari / Chrome 131 / 124 / 120 / Firefox / Edge） | 全部 403 |
| 无头 Chromium / 有头 Chromium（Xvfb）/ 有头真实 Chrome | 全部 403 |
| 加 stealth 脚本（抹 `navigator.webdriver` 等） | 无效 |

**真正有效的做法是用真实浏览器。** 实测对照（**同一 IP、同一时刻**）：

| 方式 | `/` | `/stats/players/individual/11816/ropz` |
|---|---|---|
| `curl_cffi`（Safari 指纹） | ❌ 403 | ❌ 403 |
| **真实浏览器 + 持久化配置文件** | ✅ **200** | ✅ **200** |

差异不在「有头/无头」，而在两点：**真实浏览器的完整指纹**，以及**使用持久化的配置文件上下文**。用匿名上下文同样会被拦。

所以**默认后端就是浏览器**，并且**开箱即用** —— 不需要你先敲命令启动 Chrome：

```bash
# 什么都不用配，直接用。（首次会在 ~/.cache/hltv-mcp 建立独立 profile）
python scripts/browser_check.py
```

启动器会自动完成这些事：

1. 若已有带调试端口的浏览器在跑（或你设了 `HLTV_BROWSER_CDP`），直接复用
2. 否则自己拉起一个浏览器，用**独立的持久化 profile**（位于 `~/.cache/hltv-mcp/chrome-profile`）
3. MCP 退出时**只关掉自己拉起的那个实例**；你自己的浏览器不会被碰

#### 不打扰你的浏览

这是硬性设计目标，不是「尽量」：

* **界面上看不见。** Linux 上启动器会自己造一个 Xvfb 虚拟显示，浏览器有头运行但根本没有
  显示设备；其他桌面系统把窗口挪到屏幕外。你既看不到窗口，也没有弹窗。
* **不抢焦点、不动你的标签页。** 所有标签页都以 CDP 的 `background=true` 创建，
  用完立刻关闭。你正在看的页面不会被跳转，也不会被顶到后台。

这两件事都实测过。用 `document.visibilityState` 和 `document.hasFocus()` 作为客观指标，
在用户页面全程开着的情况下跑完 4 次真实查询：

| | 查询前 | 全程查询中 / 查询后 |
|---|---|---|
| 用户页面 URL | `example.com/` | 未变 |
| `visibilityState` | `visible` | `visible` |
| `hasFocus()` | 未变 | 未变 |
| 标签页数 | 1 | 1（无残留） |

对照实验也做了：用早期实现的 `background=false` 方式，同一场景下用户页面的
`visibilityState` 会立刻变成 `hidden`、`hasFocus()` 变 `false` —— 也就是被顶掉了。
这正是本项目**不用 Playwright** 的原因之一（它的 `new_page()` 一定会激活新标签页）。

`python scripts/browser_check.py` 里内置了这项检查，可以自己验证。

#### Android / Termux

Termux 是明确支持的目标平台：**浏览器照样由本服务自己拉起、界面上看不见，
不需要动你手机上的浏览器，也不需要 adb 转发。**

```bash
pkg install tur-repo x11-repo
pkg install chromium xorg-server-xvfb python
pip install hltv-mcp
```

几个容易踩的点：

* **Chromium 不在官方 main 源里**，它在 TUR（`tur-repo`），并且依赖 `x11-repo`
  里的 GTK/X11 库（即使跑无头也会链接这些库）。但注意：`tur-repo` 和 `x11-repo`
  这两个**「启用源」的包本身就在 main 源里** —— 所以只要官方源可用就够了，
  不需要任何第三方源。反过来，如果 `pkg install chromium` 报找不到包，
  先确认这两条 `pkg install tur-repo x11-repo` 执行成功了。
* **Chromium 的可执行文件叫 `chromium-browser`**，不是 `chromium`。本项目会自动找到它
  （`$PREFIX/bin/chromium-browser`）。
* **`xorg-server-xvfb` 是必须的** —— 它就是"界面上看不见"的实现方式：浏览器有头运行，
  但没有显示设备。没有它就只能退化成无头模式，而无头会被 Cloudflare 拦。
* 启动时自动带上 Android 需要的 `--no-sandbox`（Android 上 setuid 沙箱不可用）和 `--disable-gpu`。
* Termux 把临时目录放在 `$TMPDIR`（`/data/data/com.termux/files/usr/tmp`）而不是 `/tmp`，
  X11 的 socket 也跟着在那里 —— 本项目会在这三处一起找。

`playwright` 在这里是**装不起来**的 —— 官方直接抛 `Unsupported platform: android`，
而且它的 `new_page()` 一定会抢焦点。所以本项目不用它，改用自带的原生 CDP 客户端
（只需纯 Python 的 `websocket-client`）。

独立 profile 不是随便选的：一是避免拿你日常的浏览数据去开调试端口，二是 Chrome 在同
profile 已有实例运行时，新进程只会把标签页塞进旧实例、调试端口根本不会打开。它还有个
副作用是好的 —— profile 持久化后 `cf_clearance` 会留存，后续启动遇到的挑战明显更少。

安全边界：**绝不关闭你的浏览器**，不读取也不导出 cookie。用户如需登录态，自己在浏览器里
登录即可，本项目不经手任何账号密码。

##### 无头模式会被拦（实测）

一个必须说清楚的点：**`--headless` 会被 Cloudflare 拦**。

| 模式 | 首页 | `/matches` | `/stats/players/...` |
|---|---|---|---|
| `--headless=new` | ❌ 挑战页 | ❌ 挑战页 | ❌ 挑战页 |
| 有头（含 Xvfb 虚拟显示） | ✅ 200 | ✅ 200 | ✅ **964KB** |

所以「没有显示器」时**不能**直接退化成无头 —— 那等于静默失效。本项目的做法是：Linux 上
若检测到没有可用显示且有 Xvfb，就**自己造一个虚拟显示**（如 `:99`），让浏览器仍以有头模式
运行。实测这条路径在容器里同样可用，退出时会连虚拟显示一起收掉。

不用 Xvfb 也没关系：只要有显示环境（桌面系统），走的就是普通有头模式。

#### 后端选择

| `HLTV_BACKEND` | 行为 |
|---|---|
| `auto`（默认） | **优先浏览器**；只有浏览器**根本起不来**时才降级到 HTTP |
| `browser` | 强制浏览器。起不来就报错，不降级 |
| `http` | 强制 HTTP。适合装不了浏览器的环境（CI、纯容器） |
| `hybrid` | **HTTP 优先**，被 Cloudflare 拦了才自动改用浏览器，并记住「哪类路径必须用浏览器」 |

注意 `auto` 的降级边界：**「页面被 Cloudflare 拦」不算「起不来」**，那种情况不会降级 ——
因为 HTTP 后端会拿到同样的拦截页，降级只会把错误变得更难理解。只有「找不到浏览器 / 连不上
调试端口 / 启动超时」这类才降级，且会在 stderr 提示一次并转到 HTTP。

`hybrid` 是 `auto` 的「快路径版」而不是缩水版 —— 最终拿到的数据完全一样，只是把顺序倒过来：
先花半秒试一次廉价请求，被拦了才启动浏览器。实测 `/stats/*` 有独立的拦截规则，其余路径
HTTP 全通。

但要如实说：**桌面端 hybrid 并不比默认的浏览器后端快**（本机实测两者都在 1 秒上下）。
它的价值在弱设备 —— 手机/Termux 上渲染 1MB HTML 的代价比多一次网络往返更高。桌面用户
直接用默认的 `auto` 就好。

#### 先诊断，再动手

```bash
python scripts/browser_check.py   # 默认后端：检查浏览器能不能用、能不能取到 HLTV
python scripts/health.py          # HTTP 后端：定位是 IP 级封禁还是路径级拦截
```

`health.py` 的判读方式：

- **首页也 403** → IP 级封禁。换出口 IP，或改用默认的浏览器后端
- **只有个别路径 403** → 路径级规则（`/stats/*` 属于此类），浏览器后端不受影响

也可用代理（`HLTV_PROXY`）换出口。住宅 IP 效果最好；机房 IP 通常同样会被拦。

#### 限流

**请求频率是使用这个 MCP 时最需要注意的事。** 短时间密集请求会让当前出口 IP 被 Cloudflare 单独限流，表现为**某一路径持续 403，而其他路径正常**，且恢复需要数分钟到数小时。

客户端默认做了这些事：

- **浏览器后端**：间隔 **0.5 秒 + 0–0.8 秒随机抖动**（`HLTV_BROWSER_MIN_INTERVAL` / `HLTV_JITTER`）。
  浏览器请求本身就是「一个真人在翻页」，Cloudflare 的判定依据与裸 HTTP 完全不同，
  按爬虫的标准自我设限只是白白卡自己
- **HTTP 后端**：间隔 **3 秒**（`HLTV_MIN_INTERVAL`）。裸 HTTP 请求最像爬虫，也最容易被限流
- 内存缓存：实时比分 15s、赛程 60s、赛果 120s、新闻 300s、排名 1h、选手/战队 30min
- 遇到 403 **不立刻重建会话**（那会丢掉已通过的 cookie，反而更糟），先退避重试，最后一次才换会话

如果某个工具持续报 403，把 `HLTV_MIN_INTERVAL` 调到 `5` 或更大，或换网络出口。

#### 地图 × 阵营的比赛数据

`hltv_get_match_stats` 能给出**某场 BO1/BO3/BO5 里，每张地图、每个阵营（CT/T）下每位选手**的完整数据：

```jsonc
// hltv_get_match_stats(match_id=2399253, map="Inferno", side="ct")
{
  "available_maps": ["2 - 1 Best of 3", "13 - 0 Dust2", "8 - 13 Inferno", "13 - 9 Mirage"],
  "results": [{
    "map": "Inferno",
    "sides": {
      "ct": [
        {"team": "100 Thieves", "players": [
          {"nickname": "rain", "opening_kd": "3 : 0", "multi_kills": "2", "kast": "83.3%",
           "clutches_1vx": "0", "kills": "8 (4)", "assists": "5 (0)", "deaths": "8 (0)",
           "adr": "78.8", "round_swing": "-2.27%", "rating": "0.90"}
        ]}
      ]
    }
  }]
}
```

两个实现要点：

* **地图必须点击切换，阵营不用。** 实测 DOM 里同时存在 `totalstats` / `ctstats` / `tstats`
  三套表，只有当前选中的那套不带 `hidden` 类 —— 所以一次取回三个阵营，只对地图做点击。
* **比赛页的 "Detailed stats" 指向另一套 ID。** 比赛页是 `/matches/{id}`，
  统计页是 `/stats/matches/{另一个id}`，两者不通用，得先从比赛页里取出来。

#### 关于 `/stats/*` 与逐年 Rating

`/stats/*` 路径（含**逐年 Rating** 所在的统计页）在 HTTP 后端下会被 Cloudflare 拦截。
**启用浏览器后端后可以正常访问** —— 这是 `hltv_get_player_year_stats` 的前提。

```jsonc
// hltv_get_player_year_stats(player_id=11816, years=[2019, 2022, 2024, 2025, 2026])
{
  "seasons": [
    {"year": 2019, "rating_version": "Rating 2.0", "rating": 1.19, "kd_ratio": 1.29,
     "adr": 80.4, "maps_played": 200, "kills": 4005},
    {"year": 2024, "rating_version": "Rating 3.0", "rating": 1.13, "kd_ratio": 1.18,
     "adr": 75.9, "maps_played": 189, "kills": 3035},
    {"year": 2025, "rating_version": "Rating 3.0", "rating": 1.18, "kd_ratio": 1.24,
     "adr": 78.6, "maps_played": 200, "kills": 3182}
  ],
  "career_total": {"rating_version": "Rating 2.0", "rating": 1.15, "maps_played": 1915}
}
```

注意 HLTV 的 Rating 体系改过版（1.0 → 2.0 → 2.1 → 3.0），**跨年份的 Rating 数值不可直接比较**，
所以每一季都返回了 `rating_version` 供判断。

#### 一个名不副实的 URL

`/stats/teams/matches/{a}/{b}` 看起来是「a 与 b 的交手记录」，但**实测它返回的是 a 队的全部比赛** ——
FaZe 的页面有 2063 张地图、131 个不同对手，第二个 ID 不起过滤作用，`?contextIds=` 参数也无效。

所以 `hltv_get_head_to_head` 改为**本地按对手名过滤**，才得到真正的 H2H
（FaZe vs Vitality = 81 张地图，37 胜 44 负，胜率 45.7%）。
代价是要下载整个页面（约 5MB / 5 秒）。

#### 解析器维护

HLTV 会改版，选择器可能失效。当某个工具抽不到数据时：

```bash
python scripts/hltv_inspect.py /matches                 # dump 页面类名分布
python scripts/hltv_inspect.py /team/6667/x --selector .profile-team-stat
```

定位到新类名后改 `src/hltv_mcp/parsers.py` 里对应的解析函数即可。所有解析器都遵循「缺字段返回 None，不抛异常」的约定，页面局部变化不会让整个工具调用失败。

### 速度

耗时几乎全在两处：**浏览器冷启动**和**取页面本身**。现在分别这么处理：

| 问题 | 做法 |
|---|---|
| 冷启动（起浏览器 + 过 Cloudflare 挑战）全压在第一次查询上 | 服务启动时后台**预热**，把这几秒挪进「客户端握手 + 你打字」的空档；预热还会让路，不会挡住你的查询 |
| 某些路径**首次**访问会被 Cloudflare 额外挑战一次（10–25 秒） | 把常用路径（赛程/实时比分/赛果/排名）都放进预热清单，在启动时消化掉 |
| 浏览器后端被按爬虫标准限速（每次请求硬等 3 秒） | 浏览器后端改用 0.5 秒间隔；HTTP 后端仍保持 3 秒 |
| 比赛统计页有两段固定 `sleep`（3.5 秒 + 3.0 秒） | 改成「等元素出现 / 等内容变化」，通常不到 1 秒就返回 |
| 挑战通过后页面由 JS 重载，中间有个「标题正常、内容残缺」的空壳 | 检测到这种情况就等内容稳定再取，避免收到一页残缺数据还不报错 |

本机实测（同一台机器、同一网络，逐页计时）：

| 场景 | 优化前 | 优化后 |
|---|---|---|
| 赛程 / 赛果 / 排名 / 实时比分等常规页 | 2.6 – 4.2 秒 | **0.3 – 2.0 秒** |
| 实时比分**首次**查询（会撞上路径挑战） | 28 秒 | **0.8 秒**（挑战已在启动预热里消化） |
| 比赛详细统计（`hltv_get_match_stats`） | 8 秒以上（光固定等待就占 6.5 秒） | **约 2 秒** |
| 第一次查询（冷启动） | 2 – 15 秒 | **≈ 0**（已被启动预热吸收） |

> 有一条**不是**代码能修的：对**不在预热清单里**的路径（`/stats/*` 尤其明显），首次访问
> 仍可能撞上一次真挑战，实测 9 – 25 秒，之后同一条路径都是 1 秒级。所以「第一次查某个
> 选手的逐年 Rating」偏慢属于正常，同一个选手再查就快了。想连这个也消掉，把对应路径加进
> `HLTV_WARMUP_PAGES` 即可。

### 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `HLTV_BACKEND` | `auto` | 后端：`auto`（优先浏览器）/ `browser`（强制）/ `http`（强制 HTTP）/ `hybrid`（HTTP 优先，被拦自动换浏览器） |
| `HLTV_WARMUP` | `1` | 启动时后台预热浏览器，让第一次查询不必等冷启动。置 `0` 关闭 |
| `HLTV_WARMUP_PAGES` | `/matches,/livescore,/results,/ranking/teams,/search` | 预热依次取这些页面。实测 Cloudflare 对**首访的某些路径**（`/livescore`、`/search`、`/stats/*`）会额外给一次真挑战，要 10–25 秒；在启动时走一遍，用户查询时就是热的 |
| `HLTV_WARMUP_IDLE` | `8` | 预热继续下一页之前，先等这么多秒看用户有没有动静。有请求就让路收工 |
| `HLTV_BROWSER_CDP` | 空 | 复用一个**外部已启动**的浏览器，如 `http://127.0.0.1:9222`。留空则由本服务自动准备 |
| `HLTV_BROWSER_AUTOLAUNCH` | `1` | 置 `0` 则禁止自动拉起浏览器，只复用已有实例 |
| `HLTV_BROWSER_VISIBLE` | `0` | 置 `1` 让浏览器窗口可见（调试用）。默认隐藏 |
| `HLTV_BROWSER_HEADLESS` | 自动 | 置 `1` 强制无头。**注意无头会被 Cloudflare 拦**，非必要别开 |
| `HLTV_CHROME_BIN` | 自动探测 | 浏览器可执行文件路径（Chrome/Chromium/Edge） |
| `HLTV_BROWSER_PORT` | `9222` | 自动启动时优先使用的调试端口，被占则自动换 |
| `HLTV_CHROME_PROFILE` | `~/.cache/hltv-mcp/chrome-profile` | 自动启动时用的独立 profile 目录 |
| `HLTV_CACHE_DIR` | 平台缓存目录 | 存放 profile、浏览器日志、端口记录 |
| `HLTV_PROXY` | 空 | 出口代理，形如 `http://user:pass@host:port` 或 `socks5://host:port`。**遇到 IP 级封锁时的主要解法** |
| `HLTV_MIN_INTERVAL` | `3.0` | **HTTP 后端**两次请求的最小间隔（秒） |
| `HLTV_BROWSER_MIN_INTERVAL` | `0.5` | **浏览器后端**两次请求的最小间隔（秒） |
| `HLTV_HYBRID_MIN_INTERVAL` | `1.0` | hybrid 模式里那次探路 HTTP 请求的最小间隔（秒） |
| `HLTV_JITTER` | `0.8` | 间隔上的随机抖动上限（秒） |
| `HLTV_TIMEOUT` | `40` | 单次请求超时（秒） |
| `HLTV_MAX_RETRIES` | `3` | 失败重试次数 |
| `HLTV_NAV_RETRIES` | `3` | 页面导航重试次数（浏览器后端） |
| `HLTV_CHALLENGE_WAIT` | `25` | 等 Cloudflare 挑战通过的上限（秒） |
| `HLTV_CHALLENGE_POLL` | `0.6` | 挑战轮询间隔（秒） |
| `HLTV_BLOCK_ASSETS` | `0` | 置 `1` 拦掉图片/字体/广告统计脚本。实测 HLTV 以服务端渲染的 HTML 为主，桌面端开了反而略慢；弱设备可以自己试 |
| `HLTV_IMPERSONATE` | `safari17_0` | HTTP 后端的 TLS 指纹，可选 `chrome131`、`firefox135` 等 |

也识别标准的 `HTTPS_PROXY` / `ALL_PROXY`。

### 极速实时比分：`scripts/hltv-live`

MCP 里的 `hltv_get_live_scores` 走浏览器后端，准确但代价是等浏览器渲染。只想快速瞄一眼比分时，
用仓库自带的脚本更划算 —— 它直接请求 `https://www.hltv.org/scores`（这条路径不受 Cloudflare
拦截，被拦的是 `/matches/*` 那类页面；gzip 后约 40KB），完全不启动浏览器：

```bash
python scripts/hltv-live             # 列出当前所有进行中的比赛（约 1.5~2.5 秒）
python scripts/hltv-live falcons     # 只筛队名含 falcons 的（可多个关键字）
python scripts/hltv-live --json      # JSON 输出
python scripts/hltv-live --watch 15  # 守护模式：每 15 秒轮询一次并写缓存
python scripts/hltv-live --cache     # 读守护进程缓存，毫秒级（不联网）
```

实测（Android/Termux，同一场比赛）：直连脚本 1.6~2.4 秒，守护模式缓存读取约 60 毫秒，
比分与页面同步；相比之下浏览器后端冷启动要几十秒。脚本同样只读公开页面，
请保持合理的轮询间隔（守护模式默认 15 秒）。

### 诊断与测试

```bash
python scripts/browser_check.py       # 默认后端：浏览器能否连接、能否取到 HLTV
python scripts/health.py              # HTTP 后端：区分 IP 级 / 路径级封锁
python scripts/health.py --json
python scripts/hltv_inspect.py /matches   # 页面结构 dump，改版时用来定位新选择器
python scripts/hltv-live --watch 15       # 极速实时比分（守护模式，写缓存）

python tests/test_parsers.py          # 离线：解析逻辑
python tests/test_launcher.py         # 离线：后端选择、显示环境、Termux 识别、CDP 探测
python tests/smoke.py                 # 联网冒烟（约 1.5 分钟）
python tests/smoke.py --only ranking player career
```

测试分两层是有意的：离线测试用与线上同构的夹具验证逻辑，不依赖网络，所以当 HLTV
限流或改版时，能立刻分清是**逻辑问题**还是**页面变了** —— 这个区分在本项目的开发过程中
救过好几次场。

### 合规声明

本项目为**非官方**工具，与 HLTV.org 无关联。它只读取公开页面，不做任何写操作。

请合理使用：保持默认的低请求频率，不要用于商业再分发或高频轮询。工具返回的数据版权归 HLTV 及其原始权利人所有。

### 许可

MIT

---

<div align="center">

### 🌐 Language / 语言

[简体中文](#简体中文) · [English](#english)

</div>

---

<a id="english"></a>

## English

Query **HLTV.org** Counter-Strike data directly from your AI assistant — matches, results, live scores, world rankings, teams, players, news, and the event calendar.

By default it fetches pages with a **real browser**: it runs **in the background, completely invisible**, and never disturbs the page you're currently reading.
Supports Windows / macOS / Linux, plus **Android Termux**.

### What it can answer

| Question | Tool called |
|---|---|
| What matches are on today? | `hltv_get_matches` |
| What's live right now? | `hltv_get_matches(live_only=True)` |
| **What's the current score?** | **`hltv_get_live_scores()`** |
| How has Vitality been doing lately? | `hltv_get_results(team="Vitality")` |
| Who's in the world top 30 right now? | `hltv_get_team_ranking` |
| ZywOo's rating and career achievements? | `hltv_get_player(name="ZywOo")` |
| **How has ZywOo performed year by year?** | **`hltv_get_player_career(name="ZywOo")`** |
| **What was ropz's rating each year?** | **`hltv_get_player_year_stats(name="ropz")`** |
| **Who played well on CT side on Inferno in this match?** | **`hltv_get_match_stats(match_id, map="Inferno", side="ct")`** |
| What's the prize pool for this Major? Who's attending? | `hltv_get_event(name="...")` |
| How has FaZe been doing lately? | `hltv_get_team_matches(name="FaZe")` |
| Who's stronger historically, FaZe or Vitality? | `hltv_get_head_to_head("FaZe", "Vitality")` |
| Who's on FaZe's current roster? | `hltv_get_team(name="FaZe")` |
| What's in the news lately? | `hltv_get_news` |
| What big events are coming up? | `hltv_get_events` |

**Every tool accepts either an ID or a name** — just write `name="Vitality"` and the server resolves it to an ID, so the model never has to run a separate search first.

> Just want a **quick glance at the current score**? The repo ships `python scripts/hltv-live` — it bypasses the browser and talks to HLTV directly, returning in 1–2 seconds. See [Fast live scores](#fast-live-scoresscriptshltv-live) below.

### Installation

```bash
git clone <repo> && cd hltv-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

**No Playwright in the dependency list** — browser control is handled by a built-in native CDP client, with a single pure-Python `websocket-client` dependency. There are two reasons for this design: Playwright can't be installed on Termux/Android, and its `new_page()` always steals focus (see "Not disturbing your browsing" below).

You need one of Chrome / Chromium / Edge installed locally. On Linux, installing `Xvfb` is also recommended to provide the invisible virtual display. If you can't install a browser (CI, for example), switch to the HTTP backend: `pip install -e ".[http]"` and set `HLTV_BACKEND=http`.

> **`curl_cffi` is an optional dependency.** Only the HTTP backend needs it; the default browser backend does not. It requires compiling curl-impersonate + BoringSSL, which is very hard to get working on platforms like Android — so **don't** add it back to `dependencies`.

#### Android / Termux offline install (zero compilation)

The most painful part of installing Python dependencies on Termux is compiling native extensions on-device (`lxml`, `cryptography`, `pydantic_core`…). This repo provides a **prebuilt offline bundle** that installs with a single command and **compiles nothing at all**:

```bash
tar xzf hltv-mcp-termux-offline.tar.gz
cd hltv-mcp-termux-offline
bash install.sh
```

The bundle already contains all 30 wheels (including the Android ARM64 build of `pydantic_core`), and installation uses `--no-index` so pip reads **only** local files and **never touches PyPI**. See the bundle notes on the [Releases](https://github.com/frogg435/hltv-mcp/releases) page.

### Wiring it into an MCP client

Add this to your client's MCP configuration:

```json
{
  "mcpServers": {
    "hltv": {
      "command": "/absolute/path/hltv-mcp/.venv/bin/python",
      "args": ["-m", "hltv_mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/hltv-mcp/src"
      }
    }
  }
}
```

After installing with `pip install -e .`, you can also use the command entry point directly:

```json
{
  "mcpServers": {
    "hltv": { "command": "/absolute/path/hltv-mcp/.venv/bin/hltv-mcp" }
  }
}
```

**No environment variables are required.** On startup the server **warms up** in the background: it launches the browser and fetches the schedule, live scores, results and rankings pages once each. In practice Cloudflare issues an extra real challenge on the **first visit to certain paths** (10–25 seconds), so doing this at startup absorbs that cost up front — **your very first query is already warm**.

Warmup **yields**: after the first page it waits 8 seconds before each subsequent page to check whether you're querying, and stops immediately if a request comes in. It never queues slow requests ahead of yours. Afterwards the same browser instance is reused, and it's shut down automatically when the MCP server exits.

A few optional tuning knobs:

```json
{
  "env": {
    "HLTV_BACKEND": "auto",
    "HLTV_BROWSER_VISIBLE": "0"
  }
}
```

### Tool reference

| Tool | Description |
|---|---|
| `hltv_search` | Search players/teams/events/news, name → ID |
| `hltv_get_matches` | Schedule (upcoming + live), filterable by team/event, live-only option |
| `hltv_get_live_scores` | **Live score snapshot**: ongoing matches, current map round count, maps won (poll for progress) |
| `hltv_get_results` | Results with scores and winner, paginated |
| `hltv_get_match` | Single match detail: map scores + **per-map, per-team player stats** (nickname, player ID, nationality, K-D, ADR, KAST, Rating, Swing) |
| `hltv_get_team_ranking` | World team rankings (with points) |
| `hltv_get_team` | Team profile: ranking, coach, roster |
| `hltv_get_player` | Player profile: Rating 3.0, ability ratings, career honours summary |
| `hltv_get_player_career` | **Year-by-year career**: teams per year, Top 20 placements by year, awards, titles, MVPs |
| `hltv_get_player_year_stats` | **Year-by-year rating and detailed stats**: Rating, K/D, ADR, maps played, rating vs Top 5/10/20 opponents |
| `hltv_get_match_stats` | **Per-map, per-side (CT/T) player stats for a single match**: Op.K-D, multi-kills, KAST, 1vX, headshots, ADR, Rating |
| `hltv_get_event` | Event detail: prize pool, dates, location, VRS weight, attending teams, placements and prize distribution |
| `hltv_get_team_matches` | Recent team results: date, opponent, score, win/loss |
| `hltv_get_head_to_head` | Head-to-head record: per-map detail + aggregated win rate by map |
| `hltv_get_news` | News list |
| `hltv_get_news_article` | News article body |
| `hltv_get_events` | Event calendar |
| `hltv_backend_status` | Which backend is in use, whether the browser is available; call this first when troubleshooting "no data" |

Everything is read-only; there are no write operations.

### How it works, and known limitations

#### Three backends for fetching pages

| Backend | How | Characteristics |
|---|---|---|
| **Browser** (default) | Fetches pages with a real browser | Most reliable against Cloudflare; the only one that can do click interactions; requires a local browser |
| **HTTP** | `curl_cffi` + Safari TLS fingerprint | Fast, light, no browser needed; but can't get past Cloudflare's path-level rules |
| **hybrid** | Tries HTTP first, falls back to the browser when blocked | Both capabilities; the cost is a half-second probe on every request |

`HLTV_BACKEND=auto` (default) / `browser` / `http` / `hybrid` controls the choice; see "Backend selection" below.

#### Cloudflare

HLTV sits behind Cloudflare. Measured results (**assuming a clean egress IP**):

| Method | Result |
|---|---|
| Plain `requests` / `curl` | ❌ 403 "Just a moment..." |
| `got-scraping` (Chrome TLS fingerprint) | ❌ 403 |
| `curl_cffi` + Chrome / Firefox / Edge fingerprints | ❌ 403 |
| **`curl_cffi` + Safari fingerprint** | ✅ **200, normal page** |
| **Real browser** | ✅ **200, including `/stats/*`** |

The HTTP backend uses `curl_cffi` with `impersonate="safari17_0"`. The optimal fingerprint may differ on another network; override it with `HLTV_IMPERSONATE`.

#### Backend: a real browser by default

Cloudflare accumulates **IP reputation**, and bans escalate in stages:

```
Clean IP  →  one path blocked (e.g. /stats/*)  →  whole site 403 (even the homepage)
```

Once you're in the second or third stage, **changing the client disguise doesn't help** — we measured it:

| Attempt | Result |
|---|---|
| 7 different TLS fingerprints (Safari / Chrome 131 / 124 / 120 / Firefox / Edge) | all 403 |
| Headless Chromium / headed Chromium (Xvfb) / headed real Chrome | all 403 |
| Adding stealth scripts (scrubbing `navigator.webdriver` etc.) | no effect |

**What actually works is a real browser.** Measured side by side (**same IP, same moment**):

| Method | `/` | `/stats/players/individual/11816/ropz` |
|---|---|---|
| `curl_cffi` (Safari fingerprint) | ❌ 403 | ❌ 403 |
| **Real browser + persistent profile** | ✅ **200** | ✅ **200** |

The difference isn't headed vs. headless — it's two things: the **complete fingerprint of a real browser**, and the use of a **persistent profile context**. An anonymous context gets blocked just the same.

So the **default backend is the browser**, and it works **out of the box** — you don't need to start Chrome yourself first:

```bash
# Nothing to configure, just run it. (A separate profile is created in ~/.cache/hltv-mcp on first run.)
python scripts/browser_check.py
```

The launcher does all of this automatically:

1. If a browser with a debugging port is already running (or you set `HLTV_BROWSER_CDP`), reuse it
2. Otherwise launch one with a **separate persistent profile** (at `~/.cache/hltv-mcp/chrome-profile`)
3. On exit, **close only the instance it launched itself** — your own browser is never touched

#### Not disturbing your browsing

This is a hard design requirement, not a "best effort":

* **Invisible.** On Linux the launcher creates its own Xvfb virtual display, so the browser runs headed but has no display device at all; on other desktop systems the window is moved off-screen. You see no window and no pop-ups.
* **No focus stealing, no touching your tabs.** Every tab is created with CDP's `background=true` and closed immediately afterwards. The page you're reading is never navigated away or pushed to the background.

Both were measured. Using `document.visibilityState` and `document.hasFocus()` as objective indicators, four real queries were run with the user's page open the whole time:

| | Before query | Throughout / after query |
|---|---|---|
| User page URL | `example.com/` | unchanged |
| `visibilityState` | `visible` | `visible` |
| `hasFocus()` | unchanged | unchanged |
| Tab count | 1 | 1 (no leftovers) |

A control experiment was run too: with the earlier `background=false` implementation, the same scenario immediately turned the user's page `visibilityState` to `hidden` and `hasFocus()` to `false` — i.e. it got pushed aside. This is one of the reasons this project **doesn't use Playwright** (its `new_page()` always activates the new tab).

`python scripts/browser_check.py` has this check built in, so you can verify it yourself.

#### Android / Termux

Termux is an explicitly supported target platform: **the service still launches the browser itself and it stays invisible; your phone's browser is untouched, and no adb forwarding is needed.**

```bash
pkg install tur-repo x11-repo
pkg install chromium xorg-server-xvfb python
pip install hltv-mcp
```

A few easy places to trip up:

* **Chromium isn't in the official main repo** — it lives in TUR (`tur-repo`) and depends on the GTK/X11 libraries from `x11-repo` (linked even in headless mode). But note: `tur-repo` and `x11-repo` — the two **repository-enabling packages themselves — are in the main repo**, so the official sources alone are enough; no third-party repo is required. Conversely, if `pkg install chromium` says the package can't be found, first check that those two `pkg install tur-repo x11-repo` commands succeeded.
* **Chromium's executable is called `chromium-browser`**, not `chromium`. This project finds it automatically (`$PREFIX/bin/chromium-browser`).
* **`xorg-server-xvfb` is mandatory** — it *is* how "invisible" is implemented: the browser runs headed but with no display device. Without it, you can only fall back to headless mode, and headless gets blocked by Cloudflare.
* Android-specific flags `--no-sandbox` (setuid sandboxing is unavailable on Android) and `--disable-gpu` are added automatically at launch.
* Termux puts its temp directory at `$TMPDIR` (`/data/data/com.termux/files/usr/tmp`) rather than `/tmp`, and the X11 socket lives there too — this project searches all three locations.

`playwright` **cannot be installed** here — it throws `Unsupported platform: android` outright, and its `new_page()` always steals focus. So this project doesn't use it, and instead ships its own native CDP client (requiring only pure-Python `websocket-client`).

The separate profile isn't an arbitrary choice: first, it avoids exposing your everyday browsing data on a debugging port; second, when a Chrome instance is already running under the same profile, a new process just stuffs tabs into the old instance and never opens a debugging port at all. It has a welcome side effect too — once the profile persists, `cf_clearance` survives, so subsequent startups hit noticeably fewer challenges.

Security boundary: **your browser is never closed**, and cookies are neither read nor exported. If you need an authenticated session, log in yourself in the browser — this project never handles any credentials.

##### Headless mode gets blocked (measured)

One thing that must be stated clearly: **`--headless` gets blocked by Cloudflare.**

| Mode | Homepage | `/matches` | `/stats/players/...` |
|---|---|---|---|
| `--headless=new` | ❌ challenge page | ❌ challenge page | ❌ challenge page |
| Headed (incl. Xvfb virtual display) | ✅ 200 | ✅ 200 | ✅ **964KB** |

So when there's "no display", you must **not** simply fall back to headless — that amounts to silently failing. This project's approach: on Linux, if no usable display is detected but Xvfb is available, it **creates a virtual display itself** (e.g. `:99`) so the browser still runs headed. This path was verified to work in containers too, and the virtual display is torn down on exit along with everything else.

Not using Xvfb is fine as well: as long as a display environment exists (a desktop OS), it just runs in ordinary headed mode.

#### Backend selection

| `HLTV_BACKEND` | Behaviour |
|---|---|
| `auto` (default) | **Browser preferred**; falls back to HTTP only when the browser **can't start at all** |
| `browser` | Force the browser. Errors out rather than falling back |
| `http` | Force HTTP. For environments where a browser can't be installed (CI, bare containers) |
| `hybrid` | **HTTP preferred**; switches to the browser when Cloudflare blocks it, and remembers "which kinds of paths require the browser" |

Note the boundary of `auto`'s fallback: **"the page was blocked by Cloudflare" does not count as "can't start"**, and doesn't trigger a fallback — because the HTTP backend would receive the same challenge page, and falling back would only make the error harder to understand. Only "browser not found / can't reach the debugging port / startup timed out" trigger the fallback, which is announced once on stderr before switching.

`hybrid` is the "fast path" version of `auto` rather than a watered-down one — the data it ultimately returns is identical, it just reverses the order: spend half a second on a cheap request first, and only launch the browser if blocked. In practice `/stats/*` has its own blocking rule while every other path goes through fine over HTTP.

But to be honest: **on desktop, hybrid isn't faster than the default browser backend** (both measured at around 1 second locally). Its value is on weak devices — on a phone/Termux, rendering 1MB of HTML costs more than an extra network round trip. Desktop users should just use the default `auto`.

#### Diagnose before you act

```bash
python scripts/browser_check.py   # default backend: is the browser usable, can it reach HLTV
python scripts/health.py          # HTTP backend: distinguish IP-level from path-level blocking
```

How to read `health.py`:

- **Homepage also 403** → IP-level ban. Change your egress IP, or switch to the default browser backend
- **Only specific paths 403** → path-level rule (`/stats/*` falls in this category); the browser backend is unaffected

You can also change the egress with a proxy (`HLTV_PROXY`). Residential IPs work best; datacenter IPs are typically blocked just the same.

#### Rate limiting

**Request frequency is the single most important thing to watch when using this MCP.** A burst of dense requests gets the current egress IP rate-limited by Cloudflare individually, showing up as **one path returning 403 persistently while others work fine**, and recovery takes minutes to hours.

The client does the following by default:

- **Browser backend**: **0.5 s interval + 0–0.8 s random jitter** (`HLTV_BROWSER_MIN_INTERVAL` / `HLTV_JITTER`). A browser request *is* "a human paging through a site" — Cloudflare judges it on entirely different grounds than bare HTTP, so throttling yourself to crawler standards just slows you down for nothing
- **HTTP backend**: **3 s interval** (`HLTV_MIN_INTERVAL`). Bare HTTP requests look most like a crawler and are throttled most readily
- In-memory cache: live scores 15 s, schedule 60 s, results 120 s, news 300 s, rankings 1 h, player/team profiles 30 min
- On a 403 it does **not** immediately rebuild the session (that would discard cookies already passed and make things worse); it backs off and retries first, and only swaps the session on the final attempt

If a tool keeps returning 403, raise `HLTV_MIN_INTERVAL` to `5` or higher, or change your network egress.

#### Per-map, per-side match data

`hltv_get_match_stats` returns complete data for **every player, on every map, on each side (CT/T), in a given BO1/BO3/BO5**:

```jsonc
// hltv_get_match_stats(match_id=2399253, map="Inferno", side="ct")
{
  "available_maps": ["2 - 1 Best of 3", "13 - 0 Dust2", "8 - 13 Inferno", "13 - 9 Mirage"],
  "results": [{
    "map": "Inferno",
    "sides": {
      "ct": [
        {"team": "100 Thieves", "players": [
          {"nickname": "rain", "opening_kd": "3 : 0", "multi_kills": "2", "kast": "83.3%",
           "clutches_1vx": "0", "kills": "8 (4)", "assists": "5 (0)", "deaths": "8 (0)",
           "adr": "78.8", "round_swing": "-2.27%", "rating": "0.90"}
        ]}
      ]
    }
  }]
}
```

Two implementation notes:

* **Maps must be clicked to switch; sides need not be.** In practice the DOM contains all three tables `totalstats` / `ctstats` / `tstats` simultaneously, and only the currently selected one lacks the `hidden` class — so all three sides are read in one go, and clicking is only needed for maps.
* **"Detailed stats" on the match page points at a different ID.** The match page is `/matches/{id}` while the stats page is `/stats/matches/{another-id}`; they aren't interchangeable, so the latter has to be extracted from the former.

#### About `/stats/*` and year-by-year ratings

The `/stats/*` paths (including the stats page where **year-by-year ratings** live) are blocked by Cloudflare under the HTTP backend. **With the browser backend enabled they load normally** — this is a prerequisite for `hltv_get_player_year_stats`.

```jsonc
// hltv_get_player_year_stats(player_id=11816, years=[2019, 2022, 2024, 2025, 2026])
{
  "seasons": [
    {"year": 2019, "rating_version": "Rating 2.0", "rating": 1.19, "kd_ratio": 1.29,
     "adr": 80.4, "maps_played": 200, "kills": 4005},
    {"year": 2024, "rating_version": "Rating 3.0", "rating": 1.13, "kd_ratio": 1.18,
     "adr": 75.9, "maps_played": 189, "kills": 3035},
    {"year": 2025, "rating_version": "Rating 3.0", "rating": 1.18, "kd_ratio": 1.24,
     "adr": 78.6, "maps_played": 200, "kills": 3182}
  ],
  "career_total": {"rating_version": "Rating 2.0", "rating": 1.15, "maps_played": 1915}
}
```

Note that HLTV's Rating system has been revised over time (1.0 → 2.0 → 2.1 → 3.0), so **rating values are not directly comparable across years**; `rating_version` is returned for each season so you can tell.

#### A misleading URL

`/stats/teams/matches/{a}/{b}` looks like "the head-to-head record between a and b", but **in practice it returns all of team a's matches** — FaZe's page has 2063 maps across 131 distinct opponents, the second ID does no filtering, and the `?contextIds=` parameter has no effect either.

So `hltv_get_head_to_head` was changed to **filter locally by opponent name**, which is what produces a genuine H2H (FaZe vs Vitality = 81 maps, 37 wins 44 losses, 45.7% win rate). The cost is downloading the whole page (about 5MB / 5 seconds).

#### Maintaining the parsers

HLTV redesigns its pages, and selectors may stop matching. When a tool returns no data:

```bash
python scripts/hltv_inspect.py /matches                 # dump the page's class-name distribution
python scripts/hltv_inspect.py /team/6667/x --selector .profile-team-stat
```

Once you've located the new class names, update the corresponding parsing function in `src/hltv_mcp/parsers.py`. All parsers follow the rule "missing field → return None, never raise", so a partial page change won't fail the entire tool call.

### Speed

Time is spent almost entirely in two places: **browser cold start** and **fetching the page itself**. Here's how each is handled:

| Problem | Approach |
|---|---|
| Cold start (launching the browser + passing the Cloudflare challenge) all landing on the first query | Background **warmup** at startup moves those seconds into the gap between "client handshake" and "you typing"; warmup also yields and never blocks your query |
| Certain paths get an extra Cloudflare challenge on **first** visit (10–25 s) | The commonly used paths (schedule / live scores / results / rankings) are all in the warmup list, absorbing that cost at startup |
| The browser backend throttled to crawler standards (a hard 3 s wait per request) | The browser backend switched to a 0.5 s interval; the HTTP backend keeps 3 s |
| The match stats page had two fixed `sleep`s (3.5 s + 3.0 s) | Replaced with "wait for the element to appear / for content to change", typically returning in under 1 second |
| After passing the challenge, the page reloads via JS, leaving a brief shell with "correct title, incomplete content" | Detected, then waits for the content to stabilise before reading — avoiding a page of partial data being returned without any error |

Measured locally (same machine, same network, timed page by page):

| Scenario | Before | After |
|---|---|---|
| Routine pages (schedule / results / rankings / live scores) | 2.6 – 4.2 s | **0.3 – 2.0 s** |
| Live scores **first** query (hits the path challenge) | 28 s | **0.8 s** (challenge absorbed by startup warmup) |
| Detailed match stats (`hltv_get_match_stats`) | 8 s+ (6.5 s of it just fixed waiting) | **~2 s** |
| First query (cold start) | 2 – 15 s | **≈ 0** (absorbed by startup warmup) |

> One thing **isn't** fixable in code: for paths **not in the warmup list** (especially `/stats/*`), the first visit may still hit a real challenge, measured at 9–25 seconds, after which the same path is consistently around 1 second. So "the first time you look up a player's year-by-year rating" being slow is normal — querying the same player again is fast. To eliminate even that, add the path to `HLTV_WARMUP_PAGES`.

### Configuration

| Environment variable | Default | Description |
|---|---|---|
| `HLTV_BACKEND` | `auto` | Backend: `auto` (browser preferred) / `browser` (forced) / `http` (forced HTTP) / `hybrid` (HTTP preferred, switch to browser when blocked) |
| `HLTV_WARMUP` | `1` | Warm up the browser in the background at startup so the first query doesn't wait for a cold start. Set `0` to disable |
| `HLTV_WARMUP_PAGES` | `/matches,/livescore,/results,/ranking/teams,/search` | Pages fetched in sequence during warmup. In practice Cloudflare issues an extra real challenge on the **first visit to certain paths** (`/livescore`, `/search`, `/stats/*`) taking 10–25 s; running through them at startup makes user queries warm |
| `HLTV_WARMUP_IDLE` | `8` | Seconds to wait before warming the next page, to see whether the user is doing anything. Yields immediately if a request arrives |
| `HLTV_BROWSER_CDP` | empty | Reuse an **externally launched** browser, e.g. `http://127.0.0.1:9222`. Leave empty to let the service prepare one |
| `HLTV_BROWSER_AUTOLAUNCH` | `1` | Set `0` to forbid auto-launching a browser and only reuse an existing instance |
| `HLTV_BROWSER_VISIBLE` | `0` | Set `1` to make the browser window visible (for debugging). Hidden by default |
| `HLTV_BROWSER_HEADLESS` | automatic | Set `1` to force headless. **Note that headless gets blocked by Cloudflare** — avoid unless necessary |
| `HLTV_CHROME_BIN` | auto-detected | Path to the browser executable (Chrome/Chromium/Edge) |
| `HLTV_BROWSER_PORT` | `9222` | Preferred debugging port when auto-launching; switches automatically if occupied |
| `HLTV_CHROME_PROFILE` | `~/.cache/hltv-mcp/chrome-profile` | Separate profile directory used when auto-launching |
| `HLTV_CACHE_DIR` | platform cache dir | Stores the profile, browser logs and port record |
| `HLTV_PROXY` | empty | Egress proxy, e.g. `http://user:pass@host:port` or `socks5://host:port`. **The primary remedy for IP-level blocking** |
| `HLTV_MIN_INTERVAL` | `3.0` | Minimum interval between two requests for the **HTTP backend** (seconds) |
| `HLTV_BROWSER_MIN_INTERVAL` | `0.5` | Minimum interval between two requests for the **browser backend** (seconds) |
| `HLTV_HYBRID_MIN_INTERVAL` | `1.0` | Minimum interval for the probing HTTP request in hybrid mode (seconds) |
| `HLTV_JITTER` | `0.8` | Upper bound of the random jitter added to intervals (seconds) |
| `HLTV_TIMEOUT` | `40` | Single-request timeout (seconds) |
| `HLTV_MAX_RETRIES` | `3` | Number of retries on failure |
| `HLTV_NAV_RETRIES` | `3` | Page navigation retries (browser backend) |
| `HLTV_CHALLENGE_WAIT` | `25` | Maximum wait for the Cloudflare challenge to pass (seconds) |
| `HLTV_CHALLENGE_POLL` | `0.6` | Challenge polling interval (seconds) |
| `HLTV_BLOCK_ASSETS` | `0` | Set `1` to block images/fonts/ad analytics scripts. Measured: HLTV is mostly server-rendered HTML, so enabling this is actually slightly slower on desktop; worth trying on weak devices |
| `HLTV_IMPERSONATE` | `safari17_0` | TLS fingerprint for the HTTP backend; also accepts `chrome131`, `firefox135`, etc. |

The standard `HTTPS_PROXY` / `ALL_PROXY` variables are recognised too.

<a id="fast-live-scoresscriptshltv-live"></a>

### Fast live scores: `scripts/hltv-live`

`hltv_get_live_scores` inside the MCP goes through the browser backend — accurate, but it pays for browser rendering. When you just want a quick glance at the score, the script shipped in the repo is a better deal: it requests `https://www.hltv.org/scores` directly (this path isn't blocked by Cloudflare — it's the `/matches/*` style pages that are; roughly 40KB gzipped) without launching a browser at all:

```bash
python scripts/hltv-live             # list all currently ongoing matches (~1.5–2.5 s)
python scripts/hltv-live falcons     # only those whose team name contains "falcons" (multiple keywords allowed)
python scripts/hltv-live --json      # JSON output
python scripts/hltv-live --watch 15  # daemon mode: poll every 15 seconds and write a cache
python scripts/hltv-live --cache     # read the daemon's cache, millisecond-level (no network)
```

Measured (Android/Termux, same match): the direct script takes 1.6–2.4 s, reading the daemon cache takes about 60 ms, and scores match the page; the browser backend's cold start, by contrast, takes tens of seconds. The script also only reads public pages — please keep polling at a reasonable interval (daemon mode defaults to 15 seconds).

### Diagnostics and tests

```bash
python scripts/browser_check.py       # default backend: can the browser connect, can it reach HLTV
python scripts/health.py              # HTTP backend: distinguish IP-level vs path-level blocking
python scripts/health.py --json
python scripts/hltv_inspect.py /matches   # page structure dump, for locating new selectors after a redesign
python scripts/hltv-live --watch 15       # fast live scores (daemon mode, writes a cache)

python tests/test_parsers.py          # offline: parsing logic
python tests/test_launcher.py         # offline: backend selection, display environment, Termux detection, CDP probing
python tests/smoke.py                 # networked smoke test (~1.5 minutes)
python tests/smoke.py --only ranking player career
```

The two-layer split is deliberate: the offline tests verify the logic against fixtures isomorphic to the live pages and don't depend on the network, so when HLTV rate-limits or redesigns, you can immediately tell whether it's a **logic problem** or **the page changed** — that distinction has saved the day several times during this project's development.

### Compliance

This project is an **unofficial** tool and is not affiliated with HLTV.org. It only reads public pages and performs no write operations.

Please use it sensibly: keep the default low request rate, and don't use it for commercial redistribution or high-frequency polling. Copyright in the data returned by the tools belongs to HLTV and its original rights holders.

### License

MIT
