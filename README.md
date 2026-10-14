# hltv-mcp

让 AI 直接查询 **HLTV.org** 的 Counter-Strike 赛事数据 —— 赛程、赛果、世界排名、战队、选手、新闻、赛事日历。

默认用**真实浏览器**取数据：**后台运行、界面上完全看不见**，也不会打扰你正在浏览的页面。
支持 Windows / macOS / Linux，以及 **Android Termux**。

## 它能回答什么

| 提问 | 调用的工具 |
|---|---|
| 今天有哪些比赛？ | `hltv_get_matches` |
| 现在正在打的有哪些？ | `hltv_get_matches(live_only=True)` |
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

## 安装

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

## 接入 MCP 客户端

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

**不需要任何环境变量。** 首次调用时服务会自动拉起一个浏览器（用独立 profile），
之后复用；MCP 退出时自动关掉它。几个可选的调优项：

```json
{
  "env": {
    "HLTV_BACKEND": "auto",
    "HLTV_MIN_INTERVAL": "3.0",
    "HLTV_BROWSER_VISIBLE": "0"
  }
}
```

## 工具清单

| 工具 | 说明 |
|---|---|
| `hltv_search` | 搜索选手/战队/赛事/新闻，名称 → ID |
| `hltv_get_matches` | 赛程（即将开始 + 进行中），支持按队伍/赛事过滤、只看直播 |
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

## 工作原理与已知限制

### 取页面的两种方式

| 后端 | 怎么用 | 特点 |
|---|---|---|
| **浏览器**（默认） | 用真实浏览器取页面 | 过 Cloudflare 最稳；唯一能做点击交互；稍慢、需要本机有浏览器 |
| **HTTP** | `curl_cffi` + Safari TLS 指纹 | 快、轻、无需浏览器；但过不了 Cloudflare 的路径级规则 |

`HLTV_BACKEND=auto`（默认）/ `browser` / `http` 控制选择，见下文「后端选择」。

### Cloudflare

HLTV 在 Cloudflare 之后。实测（**在出口 IP 干净的前提下**）：

| 方式 | 结果 |
|---|---|
| 裸 `requests` / `curl` | ❌ 403 Just a moment... |
| `got-scraping`（Chrome TLS 指纹） | ❌ 403 |
| `curl_cffi` + Chrome / Firefox / Edge 指纹 | ❌ 403 |
| **`curl_cffi` + Safari 指纹** | ✅ **200，正常页面** |
| **真实浏览器** | ✅ **200，含 /stats/\*** |

HTTP 后端用 `curl_cffi` 且 `impersonate="safari17_0"`。换网络环境后最优指纹可能不同，可用 `HLTV_IMPERSONATE` 覆盖。

### 后端：默认用真实浏览器

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

### 不打扰你的浏览

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

### Android / Termux

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

#### 无头模式会被拦（实测）

一个必须说清楚的点：**`--headless` 会被 Cloudflare 拦**。

| 模式 | 首页 | `/matches` | `/stats/players/...` |
|---|---|---|---|
| `--headless=new` | ❌ 挑战页 | ❌ 挑战页 | ❌ 挑战页 |
| 有头（含 Xvfb 虚拟显示） | ✅ 200 | ✅ 200 | ✅ **964KB** |

所以「没有显示器」时**不能**直接退化成无头 —— 那等于静默失效。本项目的做法是：Linux 上
若检测到没有可用显示且有 Xvfb，就**自己造一个虚拟显示**（如 `:99`），让浏览器仍以有头模式
运行。实测这条路径在容器里同样可用，退出时会连虚拟显示一起收掉。

不用 Xvfb 也没关系：只要有显示环境（桌面系统），走的就是普通有头模式。

### 后端选择

| `HLTV_BACKEND` | 行为 |
|---|---|
| `auto`（默认） | **优先浏览器**；只有浏览器**根本起不来**时才降级到 HTTP |
| `browser` | 强制浏览器。起不来就报错，不降级 |
| `http` | 强制 HTTP。适合装不了浏览器的环境（CI、纯容器） |

注意 `auto` 的降级边界：**「页面被 Cloudflare 拦」不算「起不来」**，那种情况不会降级 ——
因为 HTTP 后端会拿到同样的拦截页，降级只会把错误变得更难理解。只有「找不到浏览器 / 连不上
调试端口 / 启动超时」这类才降级，且会在 stderr 提示一次并转到 HTTP。

### 先诊断，再动手

```bash
python scripts/browser_check.py   # 默认后端：检查浏览器能不能用、能不能取到 HLTV
python scripts/health.py          # HTTP 后端：定位是 IP 级封禁还是路径级拦截
```

`health.py` 的判读方式：

- **首页也 403** → IP 级封禁。换出口 IP，或改用默认的浏览器后端
- **只有个别路径 403** → 路径级规则（`/stats/*` 属于此类），浏览器后端不受影响

也可用代理（`HLTV_PROXY`）换出口。住宅 IP 效果最好；机房 IP 通常同样会被拦。

### 限流

**请求频率是使用这个 MCP 时最需要注意的事。** 短时间密集请求会让当前出口 IP 被 Cloudflare 单独限流，表现为**某一路径持续 403，而其他路径正常**，且恢复需要数分钟到数小时。

