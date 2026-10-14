#!/usr/bin/env python3
"""解析器离线单元测试。

不访问网络：用与线上 DOM 同构的夹具验证解析逻辑。这样即使 HLTV 限流、
或者哪天改版，也能先分清「是解析逻辑错了」还是「是页面变了」。

夹具里的类名与图标路径均取自 2026-10 实测页面。

    python tests/test_parsers.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bs4 import BeautifulSoup  # noqa: E402

from hltv_mcp import parsers as P  # noqa: E402


# --------------------------------------------------------------------------
# 夹具：模拟选手资料页里的荣誉类表格
# 关键点是图标路径 —— 解析器靠它区分「年度 Top20 / 评委会奖 / 赛事冠军 / MVP」
# --------------------------------------------------------------------------
PLAYER_FIXTURE = """
<div class="playerProfile">
  <table>
    <tr><th class="time-period-cell">Time period</th><th class="team-header-cell">Team</th>
        <th class="table-trophy-row">Trophies</th></tr>
    <tr class="team">
      <td class="time-period-cell"><span data-time-format="MMM yyyy" data-unix="1736463600000">Jan 2025</span> - Present</td>
      <td class="team-name-cell"><a href="/team/9565/vitality">Vitality</a></td>
      <td></td>
    </tr>
    <tr class="team past-team">
      <td class="time-period-cell"><span data-time-format="MMM yyyy" data-unix="1641164400000">Jan 2022</span> - <span data-time-format="MMM yyyy" data-unix="1736463600000">Jan 2025</span></td>
      <td class="team-name-cell"><a href="/team/6667/faze">FaZe</a></td>
      <td></td>
    </tr>
  </table>

  <table>
    <tr><th class="placement-cell">Placement</th><th class="team-name-cell">Team</th>
        <th class="tournament-name-cell">Tournament</th></tr>
    <tr class="team">
      <td class="placement-cell gold"><div class="achievement">1st</div></td>
      <td class="team-name-cell"><a href="/team/9565/vitality">Vitality</a></td>
      <td class="tournament-name-cell">IEM Cologne Major 2026</td>
    </tr>
  </table>

  <table>
    <tr><th class="trophy-cell">Trophy</th><th class="rating-cell">Year</th></tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail"><img class="trophy-icon" src="/img/static/event/trophies/2025/3.png"/>
          <div class="trophy-event"><a href="/news/43608/top-20-players-of-2025">#3 best player in 25</a></div></div></td>
      <td class="rating-cell">2025</td>
    </tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail"><img class="trophy-icon" src="/img/static/event/trophies/2024/18.png"/>
          <div class="trophy-event"><a href="/news/40614/top-20-players-of-2024">#18 best player in 24</a></div></div></td>
      <td class="rating-cell">2024</td>
    </tr>
  </table>

  <table>
    <tr><th class="trophy-cell">Award</th><th class="rating-cell">Year</th></tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail"><img class="trophy-icon" src="/img/static/award/hltvAwardCT.png"/>
          <div class="trophy-event"><a href="/awards#awardshow-2025">Closer of the Year (Panel Award)</a></div></div></td>
      <td class="rating-cell">2025</td>
    </tr>
  </table>

  <table>
    <tr><th class="trophy-cell">Trophy</th></tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail">
          <img class="trophy-icon" src="https://img-cdn.hltv.org/eventtrophy/wPxgsQxdOzllRodf6Py95a.png"/>
          <div class="trophy-event"><a href="/events/1234/x">IEM Katowice 2025</a></div></div></td>
    </tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail">
          <img class="trophy-icon" src="/img/static/event/grandSlam.png"/>
          <div class="trophy-event"><a href="/news/1/x">Winner of ESL Grand Slam Season 5</a></div></div></td>
    </tr>
  </table>

  <table>
    <tr><th class="trophy-cell">Trophy</th></tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail">
          <img class="trophy-icon" src="https://img-cdn.hltv.org/mvpmedal/KhzJCYkclkI3NkIcwhbnK6.png"/>
          <div class="trophy-event"><a href="/news/2/x">IEM Dallas 2025 MVP</a></div></div></td>
    </tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail">
          <img class="trophy-icon" src="/img/static/event/mvpSilver.png"/>
          <div class="trophy-event"><a href="/news/3/x">BLAST Rivals MVP</a></div></div></td>
    </tr>
  </table>

  <!-- 参赛记录（eventlogo）：不是荣誉，应被忽略 -->
  <table>
    <tr><th class="trophy-cell">Trophy</th></tr>
    <tr class="trophy-row">
      <td><div class="trophy-detail">
          <img class="trophy-icon" src="https://img-cdn.hltv.org/eventlogo/2mt5dKGFBdIcxv37gayq1X.png"/>
          <div class="trophy-event"><a href="/events/99/x">Some Event 2024</a></div></div></td>
    </tr>
  </table>
