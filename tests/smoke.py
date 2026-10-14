#!/usr/bin/env python3
"""真实网络冒烟测试。

逐个调用所有工具，断言返回结构可用。会真的访问 hltv.org，注意请求间隔
（默认 3 秒 + 抖动），一次完整跑完约 1 分钟。

    python tests/smoke.py
    python tests/smoke.py --only ranking player

退出码 0 表示全部通过。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hltv_mcp import server as S  # noqa: E402


CASES: list[tuple[str, str, dict]] = [
    ("search", "hltv_search", {"query": "Vitality", "kind": "team"}),
    ("matches", "hltv_get_matches", {"limit": 5}),
    ("live", "hltv_get_matches", {"live_only": True, "limit": 5}),
    ("results", "hltv_get_results", {"limit": 5}),
    ("ranking", "hltv_get_team_ranking", {"limit": 10}),
    ("team", "hltv_get_team", {"name": "Vitality"}),
    ("player", "hltv_get_player", {"name": "ZywOo"}),
    ("career", "hltv_get_player_career", {"name": "ropz", "include_achievements": False}),
    ("yearstats", "hltv_get_player_year_stats",
     {"player_id": 11816, "years": [2024, 2019], "include_career_total": False}),
    ("event", "hltv_get_event", {"event_id": 8932}),
    ("teammatch", "hltv_get_team_matches", {"name": "FaZe", "limit": 5}),
    ("h2h", "hltv_get_head_to_head", {"team1": "FaZe", "team2": "Vitality", "limit": 5}),
    ("matchstats", "hltv_get_match_stats", {"match_id": 2399253, "map": "Inferno", "side": "ct"}),
    ("backend", "hltv_backend_status", {}),
    ("news", "hltv_get_news", {"limit": 5}),
    ("events", "hltv_get_events", {"limit": 5}),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="HLTV MCP 冒烟测试")
    ap.add_argument("--only", nargs="*", help="只跑指定用例")
    args = ap.parse_args()

    cases = [c for c in CASES if not args.only or c[0] in args.only]
    passed = failed = 0

    for label, tool_name, kwargs in cases:
        tool = getattr(S, tool_name)
        started = time.time()
        try:
            payload = json.loads(tool(**kwargs))
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {label:9s} 调用抛异常 {type(exc).__name__}: {exc}")
            failed += 1
            continue

        if "error" in payload:
            print(f"✗ {label:9s} {str(payload['error'])[:120]}")
            failed += 1
            continue

        # 至少要有内容，不能是空壳
        interesting = [
            k for k in ("matches", "results", "ranking", "news", "events", "results")
            if k in payload
        ]
        if interesting:
            count = payload.get("count", len(payload.get(interesting[0], [])))
            ok = count > 0
        elif "results" in payload and isinstance(payload["results"], list):
            ok = len(payload["results"]) > 0
        elif "summary" in payload and "by_map" in payload:
            ok = payload["summary"].get("maps_played", 0) > 0
        elif "sides" in payload and "results" in payload:
            ok = any(r.get("sides") for r in payload["results"])
        elif "backend_in_use" in payload:
            ok = payload.get("backend_in_use") in ("browser", "http")
        elif "seasons" in payload:
            # 逐年统计：至少有一年拿到了 Rating 才算通过
            ok = any(season.get("rating") for season in payload["seasons"])
        else:
            # 详情类工具：至少要有关键字段
            ok = any(
                payload.get(field)
                for field in ("name", "nickname", "title", "count", "results")
            )

        mark = "✓" if ok else "✗"
        detail = ""
        if interesting:
            detail = f"{payload.get('count', '?')} 项"
        elif payload.get("nickname"):
            # hltv_get_player 用 rating；hltv_get_player_career 用 career_rating
            score = payload.get("career_rating") or payload.get("rating")
            top20 = payload.get("top20_by_year")
            detail = (
                f"{payload['nickname']} / rating={score}"
                + (f" / Top20 {len(top20)} 年" if top20 else "")
            )
        elif payload.get("name"):
            detail = payload["name"]
        elif payload.get("sides"):
            total = sum(len(v) for v in payload["sides"].values())
            detail = f"{payload.get('map')} / {payload.get('side')} -> {total} 队"
        elif payload.get("placements") is not None:
            detail = f"{payload.get('name')} / 奖池 {payload.get('prize_pool')} / {payload.get('teams_count')} 队"
        elif payload.get("record"):
            detail = f"{payload['record']['wins']}胜{payload['record']['losses']}负"
        elif payload.get("by_map"):
            detail = (f"{payload['summary']['maps_played']} 图 "
                      f"{payload['summary']['maps_won']}胜{payload['summary']['maps_lost']}负")
        elif "backend_in_use" in payload:
            detail = f"{payload.get('backend_in_use')} / 浏览器={payload.get('browser_version') or '未连接'}"
        elif payload.get("seasons"):
            rated = [x for x in payload["seasons"] if x.get("rating")]
            detail = ", ".join(f"{x['year']}:{x['rating']}" for x in rated[:3])
        elif payload.get("title"):
            detail = str(payload["title"])[:40]

        print(f"{mark} {label:9s} {detail}  ({time.time() - started:.1f}s)")
        passed += ok
        failed += (not ok)

    print(f"\n{passed} 通过 / {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
