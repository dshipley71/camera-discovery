from __future__ import annotations

from typing import Any

from camera_discovery.core.models import DiscoveryMode, TargetContext
from camera_discovery.discovery.source_rows import DirectorySourceProvider, DirectUrlSourceProvider
from camera_discovery.extraction.pagination import _pagination_rows
from camera_discovery.harvest.media_filter import classify_media_url
from camera_discovery.harvest.records import row_from_source_entry
from camera_discovery.sources import SourcePolicy


def target_directory_rows(policy: SourcePolicy, target: TargetContext) -> list[dict[str, str]]:
    return DirectorySourceProvider(policy).rows_for_target(target)


def target_direct_rows(urls: list[str], policy: SourcePolicy, target: TargetContext) -> list[dict[str, str]]:
    return DirectUrlSourceProvider(urls, policy).rows_for_target(target)


def query_directory_rows(policy: SourcePolicy, query: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in policy.enabled_allowed_sources():
        if policy.is_blocked(entry.url):
            continue
        rows.append(row_from_source_entry(entry, query, provider="directory"))
    return rows


def query_direct_rows(urls: list[str], policy: SourcePolicy, query: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for url in urls:
        if policy.is_blocked(url):
            continue
        media_type = classify_media_url(url)
        rows.append(
            {
                "query": query,
                "title": url,
                "url": url,
                "source_provider": "direct",
                "source_kind": "direct_media" if media_type else "page",
                "source_name": url,
            }
        )
    return rows


def select_source_rows(
    rows: list[dict[str, str]],
    *,
    source_policy: SourcePolicy,
    max_pages_per_source: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Select neutral source rows and return blocked-row diagnostics."""
    selected: list[dict[str, str]] = []
    blocked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        url = (row.get("url") or "").split("#", 1)[0]
        if not url.startswith(("http://", "https://", "rtsp://", "rtsps://")):
            continue
        reason = source_policy.block_reason(url)
        if reason:
            blocked.append({**row, "blocked_reason": reason, "source_policy_checked": True})
            continue
        if url in seen:
            continue
        seen.add(url)
        base_row = {**row, "url": url, "original_query": row.get("query") or "", "source_policy_checked": "true"}
        selected.append(base_row)
        if url.startswith(("rtsp://", "rtsps://")):
            continue
        for page_row in _pagination_rows(base_row, max(1, max_pages_per_source)):
            page_url = (page_row.get("url") or "").split("#", 1)[0]
            if not page_url or page_url in seen:
                continue
            page_reason = source_policy.block_reason(page_url)
            if page_reason:
                blocked.append({**page_row, "blocked_reason": page_reason, "source_policy_checked": True})
                continue
            seen.add(page_url)
            selected.append({**page_row, "url": page_url, "source_policy_checked": "true"})
    return selected, blocked


def direct_rows_requested(mode: DiscoveryMode) -> bool:
    return mode in {DiscoveryMode.DIRECT, DiscoveryMode.BOTH, DiscoveryMode.BLIND, DiscoveryMode.DIRECTORY}