</div>
"""


# 分时段统计页（Overview）的夹具：.stats-row 成对标签，Rating 在正文里
PERIOD_FIXTURE = """
<div>
  <div class="stats">
    <div class="stats-row"><span>Total kills</span><span>3035</span></div>
    <div class="stats-row"><span>Headshot %</span><span>52.9%</span></div>
    <div class="stats-row"><span>Total deaths</span><span>2574</span></div>
    <div class="stats-row"><span>K/D Ratio</span><span>1.18</span></div>
    <div class="stats-row" title="..."><span>Damage / Round</span><span>75.9</span></div>
    <div class="stats-row"><span>Maps played</span><span>189</span></div>
    <div class="stats-row"><span>Rounds played</span><span>4174</span></div>
    <div class="stats-row"><span>Kills / round</span><span>0.73</span></div>
    <div class="stats-row"><span>Impact rating</span><span>1.05</span></div>
  </div>
  <div>Featured ratings Rating 3.0 1.05
    vs top 5 opponents (56 maps) 1.07
    vs top 10 opponents (92 maps) 1.10
    vs top 20 opponents (139 maps) 1.11
  </div>
</div>
"""

# 老版本 Rating 的夹具（HLTV 改过版，写法不同）
LEGACY_FIXTURE = """
<div><div class="stats-row"><span>Maps played</span><span>200</span></div>
<div>Featured ratings Rating 2.0 1.19</div></div>
"""


# ---- 赛事详情 ----
EVENT_FIXTURE = """
<div>
  <h1>Thunderpick World Championship 2026</h1>
  <table><tr><th>Start date</th><th>End date</th><th>VRS date</th><th>Teams</th><th>Total prize pool</th><th>Location</th></tr>
  <tr><td>Oct 14th 2026</td><td>Oct 18th 2026</td><td>Aug 3rd 2026</td><td>8</td>
      <td class="prizepool" title="$1,000,000">$1,000,000</td><td>Malta</td></tr></table>
  <div class="teams-attending">
    <div class="team-name"><a href="/team/8297/furia"><div class="text-container"><div class="text">FURIA</div></div></a></div>
    <div class="team-name"><a href="/team/11283/falcons"><div class="text-container"><div class="text">Falcons</div></div></a></div>
  </div>
  <div class="col top-placement"><div class="placement"><div class="team"></div><div>1st</div><div class="prize">$250,000</div></div></div>
  <div class="col"><div class="placement"><div class="team"></div><div>2nd</div><div class="prize">$125,000</div></div></div>
</div>
"""

# ---- 战队近期战绩 ----
TEAM_MATCHES_FIXTURE = """
<table class="table-container match-table">
<tr class="team-row">
  <td class="date-cell"><span data-unix="1791656400000">11/10/2026</span></td>
  <td class="team-center-cell"><a class="team-name team-1">FaZe</a> 2 : 0 <a class="team-name team-2">NAVI Junior</a></td>
  <td class="stats-button-cell"><a href="/matches/2399055/faze-vs-navi-junior">Match</a></td>
</tr>
<tr class="team-row">
  <td class="date-cell"><span data-unix="1791570000000">10/10/2026</span></td>
  <td class="team-center-cell"><a class="team-name team-1">FaZe</a> 1 : 2 <a class="team-name team-2">Vitality</a></td>
  <td class="stats-button-cell"><a href="/matches/2399052/faze-vs-vitality">Match</a></td>
