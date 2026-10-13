# hltv-mcp

让 AI 直接查询 **HLTV.org** 的 Counter-Strike 赛事数据 —— 赛程、赛果、世界排名、战队、选手、新闻、赛事日历。

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

## 工具清单

| 工具 | 说明 |
|---|---|
| `hltv_search` | 搜索选手/战队/赛事/新闻，名称 → ID |
| `hltv_get_matches` | 赛程（即将开始 + 进行中），支持按队伍/赛事过滤、只看直播 |
| `hltv_get_results` | 赛果，含比分与胜方，支持分页 |
| `hltv_get_match` | 单场详情：地图比分、双方选手数据 |
| `hltv_get_team_ranking` | 世界战队排名（含积分） |
| `hltv_get_team` | 战队资料：排名、教练、阵容 |
| `hltv_get_player` | 选手资料：Rating 3.0、能力评分、生涯荣誉汇总 |
| `hltv_get_player_career` | **选手逐年生涯**：历年在哪支队、历年 Top20 排名、奖项、冠军、MVP |
| `hltv_get_player_year_stats` | **选手逐年 Rating 与详细数据**：Rating、K/D、ADR、地图数、对 Top5/10/20 对手的 Rating（需浏览器后端）|
| `hltv_get_match_stats` | **单场比赛逐地图、分阵营（CT/T）的选手数据**：Op.K-D、多杀、KAST、1vX、爆头、ADR、Rating（需浏览器后端）|
| `hltv_get_event` | 赛事详情：奖金池、日期、地点、VRS 权重、参赛队、名次与奖金分配 |
| `hltv_get_team_matches` | 战队近期战绩：日期、对手、比分、胜负 |
| `hltv_get_head_to_head` | 两队交手记录：逐地图明细 + 按地图聚合胜率 |
| `hltv_get_news` | 新闻列表 |
| `hltv_get_news_article` | 新闻正文 |
| `hltv_get_events` | 赛事日历 |

全部只读，没有任何写操作。

## 工作原理与已知限制

### Cloudflare

HLTV 在 Cloudflare 之后。实测（**在出口 IP 干净的前提下**）：

| 方式 | 结果 |
|---|---|
| 裸 `requests` / `curl` | ❌ 403 Just a moment... |
| `got-scraping`（Chrome TLS 指纹） | ❌ 403 |
| `curl_cffi` + Chrome / Firefox / Edge 指纹 | ❌ 403 |
| **`curl_cffi` + Safari 指纹** | ✅ **200，正常页面** |

所以客户端用 `curl_cffi` 且 `impersonate="safari17_0"`。换网络环境后最优指纹可能不同，可用 `HLTV_IMPERSONATE` 覆盖。

### 出口 IP 与浏览器后端

Cloudflare 按 **IP 累积信誉**，封禁会逐级升级：

```
干净 IP  →  某条路径被拦（如 /stats/*）  →  整站 403（首页也进不去）
```

但**换客户端伪装是没用的** —— 我们实测过，结果如下：

| 尝试 | 结果 |
|---|---|
| 换 7 种 TLS 指纹（Safari / Chrome 131 / 124 / 120 / Firefox / Edge） | 全部 403 |
| 无头 Chromium / 有头 Chromium（Xvfb）/ 有头真实 Chrome | 全部 403 |
| 加 stealth 脚本（抹 `navigator.webdriver` 等） | 无效 |

**真正有效的做法是借用用户自己的浏览器**。实测对照（**同一 IP、同一时刻**）：

| 方式 | `/` | `/stats/players/individual/11816/ropz` |
|---|---|---|
| `curl_cffi`（Safari 指纹） | ❌ 403 | ❌ 403 |
| **CDP 连接真实 Chrome 的默认配置文件** | ✅ **200** | ✅ **200** |

差异不在「有头/无头」，而在两点：**真实浏览器的完整指纹**，以及**使用 Chrome 的默认持久化配置文件上下文**（`browser.contexts[0]`）。用 `new_context()` 新建的匿名上下文同样会被拦。

所以本项目提供**浏览器后端**：

```bash
# 1. 带远程调试端口启动 Chrome（保持开着）
#    macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
#    Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
#    Linux
google-chrome --remote-debugging-port=9222

# 2. 告诉 MCP 走浏览器后端
export HLTV_BROWSER_CDP=http://127.0.0.1:9222

# 3. 自检
python scripts/browser_check.py
```

安全边界：只借用浏览器的网络栈取页面，**绝不关闭你的浏览器**，不读取也不导出 cookie。
用户如需登录态，自己在浏览器里登录即可，本项目不经手任何账号密码。

### 先诊断，再动手

遇到 403 先跑诊断脚本，它会告诉你问题出在哪一层：

```bash
python scripts/health.py
```

- **首页也 403** → IP 或客户端真实度不够，改用浏览器后端（见上）或换出口 IP
- **只有个别路径 403** → 路径级规则（`/stats/*` 属于此类），**浏览器后端可以绕过**

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
| `HLTV_BROWSER_CDP` | 空 | 浏览器后端：CDP 地址，如 `http://127.0.0.1:9222`。启用后可访问 `/stats/*`（逐年 Rating）|
| `HLTV_PROXY` | 空 | 出口代理，形如 `http://user:pass@host:port` 或 `socks5://host:port`。**遇到 IP 级封锁时的主要解法** |
| `HLTV_MIN_INTERVAL` | `3.0` | 两次请求的最小间隔（秒） |
| `HLTV_JITTER` | `0.8` | 间隔上的随机抖动上限（秒） |
| `HLTV_TIMEOUT` | `40` | 单次请求超时（秒） |
| `HLTV_MAX_RETRIES` | `3` | 失败重试次数 |
| `HLTV_IMPERSONATE` | `safari17_0` | TLS 指纹，可选 `chrome131`、`firefox135` 等 |

也识别标准的 `HTTPS_PROXY` / `ALL_PROXY`。

## 诊断与测试

```bash
python scripts/health.py              # 连通性诊断：区分 IP 级 / 路径级封锁
python scripts/health.py --json
python scripts/hltv_inspect.py /matches   # 页面结构 dump，改版时用来定位新选择器

python tests/test_parsers.py          # 离线单元测试，不联网，秒级
python tests/smoke.py                 # 联网冒烟测试（约 1 分钟）
python tests/smoke.py --only ranking player career
```

测试分两层是有意的：`test_parsers.py` 用与线上同构的夹具验证解析逻辑，不依赖网络，
所以当 HLTV 限流或改版时，能立刻分清是**逻辑问题**还是**页面变了**。

## 合规声明

本项目为**非官方**工具，与 HLTV.org 无关联。它只读取公开页面，不做任何写操作。

请合理使用：保持默认的低请求频率，不要用于商业再分发或高频轮询。工具返回的数据版权归 HLTV 及其原始权利人所有。

## 许可

MIT
