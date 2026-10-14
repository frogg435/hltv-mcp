"""HLTV MCP 服务器。

暴露一组只读工具，让 AI 能查 CS 赛程、赛果、排名、战队、选手、新闻与赛事。

设计取舍：
  * 所有工具接受「ID 或名称」两种入参 —— AI 通常拿不到数字 ID，名称解析在
    服务端内部完成，避免让模型先查一次搜索再查一次详情。
  * 返回值统一是 JSON 字符串。跨客户端兼容性最好，模型也容易继续加工。
  * 只读。不做任何写操作，也就不存在误伤线上数据的风险。
"""

from __future__ import annotations

import json
import re
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import parsers as P
from .client import HltvError, get_client
from .resolver import require_id, search as _search

MAX_LIMIT = 100

server = MCPServer(
    name="hltv",
    title="HLTV.org",
    version="1.2.0",
    instructions=(
        "查询 HLTV.org 的 Counter-Strike 赛事数据：赛程、赛果、世界排名、战队、选手、"
        "新闻与赛事日历。所有工具都接受数字 id 或名称（如 \"Vitality\"、\"ZywOo\"），"
        "名称会由服务端自动解析。不确定名称拼写时先用 hltv_search。"
    ),
)


# --------------------------- 辅助 ---------------------------

def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _clamp(limit: int, default: int = 20) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, MAX_LIMIT))


def _match_tokens(*values: Any) -> list[str]:
    return [str(v).strip().lower() for v in values if v]


def _filter_matches(
    rows: list[dict[str, Any]],
    team: str | None = None,
    event: str | None = None,
) -> list[dict[str, Any]]:
    """按队伍或赛事名做宽松过滤（大小写不敏感、允许子串）。"""
    out = rows
    if team:
        needle = team.strip().lower()
        out = [
            r
            for r in out
            if needle in (r.get("team1") or "").lower()
            or needle in (r.get("team2") or "").lower()
        ]
    if event:
        needle = event.strip().lower()
        out = [r for r in out if needle in (r.get("event") or "").lower()]
    return out


# --------------------------- 工具 ---------------------------

