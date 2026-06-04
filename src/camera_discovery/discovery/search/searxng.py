from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx


def searxng_enabled(base_url: str | None) -> bool:
    return bool(str(base_url or "").strip())


def parse_searxng_results(data: dict[str, Any], *, query: str = "", max_results: int = 50) -> list[dict[str, Any]]:
    """Parse a SearXNG JSON response into normalized search rows."""
    if not isinstance(data, dict) or max_results <= 0:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip().split("#", 1)[0]
        if not url or not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "query": query,
                "title": str(item.get("title") or url).strip(),
                "url": url,
                "snippet": str(item.get("content") or "").strip(),
                "source_provider": "blind:searxng",
                "source_name": "SearXNG",
                "source_kind": "search_result",
                "search_engine": "searxng",
                "searxng_engines": item.get("engines") or [],
            }
        )
        if len(rows) >= max_results:
            break
    return rows


def search_searxng(
    query: str,
    *,
    base_url: str,
    user_agent: str,
    http_timeout: float,
    categories: str = "general",
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Query a configured SearXNG instance. Empty base_url disables the engine."""
    if not searxng_enabled(base_url):
        return []
    endpoint = urljoin(base_url.rstrip("/") + "/", "search")
    with httpx.Client(timeout=http_timeout, headers={"User-Agent": user_agent}, follow_redirects=True) as client:
        response = client.get(endpoint, params={"q": query, "format": "json", "categories": categories})
        response.raise_for_status()
        data = response.json()
    return parse_searxng_results(data, query=query, max_results=max_results)
