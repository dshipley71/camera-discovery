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
    selected_blind_rows = sum(1 for row in selected if _provider_group(row.get("source_provider")) == "blind")
    selected_directory_rows = sum(1 for row in selected if _provider_group(row.get("source_provider")) == "directory")
    selected_direct_rows = sum(1 for row in selected if _provider_group(row.get("source_provider")) == "direct")
    selected_by_provider_group = {
        "blind": selected_blind_rows,
        "directory": selected_directory_rows,
        "direct": selected_direct_rows,
    }
    search_service_summary = build_search_service_summary(blind_diagnostics, selected, blocked_rows)
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
        "selected_by_provider_group": selected_by_provider_group,
        "selected_by_kind": count_rows_by_key(selected, "source_kind"),
        "selected_directory_rows": selected_directory_rows,
        "selected_blind_rows": selected_blind_rows,
        "selected_direct_rows": selected_direct_rows,
        "blocked_source_rows": len(blocked_rows),
        "blocked_source_rows_by_provider": count_rows_by_key(blocked_rows, "source_provider"),
        "blind_search_queries": _unique_blind_query_texts(blind_diagnostics),
        "blind_search_query_count": sum(1 for item in blind_diagnostics if item.get("query_key") and item.get("status") != "duplicate_suppressed"),
        "blind_search_query_attempts": _blind_query_attempts(blind_diagnostics),
        "blind_search_parsed_rows": sum(int(item.get("parsed_rows") or 0) for item in blind_diagnostics if item.get("query_key")),
        "blind_search_errors": sum(int(item.get("error_count") or (1 if item.get("error") else 0)) for item in blind_diagnostics if item.get("query_key")),
        "blind_search_results_by_query": _blind_results_by_query(blind_diagnostics),
        "search_service_summary": search_service_summary,
        "duplicate_source_rows": max(0, len(selected_before_budget) + len(blocked_rows) - len({str(row.get("url") or "").split("#", 1)[0] for row in [*directory_rows, *blind_rows, *direct_rows] if row.get("url")})),
        "media_filter_rejected_rows": 0,
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
    data.setdefault("source_policy_checked", True)
    if not data.get("blocked_reason"):
        data.pop("blocked_reason", None)
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


def _provider_group(value: Any) -> str:
    text = str(value or "unknown").casefold()
    if text == "directory" or text.startswith("directory:"):
        return "directory"
    if text == "direct" or text.startswith("direct:"):
        return "direct"
    if text == "blind" or text.startswith("blind:"):
        return "blind"
    return text


def _row_matches_service(row: dict[str, Any], service: str) -> bool:
    engine = str(row.get("search_engine") or "").casefold()
    if engine == service:
        return True
    engines = row.get("search_engines")
    return isinstance(engines, list) and service in {str(item).casefold() for item in engines}


def _empty_query_type_counts() -> dict[str, dict[str, int]]:
    return {
        "normal": {"queries_attempted": 0, "results_seen": 0, "parsed_rows": 0, "selected_rows": 0, "blocked_rows": 0, "duplicate_rows": 0, "error_count": 0},
        "dork": {"queries_attempted": 0, "results_seen": 0, "parsed_rows": 0, "selected_rows": 0, "blocked_rows": 0, "duplicate_rows": 0, "error_count": 0},
    }


def _search_engine_entry(engine: str) -> dict[str, Any]:
    configured = engine in {"ddg", "bing"}
    default_skip_reason = ""
    if not configured:
        default_skip_reason = {
            "searxng": "searxng_base_url_not_configured",
            "github": "github_token_not_configured",
            "google": "google_backend_not_configured",
        }.get(engine, "backend_not_configured")
    return {
        "configured": configured,
        "attempted": False,
        "status": "skipped" if configured else "not_configured",
        "queries_attempted": 0,
        "normal_queries_attempted": 0,
        "dork_queries_attempted": 0,
        "results_seen": 0,
        "parsed_rows": 0,
        "selected_rows": 0,
        "blocked_rows": 0,
        "duplicate_rows": 0,
        "duplicate_query_attempts_suppressed": 0,
        "error_count": 0,
        "skip_reason": default_skip_reason,
        "diagnostics_path": "logs/search_engine_diagnostics.jsonl",
        "by_query_type": _empty_query_type_counts(),
    }