@server.tool(
    name="hltv_search",
    description=(
        "在 HLTV 上搜索选手、战队、赛事或新闻，返回名称与对应 ID。"
        "不确定拼写、或需要把名称换成 ID 时先调这个。"
    ),
)
def hltv_search(query: str, kind: str | None = None, limit: int = 15) -> str:
    """
    Args:
        query: 搜索关键词，例如 "vitality"、"zywoo"、"ESL Pro League"。
        kind: 可选过滤，取值 player / team / event / news / stats。
        limit: 返回条数，默认 15，上限 100。
    """
    try:
        return _dump({"query": query, "results": _search(query, kind=kind, limit=_clamp(limit, 15))})
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_matches",
    description=(
        "获取赛程：即将开始与正在进行中的比赛。可按队伍名或赛事名过滤，"
        "也可只看正在直播的比赛。"
    ),
)
def hltv_get_matches(
    team: str | None = None,
    event: str | None = None,
    live_only: bool = False,
    limit: int = 20,
) -> str:
    """
    Args:
        team: 队伍名过滤，子串匹配，例如 "Vitality"。
        event: 赛事名过滤，子串匹配，例如 "ESL"。
        live_only: 为 true 时只返回正在进行的比赛。
        limit: 返回条数，默认 20。
    """
    try:
        rows = P.parse_match_list(get_client().fetch_soup("/matches"))
        if live_only:
            rows = [r for r in rows if r.get("live")]
        rows = _filter_matches(rows, team, event)
        return _dump({"count": len(rows), "matches": rows[:_clamp(limit)]})
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_results",
    description="获取最近的比赛结果（已结束），含比分与胜方。可按队伍或赛事过滤。",
)
def hltv_get_results(
    team: str | None = None,
    event: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Args:
        team: 队伍名过滤，子串匹配。
        event: 赛事名过滤，子串匹配。
        limit: 返回条数，默认 20。
        offset: 分页偏移，每页 100 条，默认 0（最近的比赛）。
    """
    try:
        page = max(0, int(offset) // 100)
        rows = P.parse_results(get_client().fetch_soup(f"/results?offset={page * 100}"))
        rows = _filter_matches(rows, team, event)
        return _dump({"count": len(rows), "results": rows[:_clamp(limit)]})
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_match",
    description="获取单场比赛的详细信息：双方阵容、地图比分、选手数据。",
)
def hltv_get_match(match_id: int, slug: str = "match") -> str:
    """
    Args:
        match_id: 比赛 ID，可由 hltv_get_matches / hltv_get_results 得到。
        slug: URL 尾段，仅影响可读性，默认 "match" 也能正常跳转。
    """
    try:
        soup = get_client().fetch_soup(f"/matches/{int(match_id)}/{slug}")
        detail = P.parse_match_detail(soup)
        detail["match_id"] = int(match_id)
        detail["url"] = f"https://www.hltv.org/matches/{int(match_id)}/{slug}"
        return _dump(detail)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_team_ranking",
    description="获取 HLTV 世界战队排名（含各队积分）。这是 CS 圈最常被引用的排名。",
)
def hltv_get_team_ranking(limit: int = 30, top_only: bool = True) -> str:
    """
    Args:
        limit: 返回条数，默认 30。
        top_only: 为 true 时只返回前 30 名，false 返回完整榜单（约 245 支）。
    """
    try:
        rows = P.parse_team_ranking(get_client().fetch_soup("/ranking/teams"))
        if top_only:
            rows = [r for r in rows if (r.get("rank") or 999) <= 30]
        return _dump({"count": len(rows), "ranking": rows[:_clamp(limit, 30)]})
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_team",
    description="获取战队资料：世界排名、Valve 排名、教练、阵容名单（含选手 ID）。",
)
def hltv_get_team(team_id: int | None = None, name: str | None = None) -> str:
    """
    Args:
        team_id: 战队 ID。与 name 二选一。
        name: 战队名，例如 "Vitality"，由服务端解析成 ID。
    """
    try:
        tid = require_id(entity="战队", entity_id=team_id, name=name, kind="team")
        team = P.parse_team(get_client().fetch_soup(f"/team/{tid}/x"))
        team["team_id"] = tid
        team["url"] = f"https://www.hltv.org/team/{tid}/x"
        return _dump(team)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_player",
    description=(
        "获取选手资料：真名、国籍、年龄、当前战队、Rating 3.0 及各项能力评分、"
        "生涯荣誉（Major 冠军数、线下赛冠军数等）。"
    ),
)
def hltv_get_player(player_id: int | None = None, name: str | None = None) -> str:
    """
    Args:
        player_id: 选手 ID。与 name 二选一。
        name: 选手昵称，例如 "ZywOo" 或 "s1mple"，由服务端解析成 ID。
    """
    try:
        pid = require_id(entity="选手", entity_id=player_id, name=name, kind="player")
        player = P.parse_player(get_client().fetch_soup(f"/player/{pid}/x"))
        player["player_id"] = pid
        player["url"] = f"https://www.hltv.org/player/{pid}/x"
        return _dump(player)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_player_career",
    description=(
        "获取选手的逐年生涯数据：历年在哪支战队、历年 HLTV Top 20 年度排名"
        "（如 2023 年第 3 名）、历年评委会奖项、历年赛事成绩。"
        "用于回答「某选手历年表现如何」这类问题。"
    ),
)
def hltv_get_player_career(
    player_id: int | None = None,
    name: str | None = None,
    include_achievements: bool = True,
) -> str:
    """
    Args:
        player_id: 选手 ID。与 name 二选一。
        name: 选手昵称，例如 "ZywOo"、"ropz"，由服务端解析成 ID。
        include_achievements: 是否返回历年赛事成绩（条数较多，默认 true）。

    注意：HLTV 的逐年 Rating 表位于 /stats/players/individual/*，该路径被
    Cloudflare 拦截，因此本工具返回的是同样按年组织、可稳定获取的 Top 20
    排名与荣誉，不含逐年 Rating 数值。当前生涯汇总 Rating 见 hltv_get_player。
    """
    try:
        pid = require_id(entity="选手", entity_id=player_id, name=name, kind="player")
        soup = get_client().fetch_soup(f"/player/{pid}/x")
        career = P.parse_player_career(soup)
        profile = P.parse_player(soup)

        result: dict[str, Any] = {
            "player_id": pid,
            "nickname": profile.get("nickname"),
            "real_name": profile.get("real_name"),
            "current_team": profile.get("current_team"),
            "career_rating": profile.get("stats", {}).get("Rating 3.0"),
            "team_history": career["team_history"],
            "top20_by_year": career["top20"],
            "awards_by_year": career["awards"],
            "mvp_medals": career["mvp_medals"],
            "event_trophies": career["event_trophies"],
            "url": f"https://www.hltv.org/player/{pid}/x",
        }
        if include_achievements:
            result["achievements"] = career["achievements"]
        else:
            result["achievements_count"] = len(career["achievements"])

        return _dump(result)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_player_year_stats",
    description=(
        "获取选手**逐年 Rating 与详细数据**（Rating 3.0/2.0、K/D、ADR、地图数、"
        "对 Top5/10/20 对手的 Rating 等）。这是回答「某选手历年数据怎么样」最直接的接口。"
    ),
)
def hltv_get_player_year_stats(
    player_id: int | None = None,
    name: str | None = None,
    years: list[int] | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    include_career_total: bool = True,
) -> str:
    """
    Args:
        player_id: 选手 ID。与 name 二选一。
        name: 选手昵称，例如 "ZywOo"、"ropz"。
        years: 指定年份列表，例如 [2024, 2025]。省略则依据选手的战队履历自动推断年份区间。
        from_year: 起始年份（与 years 互斥，优先级低于 years）。
        to_year: 结束年份，默认当前年份。
        include_career_total: 是否附带生涯汇总（不限定时间段）。

    每年需要加载一次统计页，年份越多耗时越长（约 2-4 秒/年）。
    """
    import datetime as _dt

    try:
        client = get_client()
        pid = require_id(entity="选手", entity_id=player_id, name=name, kind="player")

        # 确定要抓哪些年份
        if years:
            targets = sorted({int(y) for y in years})
        else:
            if from_year is None or to_year is None:
                # 从战队履历推断生涯起止年份（多花一次页面加载，但能避免抓无意义的年份）
                career = P.parse_player_career(client.fetch_soup(f"/player/{pid}/x"))
                start = _dt.date.today().year
                for entry in career.get("team_history", []):
                    match = re.search(r"(20\d{2})", str(entry.get("from") or ""))
                    if match:
                        start = min(start, int(match.group(1)))
                from_year = from_year or min(start, _dt.date.today().year)
            to_year = to_year or _dt.date.today().year
            targets = list(range(int(from_year), int(to_year) + 1))

        current_year = _dt.date.today().year
        seasons: list[dict[str, Any]] = []
        for year in targets:
            path = f"/stats/players/{pid}/x?startDate={year}-01-01&endDate={year}-12-31"
            try:
                season = P.parse_player_period_stats(client.fetch_soup(path))
            except HltvError as exc:
                seasons.append({"year": year, "error": str(exc)[:160]})
                continue
            if not season.get("rating") and not season.get("maps_played"):
                seasons.append({"year": year, "note": "该年无出场记录"})
                continue
            season["year"] = year
            seasons.append(season)

        result: dict[str, Any] = {
            "player_id": pid,
            "years": targets,
            "seasons": seasons,
            "url": f"https://www.hltv.org/stats/players/{pid}/x",
        }

        if include_career_total:
            try:
                total = P.parse_player_period_stats(
                    client.fetch_soup(f"/stats/players/{pid}/x")
                )
                result["career_total"] = total
            except HltvError as exc:
                result["career_total_error"] = str(exc)[:160]

        # 未走浏览器后端时给出明确指引
        if client.backend_in_use != "browser":
            result["warning"] = (
                f"当前使用 {client.backend_in_use} 后端，/stats/* 会被 Cloudflare 拦截。"
                "若数据为空或报错，请检查浏览器后端（默认已启用；"
                "运行 hltv_backend_status 可查看当前状态）。"
            )

        return _dump(result)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_event",
    description=(
        "获取赛事详情：总奖金池、起止日期、地点、VRS 权重、参赛队伍名单、"
        "以及名次与奖金分配（冠军/亚军/各名次拿多少钱）。"
    ),
)
def hltv_get_event(event_id: int | None = None, name: str | None = None) -> str:
    """
    Args:
        event_id: 赛事 ID（可由 hltv_get_events 得到）。
        name: 赛事名，由服务端解析成 ID。
    """
    try:
        eid = require_id(entity="赛事", entity_id=event_id, name=name, kind="event")
        event = P.parse_event(get_client().fetch_soup(f"/events/{eid}/x"))
        event["event_id"] = eid
        event["url"] = f"https://www.hltv.org/events/{eid}/x"
        return _dump(event)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_team_matches",
    description=(
        "获取某支战队的近期比赛战绩：日期、对手、比分、胜负。"
        "用于回答「某队最近打得怎么样」。"
    ),
)
def hltv_get_team_matches(
    team_id: int | None = None,
    name: str | None = None,
    limit: int = 15,
    only_wins: bool = False,
    only_losses: bool = False,
) -> str:
    """
    Args:
        team_id: 战队 ID。与 name 二选一。
        name: 战队名，例如 "Vitality"。
        limit: 返回条数，默认 15。
        only_wins: 只看胜利的比赛。
        only_losses: 只看失利的比赛。
    """
    try:
        tid = require_id(entity="战队", entity_id=team_id, name=name, kind="team")
        rows = P.parse_team_matches(get_client().fetch_soup(f"/team/{tid}/x"))
        if only_wins:
            rows = [r for r in rows if r.get("won") is True]
        if only_losses:
            rows = [r for r in rows if r.get("won") is False]
        wins = sum(1 for r in rows if r.get("won") is True)
        losses = sum(1 for r in rows if r.get("won") is False)
        return _dump(
            {
                "team_id": tid,
                "count": len(rows),
                "record": {"wins": wins, "losses": losses},
                "matches": rows[:_clamp(limit, 15)],
            }
        )
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_head_to_head",
    description=(
        "获取两支队伍的历史交手记录（H2H）。返回逐地图的对战明细"
        "（日期、赛事、地图、比分、胜负）与按地图聚合的胜率，用于赛前分析。"
    ),
)
def hltv_get_head_to_head(
    team1_id: int | None = None,
    team2_id: int | None = None,
    team1: str | None = None,
    team2: str | None = None,
    limit: int = 30,
) -> str:
    """
    Args:
        team1_id / team2_id: 两支队伍的 ID。
        team1 / team2: 两支队伍的名称，二选一以上两种之一。
        limit: 返回多少条明细，默认 30（按时间倒序，最近的在前）。
    """
    from .resolver import resolve_id

    try:
        a = require_id(entity="战队1", entity_id=team1_id, name=team1, kind="team")
        b = require_id(entity="战队2", entity_id=team2_id, name=team2, kind="team")

        # 该页面实际上返回 team1 的全部比赛，需要本地按对手名过滤。
        # 因此必须拿到 team2 的名字 —— 用户没给就从 ID 反查。
        opponent_name = team2
        if not opponent_name:
            _, hit = resolve_id(str(b), kind="team")
            opponent_name = (hit or {}).get("text") or str(b)

        data = P.parse_head_to_head(
            get_client().fetch_soup(f"/stats/teams/matches/{a}/{b}"),
            opponent=opponent_name,
        )
        data["team1_id"] = a
        data["team2_id"] = b
        data["team1"] = team1 or str(a)
        data["team2"] = opponent_name
        data["url"] = f"https://www.hltv.org/stats/teams/matches/{a}/{b}"
        data["records"] = data["records"][:_clamp(limit, 30)]
        return _dump(data)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_match_stats",
    description=(
        "获取单场比赛的**逐地图、分阵营（CT/T）的选手详细数据**："
        "Op.K-D、多杀、KAST、1vX 残局、爆头数、助攻、死亡、ADR、Rating 等。"
        "支持按地图（All/Inferno/Ancient…）与阵营（both/T/CT）筛选。"
    ),
)
def hltv_get_match_stats(
    match_id: int,
    map: str = "all",
    side: str = "both",
    all_maps: bool = False,
) -> str:
    """
    Args:
        match_id: 比赛 ID（由 hltv_get_matches / hltv_get_results 得到）。
        map: 地图名，如 "Inferno"、"Ancient"；"all" 表示全部地图合计。
        side: both（合计）/ t（恐怖分子方）/ ct（反恐精英方）/ all（三个都返回）。
        all_maps: 为 true 时遍历所有地图，返回每张图的数据（较慢）。

    BO1/BO3/BO5 均适用 —— 有几张图就有几个可选地图项。
    该工具必须用浏览器后端：地图切换是前端按钮，纯 HTTP 请求无法触发。
    """
    from .browser import get_browser_fetcher

    try:
        fetcher = get_browser_fetcher()
        wanted = ["both", "ct", "t"] if (side or "both").lower() == "all" else [(side or "both").lower()]
        for name in wanted:
            if name not in ("both", "ct", "t"):
                return _dump({"error": f"side 只支持 both / ct / t / all，收到 {side!r}"})

        # 先取一次：既拿到可选地图列表，也顺带完成默认地图的数据
        first = fetcher.fetch_match_stats(match_id, map_name=map)
        available_maps = first.get("available_maps") or []

        if all_maps:
            targets = _extract_map_names(available_maps) or [map]
        else:
            targets = [map]

        results: list[dict[str, Any]] = []
        for index, target in enumerate(targets):
            # 第一次的结果直接复用，避免重复打开页面
            raw = (
                first
                if index == 0 and target == map
                else fetcher.fetch_match_stats(match_id, map_name=target)
            )
            parsed = P.parse_match_stats_html(raw["html"], sides=wanted)
            results.append({"map": target, "sides": parsed["sides"]})

        return _dump(
            {
                "match_id": match_id,
                "available_maps": available_maps,
                "sides_returned": wanted,
                "results": results,
            }
        )
    except HltvError as exc:
        return _dump({"error": str(exc)})


def _extract_map_names(labels: list[str]) -> list[str]:
    """从地图按钮文本里取出地图名。

    按钮文本形如 "13 - 0 Dust2"、"2 - 1 Best of 3"、"8 - 13 Inferno"，
    末段是地图名或 "Best of 3"（比赛整体，不算地图）。
    """
    names: list[str] = []
    for label in labels or []:
        text = re.sub(r"^[\d\s\-–:]+", "", str(label)).strip()
        if not text or "Best of" in text:
            continue
        names.append(text)
    return names


@server.tool(
    name="hltv_get_news",
    description="获取 HLTV 最新新闻列表（标题、分类、时间、链接）。",
)
def hltv_get_news(limit: int = 20) -> str:
    """
    Args:
        limit: 返回条数，默认 20。
    """
    try:
        rows = P.parse_news_list(get_client().fetch_soup("/news/archive"))
        return _dump({"count": len(rows), "news": rows[:_clamp(limit)]})
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_news_article",
    description="获取一篇 HLTV 新闻的正文内容。",
)
def hltv_get_news_article(news_id: int, slug: str = "news") -> str:
    """
    Args:
        news_id: 新闻 ID，可由 hltv_get_news 得到。
        slug: URL 尾段，仅影响可读性。
    """
    try:
        soup = get_client().fetch_soup(f"/news/{int(news_id)}/{slug}")
        article = P.parse_news_article(soup)
        article["news_id"] = int(news_id)
        article["url"] = f"https://www.hltv.org/news/{int(news_id)}/{slug}"
        return _dump(article)
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_get_events",
    description="获取赛事日历：正在进行与即将开始的比赛及线下大赛（含赛事 ID、地点、横幅）。",
)
def hltv_get_events(limit: int = 30, name: str | None = None) -> str:
    """
    Args:
        limit: 返回条数，默认 30。
        name: 按赛事名过滤，子串匹配。
    """
    try:
        rows = P.parse_events(get_client().fetch_soup("/events"))
        if name:
            needle = name.strip().lower()
            rows = [r for r in rows if needle in (r.get("name") or "").lower()]
        return _dump({"count": len(rows), "events": rows[:_clamp(limit, 30)]})
    except HltvError as exc:
        return _dump({"error": str(exc)})


@server.tool(
    name="hltv_backend_status",
    description=(
        "查看当前用哪种方式访问 HLTV（浏览器后端 / HTTP 后端）、浏览器是否可用、"
        "以及各页面能否正常取到。排查「查不到数据」类问题时先调这个。"
    ),
)
def hltv_backend_status(check_pages: bool = False) -> str:
    """
    Args:
        check_pages: 为 true 时真实访问几个代表性页面验证连通性（较慢，约 10-20 秒）。
    """
    from .client import BACKEND, wants_browser
    from .launcher import AUTOLAUNCH, CACHE_DIR, PROFILE_DIR, find_browser

    client = get_client()
    info: dict[str, Any] = {
        "configured_backend": BACKEND,
        "backend_in_use": client.backend_in_use,
        "autolaunch": AUTOLAUNCH,
        "profile_dir": str(PROFILE_DIR),
        "log_file": str(CACHE_DIR / "chrome.log"),
    }

    if wants_browser():
        try:
            binary = find_browser()
            info["browser_binary"] = binary or "(未找到)"
        except HltvError as exc:
            info["browser_binary"] = f"(错误) {exc}"
            binary = None
        if binary:
            try:
                from .browser import get_browser_fetcher

                probe = get_browser_fetcher().probe()
                info["browser_connected"] = True
                info["browser_version"] = probe.get("browser_version")
                info["cdp_url"] = probe.get("cdp_url")
                info["autolaunched"] = probe.get("autolaunched")
                info["homepage_challenged"] = probe.get("challenged")
            except HltvError as exc:
                info["browser_connected"] = False
                info["browser_error"] = str(exc)[:300]

    if check_pages:
        checks: list[dict[str, Any]] = []
        for label, path in [
            ("赛程", "/matches"),
            ("选手资料", "/player/11816/ropz"),
            ("选手逐年统计", "/stats/players/11816/ropz"),
        ]:
            try:
                size = len(client.fetch_html(path))
                checks.append({"page": label, "ok": True, "bytes": size})
            except HltvError as exc:
                checks.append({"page": label, "ok": False, "error": str(exc)[:200]})
        info["page_checks"] = checks

    return _dump(info)


def main() -> None:
    """入口：默认 stdio，供 MCP 客户端拉起。"""
    server.run("stdio")


if __name__ == "__main__":
    main()
