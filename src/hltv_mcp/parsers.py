"""HLTV HTML → 结构化数据。

选择器全部基于 2026-10 实测的线上 DOM，不是照抄旧版库。HLTV 会改版，
若某天解析异常，先用 `scripts/hltv_inspect.py` dump 页面核对类名。

每个解析函数都遵循同一约定：缺字段就返回 None，不抛异常 —— 页面局部结构
变化不应该让整个工具调用失败。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

HLTV_BASE = "https://www.hltv.org"

# 从各种 href 里抠出数字 ID
_ID_RE = re.compile(r"/(\d+)(?:/|$)")


# --------------------------- 小工具 ---------------------------

def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _abs(href: str | None) -> str | None:
    return urljoin(HLTV_BASE, href) if href else None


def _id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    match = _ID_RE.search(href)
    return int(match.group(1)) if match else None


def _truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _clean_text(node: Any) -> str | None:
    """把 Tag 或字符串规整为干净的文本；None 原样返回。

    接受两种输入是有意为之：调用处经常是 `_clean_text(soup.select_one(...))`，
    结果可能是 Tag 也可能是 None，让这里统一兜住，避免每个调用点都写判断。
    """
    if node is None:
        return None
    if isinstance(node, Tag):
        raw = node.get_text(" ", strip=True)
    else:
        raw = str(node)
    cleaned = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip()
    return cleaned or None


# --------------------------- 赛程 ---------------------------

def parse_match_list(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析 /matches 的赛事列表（含即将开始与进行中）。"""
    matches: list[dict[str, Any]] = []

    for wrapper in soup.select(".match-wrapper[data-match-id]"):
        top = wrapper.select_one("a.match-top")
        href = top.get("href") if top else None

        teams = [_clean_text(t) for t in wrapper.select(".match-teamname")]
        teams = [t for t in teams if t]

        meta = [_clean_text(m) for m in wrapper.select(".match-meta")]
        meta = [m for m in meta if m]

        matches.append(
            {
                "match_id": _int(wrapper.get("data-match-id")),
                "url": _abs(href),
                "team1": teams[0] if len(teams) > 0 else None,
                "team2": teams[1] if len(teams) > 1 else None,
                "team1_id": _int(wrapper.get("team1")),
                "team2_id": _int(wrapper.get("team2")),
                "event": _clean_text(wrapper.select_one(".match-event")),
                "event_id": _int(wrapper.get("data-event-id")),
                "event_type": wrapper.get("data-eventtype"),
                "stage": _clean_text(wrapper.select_one(".match-stage")),
                "format": next((m for m in meta if m.lower().startswith("bo")), None),
                "live": _truthy(wrapper.get("live")) or any(m.lower() == "live" for m in meta),
                "lan": _truthy(wrapper.get("lan")),
                "region": wrapper.get("data-region"),
                "stars": _int(wrapper.get("data-stars")),
                "time": _clean_text(wrapper.select_one(".match-time")),
                "time_unix": _int(wrapper.get("data-unix")),
            }
        )

    return matches


# --------------------------- 赛果 ---------------------------