</tr>
</table>
"""

# ---- H2H ----
H2H_FIXTURE = """
<table>
<tr><th>Date</th><th>Event</th><th>Opponent</th><th>Map</th><th>Result</th><th>W/L</th></tr>
<tr><td class="time"><a href="/stats/matches/mapstatsid/1/x">20/08/26</a></td>
    <td class="gtSmartphone-only">Esports World Cup 2026</td><td class="smartphone-only">EWC 2026</td>
    <td>Vitality</td><td class="statsMapPlayed">Nuke</td><td class="text-center">13 - 9</td>
    <td class="text-center match-won won">W</td></tr>
<tr><td class="time"><a href="/stats/matches/mapstatsid/2/x">13/05/26</a></td>
    <td class="gtSmartphone-only">IEM Atlanta 2026</td><td class="smartphone-only">IEM Atlanta</td>
    <td>Vitality</td><td class="statsMapPlayed">Dust2</td><td class="text-center">5 - 13</td>
    <td class="text-center match-lost lost">L</td></tr>
<tr><td class="time"><a href="/stats/matches/mapstatsid/3/x">01/02/25</a></td>
    <td class="gtSmartphone-only">BLAST</td><td class="smartphone-only">BLAST</td>
    <td>MOUZ</td><td class="statsMapPlayed">Inferno</td><td class="text-center">13 - 2</td>
    <td class="text-center match-won won">W</td></tr>
</table>
"""

# ---- 比赛详细统计（地图 × 阵营）----
MATCH_STATS_FIXTURE = """
<div class="stats-content"><table class="stats-table totalstats hidden">
  <thead><tr><th class="st-teamname"><img class="logo" alt="100 Thieves"/></th>
    <th class="st-opkd">Op. K-D</th><th class="st-mks">MKs</th><th class="st-kast">KAST</th>
    <th class="st-clutches">1vsX</th><th class="st-kills">K (hs)</th><th class="st-assists">A (f)</th>
    <th class="st-deaths">D (t)</th><th class="st-adr">ADR</th><th class="st-roundSwing">Swing</th>
    <th class="st-rating">Rating 3.0</th></tr></thead>
  <tbody><tr><td class="st-player">rain</td>
    <td class="st-opkd traditional-data">4 : 0</td><td class="st-opkd eco-adjusted-data hidden">5 : 0</td>
    <td class="st-mks">4</td><td class="st-kast traditional-data">85.7%</td>
    <td class="st-clutches">0</td><td class="st-kills traditional-data">19 (13)</td>
    <td class="st-assists">6 (0)</td><td class="st-deaths traditional-data">15 (1)</td>
    <td class="st-adr traditional-data">98.4</td><td class="st-roundSwing won">+3.10%</td>
    <td class="st-rating ratingPositive">1.28</td></tr></tbody>
</table></div>
<div class="stats-content"><table class="stats-table ctstats">
  <thead><tr><th class="st-teamname"><img class="logo" alt="100 Thieves"/></th>
    <th class="st-opkd">Op. K-D</th><th class="st-kast">KAST</th><th class="st-adr">ADR</th>
    <th class="st-rating">Rating 3.0</th></tr></thead>
  <tbody><tr><td class="st-player">poiii</td>
    <td class="st-opkd traditional-data">1 : 2</td><td class="st-kast traditional-data">66.7%</td>
    <td class="st-adr traditional-data">73.3</td><td class="st-rating ratingNegative">0.96</td></tr></tbody>
</table></div>
<div class="stats-content"><table class="stats-table tstats hidden">
  <thead><tr><th class="st-teamname"><img class="logo" alt="100 Thieves"/></th>
    <th class="st-adr">ADR</th><th class="st-rating">Rating 3.0</th></tr></thead>
  <tbody><tr><td class="st-player">rain</td>
    <td class="st-adr traditional-data">124.6</td><td class="st-rating ratingPositive">1.55</td></tr></tbody>
