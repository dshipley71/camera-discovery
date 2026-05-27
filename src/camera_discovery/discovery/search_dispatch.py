from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any
from urllib.parse import quote_plus, urlencode, urljoin, urlparse

import httpx

from camera_discovery.core.models import CameraCandidate, CandidateSet, DiscoveryMode, TargetContext
from camera_discovery.llm.factory import build_candidate_review_client, build_location_inference_client
from camera_discovery.utils.io import write_json, write_jsonl
from camera_discovery.utils.json_utils import extract_json_object
from camera_discovery.discovery.source_rows import (
    _camera_category_slugs,
    _dedupe_rows,
    _row_from_source_entry,
    _slugify,
    _target_aware_site_rows,
    _target_country_slugs,
    _target_region_slugs,
    _url_query_mapping,
)
from camera_discovery.enrichment.location import (
    _append_target_context_to_query,
    _candidate_has_location_inference_evidence,
    _candidate_location_enrichment_sort_key,
    _candidate_location_inference_evidence_text,
    _haversine_km,
    _is_broad_or_target_level_inference,
    _is_safe_geocode_query,
    _limited_scalar_metadata,
    _llm_location_evidence_supported,
    _normalize_location_inference_rows,
    _point_in_bbox,
    _specific_candidate_location_text,
    _valid_lat_lon,
)
from camera_discovery.extraction.browser import BrowserCaptureDecision, BrowserCaptureResult, PageDiscoverySignals, browser_backend_preflight
from camera_discovery.extraction.html import (
    _first_nonempty,
    _html_soup,
    _media_urls_from_html_tag,
    _metadata_from_html_tag,
    _nearby_text,
)
from camera_discovery.extraction.http import _get_with_retry
from camera_discovery.extraction.json_records import (
    CAMERA_TYPE_DISPLAY_CATEGORIES,
    IMAGE_KEYS,
    LAT_KEYS,
    LON_KEYS,
    THUMBNAIL_IMAGE_KEYS,
    TITLE_KEYS,
    URL_KEYS,
    _flatten_camera_record,
    _json_camera_record_metadata,
    _lat_lon_from_geojson_coordinates,
    _looks_like_json_response,
    _record_lat_lon,
    _record_location_text,
    _record_looks_like_camera_record,
    _record_media_urls,
    _record_title,
    _simple_metadata,
    _source_record_schema_hint,
    _stable_camera_id,
    _update_json_stats,
)
from camera_discovery.extraction.media import (
    COORD_RE,
    DYNAMIC_PAGE_HINT_RE,
    IMAGE_RE,
    JSON_FEED_HINT_RE,
    M3U8_RE,
    MAP_LAYER_API_RE,
    _candidate_media_type,
    _chunks,
    _dedupe_media_urls,
    _dedupe_strings,
    _float_or_none,
    _int_or_none,
    _looks_like_hls,
    _looks_like_image,
    _looks_like_non_camera_asset,
    _camera_id_from_url,
    _humanize_camera_slug_from_url,
)
from camera_discovery.extraction.pagination import (
    _asset_host_discovery_urls,
    _expand_structured_endpoint_urls,
    _looks_like_paginated_directory_url,
    _looks_like_pagination_url,
    _pagination_rows,
)
from camera_discovery.extraction.search import clean_ddg_result_url, parse_ddg_result_rows


