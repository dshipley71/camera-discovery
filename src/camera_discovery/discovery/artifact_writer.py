from __future__ import annotations

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


class ArtifactWriterMixin:
    """Discovery artifact and per-target summary writing helpers."""

    def _write_artifacts(self, queries: list[str], results: list[dict], cs: CandidateSet, target: TargetContext) -> None:
        target_logs = self.logs_dir / "targets" / target.target_id
        target_candidates = self.candidates_dir / target.target_id
        write_json(target_logs / "source_policy_summary.json", self.source_policy.to_dict())
        write_json(self.logs_dir / "source_policy_summary.json", self.source_policy.to_dict())
        write_json(target_logs / "search_queries.json", {"target_id": target.target_id, "queries": queries})
        write_jsonl(target_logs / "search_results.jsonl", results)
        write_jsonl(target_candidates / "agentic_candidates.jsonl", [asdict(candidate) for candidate in cs.raw])
        write_jsonl(target_candidates / "agentic_candidates_unique.jsonl", [asdict(candidate) for candidate in cs.unique])
        summary = {
            "target_id": target.target_id,
            "target_label": target.target_label,
            "discovery_mode": self.config.discovery_mode.value,
            "sources_file": str(self.config.sources_file) if self.config.sources_file else None,
            "allowed_directory_sources": len(self.source_policy.enabled_allowed_sources()),
            "blocked_patterns": len(self.source_policy.blocked_sources),
            "raw": len(cs.raw),
            "unique": len(cs.unique),
            "coordinate_bearing": len(cs.coordinate_bearing),
            "in_scope": len(cs.in_scope),
            "review": len(cs.review),
            "rejected": len(cs.rejected),
            "llm_semantic_reviewed": sum(1 for candidate in cs.unique if candidate.llm_semantic_decision),
            "browser_capture_enabled": self.config.enable_browser_capture,
            "browser_backend": self.config.browser_backend,
            "browser_rows_considered": self._browser_capture_summary.get("rows_considered", 0),
            "browser_rows_selected": self._browser_capture_summary.get("rows_selected", 0),
            "browser_pages_attempted": self._browser_capture_summary.get("pages_attempted", 0),
            "browser_candidates": self._browser_capture_summary.get("candidates", 0),
            "browser_hls_candidates": self._browser_capture_summary.get("hls_candidates", 0),
            "browser_image_snapshot_candidates": self._browser_capture_summary.get("image_snapshot_candidates", 0),
            "browser_errors": self._browser_capture_summary.get("errors", 0),
            "browser_timeouts": self._browser_capture_summary.get("timeouts", 0),
        }
        write_json(target_logs / "browser_capture_summary.json", self._browser_capture_summary)
        write_json(self.logs_dir / "browser_capture_summary.json", self._browser_capture_summary)
        self._emit_progress(
            "browser_capture_complete",
            target=target,
            rows_considered=self._browser_capture_summary.get("rows_considered", 0),
            rows_selected=self._browser_capture_summary.get("rows_selected", 0),
            pages_attempted=self._browser_capture_summary.get("pages_attempted", 0),
            candidates=self._browser_capture_summary.get("candidates", 0),
            errors=self._browser_capture_summary.get("errors", 0),
            browser_backend=self.config.browser_backend,
        )
        write_json(target_logs / "candidate_discovery_summary.json", summary)
        if target.target_index == 0:
            write_json(self.logs_dir / "search_queries.json", {"queries": queries})
            write_jsonl(self.logs_dir / "search_results.jsonl", results)
            write_jsonl(self.candidates_dir / "agentic_candidates.jsonl", [asdict(candidate) for candidate in cs.raw])
            write_jsonl(self.candidates_dir / "agentic_candidates_unique.jsonl", [asdict(candidate) for candidate in cs.unique])
            write_json(self.logs_dir / "candidate_discovery_summary.json", summary)