def parse_results(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析 /results 的已结束比赛。"""
    results: list[dict[str, Any]] = []

    for node in soup.select(".result-con"):
        link = node.select_one("a.a-reset") or node.select_one("a")
        href = link.get("href") if link else None

        # 队名与比分：.team 列表里带 team-won 标记胜方
        team_nodes = node.select(".team")
        team_names = [_clean_text(t) for t in team_nodes]
        team_names = [t for t in team_names if t]

        won_flags = ["team-won" in (t.get("class") or []) for t in team_nodes]

        score_node = node.select_one(".result-score")
        score_text = _clean_text(score_node) if score_node else None
        scores: list[int | None] = [None, None]
        if score_text:
            parts = re.findall(r"\d+", score_text)
            if len(parts) >= 2:
                scores = [int(parts[0]), int(parts[1])]

        unix_ms = _int(node.get("data-zonedgrouping-entry-unix"))

        results.append(
            {
                "match_id": _id_from_href(href),
                "url": _abs(href),
                "team1": team_names[0] if len(team_names) > 0 else None,
                "team2": team_names[1] if len(team_names) > 1 else None,
                "score1": scores[0],
                "score2": scores[1],
                "winner": (
                    team_names[0] if len(won_flags) > 0 and won_flags[0]
                    else team_names[1] if len(won_flags) > 1 and won_flags[1]
                    else None
                ),
                "event": _clean_text(node.select_one(".event")),
                "time_unix_ms": unix_ms,
                "time": (
                    _clean_text(node.select_one(".date"))
                    or _clean_text(node.select_one("[data-unix]"))
                ),
            }
        )

    return results


# --------------------------- 比赛详情 ---------------------------

def parse_match_detail(soup: BeautifulSoup) -> dict[str, Any]:
    """解析单场比赛页面。字段随赛事状态差异较大，缺失即为 None。"""
    detail: dict[str, Any] = {}

    team_names = [_clean_text(t) for t in soup.select(".teamName")]
    team_names = [t for t in team_names if t]
    detail["team1"] = team_names[0] if len(team_names) > 0 else None
    detail["team2"] = team_names[1] if len(team_names) > 1 else None

    # 比分区
    scores = [_clean_text(s) for s in soup.select(".team1-gradient .won, .team2-gradient .won")]
    total = soup.select_one(".totalrounds")
    detail["total_rounds"] = _clean_text(total)

    # 单图（map）结果
    maps: list[dict[str, Any]] = []
    for map_node in soup.select(".mapholder"):
        name = _clean_text(map_node.select_one(".mapname"))
        if not name:
            continue
        left = map_node.select_one(".results-left .results-team-score")
        right = map_node.select_one(".results-right .results-team-score")
        maps.append(
            {
                "map": name,
                "score1": _clean_text(left),
                "score2": _clean_text(right),
                "picked_by": _clean_text(map_node.select_one(".pick")),
            }
        )
    detail["maps"] = maps

    # 基础信息
    detail["event"] = _clean_text(soup.select_one(".event a")) or _clean_text(soup.select_one(".event"))
    detail["date"] = _clean_text(soup.select_one(".date"))
    detail["format"] = _clean_text(soup.select_one(".match-info-box .padding div:nth-child(3)"))

    # 双方选手表现
    for idx, side in enumerate(("team1", "team2"), start=1):
        players: list[dict[str, Any]] = []
        for row in soup.select(f".stats-content .team{idx}-table tbody tr, .stats-content table tbody tr"):
            name = _clean_text(row.select_one(".player-nick, td:nth-child(1)"))
            if not name:
                continue
            cells = [_clean_text(td) for td in row.select("td")]
            players.append({"name": name, "cells": [c for c in cells if c]})
        if players:
            detail[f"{side}_players"] = players[:10]

    return detail


# --------------------------- 排位 ---------------------------

def parse_team_ranking(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析 /ranking/teams 的世界排名。"""
    ranking: list[dict[str, Any]] = []

    for row in soup.select(".ranked-team"):
        name_node = row.select_one(".name")
        link = row.select_one("a")
        points = _clean_text(row.select_one(".points"))
        place = _clean_text(row.select_one(".position"))

        players = [_clean_text(p) for p in row.select(".player-nick, .rankingNickname")]
        players = [p for p in players if p]

        rank = None
        if place:
            num = re.search(r"\d+", place)
            rank = int(num.group()) if num else None

        point_value = None
        if points:
            num = re.search(r"\d+", points.replace(",", ""))
            point_value = int(num.group()) if num else None

        ranking.append(
            {
                "rank": rank,
                "team": _clean_text(name_node),
                "team_id": _id_from_href(link.get("href") if link else None),
                "points": point_value,
                "players": players,
            }
        )

    return ranking


# --------------------------- 战队 ---------------------------

def parse_team(soup: BeautifulSoup) -> dict[str, Any]:
    """解析战队资料页 /team/{id}/{slug}。"""
    logo_img = soup.select_one(".teamlogo, .team-logo-container img")
    team: dict[str, Any] = {
        "name": _clean_text(soup.select_one(".profile-team-name")),
        "logo": logo_img.get("src") if logo_img else None,
        "country": _clean_text(soup.select_one(".team-country")) or _clean_text(
            soup.select_one(".profile-team-info .team-country")
        ),
    }

    # .profile-team-stat 的结构是：图标 + <b>标签</b> + <span class="right">值</span>
    stats: dict[str, str] = {}
    for stat in soup.select(".profile-team-stat"):
        label = (
            _clean_text(stat.select_one(".regional-name-full"))
            or _clean_text(stat.select_one("b"))
            or _clean_text(stat.select_one(".regional-name-short"))
        )
        right = stat.select_one(".right")
        value = _clean_text(right)
        if label:
            # .right 里可能套着 <a>，取纯文本即可
            stats[label] = value or ""
    team["stats"] = stats

    # 阵容
    roster: list[dict[str, Any]] = []
    for item in soup.select(".bodyshot-team a, .team-roster-item"):
        href = item.get("href")
        nickname = _clean_text(item.select_one(".text-ellipsis, .nick")) or item.get("title")
        if not nickname:
            continue
        flag = item.select_one("img.flag")
        roster.append(
            {
                "nickname": nickname,
                "player_id": _id_from_href(href),
                "url": _abs(href),
                "country": flag.get("title") if flag else None,
                "country_code": flag.get("src", "").rsplit("/", 1)[-1].split(".")[0] if flag else None,
            }
        )
    team["roster"] = roster

    coach = soup.select_one(".profile-team-coach .bold, .team-coach .bold")
    team["coach"] = _clean_text(coach)

    return team


# --------------------------- 选手 ---------------------------

def parse_player(soup: BeautifulSoup) -> dict[str, Any]:
    """解析选手资料页 /player/{id}/{slug}。

    页面上的统计分两处：
      `.player-stat`        —— Rating 3.0、Firepower、Entrying 等能力项
      `.highlighted-stat`   —— Teams、Days in current team 一类的汇总数字
    """
    flag = soup.select_one(".player-summary-stat-box-left-flag img.flag")
    team_link = soup.select_one(".playerTeam a")

    player: dict[str, Any] = {
        "nickname": _clean_text(soup.select_one(".playerNickname")),
        "real_name": _clean_text(soup.select_one(".playerRealname")),
        "photo": (
            (soup.select_one(".player-summary-stat-box-left-bodyshot") or {}).get("src")
            if soup.select_one(".player-summary-stat-box-left-bodyshot")
            else None
        ),
        "country": flag.get("title") if flag else None,
        "country_code": (
            flag.get("src", "").rsplit("/", 1)[-1].split(".")[0] if flag else None
        ),
        "age_block": _clean_text(soup.select_one(".playerAge, [itemprop=age]")),
        "current_team": _clean_text(team_link) or _clean_text(soup.select_one(".playerTeam")),
        "current_team_id": _id_from_href(team_link.get("href") if team_link else None),
    }

    # 能力项与评分：<div class="player-stat"><b>标签</b><span class="statsVal"><p>值</p>…
    stats: dict[str, str] = {}
    for stat in soup.select(".player-stat"):
        label = _clean_text(stat.select_one("b"))
        value_node = stat.select_one(".statsVal")
        value = _clean_text(value_node) if value_node else None
        if label and value:
            # "67/100" 这类复合值只保留分子，更利于直接使用
            match = re.match(r"^(\d+)\s*/\s*100$", value)
            if match:
                value = match.group(1)
            stats[label.replace(":", "")] = value

    # 汇总数字
    highlights: dict[str, str] = {}
    for item in soup.select(".highlighted-stat"):
        label = _clean_text(item.select_one(".description"))
        value = _clean_text(item.select_one(".stat"))
        if label and value:
            highlights[label] = value

    player["stats"] = stats
    player["highlights"] = highlights
    player["rating"] = stats.get("Rating 3.0") or stats.get("Rating 2.1")

    aliases = [_clean_text(a) for a in soup.select(".playerAlias")]
    player["aliases"] = [a for a in aliases if a]

    return player


# --------------------------- 新闻 ---------------------------

def parse_news_list(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析新闻列表（/news/archive）。"""
    items: list[dict[str, Any]] = []

    for node in soup.select(".newsline"):
        href = node.get("href") if isinstance(node, Tag) else None
        items.append(
            {
                "title": _clean_text(node.select_one(".newstext")),
                "url": _abs(href),
                "news_id": _id_from_href(href),
                "category": _clean_text(node.select_one(".newsflag")),
                "time": _clean_text(node.select_one(".newsdate")),
            }
        )

    return [i for i in items if i["title"]]


def parse_news_article(soup: BeautifulSoup) -> dict[str, Any]:
    """解析新闻正文页。"""
    body_nodes = soup.select(".newsdesk .standard-box, .newsitem .body, .news-a")
    body = "\n\n".join(
        t for t in (_clean_text(" ".join(n.stripped_strings)) for n in body_nodes) if t
    )

    return {
        "title": _clean_text(soup.select_one(".newsitem .entry-title, h1")) or _clean_text(soup.title),
        "date": _clean_text(soup.select_one(".date, .newsdate")),
        "author": _clean_text(soup.select_one(".author, .newsitem .byline")),
        "body": body or None,
    }


# --------------------------- 赛事 ---------------------------

def parse_events(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析 /events 的赛事日历。

    结构：`.big-event`（有横幅的大赛事）与 `.small-event`（列表行），
    两者都是 <a href="/events/{id}/{slug}">。日期与参赛队在相邻的
    `tr.eventDetails` 行里，这里只取赛事本体信息。
    """
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for node in soup.select("a.big-event, a.small-event"):
        href = node.get("href")
        if not href or href in seen:
            continue
        seen.add(href)

        name = (
            _clean_text(node.select_one(".big-event-name"))
            or _clean_text(node.select_one(".event-name"))
            or _clean_text(node.select_one(".event-logo-container img"))
            or _clean_text(node.select_one(".event-header"))
        )
        if not name:
            continue

        logo = node.select_one("img")
        info = _clean_text(node.select_one(".big-event-info .info, .event-info"))

        events.append(
            {
                "name": name,
                "event_id": _id_from_href(href),
                "url": _abs(href),
                "logo": logo.get("src") if logo else None,
                "info": info,
                "dates": _clean_text(node.select_one(".eventDate, .date-col")),
                "prize_pool": _clean_text(node.select_one(".prizepool, .prizePool")),
                "teams": _int(node.select_one(".teams-number, .team-number")),
                "location": _clean_text(node.select_one(".location, .event-location")),
            }
        )

    return events


# --------------------------- 搜索 ---------------------------

def parse_search(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析 /search?query=xx 的结果，用于名称 → ID 解析。"""
    out: list[dict[str, Any]] = []

    for node in soup.select(".search-item, .search-result"):
        link = node.select_one("a")
        text = _clean_text(node.get_text(" ", strip=True))
        sub = node.select_one(".search-item-sub, .sub")
        if text:
            out.append(
                {
                    "text": text,
                    "sub": _clean_text(sub),
                    "url": _abs(link.get("href") if link else None),
                }
            )

    # 兜底：直接扫内容区里的站内链接，按 URL 前缀归类
    if not out:
        for link in soup.select("a[href]"):
            href = link.get("href") or ""
            m = re.match(r"^/(player|team|event|matches|news|stats)/(\d+)", href)
            if not m:
                continue
            label = _clean_text(link.get_text(" ", strip=True))
            if not label:
                continue
            out.append(
                {
                    "text": label,
                    "sub": m.group(1),
                    "url": _abs(href),
                    "kind": m.group(1),
                    "id": int(m.group(2)),
                }
            )

    # 去重
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        key = item.get("url") or item.get("text", "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


# --------------------------- 选手生涯（逐年） ---------------------------

def _table_kind(table: Tag) -> str | None:
    """按表头 class 判断表格类型，比按索引取更耐改版。"""
    th_classes: set[str] = set()
    for th in table.select("th"):
        th_classes.update(th.get("class") or [])

    if "time-period-cell" in th_classes:
        return "team_history"
    if "placement-cell" in th_classes:
        return "placements"
    if "trophy-cell" in th_classes:
        return "trophy_or_award"
    if "rating-cell" in th_classes:
        return "trophy_or_award"
    return None


def parse_player_career(soup: BeautifulSoup) -> dict[str, Any]:
    """解析选手的逐年生涯数据。

    说明：HLTV 把「逐年 Rating 表」放在 `/stats/players/individual/{id}/{slug}`，
    该路径被 Cloudflare 整体拦截（见 README「无法访问的页面」）。本函数改为
    从选手资料页抽取**同样按年组织**、且能稳定获取的数据：

      team_history  队伍履历（起止时间 + 队伍 + 期间奖杯数）
      top20         历年 HLTV Top 20 选手排名（即年度最佳评选名次）
      awards        历年评委会奖项（如 Closer of the Year）
      achievements  赛事冠军/名次（含年份）
    """
    career: dict[str, Any] = {
        "team_history": [],
        "top20": [],
        "awards": [],
        "event_trophies": [],
        "mvp_medals": [],
        "achievements": [],
    }

    for table in soup.select("table"):
        kind = _table_kind(table)
        if kind is None:
            continue

        if kind == "team_history":
            for row in table.select("tr.team"):
                period_cell = row.select_one("td.time-period-cell")
                team_link = row.select_one("td.team-name-cell a")
                if not team_link:
                    continue

                # 时间是 <span data-unix="毫秒">文本</span>，可能有一个（至今）或两个
                stamps = period_cell.select("span[data-unix]") if period_cell else []
                period_text = _clean_text(period_cell)
                start = stamps[0].get_text(strip=True) if len(stamps) > 0 else None
                end = stamps[1].get_text(strip=True) if len(stamps) > 1 else "Present"

                career["team_history"].append(
                    {
                        "team": _clean_text(team_link),
                        "team_id": _id_from_href(team_link.get("href")),
                        "from": start,
                        "to": end,
                        "period": period_text,
                        "current": "past-team" not in (row.get("class") or []),
                    }
                )

        elif kind == "placements":
            for row in table.select("tr.team"):
                placement = _clean_text(row.select_one("td.placement-cell"))
                team_link = row.select_one("td.team-name-cell a")
                tournament = _clean_text(row.select_one("td.tournament-name-cell"))
                if not (placement or tournament):
                    continue
                career["achievements"].append(
                    {
                        "placement": placement,
                        "team": _clean_text(team_link),
                        "tournament": tournament,
                    }
                )

        elif kind == "trophy_or_award":
            for row in table.select("tr.trophy-row"):
                cells = row.select("td")
                if not cells:
                    continue
                icon = row.select_one("img.trophy-icon")
                icon_src = icon.get("src") if icon else ""
                label = _clean_text(row.select_one(".trophy-event a")) or _clean_text(
                    row.select_one(".trophy-event")
                )
                year = _clean_text(cells[-1]) if len(cells) > 1 else None

                if not label:
                    continue

                entry: dict[str, Any] = {"name": label}

                # 按图标路径分类。HLTV 用不同的图标源区分这几种荣誉，
                # 混在一起会让「评委会奖项」里塞满赛事冠军。
                if "/static/award/" in icon_src:
                    entry["year"] = year
                    career["awards"].append(entry)
                elif "/static/event/trophies/" in icon_src:
                    # /img/static/event/trophies/2025/3.png —— 路径里的数字即年度名次
                    match = re.search(r"/trophies/(\d{4})/(\d+)\.png", icon_src)
                    if match:
                        entry["year"] = year or match.group(1)
                        entry["rank"] = int(match.group(2))
                    else:
                        entry["year"] = year
                    career["top20"].append(entry)
                elif "eventtrophy" in icon_src or "grandSlam" in icon_src:
                    entry["year"] = year
                    career["event_trophies"].append(entry)
                elif "mvpmedal" in icon_src or "mvp" in icon_src.lower():
                    entry["year"] = year
                    career["mvp_medals"].append(entry)
                # 其余（eventlogo 一类）是参赛记录，不算荣誉，跳过

    # 按年份倒序，便于直接阅读
    def _year_key(item: dict[str, Any]) -> int:
        value = str(item.get("year") or "")
        num = re.search(r"\d{4}", value)
        return int(num.group()) if num else 0

    for key in ("top20", "awards"):
        career[key].sort(key=_year_key, reverse=True)

    return career

# --------------------------- 选手分时段统计（逐年 Rating） ---------------------------

# HLTV 的 Rating 体系改过多次版本：1.0 → 2.0 → 2.1 → 3.0。
# 按年份抓取时会返回当年生效的版本，这里把版本号一起解析出来。
_RATING_RE = re.compile(r"Rating\s*(3\.0|2\.1|2\.0|1\.0)\s*([\d.]+)")
# vs top N opponents (M maps) X.XX
_VS_TOP_RE = re.compile(r"vs top (\d+) opponents\s*\((\d+)\s*maps\)\s*([\d.]+)")


def parse_player_period_stats(soup: BeautifulSoup) -> dict[str, Any]:
    """解析选手 Overview 统计页（可带 startDate/endDate 限定时间段）。

    页面结构：
      `.stats-row`            —— 「标签 + 数值」成对的统计项
      「Featured ratings」区块 —— 该时段的 Rating（含对各档对手的细分）
    """
    stats: dict[str, str] = {}
    for row in soup.select(".stats-row"):
        spans = row.find_all("span")
        if len(spans) >= 2:
            label = _clean_text(spans[0])
            value = _clean_text(spans[-1])
            if label and value:
                stats[label] = value

    text = soup.get_text(" ", strip=True)

    rating = rating_version = None
    match = _RATING_RE.search(text)
    if match:
        rating_version, rating = f"Rating {match.group(1)}", match.group(2)

    vs_top = [
        {"top_n": int(n), "maps": int(maps), "rating": float(value)}
        for n, maps, value in _VS_TOP_RE.findall(text)
    ]

    def num(key: str) -> float | None:
        raw = stats.get(key)
        if not raw:
            return None
        found = re.search(r"-?\d+(?:\.\d+)?", raw.replace(",", ""))
        return float(found.group()) if found else None

    def count(key: str) -> int | None:
        """计数类字段取整，避免出现「200.0 张地图」这种读起来别扭的值。"""
        value = num(key)
        return int(value) if value is not None else None

    return {
        "rating": float(rating) if rating else None,
        "rating_version": rating_version,
        "kd_ratio": num("K/D Ratio"),
        "adr": num("Damage / Round"),
        "kills": count("Total kills"),
        "deaths": count("Total deaths"),
        "headshot_pct": stats.get("Headshot %"),
        "maps_played": count("Maps played"),
        "rounds_played": count("Rounds played"),
        "kills_per_round": num("Kills / round"),
        "impact_rating": num("Impact rating"),
        "vs_top_opponents": vs_top,
        "raw": stats,
    }


# --------------------------- 赛事详情 ---------------------------

def parse_event(soup: BeautifulSoup) -> dict[str, Any]:
    """解析赛事详情页 /events/{id}/{slug}。

    页面有两张关键表格：
      · 头部信息表：Start date / End date / VRS date / Teams / Total prize pool / Location
      · 名次表：`.placement` 区块（名次 + 奖金 + 战队）
    参赛队单独在 `.teams-attending` 里。
    """
    event: dict[str, Any] = {}

    name_node = soup.select_one("h1, .event-name, .event-title")
    event["name"] = _clean_text(name_node)

    # 头部信息表：找表头里含 Start date / Total prize pool 的那张
    info: dict[str, str] = {}
    for table in soup.select("table"):
        headers = [_clean_text(th) or "" for th in table.select("th")]
        if any("Start date" in h or "Total prize pool" in h or "Prize pool" in h for h in headers):
            cells = [_clean_text(td) for td in table.select("td")]
            for key, value in zip(headers, cells):
                if key and value:
                    info[key.split("(")[0].strip()] = value
    event["info"] = info

    # 金额：优先取带 title 的 prize 单元格（值是完整数字）
    prize_node = soup.select_one("td.prizepool[title], .prizepool[title]")
    event["prize_pool"] = (
        prize_node.get("title") if prize_node else info.get("Total prize pool") or info.get("Prize pool")
    )
    event["date"] = info.get("Date") or (
        f"{info.get('Start date', '')} – {info.get('End date', '')}".strip(" –") or None
    )
    event["location"] = info.get("Location")
    event["vrs_date"] = info.get("VRS date")
    event["vrs_weight"] = info.get("VRS weight")

    # 参赛队伍
    teams: list[dict[str, Any]] = []
    for node in soup.select(".teams-attending .team-name a, .teams-attending a[href^='/team/']"):
        team_name = _clean_text(node.select_one(".text")) or _clean_text(node)
        if not team_name:
            continue
        href = node.get("href")
        rank_node = node.select_one(".event-world-ranking, .ranking")
        teams.append(
            {
                "team": team_name,
                "team_id": _id_from_href(href),
                "world_ranking": _clean_text(rank_node),
            }
        )
    # 去重（一个队伍可能出现多个链接）
    seen: set[str] = set()
    unique_teams = []
    for team in teams:
        key = str(team["team_id"]) or team["team"]
        if key in seen:
            continue
        seen.add(key)
        unique_teams.append(team)
    event["teams"] = unique_teams
    event["teams_count"] = len(unique_teams)

    # 名次与奖金分配
    placements: list[dict[str, Any]] = []
    for block in soup.select(".placement"):
        place = None
        prize = None
        for child in block.find_all("div", recursive=False):
            text = _clean_text(child)
            classes = child.get("class") or []
            if "prize" in classes:
                if prize is None and text:
                    prize = text
            elif text and place is None and re.match(r"^\d+(st|nd|rd|th)$|^\d+\s*[-–]\s*\d+", text):
                place = text
        link = block.select_one("a[href^='/team/']")
        if place or prize:
            placements.append(
                {
                    "placement": place,
                    "team": _clean_text(link),
                    "team_id": _id_from_href(link.get("href") if link else None),
                    "prize": prize,
                }
            )
    event["placements"] = placements

    return event


# --------------------------- 战队近期战绩 ---------------------------

def parse_team_matches(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析战队战绩表（战队页里的 `table.match-table`）。

    每行是一场比赛：日期、对阵（含比分）、以及指向比赛页的链接。
    """
    matches: list[dict[str, Any]] = []

    for row in soup.select("tr.team-row"):
        date_cell = row.select_one("td.date-cell")
        center = row.select_one("td.team-center-cell")
        link = row.select_one("a[href^='/matches/']")
        if not center:
            continue

        # 对阵文本形如 "FaZe 2 : 0 NAVI Junior"
        text = _clean_text(center) or ""
        score = re.search(r"(\d+)\s*:\s*(\d+)", text)
        names = re.split(r"\s*\d+\s*:\s*\d+\s*", text) if score else [text]
        team1 = _clean_text(names[0]) if names else None
        team2 = _clean_text(names[1]) if len(names) > 1 else None

        # 胜负：本方队伍通过 team-name 元素的 team-1 类标记
        mine = center.select_one("a.team-name.team-1")
        my_name = _clean_text(mine) if mine else None
        won = None
        if score and my_name:
            a, b = int(score.group(1)), int(score.group(2))
            won = a > b if team1 and my_name in team1 else b > a

        unix = date_cell.select_one("[data-unix]") if date_cell else None
        matches.append(
            {
                "date": _clean_text(date_cell),
                "time_unix_ms": _int(unix.get("data-unix")) if unix else None,
                "team1": team1,
                "team2": team2,
                "score1": int(score.group(1)) if score else None,
                "score2": int(score.group(2)) if score else None,
                "won": won,
                "match_id": _id_from_href(link.get("href") if link else None),
                "url": _abs(link.get("href") if link else None),
            }
        )

    return matches


# --------------------------- 交手记录（H2H） ---------------------------

def parse_head_to_head(soup: BeautifulSoup, opponent: str | None = None) -> dict[str, Any]:
    """解析两队交手记录。

    ⚠️ 重要：`/stats/teams/matches/{a}/{b}` 这个名字有误导性 —— 实测它返回的
    是 **a 队的全部比赛**（FaZe 的页面有 2063 张地图、131 个不同对手），
    第二个 ID 并不起过滤作用，`?contextIds=` 参数也无效。

    因此这里改为**本地按对手名过滤**，才是真正的 H2H。

    表头为 Date / Event / Opponent / Map / Result / W-L，**每一行是一张地图**，
    同一场比赛会占多行。
    """
    records: list[dict[str, Any]] = []

    for row in soup.select("table tr"):
        time_cell = row.select_one("td.time")
        if time_cell is None:
            continue

        cells = row.select("td")
        map_cell = row.select_one("td.statsMapPlayed")
        if map_cell is None or len(cells) < 5:
            continue

        # 对手是紧挨着地图列的前一格（该 td 没有 class，只能按位置取）
        index = cells.index(map_cell)
        opponent_name = _clean_text(cells[index - 1]) if index >= 1 else None
        if not opponent_name:
            continue

        if opponent:
            key = opponent.strip().lower()
            if key not in opponent_name.lower():
                continue

        win_node = row.select_one("td.match-won, td.match-lost, td.won, td.lost")
        won = None
        if win_node is not None:
            classes = " ".join(win_node.get("class") or [])
            won = "won" in classes

        # 结果比分在 W/L 格之前
        result = None
        for cell in cells[index + 1:]:
            text = _clean_text(cell)
            if text and re.match(r"^\d+\s*[-–:]\s*\d+$", text):
                result = text
                break

        link = time_cell.select_one("a[href]")
        event = None
        for cell in cells[:index]:
            text = _clean_text(cell)
            if text and text != _clean_text(time_cell):
                event = text
                break

        records.append(
            {
                "date": _clean_text(time_cell),
                "event": event,
                "opponent": opponent_name,
                "map": _clean_text(map_cell),
                "result": result,
                "won": won,
                "url": _abs(link.get("href") if link else None),
            }
        )

    wins = sum(1 for r in records if r["won"])
    losses = sum(1 for r in records if r["won"] is False)

    by_map: dict[str, dict[str, int]] = {}
    for record in records:
        name = record.get("map") or "Unknown"
        bucket = by_map.setdefault(name, {"played": 0, "won": 0, "lost": 0})
        bucket["played"] += 1
        if record["won"]:
            bucket["won"] += 1
        elif record["won"] is False:
            bucket["lost"] += 1

    # 按日期倒序，最近的在前。
    # 线上格式是 dd/mm/yy，直接按字符串排会错（"31/05/22" 会排到 "30/03/24" 前面），
    # 因此解析成 (年, 月, 日) 再排。
    def _date_key(record: dict[str, Any]) -> tuple[int, int, int]:
        raw = str(record.get("date") or "")
        match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
        if not match:
            return (0, 0, 0)
        day, month, year = (int(g) for g in match.groups())
        if year < 100:  # 两位年份补成 20xx
            year += 2000
        return (year, month, day)

    records.sort(key=_date_key, reverse=True)

    return {
        "summary": {
            "maps_played": len(records),
            "maps_won": wins,
            "maps_lost": losses,
            "map_win_rate": round(wins / len(records), 3) if records else None,
            "opponent": opponent,
        },
        "by_map": dict(
            sorted(by_map.items(), key=lambda kv: kv[1]["played"], reverse=True)
        ),
        "records": records,
    }


# --------------------------- 比赛详细统计（地图 × 阵营 × 选手） ---------------------------

# `st-*` 类名 → 输出字段名。HLTV 用这套类名标记每一列，
# 按类名取值比按列序取值稳得多。
_MATCH_STAT_FIELDS = {
    "st-opkd": "opening_kd",
    "st-mks": "multi_kills",
    "st-kast": "kast",
    "st-clutches": "clutches_1vx",
    "st-kills": "kills",
    "st-assists": "assists",
    "st-deaths": "deaths",
    "st-adr": "adr",
    "st-roundswing": "round_swing",
    "st-rating": "rating",
}

# 表 class 里的阵营标记 → 输出键
_MATCH_STAT_SIDES = {"totalstats": "both", "ctstats": "ct", "tstats": "t"}


def parse_match_stats_html(html: str, sides: list[str] | None = None) -> dict[str, Any]:
    """解析比赛详细统计页（地图已选好的状态下）。

    页面结构要点（实测）：
      · 每支队伍在每个阵营下都有一张 `table.stats-table`，
        三套并存：`.totalstats`（合计）/ `.ctstats`（CT 方）/ `.tstats`（T 方），
        只有当前选中的那套不带 `hidden` 类。
      · 因此**阵营无需点击**，一次取回三套；**地图仍需点击**（点击后表格会被重新填充）。
      · 列名在 `th.st-*`，值在 `td.st-*`，按类名对应。
      · 每列还分 traditional / eco-adjusted 两套（后者带 `eco-adjusted-data` 类），
        这里取 traditional，跳过 eco 版本。
    """
    soup = BeautifulSoup(html, "lxml")
    wanted = set(sides or ["both", "ct", "t"])

    result: dict[str, list[dict[str, Any]]] = {}

    for table in soup.select("table.stats-table"):
        classes = [c.lower() for c in (table.get("class") or [])]
        side = next((_MATCH_STAT_SIDES[c] for c in classes if c in _MATCH_STAT_SIDES), None)
        if side is None or side not in wanted:
            continue

        team_th = table.select_one("th.st-teamname")
        logo = team_th.select_one("img.logo") if team_th else None
        team_name = (
            (logo.get("alt") or logo.get("title")) if logo else _clean_text(team_th)
        )

        # 列名：th.st-* 的文本，按类名索引
        columns: dict[str, str] = {}
        for th in table.select("th"):
            for cls in th.get("class") or []:
                key = _MATCH_STAT_FIELDS.get(cls.lower())
                if key:
                    columns[key] = _clean_text(th)

        players: list[dict[str, Any]] = []
        for row in table.select("tbody tr"):
            nick = row.select_one("td.st-player")
            if nick is None:
                continue
            record: dict[str, Any] = {"nickname": _clean_text(nick)}
            for td in row.find_all("td"):
                cell_classes = [c.lower() for c in (td.get("class") or [])]
                if "eco-adjusted-data" in cell_classes:
                    continue  # 经济调整版，跳过
                for cls in cell_classes:
                    key = _MATCH_STAT_FIELDS.get(cls)
                    if key and key not in record:
                        record[key] = _clean_text(td)
            players.append(record)

        if players:
            entry = {"team": team_name, "columns": columns, "players": players}
            result.setdefault(side, []).append(entry)

    return {
        "sides": {k: v for k, v in result.items()},
        "side_count": {k: len(v) for k, v in result.items()},
    }


# --------------------------- 排行（选手） ---------------------------

def parse_player_ranking(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """解析选手排行榜页面。"""
    rows: list[dict[str, Any]] = []

    for node in soup.select(".ratingCol, .player-ranking-row, tr"):
        name = _clean_text(node.select_one(".playerCol a, .ranked-player a, .player-nick"))
        if not name:
            continue
        rows.append(
            {
                "player": name,
                "player_id": _id_from_href(
                    (node.select_one("a").get("href") if node.select_one("a") else None)
                ),
                "rating": _clean_text(node.select_one(".ratingCol, .rating")),
                "maps": _clean_text(node.select_one(".mapsCol, .maps")),
            }
        )

    return rows