客户端默认做了这些事：

- 请求间隔 **3 秒 + 0–0.8 秒随机抖动**（`HLTV_MIN_INTERVAL` / `HLTV_JITTER` 可调）
- 内存缓存：赛程 60s、赛果 120s、新闻 300s、排名 1h、选手/战队 30min
- 遇到 403 **不立刻重建会话**（那会丢掉已通过的 cookie，反而更糟），先退避重试，最后一次才换会话

如果某个工具持续报 403，把 `HLTV_MIN_INTERVAL` 调到 `5` 或更大，或换网络出口。

### 地图 × 阵营的比赛数据

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

### 关于 `/stats/*` 与逐年 Rating

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

### 一个名不副实的 URL

`/stats/teams/matches/{a}/{b}` 看起来是「a 与 b 的交手记录」，但**实测它返回的是 a 队的全部比赛** ——
FaZe 的页面有 2063 张地图、131 个不同对手，第二个 ID 不起过滤作用，`?contextIds=` 参数也无效。

所以 `hltv_get_head_to_head` 改为**本地按对手名过滤**，才得到真正的 H2H
（FaZe vs Vitality = 81 张地图，37 胜 44 负，胜率 45.7%）。
代价是要下载整个页面（约 5MB / 5 秒）。

### 解析器维护

HLTV 会改版，选择器可能失效。当某个工具抽不到数据时：

```bash
python scripts/hltv_inspect.py /matches                 # dump 页面类名分布
python scripts/hltv_inspect.py /team/6667/x --selector .profile-team-stat
```

定位到新类名后改 `src/hltv_mcp/parsers.py` 里对应的解析函数即可。所有解析器都遵循「缺字段返回 None，不抛异常」的约定，页面局部变化不会让整个工具调用失败。

## 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `HLTV_BACKEND` | `auto` | 后端：`auto`（优先浏览器）/ `browser`（强制）/ `http`（强制 HTTP） |
| `HLTV_BROWSER_CDP` | 空 | 复用一个**外部已启动**的浏览器，如 `http://127.0.0.1:9222`。留空则由本服务自动准备 |
| `HLTV_BROWSER_AUTOLAUNCH` | `1` | 置 `0` 则禁止自动拉起浏览器，只复用已有实例 |
| `HLTV_BROWSER_VISIBLE` | `0` | 置 `1` 让浏览器窗口可见（调试用）。默认隐藏 |
| `HLTV_BROWSER_HEADLESS` | 自动 | 置 `1` 强制无头。**注意无头会被 Cloudflare 拦**，非必要别开 |
| `HLTV_CHROME_BIN` | 自动探测 | 浏览器可执行文件路径（Chrome/Chromium/Edge） |
| `HLTV_BROWSER_PORT` | `9222` | 自动启动时优先使用的调试端口，被占则自动换 |
| `HLTV_CHROME_PROFILE` | `~/.cache/hltv-mcp/chrome-profile` | 自动启动时用的独立 profile 目录 |
| `HLTV_CACHE_DIR` | 平台缓存目录 | 存放 profile、浏览器日志、端口记录 |
| `HLTV_PROXY` | 空 | 出口代理，形如 `http://user:pass@host:port` 或 `socks5://host:port`。**遇到 IP 级封锁时的主要解法** |
| `HLTV_MIN_INTERVAL` | `3.0` | 两次请求的最小间隔（秒） |
| `HLTV_JITTER` | `0.8` | 间隔上的随机抖动上限（秒） |
| `HLTV_TIMEOUT` | `40` | 单次请求超时（秒） |
| `HLTV_MAX_RETRIES` | `3` | 失败重试次数 |
| `HLTV_NAV_RETRIES` | `3` | 页面导航重试次数（浏览器后端） |
| `HLTV_IMPERSONATE` | `safari17_0` | HTTP 后端的 TLS 指纹，可选 `chrome131`、`firefox135` 等 |

也识别标准的 `HTTPS_PROXY` / `ALL_PROXY`。

## 诊断与测试

```bash
python scripts/browser_check.py       # 默认后端：浏览器能否连接、能否取到 HLTV
python scripts/health.py              # HTTP 后端：区分 IP 级 / 路径级封锁
python scripts/health.py --json
python scripts/hltv_inspect.py /matches   # 页面结构 dump，改版时用来定位新选择器

python tests/test_parsers.py          # 离线：解析逻辑
python tests/test_launcher.py         # 离线：后端选择、显示环境、Termux 识别、CDP 探测
python tests/smoke.py                 # 联网冒烟（约 1.5 分钟）
python tests/smoke.py --only ranking player career
```

测试分两层是有意的：离线测试用与线上同构的夹具验证逻辑，不依赖网络，所以当 HLTV
限流或改版时，能立刻分清是**逻辑问题**还是**页面变了** —— 这个区分在本项目的开发过程中
救过好几次场。

## 合规声明

本项目为**非官方**工具，与 HLTV.org 无关联。它只读取公开页面，不做任何写操作。

请合理使用：保持默认的低请求频率，不要用于商业再分发或高频轮询。工具返回的数据版权归 HLTV 及其原始权利人所有。

## 许可

MIT
