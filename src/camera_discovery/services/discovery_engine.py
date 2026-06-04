from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Callable
from urllib.parse import quote_plus, urlencode, urljoin, urlparse

import httpx

from camera_discovery.core.models import CameraCandidate, CandidateSet, DiscoveryMode, RunConfig, TargetContext
from camera_discovery.llm.base import ChatMessage, LLMClient
from camera_discovery.llm.factory import build_candidate_review_client, build_location_inference_client
from camera_discovery.sources import load_source_policy
from camera_discovery.utils.io import write_json, write_jsonl
from camera_discovery.utils.json_utils import extract_json_object
from camera_discovery.discovery.source_rows import (
    DirectorySourceProvider,
    DirectUrlSourceProvider,
)
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
    MAX_WORKERS,
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


from camera_discovery.discovery.artifact_writer import ArtifactWriterMixin
from camera_discovery.discovery.browser_capture import BrowserCaptureMixin
from camera_discovery.discovery.candidate_extraction import CandidateExtractionMixin
from camera_discovery.discovery.candidate_processing import CandidateProcessingMixin
from camera_discovery.discovery.search_dispatch import SearchDispatchMixin

# Compatibility imports/re-exports are intentionally preserved for existing tests
# and external code that imported helper symbols from this legacy module.

class CandidateDiscoveryEngine(
    BrowserCaptureMixin,
    SearchDispatchMixin,
    CandidateExtractionMixin,
    CandidateProcessingMixin,
    ArtifactWriterMixin,
):
    """Discover candidates while keeping source allow-lists and block rules deterministic.

    Blind search, directory sources, and direct URLs are discovery inputs inside this
    service. Global block rules from SOURCES.md apply to every mode, including blind
    search, directory mode, and direct seed URLs.
    """

    def __init__(
        self,
        config: RunConfig,
        semantic_review_client: LLMClient | None = None,
        location_inference_client: LLMClient | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.config = config
        self.semantic_review_client = semantic_review_client
        self.location_inference_client = location_inference_client
        self.progress_callback = progress_callback
        self.logs_dir = config.output_dir / "logs"
        self.candidates_dir = config.output_dir / "candidates"
        self.source_policy = load_source_policy(config.sources_file, config.block_patterns)
        self.directory_provider = DirectorySourceProvider(self.source_policy)
        self.direct_provider = DirectUrlSourceProvider(config.seed_urls, self.source_policy)
        self._browser_capture_lock = threading.RLock()
        self._browser_capture_counts = {"total": 0, "blind": 0, "directory": 0, "direct": 0, "asset_host_promotion": 0}
        self._browser_capture_host_counts: dict[str, int] = {}
        self._browser_capture_host_failures: dict[str, int] = {}
        self._browser_capture_summary: dict[str, Any] = {
            "enabled": self.config.enable_browser_capture,
            "backend": self.config.browser_backend,
            "browser_backend": self.config.browser_backend,
            "rows_considered": 0,
            "rows_selected": 0,
            "rows_skipped": 0,
            "pages_attempted": 0,
            "candidates": 0,
            "hls_candidates": 0,
            "image_snapshot_candidates": 0,
            "errors": 0,
            "timeouts": 0,
            "by_source_provider": {},
            "preflight_ok": None,
            "disabled_reason": "",
            "install_hint": "",
        }

    def _emit_progress(self, event: str, **payload: Any) -> None:
        if self.progress_callback is None:
            return
        safe_payload = dict(payload)
        target = safe_payload.pop("target", None)
        if target is not None:
            safe_payload.setdefault("target_id", getattr(target, "target_id", None))
            safe_payload.setdefault("target_label", getattr(target, "target_label", None) or getattr(target, "canonical_target", None))
        try:
            self.progress_callback(event, safe_payload)
        except Exception:
            # Progress reporting must never affect discovery results.
            return

    def discover(self, target: TargetContext) -> CandidateSet:
        self._run_browser_preflight()
        queries = self._search_queries(target) if self.config.discovery_mode in {DiscoveryMode.BLIND, DiscoveryMode.BOTH} else []
        self._emit_progress("search_queries_ready", target=target, queries=len(queries))
        client = self._make_client()
        results: list[dict[str, str]] = []
        raw: list[CameraCandidate] = []
        try:
            self._emit_progress("source_rows_loading", target=target)
            results = self._source_rows(target, queries, client)
            selected_rows = self._select_rows(results)
            primary_rows = selected_rows[: self.config.max_total_candidates]
            self._emit_progress(
                "source_rows_selected",
                target=target,
                discovered_rows=len(results),
                selected_rows=len(selected_rows),
                primary_rows=len(primary_rows),
            )
            raw = self._collect_candidates_from_rows(primary_rows, client, target=target, phase="primary")

            if not self._candidate_budgets_full(raw):
                remaining_rows = max(0, self.config.max_total_candidates - len(primary_rows))
                promoted_rows = self._promoted_asset_host_rows(raw, target, selected_rows)
                if promoted_rows and remaining_rows > 0:
                    raw.extend(
                        self._collect_candidates_from_rows(
                            promoted_rows[:remaining_rows],
                            client,
                            existing=raw,
                            target=target,
                            phase="promoted_asset_hosts",
                        )
                    )
        finally:
            client.close()

        self._emit_progress("candidate_metadata_started", target=target, raw=len(raw))
        raw = self._apply_candidate_metadata(raw, target)
        unique = self._dedupe(raw)
        unique = self._apply_candidate_metadata(unique, target)
        self._emit_progress(
            "coordinate_enrichment_started",
            target=target,
            unique=len(unique),
            already_coordinate_bearing=sum(1 for c in unique if c.has_coordinates),
        )
        self._enrich_candidate_coordinates(unique, target)
        self._emit_progress("scope_review_started", target=target, unique=len(unique))
        self._scope_candidates(unique, target)
        self._apply_llm_candidate_review(unique, target)
        cs = self._build_candidate_set(raw, unique)
        dork_summary = getattr(self, "_google_dorking_summary", None)
        if isinstance(dork_summary, dict) and dork_summary.get("enabled"):
            dork_summary["candidates_extracted"] = sum(1 for c in cs.raw if (c.source_metadata or {}).get("query") and "site:" in str((c.source_metadata or {}).get("query")).casefold())
            write_json(self.logs_dir / "google_dorking_summary.json", dork_summary)
        self._write_artifacts(queries, results, cs, target)
        self._emit_progress(
            "discovery_complete",
            target=target,
            raw=len(cs.raw),
            unique=len(cs.unique),
            coordinate_bearing=len(cs.coordinate_bearing),
            in_scope=len(cs.in_scope),
        )
        return cs



    def _make_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.config.http_timeout,
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )

    def _collect_candidates_from_rows(
        self,
        rows: list[dict[str, str]],
        client: httpx.Client,
        *,
        existing: list[CameraCandidate] | None = None,
        target: TargetContext | None = None,
        phase: str = "primary",
    ) -> list[CameraCandidate]:
        raw: list[CameraCandidate] = []
        hls_count = sum(1 for c in (existing or []) if _candidate_media_type(c) == "hls")
        snap_count = sum(1 for c in (existing or []) if _candidate_media_type(c) != "hls")
        total_count = len(existing or [])
        processed_rows = 0
        self._emit_progress(
            "source_row_batch_started",
            target=target,
            phase=phase,
            rows=len(rows),
            hls_count=hls_count,
            image_snapshot_count=snap_count,
            accepted_total=total_count,
        )

        def budgets_full() -> bool:
            return (
                (hls_count >= self.config.max_hls_candidates and snap_count >= self.config.max_image_snapshot_candidates)
                or total_count >= self.config.max_total_candidates
            )

        def extract_row(row: dict[str, str]) -> list[CameraCandidate]:
            try:
                return self._extract_from_source_row(row, client, phase=phase)
            except TypeError as exc:
                # Keep tests and third-party callers that monkeypatch the older
                # two-argument private helper working while the built-in
                # implementation receives phase-aware browser-capture context.
                if "phase" in str(exc):
                    return self._extract_from_source_row(row, client)
                raise

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(extract_row, row): row for row in rows}
            for future in concurrent.futures.as_completed(futures):
                try:
                    candidates = future.result()
                except Exception:
                    candidates = []
                processed_rows += 1
                accepted_from_row = 0
                if not budgets_full():
                    for c in candidates:
                        media_type = _candidate_media_type(c)
                        if media_type == "hls":
                            if hls_count >= self.config.max_hls_candidates:
                                continue
                            c.source_metadata.setdefault("media_type", "hls")
                            hls_count += 1
                        else:
                            if snap_count >= self.config.max_image_snapshot_candidates:
                                continue
                            c.source_metadata.setdefault("media_type", media_type or "image_snapshot")
                            snap_count += 1
                        raw.append(c)
                        accepted_from_row += 1
                        total_count += 1
                        if total_count >= self.config.max_total_candidates:
                            break
                self._emit_progress(
                    "source_row_processed",
                    target=target,
                    phase=phase,
                    processed_rows=processed_rows,
                    rows=len(rows),
                    candidates_found=len(candidates),
                    accepted_from_row=accepted_from_row,
                    accepted_total=total_count,
                    hls_count=hls_count,
                    image_snapshot_count=snap_count,
                    budgets_full=budgets_full(),
                )
        self._emit_progress(
            "source_row_batch_complete",
            target=target,
            phase=phase,
            processed_rows=processed_rows,
            rows=len(rows),
            accepted_total=total_count,
            hls_count=hls_count,
            image_snapshot_count=snap_count,
        )
        return raw