class SearchDispatchMixin:
    """Search, directory, direct, pagination, and promoted-row dispatch helpers."""

    def _source_rows(self, target: TargetContext, queries: list[str], client: httpx.Client | None = None) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        if self.config.discovery_mode == DiscoveryMode.BOTH:
            self._emit_progress("source_discovery_parallel_started", target=target, providers=["directory", "blind"])
            directory_rows: list[dict[str, str]] = []
            blind_rows: list[dict[str, str]] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = {
                    pool.submit(self.directory_provider.rows_for_target, target): "directory",
                    # Use an independent HTTP client for blind search so row discovery
                    # is truly parallel without sharing one client across threads.
                    pool.submit(self._blind_search, queries, None): "blind",
                }
                for future in concurrent.futures.as_completed(futures):
                    provider = futures[future]
                    try:
                        provider_rows = future.result()
                    except Exception as exc:
                        provider_rows = [{"query": f"{provider}:{target.target_id}", "url": "", "title": "", "error": repr(exc), "source_provider": provider}]
                    if provider == "directory":
                        directory_rows = provider_rows
                    else:
                        blind_rows = provider_rows
            rows.extend(directory_rows)
            rows.extend(blind_rows)
            self._emit_progress(
                "source_discovery_parallel_complete",
                target=target,
                directory_rows=len(directory_rows),
                blind_rows=len(blind_rows),
            )
        else:
            if self.config.discovery_mode == DiscoveryMode.DIRECTORY:
                rows.extend(self.directory_provider.rows_for_target(target))
            if self.config.discovery_mode == DiscoveryMode.BLIND:
                rows.extend(self._blind_search(queries, client))
        if self.config.seed_urls and self.config.discovery_mode in {DiscoveryMode.DIRECT, DiscoveryMode.BOTH, DiscoveryMode.BLIND, DiscoveryMode.DIRECTORY}:
            rows.extend(self.direct_provider.rows_for_target(target))
        return rows

    def _search_queries(self, target: TargetContext) -> list[str]:
        base = target.canonical_target or target.user_query
        camera_intent = (target.intent.camera_type_intent or "public_live").replace("_", " ").casefold()
        candidates: list[str] = []

        if "traffic" in camera_intent:
            # Generic transportation-camera discovery expansions. These are not tied
            # to any source, state, or agency. They are intentionally ordered before
            # generic camera terms so they survive small max_search_queries values.
            candidates.extend(
                [
                    f"{base} traffic cameras",
                    f"{base} traffic camera map",
                    f"{base} department of transportation cameras",
                    f"{base} traffic camera API json",
                    f"{base} transportation cameras",
                    f"{base} road conditions cameras",
                    f"{base} CCTV traffic cameras",
                    f"{base} live traffic camera list",
                    f"{base} traffic camera MapServer FeatureServer",
                    f"{base} traffic camera m3u8",
                ]
            )
        elif "weather" in camera_intent:
            # Weather-camera searches get their own intent-specific terms. Do not
            # leak traffic/DOT vocabulary into weather runs.
            candidates.extend(
                [
                    f"{base} weather cameras",
                    f"{base} weather webcams",
                    f"{base} live weather camera",
                    f"{base} weather camera map",
                    f"{base} weather station webcam",
                    f"{base} airport weather camera",
                    f"{base} mountain weather camera",
                    f"{base} public weather webcam",
                    f"{base} weather camera feed json",
                    f"{base} weather webcam HLS",
                ]
            )
        else:
            candidates.extend(
                [
                    f"{base} public live cameras",
                    f"{base} live webcams",
                    f"{base} public camera map",
                    f"{base} public camera feed json",
                    f"{base} webcam HLS",
                    f"{base} camera snapshots",
                ]
            )

        # Generic structured-data discovery terms are safe for every camera type.
        candidates.extend(
            [
                f"{base} camera map layer feed",
                f"{base} public camera API json",
                f"{base} camera MapServer FeatureServer",
                f"{base} public live cameras m3u8",
            ]
        )
        return _dedupe_strings(candidates)[: self.config.max_search_queries]

    def _blind_search(self, queries: list[str], client: httpx.Client | None = None) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        owns_client = client is None
        client = client or self._make_client()
        try:
            for query in queries:
                try:
                    resp = _get_with_retry(client, f"https://duckduckgo.com/html/?q={quote_plus(query)}")
                    resp.raise_for_status()
                    rows.extend(self._parse_ddg(query, resp.text))
                except Exception as exc:
                    rows.append({"query": query, "url": "", "title": "", "error": repr(exc), "source_provider": "blind"})
        finally:
            if owns_client:
                client.close()
        return rows

    def _parse_ddg(self, query: str, html: str) -> list[dict[str, str]]:
        return parse_ddg_result_rows(
            query,
            html,
            max_results=self.config.max_search_results_per_query,
            include_source_kind=False,
        )

    def _clean(self, href: str) -> str:
        return clean_ddg_result_url(href)

    def _select_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        selected: list[dict[str, str]] = []
        blocked_rows: list[dict[str, str]] = []
        for row in rows:
            url = row.get("url") or ""
            key = url.split("#", 1)[0]
            if not url.startswith("http") or key in seen:
                continue
            reason = self.source_policy.block_reason(url)
            if reason:
                blocked = dict(row)
                blocked["blocked_reason"] = reason
                blocked_rows.append(blocked)
                continue
            seen.add(key)
            selected.append({**row, "url": key})
            for page_row in _pagination_rows({**row, "url": key}, self.config.max_directory_pages if row.get("source_provider") in {"directory", "direct"} else 1):
                page_key = page_row["url"].split("#", 1)[0]
                if page_key not in seen and not self.source_policy.block_reason(page_key):
                    seen.add(page_key)
                    selected.append(page_row)
        write_jsonl(self.logs_dir / "blocked_source_rows.jsonl", blocked_rows)
        return selected

    def _promoted_asset_host_rows(self, candidates: list[CameraCandidate], target: TargetContext, existing_rows: list[dict[str, str]]) -> list[dict[str, str]]:
        host_counts: dict[str, int] = {}
        for candidate in candidates:
            host = urlparse(candidate.stream_url).netloc.casefold()
            if host:
                host_counts[host] = host_counts.get(host, 0) + 1
        existing_urls = {row.get("url", "").split("#", 1)[0] for row in existing_rows}
        rows: list[dict[str, str]] = []
        for host, count in sorted(host_counts.items(), key=lambda item: item[1], reverse=True):
            if count < self.config.asset_host_promotion_threshold:
                continue
            for seed in _asset_host_discovery_urls(host, target):
                if seed in existing_urls or self.source_policy.is_blocked(seed):
                    continue
                rows.append(
                    {
                        "query": f"promoted_asset_host:{target.target_id}",
                        "title": f"Promoted camera asset host {host}",
                        "url": seed,
                        "snippet": f"Host appeared in {count} candidate media URLs",
                        "source_provider": "asset_host_promotion",
                        "source_kind": "promoted_host",
                        "source_name": host,
                    }
                )
        if rows:
            write_jsonl(self.logs_dir / "promoted_asset_host_rows.jsonl", rows)
        return rows
