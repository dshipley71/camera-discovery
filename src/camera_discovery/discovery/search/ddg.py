from __future__ import annotations

from typing import Any

from camera_discovery.extraction.search import parse_ddg_result_rows


def parse_ddg_results(html: str, *, query: str = "", max_results: int = 50) -> list[dict[str, Any]]:
    """Parse DuckDuckGo HTML results into normalized search rows."""
    rows = parse_ddg_result_rows(query, html, max_results=max_results, include_source_kind=True)
    for row in rows:
        row["search_engine"] = "ddg"
        row["source_provider"] = "blind:ddg"
        row["source_name"] = "DuckDuckGo"
    return rows