</table></div>
"""


# ---- 比赛页面（/matches/{id}）的统计表 ----
# 这个页面与统计页的类名不同：td.players / td.kd / td.adr（统计页是 td.st-*）。
# 曾经因为选择器写成 A, B（逗号=或）导致两队数据完全重复，这组夹具专门锁住它。
MATCH_PAGE_FIXTURE = """
<!-- 一个 .stats-content = 一张地图；里面每支队伍各一张 totalstats，
     另有 hidden 的 ctstats / tstats（应被忽略） -->
<div class="stats-content">
  <table class="table totalstats">
    <tr><td class="players"><img class="logo" alt="Alpha"/></td>
        <td>K-D</td><td>eK-eD</td><td>Swing</td><td>ADR</td><td>eADR</td>
        <td>KAST</td><td>eKAST</td><td>Rating 3.0</td></tr>
    <tr><td class="players"><img class="flag" title="Sweden"/>
          <a href="/player/111/aaa"><span class="player-nick">AAA</span></a></td>
        <td class="kd traditional-data">20-10</td>
        <td class="kd eco-adjusted-data hidden">21-11</td>
        <td class="roundSwing">+5.00%</td>
        <td class="adr traditional-data">90.5</td>
        <td class="adr eco-adjusted-data hidden">91.5</td>
        <td class="kast traditional-data">75.0%</td>
        <td class="kast eco-adjusted-data hidden">76.0%</td>
        <td class="rating">1.40</td></tr>
    <tr><td class="players"><img class="flag" title="Denmark"/>
          <a href="/player/222/bbb"><span class="player-nick">BBB</span></a></td>
        <td class="kd traditional-data">12-15</td>
        <td class="kd eco-adjusted-data hidden">12-16</td>
        <td class="roundSwing">-2.00%</td>
        <td class="adr traditional-data">60.1</td>
        <td class="adr eco-adjusted-data hidden">61.1</td>
        <td class="kast traditional-data">55.0%</td>
        <td class="kast eco-adjusted-data hidden">56.0%</td>
        <td class="rating">0.80</td></tr>
  </table>
  <table class="table ctstats hidden"><tr><td class="players">(CT)</td></tr></table>
  <table class="table tstats hidden"><tr><td class="players">(T)</td></tr></table>
  <table class="table totalstats">
    <tr><td class="players"><img class="logo" alt="Beta"/></td><td>K-D</td><td>ADR</td></tr>
    <tbody>
    <tr><td class="players"><a href="/player/333/ccc"><span class="player-nick">CCC</span></a></td>
        <td class="kd traditional-data">30-8</td>
        <td class="adr traditional-data">110.0</td></tr>
    </tbody>
  </table>
</div>
<!-- 第二张地图：结构一致，只有一队 -->
<div class="stats-content">
  <table class="table totalstats">
    <tr><td class="players"><img class="logo" alt="Beta"/></td><td>K-D</td></tr>
    <tr><td class="players"><a href="/player/333/ccc"><span class="player-nick">CCC</span></a></td>
        <td class="kd traditional-data">13-4</td></tr>
  </table>
