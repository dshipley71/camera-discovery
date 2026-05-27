from __future__ import annotations

import csv
import json
from dataclasses import asdict
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from camera_discovery.core.models import DiscoveryMode, HarvestConfig, HarvestedUrlRecord
from camera_discovery.sources import SourcePolicy


def build_source_rows_summary(
    *,
    config: HarvestConfig,
    source_policy: SourcePolicy,
    directory_rows: list[dict[str, str]],
    blind_rows: list[dict[str, str]],
    direct_rows: list[dict[str, str]],
    selected_before_budget: list[dict[str, str]],
    selected: list[dict[str, str]],
    blocked_rows: list[dict[str, Any]],
    max_source_rows_applied: bool,
    blind_search_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize harvest source-row provenance for reporting/debugging.

    This is deliberately metadata-only: it reports whether SOURCES.md/directory,
    blind search, and direct seeds contributed rows, without changing extraction.
    """

    sources_file = str(source_policy.source_file) if source_policy.source_file else None
    sources_file_exists = bool(source_policy.source_file and source_policy.source_file.exists())
    directory_requested = config.discovery_mode in {DiscoveryMode.DIRECTORY, DiscoveryMode.BOTH}
    blind_requested = config.discovery_mode in {DiscoveryMode.BLIND, DiscoveryMode.BOTH}
    direct_requested = config.discovery_mode in {DiscoveryMode.DIRECT, DiscoveryMode.BOTH, DiscoveryMode.BLIND, DiscoveryMode.DIRECTORY}
    selected_by_provider = count_rows_by_key(selected, "source_provider")
    generated_by_provider = count_rows_by_key([*directory_rows, *blind_rows, *direct_rows], "source_provider")
    blind_diagnostics = blind_search_diagnostics or []
    summary = {
        "discovery_mode": config.discovery_mode.value,
        "sources_file": sources_file,
        "sources_file_exists": sources_file_exists,
        "sources_file_loaded": bool(sources_file_exists and source_policy.allowed_sources),
        "sources_file_used": bool(directory_requested and selected_by_provider.get("directory", 0) > 0),
        "directory_requested": directory_requested,
        "blind_requested": blind_requested,
        "direct_requested": direct_requested,
        "directory_sources_configured": len(source_policy.allowed_sources),
        "directory_sources_enabled": len(source_policy.enabled_allowed_sources()),
        "blocked_patterns_configured": len(source_policy.blocked_sources),
        "generated_rows": len(directory_rows) + len(blind_rows) + len(direct_rows),
        "generated_by_provider": generated_by_provider,
        "generated_by_kind": count_rows_by_key([*directory_rows, *blind_rows, *direct_rows], "source_kind"),
        "selected_rows_before_budget": len(selected_before_budget),
        "selected_rows": len(selected),
        "selected_by_provider": selected_by_provider,
        "selected_by_kind": count_rows_by_key(selected, "source_kind"),
        "selected_directory_rows": selected_by_provider.get("directory", 0),
        "selected_blind_rows": selected_by_provider.get("blind", 0),
        "selected_direct_rows": selected_by_provider.get("direct", 0),
        "blocked_source_rows": len(blocked_rows),
        "blocked_source_rows_by_provider": count_rows_by_key(blocked_rows, "source_provider"),
        "blind_search_queries": [item.get("query") for item in blind_diagnostics if item.get("query")],
        "blind_search_query_count": len(blind_diagnostics),
        "blind_search_parsed_rows": sum(int(item.get("parsed_rows") or 0) for item in blind_diagnostics),
        "blind_search_errors": sum(1 for item in blind_diagnostics if item.get("error")),
        "blind_search_results_by_query": {str(item.get("query") or ""): int(item.get("parsed_rows") or 0) for item in blind_diagnostics if item.get("query")},
        "max_source_rows": config.max_source_rows,
        "max_source_rows_applied": max_source_rows_applied,
    }
    return summary

def count_rows_by_key(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row.get(key) or "unknown") for row in rows)
    return dict(sorted(counts.items()))

def record_to_dict(record: HarvestedUrlRecord) -> dict[str, Any]:
    data = asdict(record)
    data.setdefault("media_url", data.get("url"))
    return data

def write_plain_urls(path: Path, records: list[HarvestedUrlRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(record.url + "\n" for record in records), encoding="utf-8")

def write_csv(path: Path, records: list[HarvestedUrlRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "url",
        "media_url",
        "media_type",
        "asset_id",
        "asset_role",
        "asset_field",
        "field_path",
        "camera_record_id",
        "camera_id",
        "title",
        "description",
        "location_text",
        "lat",
        "lon",
        "coordinate_source",
        "direction",
        "bearing",
        "heading",
        "orientation",
        "in_service",
        "status",
        "date",
        "time",
        "timestamp",
        "last_updated",
        "last_refresh",
        "image_description",
        "current_image_update_frequency",
        "reference_image_update_frequency",
        "source_url",
        "source_endpoint_url",
        "source_page_url",
        "source_provider",
        "source_name",
        "discovery_method",
        "json_record_path",
        "metadata",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for record in records:
            data = record_to_dict(record)
            data.setdefault("media_url", data.get("url"))
            if isinstance(data.get("metadata"), dict):
                data["metadata"] = json.dumps(data["metadata"], ensure_ascii=False, sort_keys=True)
            writer.writerow({field: data.get(field) for field in fields})
