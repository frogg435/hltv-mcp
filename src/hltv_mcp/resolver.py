"""名称 → ID 解析。

AI 提问时给的多半是「Vitality 的排名」「ZywOo 的数据」这种自然语言名称，
而不是 HLTV 的数字 ID。所有工具都接受 id 与 name 两种入参，这里负责把
名称换成 ID。

HLTV 没有公开的 JSON 搜索接口，站内 `/search?query=` 返回的是 HTML，
因此用 `parsers.parse_search` 抽链接，再按「完全匹配 > 前缀匹配 > 包含匹配」
排序取最优。
"""

from __future__ import annotations

from typing import Any

from .client import HltvClient, HltvError, get_client
from .parsers import parse_search

# 站内 URL 前缀 → 实体类型
_KINDS = ("player", "team", "event", "matches", "news", "stats")


def _score(candidate: str, query: str) -> int:
    c, q = candidate.strip().lower(), query.strip().lower()
    if c == q:
        return 3
    if c.startswith(q):
        return 2
    if q in c:
        return 1
    return 0


def search(
    query: str,
    *,
    kind: str | None = None,
    limit: int = 15,
    client: HltvClient | None = None,
) -> list[dict[str, Any]]:
    """搜索 HLTV，可按实体类型过滤。

    Args:
        query: 关键词，例如 "vitality" / "zywoo" / "ESL Pro League"
        kind: 过滤类型，可选 player / team / event；None 表示不过滤
        limit: 返回条数上限
    """
    client = client or get_client()
    if not query.strip():
        return []

    soup = client.fetch_soup(f"/search?query={query.strip().replace(' ', '+')}")
    results = parse_search(soup)

    # 补全类型与 ID：parse_search 的兜底分支已经给了 kind/id，主分支没有
    for item in results:
        url = item.get("url") or ""
        if "kind" not in item:
            for k in _KINDS:
                if f"/{k}/" in url:
                    item["kind"] = k
                    break
        if "id" not in item and url:
            tail = url.rstrip("/").split("/")
            for part in tail:
                if part.isdigit():
                    item["id"] = int(part)
                    break

    # 类型过滤
    if kind:
        wanted = kind if kind != "player" else "player"
        results = [r for r in results if r.get("kind") == wanted]

    # 相关性排序：名称匹配度优先，其次保持站内顺序
    results.sort(key=lambda r: -_score(r.get("text", ""), query))
    return results[:limit]


def resolve_id(
    query: str | None,
    *,
    kind: str,
    client: HltvClient | None = None,
) -> tuple[int | None, dict[str, Any] | None]:
    """把名称解析成 ID。

    Returns:
        (entity_id, 命中的条目)。解析不到时返回 (None, None)。
    """
    if not query:
        return None, None

    candidates = search(query, kind=kind, limit=10, client=client)
    for item in candidates:
        if item.get("id"):
            return int(item["id"]), item
    return None, None


def require_id(
    *,
    entity: str,
    entity_id: int | None,
    name: str | None,
    kind: str,
    client: HltvClient | None = None,
) -> int:
    """取 ID：优先用显式传入的 id，否则用名称解析；都拿不到就抛错。"""
    if entity_id:
        return int(entity_id)
    if name:
        resolved, hit = resolve_id(name, kind=kind, client=client)
        if resolved:
            return resolved
        raise HltvError(f"找不到匹配的{entity}：{name!r}。可以先用 hltv_search 查证名称。")
    raise HltvError(f"需要提供 {entity} 的 id 或名称。")