</div>
"""


def parse(soup):
    return P.parse_player_career(soup)


def main() -> int:
    soup = BeautifulSoup(PLAYER_FIXTURE, "lxml")
    career = parse(soup)
    failures: list[str] = []

    def check(label: str, actual, expected) -> None:
        ok = actual == expected
        print(f"{'✓' if ok else '✗'} {label}")
        if not ok:
            print(f"     期望 {expected!r}\n     实际 {actual!r}")
            failures.append(label)

    # 队伍履历
    check("队伍履历条数", len(career["team_history"]), 2)
    check("履历[0] 队伍", career["team_history"][0]["team"], "Vitality")
    check("履历[0] 时间段", career["team_history"][0]["period"], "Jan 2025 - Present")
    check("履历[0] current", career["team_history"][0]["current"], True)
    check("履历[1] current", career["team_history"][1]["current"], False)
    check("履历[1] 结束时间", career["team_history"][1]["to"], "Jan 2025")
    check("履历[1] team_id", career["team_history"][1]["team_id"], 6667)

    # 年度 Top20：来自 /static/event/trophies/{year}/{rank}.png
    check("Top20 条数", len(career["top20"]), 2)
    check("Top20[0] 年份", career["top20"][0]["year"], "2025")
    check("Top20[0] 名次", career["top20"][0]["rank"], 3)
    check("Top20[1] 名次", career["top20"][1]["rank"], 18)

    # 评委会奖项：来自 /static/award/
    check("评委会奖条数", len(career["awards"]), 1)
    check("评委会奖[0] 年份", career["awards"][0]["year"], "2025")
    check("评委会奖[0] 名称", career["awards"][0]["name"], "Closer of the Year (Panel Award)")

    # 赛事冠军：eventtrophy / grandSlam
    check("赛事冠军条数", len(career["event_trophies"]), 2)
    check("赛事冠军内容", career["event_trophies"][0]["name"], "IEM Katowice 2025")

    # MVP：mvpmedal / mvpSilver
    check("MVP 条数", len(career["mvp_medals"]), 2)

    # 参赛记录不应进入任何荣誉分类
    all_names = [
        item["name"]
        for key in ("top20", "awards", "event_trophies", "mvp_medals")
        for item in career[key]
    ]
    check("eventlogo 已被忽略", "Some Event 2024" in all_names, False)

    # 赛事成绩
    check("赛事成绩条数", len(career["achievements"]), 1)
    check("成绩[0] 名次", career["achievements"][0]["placement"], "1st")

    # 分类互不污染：评委会奖里不应出现赛事冠军
    check(
        "奖项未被赛事冠军污染",
        any("IEM Katowice" in a["name"] for a in career["awards"]),
        False,
    )

    # ---- 分时段统计（逐年 Rating）----
    period = P.parse_player_period_stats(BeautifulSoup(PERIOD_FIXTURE, "lxml"))
    check("Rating 值", period["rating"], 1.05)
    check("Rating 版本", period["rating_version"], "Rating 3.0")
    check("K/D", period["kd_ratio"], 1.18)
    check("ADR", period["adr"], 75.9)
    check("地图数为整数", period["maps_played"], 189)
    check("Kills 为整数", period["kills"], 3035)
    check("回合数为整数", period["rounds_played"], 4174)
    check("对 Top5 的 Rating", period["vs_top_opponents"][0]["rating"], 1.07)
    check("对 Top5 的地图数", period["vs_top_opponents"][0]["maps"], 56)

    legacy = P.parse_player_period_stats(BeautifulSoup(LEGACY_FIXTURE, "lxml"))
    check("旧版 Rating 也能解析", legacy["rating"], 1.19)
    check("旧版版本号", legacy["rating_version"], "Rating 2.0")

    # ---- 赛事详情 ----
    event = P.parse_event(BeautifulSoup(EVENT_FIXTURE, "lxml"))
    check("赛事名", event["name"], "Thunderpick World Championship 2026")
    check("奖池", event["prize_pool"], "$1,000,000")
    check("地点", event["location"], "Malta")
    check("参赛队数", event["teams_count"], 2)
    check("参赛队名", event["teams"][0]["team"], "FURIA")
    check("参赛队 ID", event["teams"][0]["team_id"], 8297)
    check("名次条数", len(event["placements"]), 2)
    check("冠军奖金", event["placements"][0]["prize"], "$250,000")

    # ---- 战队近期战绩 ----
    tm = P.parse_team_matches(BeautifulSoup(TEAM_MATCHES_FIXTURE, "lxml"))
    check("战绩条数", len(tm), 2)
    check("首场比分", (tm[0]["score1"], tm[0]["score2"]), (2, 0))
    check("首场对手", tm[0]["team2"], "NAVI Junior")
    check("首场为胜", tm[0]["won"], True)
    check("次场为负", tm[1]["won"], False)
    check("比赛 ID", tm[0]["match_id"], 2399055)

    # ---- H2H：必须按对手过滤，且日期排序正确 ----
    h2h = P.parse_head_to_head(BeautifulSoup(H2H_FIXTURE, "lxml"), opponent="Vitality")
    check("H2H 只含目标对手", len(h2h["records"]), 2)
    check("H2H 汇总场次", h2h["summary"]["maps_played"], 2)
    check("H2H 胜场", h2h["summary"]["maps_won"], 1)
    check("H2H 负场", h2h["summary"]["maps_lost"], 1)
    check("H2H 按图拆分 Nuke", h2h["by_map"]["Nuke"]["played"], 1)
    check("H2H 日期倒序", h2h["records"][0]["date"], "20/08/26")
    check("H2H 第二早", h2h["records"][1]["date"], "13/05/26")
    unfiltered = P.parse_head_to_head(BeautifulSoup(H2H_FIXTURE, "lxml"))
    check("H2H 不传对手则全部返回", len(unfiltered["records"]), 3)

    # ---- 比赛详细统计：三套阵营并存，按类名取值 ----
    ms = P.parse_match_stats_html(MATCH_STATS_FIXTURE)
    check("三个阵营齐全", sorted(ms["sides"].keys()), ["both", "ct", "t"])
    both = ms["sides"]["both"][0]
    check("队伍名", both["team"], "100 Thieves")
    rain = both["players"][0]
    check("选手名", rain["nickname"], "rain")
    check("取 traditional 而非 eco", rain["opening_kd"], "4 : 0")
    check("多杀", rain["multi_kills"], "4")
    check("ADR", rain["adr"], "98.4")
    check("Rating", rain["rating"], "1.28")
    check("字段映射齐全", sorted(k for k in rain if k != "nickname"),
          ["adr", "assists", "clutches_1vx", "deaths", "kast", "kills",
           "multi_kills", "opening_kd", "rating", "round_swing"])
    check("CT 阵营独立取值", ms["sides"]["ct"][0]["players"][0]["rating"], "0.96")
    check("T 阵营独立取值", ms["sides"]["t"][0]["players"][0]["adr"], "124.6")
    only_ct = P.parse_match_stats_html(MATCH_STATS_FIXTURE, sides=["ct"])
    check("可只取指定阵营", sorted(only_ct["sides"].keys()), ["ct"])

    # ---- 比赛页面统计：两队不能混在一起 ----
    stats = P.parse_match_page_stats(
        BeautifulSoup(MATCH_PAGE_FIXTURE, "lxml"), ["All maps", "Dust2"]
    )
    check("按地图分组", sorted(stats.keys()), ["All maps", "Dust2"])

    alpha_team, beta_team = stats["All maps"]
    check("第一队队名", alpha_team["team"], "Alpha")
    check("第二队队名", beta_team["team"], "Beta")

    a_nicks = [p["nickname"] for p in alpha_team["players"]]
    check("A 队选手", a_nicks, ["AAA", "BBB"])
    check("选手昵称取自 player-nick，不是全名", "AAA" in a_nicks, True)

    # 这两条是这个 bug 的核心回归点
    check("两队选手不重复", set(a_nicks) & {"CCC"}, set())
    check("B 队只有自己的选手", [p["nickname"] for p in beta_team["players"]], ["CCC"])

    first = alpha_team["players"][0]
    check("取 traditional 而非 eco 的 K-D", first["kd"], "20-10")
    check("ADR", first["adr"], "90.5")
    check("KAST", first["kast"], "75.0%")
    check("Rating", first["rating"], "1.40")
    check("Swing", first["round_swing"], "+5.00%")
    check("选手 ID", first["player_id"], 111)
    check("国籍", first["country"], "Sweden")

    # 表头行不能被当成选手
    check("表头未被计入", all(p["nickname"] not in ("Alpha", "K-D") for p in alpha_team["players"]), True)

    # 隐藏的阵营表不参与概览
    check("只用 totalstats，隐藏的阵营表被忽略", len(stats["All maps"]), 2)
    check("第二张地图独立解析", stats["Dust2"][0]["team"], "Beta")
    check("第二张地图的选手", [p["nickname"] for p in stats["Dust2"][0]["players"]], ["CCC"])

    print()
    if failures:
        print(f"{len(failures)} 项失败：{', '.join(failures)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