def build_search_service_summary(
    diagnostics: list[dict[str, Any]] | None,
    selected_rows: list[dict[str, Any]],
    blocked_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    diagnostics = diagnostics or []
    services = {engine: _search_engine_entry(engine) for engine in ("ddg", "bing", "searxng", "github", "google")}
    query_attempts = [diag for diag in diagnostics if diag.get("query_key")]
    for diag in query_attempts:
        engine = str(diag.get("engine") or "").casefold()
        if engine not in services:
            continue
        query_type = str(diag.get("query_type") or "normal").casefold()
        if query_type not in {"normal", "dork"}:
            query_type = "normal"
        entry = services[engine]
        entry["configured"] = bool(diag.get("configured", entry["configured"]))
        qtype_entry = entry["by_query_type"][query_type]
        if diag.get("status") == "duplicate_suppressed":
            entry["duplicate_query_attempts_suppressed"] += 1
            entry["duplicate_rows"] += 1
            qtype_entry["duplicate_rows"] += 1
            continue
        if not diag.get("attempted"):
            entry["status"] = str(diag.get("status") or "skipped")
            entry["skip_reason"] = str(diag.get("skip_reason") or diag.get("reason") or "skipped")
            continue
        entry["attempted"] = True
        entry["status"] = "error" if diag.get("error") or int(diag.get("error_count") or 0) else "ran"
        entry["queries_attempted"] += 1
        if query_type == "dork":
            entry["dork_queries_attempted"] += 1
        else:
            entry["normal_queries_attempted"] += 1
        qtype_entry["queries_attempted"] += 1
        for key in ("results_seen", "parsed_rows", "selected_rows", "blocked_rows", "duplicate_rows", "error_count"):
            value = int(diag.get(key) or 0)
            entry[key] += value
            qtype_entry[key] += value
        if diag.get("error") or int(diag.get("error_count") or 0):
            entry["skip_reason"] = str(diag.get("skip_reason") or diag.get("error") or "error")[:300]
    for service, entry in services.items():
        entry["selected_rows"] = max(int(entry["selected_rows"]), sum(1 for row in selected_rows if _row_matches_service(row, service)))
        entry["blocked_rows"] = max(int(entry["blocked_rows"]), sum(1 for row in blocked_rows if _row_matches_service(row, service)))
        if service == "searxng" and not entry["attempted"] and not entry["configured"]:
            entry["status"] = "not_configured"
            entry["skip_reason"] = "searxng_base_url_not_configured"
        if service == "github" and not entry["attempted"] and not entry["configured"]:
            entry["status"] = "not_configured"
            entry["skip_reason"] = "github_token_not_configured"
        if service == "google":
            entry["configured"] = False
            entry["attempted"] = False
            entry["status"] = "unsupported_backend"
            entry["skip_reason"] = "google_backend_not_configured"
        elif not entry["attempted"] and entry["configured"] and not entry["skip_reason"]:
            entry["skip_reason"] = "no_queries_for_service"
    global_summary = _search_global_summary(query_attempts, services)
    return {**services, "global": global_summary}


def _search_global_summary(query_attempts: list[dict[str, Any]], services: dict[str, dict[str, Any]]) -> dict[str, Any]:
    duplicate_suppressed = sum(1 for diag in query_attempts if diag.get("status") == "duplicate_suppressed")
    unique_attempts = [diag for diag in query_attempts if diag.get("status") != "duplicate_suppressed"]
    attempted = [diag for diag in unique_attempts if diag.get("attempted")]
    return {
        "total_query_attempts": len(query_attempts),
        "unique_query_attempts": len(unique_attempts),
        "duplicate_query_attempts_suppressed": duplicate_suppressed,
        "unique_query_texts": len({str(diag.get("normalized_query") or "") for diag in query_attempts if diag.get("normalized_query")}),
        "engines_attempted": sorted({str(diag.get("engine") or "") for diag in attempted if diag.get("engine")}),
        "engines_skipped": sorted(engine for engine, entry in services.items() if not entry.get("attempted")),
        "dork_queries_enabled": any(diag.get("query_type") == "dork" for diag in query_attempts),
        "dork_queries_attempted": sum(1 for diag in attempted if diag.get("query_type") == "dork"),
        "normal_queries_attempted": sum(1 for diag in attempted if diag.get("query_type") != "dork"),
    }


def _blind_query_attempts(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "engine",
        "query_type",
        "query",
        "normalized_query",
        "query_key",
        "configured",
        "attempted",
        "status",
        "results_seen",
        "parsed_rows",
        "selected_rows",
        "blocked_rows",
        "duplicate_rows",
        "error_count",
        "skip_reason",
        "diagnostics_path",
    )
    return [{field: diag.get(field) for field in fields if field in diag} for diag in diagnostics if diag.get("query_key")]


def _unique_blind_query_texts(diagnostics: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for diag in diagnostics:
        query = str(diag.get("query") or "")
        normalized = str(diag.get("normalized_query") or query.casefold())
        if not query or normalized in seen:
            continue
        seen.add(normalized)
        out.append(query)
    return out


def _blind_results_by_query(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    for diag in diagnostics:
        if not diag.get("query_key") or diag.get("status") == "duplicate_suppressed":
            continue
        engine = str(diag.get("engine") or "unknown")
        query_type = str(diag.get("query_type") or "normal")
        query = str(diag.get("query") or "")
        out.setdefault(engine, {}).setdefault(query_type, {})[query] = {
            "results_seen": int(diag.get("results_seen") or 0),
            "parsed_rows": int(diag.get("parsed_rows") or 0),
            "selected_rows": int(diag.get("selected_rows") or 0),
            "blocked_rows": int(diag.get("blocked_rows") or 0),
        }
    return out
