from __future__ import annotations

from camera_discovery.harvest.media_filter import canonical_media_url

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
from camera_discovery.llm.base import ChatMessage, LLMClient
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
    _point_in_geojson_geometry,
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


class CandidateProcessingMixin:
    """Candidate metadata, dedupe, coordinate enrichment, scoping, and LLM review helpers."""

    def _candidate_budgets_full(self, candidates: list[CameraCandidate]) -> bool:
        hls_count = sum(1 for c in candidates if _candidate_media_type(c) == "hls")
        snap_count = sum(1 for c in candidates if _candidate_media_type(c) != "hls")
        return (
            len(candidates) >= self.config.max_total_candidates
            or (hls_count >= self.config.max_hls_candidates and snap_count >= self.config.max_image_snapshot_candidates)
        )

    def _apply_candidate_metadata(self, candidates: list[CameraCandidate], target: TargetContext) -> list[CameraCandidate]:
        for c in candidates:
            c.target_id = target.target_id
            c.target_index = target.target_index
            c.target_label = target.target_label or target.canonical_target
            c.source_metadata.setdefault("camera_type", target.intent.camera_type_intent or "camera")
            if _looks_like_hls(c.stream_url):
                c.source_metadata.setdefault("media_type", "hls")
            if "camera_id" not in c.source_metadata:
                camera_id = _camera_id_from_url(c.stream_url)
                if camera_id:
                    c.source_metadata["camera_id"] = camera_id
        return candidates

    def _build_candidate_set(self, raw: list[CameraCandidate], unique: list[CameraCandidate]) -> CandidateSet:
        return CandidateSet(
            raw=raw,
            unique=unique,
            coordinate_bearing=[c for c in unique if c.has_coordinates],
            in_scope=[c for c in unique if c.scope_status == "in_scope"],
            review=[c for c in unique if c.scope_status in {"review", "unknown", "in_scope"}],
            rejected=[c for c in unique if c.scope_status == "out_of_scope"],
        )

    def _dedupe(self, rows: list[CameraCandidate]) -> list[CameraCandidate]:
        by_key: dict[str, CameraCandidate] = {}
        order: list[str] = []
        for row in rows:
            row.stream_url = canonical_media_url(row.stream_url)
            key = row.stream_url.split("#", 1)[0]
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = row
                order.append(key)
                continue
            row_type = _candidate_media_type(row)
            existing_type = _candidate_media_type(existing)
            if row_type == "hls" and existing_type != "hls":
                by_key[key] = row
                continue
            row_has_json = bool((row.source_metadata or {}).get("json_metadata_extracted"))
            existing_has_json = bool((existing.source_metadata or {}).get("json_metadata_extracted"))
            if row.has_coordinates and (not existing.has_coordinates or (row_has_json and not existing_has_json)):
                # Prefer authoritative structured endpoint geometry over weaker URL/text-derived evidence.
                row.source_metadata.update({k: v for k, v in existing.source_metadata.items() if k not in row.source_metadata or row.source_metadata[k] in (None, "")})
                by_key[key] = row
                continue
            if row.title and (not existing.title or row_has_json and not existing_has_json):
                existing.title = row.title
            if row.location_text and (not existing.location_text or row_has_json and not existing_has_json):
                existing.location_text = row.location_text
            preferred = {k: v for k, v in row.source_metadata.items() if k not in existing.source_metadata or existing.source_metadata[k] in (None, "")}
            if row_has_json:
                for k, v in row.source_metadata.items():
                    if k in {"camera_id", "camera_name", "camera_type", "raw_camera_type", "location_display", "camera_refresh_rate", "refresh_rate_seconds", "map_refresh_rate_seconds", "image_snapshot_refresh_delay_seconds", "json_metadata_extracted", "json_endpoint_url", "json_record_path", "json_record_schema_hint"}:
                        preferred[k] = v
            existing.source_metadata.update(preferred)
        return [by_key[key] for key in order]

    def _enrich_candidate_coordinates(self, candidates: list[CameraCandidate], target: TargetContext) -> None:
        """Populate real candidate coordinates from source evidence or geocoding.

        The enrichment step never invents coordinates. It uses the following
        precedence:
        1. structured/source lat/lon already attached to the candidate,
        2. coordinates in candidate metadata or URL query parameters,
        3. Nominatim geocoding of explicit title/location metadata,
        4. LLM-inferred place-name variants from candidate evidence, followed by
           Nominatim and target-scope validation.

        The LLM fallback is only allowed to return place names, road/intersection
        names, agency hints, camera IDs, evidence tokens, and query variants. It
        never supplies lat/lon. Accepted fallback coordinates always come from
        Nominatim and remain review-only unless downstream trust rules validate
        them.
        """
        metadata_enriched = 0
        geocode_attempted = 0
        geocode_enriched = 0
        geocode_skipped = 0
        llm_location_attempted = 0
        llm_location_enriched = 0
        llm_location_skipped = 0
        diagnostics: list[dict[str, Any]] = []
        geocode_cache: dict[str, tuple[float, float, str] | None] = {}
        effective_max_geocodes = self._effective_candidate_geocode_limit(candidates, target)
        max_llm_location_inferences = max(0, int(getattr(self.config, "max_llm_location_inferences", 0)))
        min_llm_confidence = max(0.0, min(1.0, float(getattr(self.config, "llm_location_inference_min_confidence", 0.70))))
        location_client: LLMClient | None = self.location_inference_client
        location_client_failed = False

        total_candidates = len(candidates)
        ordered_candidates = sorted(candidates, key=lambda c: _candidate_location_enrichment_sort_key(c))
        for processed_index, candidate in enumerate(ordered_candidates, start=1):
            try:
                if not candidate.has_coordinates:
                    lat_lon = self._candidate_lat_lon_from_existing_evidence(candidate)
                    if lat_lon:
                        candidate.lat, candidate.lon = lat_lon
                        candidate.coordinate_source = candidate.coordinate_source or "candidate_metadata"
                        candidate.reasons.append("coordinates_extracted_from_candidate_metadata")
                        metadata_enriched += 1

                if candidate.has_coordinates:
                    if (
                        candidate.coordinate_source == "proximity_text"
                        and getattr(self.config, "enable_llm_location_inference", False)
                        and _candidate_has_location_inference_evidence(candidate)
                        and llm_location_attempted < max_llm_location_inferences
                        and not location_client_failed
                    ):
                        if location_client is None:
                            try:
                                location_client = build_location_inference_client(self.config)
                            except Exception as exc:
                                location_client_failed = True
                                llm_location_skipped += 1
                                diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_conflict_check", "status": "client_unavailable", "error": repr(exc)})
                                continue
                        llm_location_attempted += 1
                        inference = self._infer_candidate_location_names(candidate, target, location_client)
                        if inference.get("status") == "ok":
                            for row in inference.get("location_candidates", []):
                                confidence = _float_or_none(row.get("confidence")) or 0.0
                                if confidence < min_llm_confidence or not _llm_location_evidence_supported(candidate, row):
                                    continue
                                for inferred_query in self._llm_location_queries(row, target):
                                    if inferred_query not in geocode_cache:
                                        geocode_cache[inferred_query] = self._geocode_candidate_location(inferred_query)
                                    result = geocode_cache[inferred_query]
                                    if result is None:
                                        continue
                                    lat, lon, display_name = result
                                    if _is_broad_or_target_level_inference(row, inferred_query, display_name, target):
                                        diagnostics.append({"stream_url": candidate.stream_url, "query": inferred_query, "stage": "llm_location_conflict_check", "status": "rejected_broad_or_target_level_inference", "display_name": display_name, "candidate": row})
                                        continue
                                    scope_ok, scope_reason = self._geocode_result_passes_target_scope(lat, lon, display_name, target)
                                    if not scope_ok:
                                        continue
                                    distance_km = _haversine_km(candidate.lat, candidate.lon, lat, lon)
                                    if distance_km is not None and distance_km >= 25.0:
                                        candidate.source_metadata["coordinate_conflict"] = {
                                            "existing_coordinate_source": candidate.coordinate_source,
                                            "existing_lat": candidate.lat,
                                            "existing_lon": candidate.lon,
                                            "inferred_query": inferred_query,
                                            "inferred_display_name": display_name,
                                            "inferred_lat": lat,
                                            "inferred_lon": lon,
                                            "distance_km": round(distance_km, 3),
                                        }
                                        candidate.reasons.append("coordinate_conflict_between_proximity_text_and_llm_geocode")
                                        diagnostics.append({"stream_url": candidate.stream_url, "query": inferred_query, "stage": "llm_location_conflict_check", "status": "coordinate_conflict", "display_name": display_name, "distance_km": distance_km})
                                    break
                                if "coordinate_conflict" in candidate.source_metadata:
                                    break
                        else:
                            diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_conflict_check", **inference})
                    continue
                if not self.config.enable_candidate_geocoding:
                    continue

                query = self._candidate_geocode_query(candidate, target)
                if query:
                    if geocode_attempted >= effective_max_geocodes:
                        geocode_skipped += 1
                    else:
                        geocode_attempted += 1
                        if query not in geocode_cache:
                            geocode_cache[query] = self._geocode_candidate_location(query)
                        result = geocode_cache[query]
                        if result is None:
                            diagnostics.append({"stream_url": candidate.stream_url, "query": query, "stage": "metadata_geocode", "status": "not_resolved"})
                        else:
                            lat, lon, display_name = result
                            scope_ok, scope_reason = self._geocode_result_passes_target_scope(lat, lon, display_name, target)
                            if not scope_ok:
                                candidate.reasons.append(scope_reason)
                                diagnostics.append({"stream_url": candidate.stream_url, "query": query, "stage": "metadata_geocode", "status": "outside_target_scope", "display_name": display_name, "scope_reason": scope_reason})
                            else:
                                self._assign_candidate_geocode(
                                    candidate,
                                    lat,
                                    lon,
                                    query,
                                    display_name,
                                    coordinate_source="candidate_geocoder",
                                    reason="coordinates_geocoded_from_candidate_metadata",
                                    metadata={"geocode_provider": "nominatim", "geocode_scope_status": scope_reason},
                                )
                                geocode_enriched += 1
                                diagnostics.append({"stream_url": candidate.stream_url, "query": query, "stage": "metadata_geocode", "status": "resolved", "display_name": display_name, "lat": lat, "lon": lon, "scope_reason": scope_reason})
                                continue
                else:
                    geocode_skipped += 1

                if candidate.has_coordinates:
                    continue

                if not getattr(self.config, "enable_llm_location_inference", False):
                    llm_location_skipped += 1
                    continue
                if llm_location_attempted >= max_llm_location_inferences:
                    llm_location_skipped += 1
                    diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_inference", "status": "skipped_max_llm_location_inferences"})
                    continue
                if not _candidate_has_location_inference_evidence(candidate):
                    llm_location_skipped += 1
                    diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_inference", "status": "skipped_no_location_like_evidence"})
                    continue
                if location_client_failed:
                    llm_location_skipped += 1
                    continue
                if location_client is None:
                    try:
                        location_client = build_location_inference_client(self.config)
                    except Exception as exc:
                        location_client_failed = True
                        llm_location_skipped += 1
                        diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_inference", "status": "client_unavailable", "error": repr(exc)})
                        continue

                llm_location_attempted += 1
                inference = self._infer_candidate_location_names(candidate, target, location_client)
                if inference.get("status") != "ok":
                    diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_inference", **inference})
                    continue

                accepted = False
                for row in inference.get("location_candidates", []):
                    confidence = _float_or_none(row.get("confidence")) or 0.0
                    if confidence < min_llm_confidence:
                        continue
                    if not _llm_location_evidence_supported(candidate, row):
                        diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_inference", "status": "unsupported_evidence", "candidate": row})
                        continue
                    for inferred_query in self._llm_location_queries(row, target):
                        if not inferred_query:
                            continue
                        if inferred_query not in geocode_cache:
                            geocode_cache[inferred_query] = self._geocode_candidate_location(inferred_query)
                        result = geocode_cache[inferred_query]
                        if result is None:
                            diagnostics.append({"stream_url": candidate.stream_url, "query": inferred_query, "stage": "llm_location_inference", "status": "not_resolved", "candidate": row})
                            continue
                        lat, lon, display_name = result
                        if _is_broad_or_target_level_inference(row, inferred_query, display_name, target):
                            diagnostics.append({"stream_url": candidate.stream_url, "query": inferred_query, "stage": "llm_location_inference", "status": "rejected_broad_or_target_level_inference", "display_name": display_name, "candidate": row})
                            continue
                        scope_ok, scope_reason = self._geocode_result_passes_target_scope(lat, lon, display_name, target)
                        if not scope_ok:
                            diagnostics.append({"stream_url": candidate.stream_url, "query": inferred_query, "stage": "llm_location_inference", "status": "outside_target_scope", "display_name": display_name, "candidate": row, "scope_reason": scope_reason})
                            continue
                        self._assign_candidate_geocode(
                            candidate,
                            lat,
                            lon,
                            inferred_query,
                            display_name,
                            coordinate_source="llm_url_location_nominatim",
                            reason="coordinates_geocoded_from_llm_inferred_location_name",
                            metadata={
                                "geocode_provider": "nominatim",
                                "geocode_scope_status": scope_reason,
                                "llm_location_inference": row,
                                "llm_location_inference_model": getattr(location_client, "model", None),
                                "llm_location_inference_queries": self._llm_location_queries(row, target),
                                "coordinate_precision": row.get("precision") or "place_or_intersection",
                            },
                        )
                        llm_location_enriched += 1
                        accepted = True
                        diagnostics.append({"stream_url": candidate.stream_url, "query": inferred_query, "stage": "llm_location_inference", "status": "resolved", "display_name": display_name, "lat": lat, "lon": lon, "confidence": confidence, "scope_reason": scope_reason})
                        break
                    if accepted:
                        break
                if not accepted:
                    diagnostics.append({"stream_url": candidate.stream_url, "stage": "llm_location_inference", "status": "no_accepted_geocode", "inference": inference})

            finally:
                self._emit_progress(
                    "coordinate_candidate_processed",
                    processed=processed_index,
                    total=total_candidates,
                    coordinate_bearing=sum(1 for c in candidates if c.has_coordinates),
                    metadata_enriched=metadata_enriched,
                    geocode_attempted=geocode_attempted,
                    geocode_enriched=geocode_enriched,
                    geocode_skipped=geocode_skipped,
                    llm_location_attempted=llm_location_attempted,
                    llm_location_enriched=llm_location_enriched,
                    llm_location_skipped=llm_location_skipped,
                )

        self._emit_progress(
            "coordinate_enrichment_complete",
            total=len(candidates),
            coordinate_bearing=sum(1 for c in candidates if c.has_coordinates),
            metadata_enriched=metadata_enriched,
            geocode_attempted=geocode_attempted,
            geocode_enriched=geocode_enriched,
            geocode_skipped=geocode_skipped,
            llm_location_attempted=llm_location_attempted,
            llm_location_enriched=llm_location_enriched,
            llm_location_skipped=llm_location_skipped,
        )

        write_json(
            self.logs_dir / "candidate_coordinate_enrichment.json",
            {
                "candidates": len(candidates),
                "already_coordinate_bearing": sum(1 for c in candidates if c.has_coordinates) - metadata_enriched - geocode_enriched - llm_location_enriched,
                "metadata_enriched": metadata_enriched,
                "geocode_attempted": geocode_attempted,
                "geocode_enriched": geocode_enriched,
                "geocode_skipped": geocode_skipped,
                "llm_location_attempted": llm_location_attempted,
                "llm_location_enriched": llm_location_enriched,
                "llm_location_skipped": llm_location_skipped,
                "enable_llm_location_inference": getattr(self.config, "enable_llm_location_inference", False),
                "max_llm_location_inferences": max_llm_location_inferences,
                "llm_location_inference_min_confidence": min_llm_confidence,
                "max_candidate_geocodes": self.config.max_candidate_geocodes,
                "effective_max_candidate_geocodes": effective_max_geocodes,
                "enable_candidate_geocoding": self.config.enable_candidate_geocoding,
                "diagnostics": diagnostics[:300],
            },
        )

    def _effective_candidate_geocode_limit(self, candidates: list[CameraCandidate], target: TargetContext) -> int:
        configured = max(0, int(self.config.max_candidate_geocodes))
        if configured == 0:
            return 0
        missing_specific = sum(
            1 for c in candidates
            if not c.has_coordinates and self._candidate_geocode_query(c, target)
        )
        broad_scope = str(target.scope_type or "").casefold() in {"state", "region", "country", "metro", "county"}
        if broad_scope and missing_specific > configured:
            return min(missing_specific, max(configured, self.config.max_state_scale_candidate_geocodes))
        return configured

    def _candidate_lat_lon_from_existing_evidence(self, candidate: CameraCandidate) -> tuple[float, float] | None:
        for mapping in (candidate.source_metadata, _url_query_mapping(candidate.stream_url), _url_query_mapping(candidate.source_url or "")):
            lat_lon = _record_lat_lon(mapping)
            if lat_lon:
                return lat_lon
        return None

    def _candidate_geocode_query(self, candidate: CameraCandidate, target: TargetContext) -> str | None:
        metadata = candidate.source_metadata or {}
        tiered_keys = [
            ("json_location", ("location_display", "location_text", "intersection", "cross_street", "route", "road", "direction", "city", "county", "district", "camera_name")),
            ("candidate_title", ()),
        ]
        parts: list[str] = []
        basis: list[str] = []
        for tier, keys in tiered_keys:
            if tier == "candidate_title":
                values = [candidate.location_text, candidate.title]
            else:
                values = [metadata.get(key) for key in keys]
                if tier == "json_location" and metadata.get("json_metadata_extracted"):
                    values.append(metadata.get("camera_id"))
            for value in values:
                if isinstance(value, (str, int, float)) and _specific_candidate_location_text(str(value), target):
                    text = str(value).strip()
                    if text not in parts:
                        parts.append(text)
                        basis.append(tier)
            if parts:
                break
        parts = _dedupe_strings(parts)
        if not parts:
            return None
        first = parts[0]
        target_only = [part.casefold() for part in (target.canonical_target, target.target_label, target.admin_region, target.country) if isinstance(part, str)]
        if first.casefold() in target_only:
            return None
        suffix_parts = _dedupe_strings([part for part in (target.canonical_target, target.admin_region, target.country) if part])
        suffix = ", ".join(suffix_parts)
        query = ", ".join([first, suffix]) if suffix and suffix.casefold() not in first.casefold() else first
        if isinstance(metadata, dict):
            metadata["geocode_query_basis"] = _dedupe_strings(basis + (["target_context"] if suffix else []))
        return query[:300]

    def _geocode_candidate_location(self, query: str) -> tuple[float, float, str] | None:
        url = f"https://nominatim.openstreetmap.org/search?{urlencode({'q': query, 'format': 'jsonv2', 'limit': '1', 'addressdetails': '1'})}"
        try:
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
                time.sleep(1.0)
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
        except Exception:
            return None
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        lat = _float_or_none(first.get("lat"))
        lon = _float_or_none(first.get("lon"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon, str(first.get("display_name") or query)

    def _assign_candidate_geocode(
        self,
        candidate: CameraCandidate,
        lat: float,
        lon: float,
        query: str,
        display_name: str,
        *,
        coordinate_source: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        candidate.lat = lat
        candidate.lon = lon
        candidate.coordinate_source = coordinate_source
        candidate.geocoded_query = query
        candidate.geocoded_display_name = display_name
        candidate.reasons.append(reason)
        if metadata:
            candidate.source_metadata.update(metadata)

    def _geocode_result_passes_target_scope(self, lat: float, lon: float, display_name: str, target: TargetContext) -> tuple[bool, str]:
        if target.bbox_verified and target.target_geometry_geojson:
            if _point_in_geojson_geometry(lat, lon, target.target_geometry_geojson):
                return True, "coordinate_inside_verified_target_polygon"
            return False, "candidate_geocode_outside_verified_target_polygon"
        if target.bbox_verified and target.bbox:
            if _point_in_bbox(lat, lon, target.bbox):
                return True, "coordinate_inside_verified_bbox"
            return False, "candidate_geocode_outside_verified_target_bbox"
        return True, "target_bbox_unverified_review_only"

    def _infer_candidate_location_names(self, candidate: CameraCandidate, target: TargetContext, client: LLMClient) -> dict[str, Any]:
        payload = self._candidate_location_inference_payload(candidate, target)
        try:
            raw = client.chat(
                [
                    ChatMessage("system", "Return strict JSON only. Infer place-name geocoding queries from evidence; never return coordinates."),
                    ChatMessage("user", self._candidate_location_inference_prompt(payload)),
                ],
                temperature=0.0,
            )
            data = extract_json_object(raw)
        except Exception as exc:
            return {"status": "failed", "error": repr(exc), "model": getattr(client, "model", None)}
        rows = data.get("location_candidates") if isinstance(data.get("location_candidates"), list) else []
        normalized = _normalize_location_inference_rows(rows)
        return {
            "status": "ok",
            "has_location_hint": bool(data.get("has_location_hint")) and bool(normalized),
            "location_candidates": normalized,
            "raw": data,
            "model": getattr(client, "model", None),
        }

    def _candidate_location_inference_payload(self, candidate: CameraCandidate, target: TargetContext) -> dict[str, Any]:
        return {
            "stream_url": candidate.stream_url,
            "source_url": candidate.source_url,
            "title": candidate.title,
            "location_text": candidate.location_text,
            "source_name": candidate.source_metadata.get("source_name"),
            "source_metadata": _limited_scalar_metadata(candidate.source_metadata),
            "target": {
                "user_query": target.user_query,
                "canonical_target": target.canonical_target,
                "target_label": target.target_label,
                "scope_type": target.scope_type,
                "admin_region": target.admin_region,
                "country": target.country,
                "bbox_verified": target.bbox_verified,
                "bbox": target.bbox if target.bbox_verified else None,
            },
        }

    def _candidate_location_inference_prompt(self, payload: dict[str, Any]) -> str:
        return (
            "Infer possible Nominatim geocoding query strings for a camera candidate that lacks coordinates. "
            "Use only evidence present in the input: stream_url, source_url, title/name, location_text, source name, source metadata, target query/scope, and nearby text if present. "
            "Do not invent latitude/longitude and do not return coordinates. "
            "If evidence is too weak or ambiguous, return has_location_hint=false and an empty location_candidates list. "
            "Every evidence token should appear in the input evidence. Prefer specific place names, intersections, road names, route names, agency names, and camera IDs. "
            "Return strict JSON exactly shaped as: "
            "{\"has_location_hint\":true,\"location_candidates\":[{\"query\":\"place or intersection query\",\"variants\":[\"alternate query\"],\"confidence\":0.0,\"evidence\":[\"token from input\"],\"reason\":\"short reason\",\"precision\":\"place|intersection|road|agency|unknown\"}]}\n"
            f"Input evidence JSON:\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)[:12000]}"
        )

    def _llm_location_queries(self, row: dict[str, Any], target: TargetContext) -> list[str]:
        raw_values: list[str] = []
        query = row.get("query")
        if isinstance(query, str):
            raw_values.append(query)
        variants = row.get("variants")
        if isinstance(variants, list):
            raw_values.extend(str(v) for v in variants if isinstance(v, str) and v.strip())
        out: list[str] = []
        for value in _dedupe_strings([v.strip() for v in raw_values if v and _is_safe_geocode_query(v)]):
            out.append(_append_target_context_to_query(value, target))
        return _dedupe_strings([q for q in out if q])[:5]

    def _scope_candidates(self, candidates: list[CameraCandidate], target: TargetContext) -> None:
        bbox = target.bbox if target.bbox_verified else None
        polygon = target.target_geometry_geojson if target.bbox_verified else None
        for candidate in candidates:
            if candidate.has_coordinates and polygon:
                assert candidate.lat is not None and candidate.lon is not None
                if _point_in_geojson_geometry(candidate.lat, candidate.lon, polygon):
                    candidate.scope_status = "in_scope"
                    candidate.reasons.append("coordinate_inside_verified_target_polygon")
                else:
                    candidate.scope_status = "out_of_scope"
                    candidate.trust_level = "rejected"
                    candidate.reasons.append("coordinate_outside_verified_target_polygon")
            elif candidate.has_coordinates and bbox:
                if bbox["min_lat"] <= candidate.lat <= bbox["max_lat"] and bbox["min_lon"] <= candidate.lon <= bbox["max_lon"]:
                    candidate.scope_status = "in_scope"
                    candidate.reasons.append("coordinate_inside_verified_bbox")
                else:
                    candidate.scope_status = "out_of_scope"
                    candidate.trust_level = "rejected"
                    candidate.reasons.append("coordinate_outside_verified_bbox")
            elif candidate.has_coordinates:
                candidate.scope_status = "review"
                candidate.reasons.append("coordinate_available_but_target_bbox_untrusted_or_missing")
            else:
                candidate.scope_status = "unknown"
                candidate.reasons.append("missing_candidate_coordinates")

    def _apply_llm_candidate_review(self, candidates: list[CameraCandidate], target: TargetContext) -> None:
        """Apply advisory LLM semantic review without making it a run-fatal step.

        Candidate semantic review is an evidence interpretation stage, not the
        stream-validation or output-trust authority. Remote LLM calls can time out
        on large candidate batches, especially in interactive runs using larger cloud
        models. To keep discovery usable, review is sent in bounded batches; a
        failed batch is recorded in diagnostics and the affected candidates remain
        review-only instead of crashing the run.
        """
        if not candidates:
            return
        max_reviews = max(0, int(self.config.max_candidate_reviews))
        if max_reviews == 0:
            write_json(
                self.logs_dir / "candidate_semantic_review.json",
                {"status": "skipped", "reason": "CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS=0"},
            )
            return

        reviewable = [candidate for candidate in candidates if not (candidate.scope_status == "out_of_scope" and candidate.trust_level == "rejected")][:max_reviews]
        if not reviewable:
            return

        client = self.semantic_review_client or build_candidate_review_client(self.config)
        batch_size = max(1, int(self.config.candidate_review_batch_size))
        by_index = {index: candidate for index, candidate in enumerate(candidates)}
        batches: list[dict[str, Any]] = []
        applied_rows: list[dict[str, Any]] = []

        for batch_number, batch in enumerate(_chunks(reviewable, batch_size), start=1):
            payload = [self._candidate_review_payload(candidate, candidates.index(candidate)) for candidate in batch]
            try:
                raw = client.chat(
                    [
                        ChatMessage("system", "Return strict JSON only. You are an advisory semantic reviewer, not a stream validator."),
                        ChatMessage("user", self._candidate_review_prompt(target, payload)),
                    ],
                    temperature=0.0,
                )
                data = extract_json_object(raw)
            except Exception as exc:  # External LLM/API failure must not corrupt deterministic review artifacts.
                message = repr(exc)[:1000]
                batches.append(
                    {
                        "batch": batch_number,
                        "status": "failed",
                        "error": message,
                        "candidate_indexes": [row["index"] for row in payload],
                        "model": getattr(client, "model", None),
                    }
                )
                for row in payload:
                    candidate = by_index.get(row["index"])
                    if candidate is not None:
                        candidate.reasons.append("llm_semantic_review_failed")
                        if candidate.scope_status == "unknown":
                            candidate.scope_status = "review"
                continue

            rows = data.get("candidates") if isinstance(data.get("candidates"), list) else []
            batches.append(
                {
                    "batch": batch_number,
                    "status": "ok",
                    "raw": raw,
                    "parsed": data,
                    "candidate_indexes": [row["index"] for row in payload],
                    "model": getattr(client, "model", None),
                }
            )
            for row in rows:
                if isinstance(row, dict) and self._apply_candidate_review_row(row, by_index, target):
                    applied_rows.append(row)

        write_json(
            self.logs_dir / "candidate_semantic_review_llm_raw.json",
            {"batches": batches, "model": getattr(client, "model", None)},
        )
        write_json(
            self.logs_dir / "candidate_semantic_review.json",
            {
                "status": "completed_with_failures" if any(batch["status"] == "failed" for batch in batches) else "completed",
                "reviewable_candidates": len(reviewable),
                "batch_size": batch_size,
                "batches": [{k: v for k, v in batch.items() if k != "raw"} for batch in batches],
                "applied_rows": applied_rows,
            },
        )

    def _candidate_review_payload(self, candidate: CameraCandidate, index: int) -> dict[str, Any]:
        return {
            "index": index,
            "stream_url": candidate.stream_url,
            "source_url": candidate.source_url,
            "title": candidate.title,
            "lat": candidate.lat,
            "lon": candidate.lon,
            "location_text": candidate.location_text,
            "deterministic_scope_status": candidate.scope_status,
            "reasons": candidate.reasons,
            "source_metadata": candidate.source_metadata,
        }

    def _apply_candidate_review_row(self, row: dict[str, Any], by_index: dict[int, CameraCandidate], target: TargetContext) -> bool:
        index = _int_or_none(row.get("index"))
        if index is None or index not in by_index:
            return False
        candidate = by_index[index]
        decision = str(row.get("decision") or "review").casefold()
        if decision not in {"in_scope", "out_of_scope", "review", "unknown"}:
            decision = "review"
        candidate.llm_semantic_decision = decision  # type: ignore[assignment]
        candidate.llm_semantic_confidence = _float_or_none(row.get("confidence"))
        candidate.llm_semantic_reason = str(row.get("reason") or "")[:500]
        candidate.reasons.append(f"llm_semantic_review:{decision}")
        if candidate.scope_status == "out_of_scope" and candidate.trust_level == "rejected":
            return True
        if decision == "out_of_scope" and (candidate.llm_semantic_confidence or 0.0) >= 0.75:
            candidate.scope_status = "out_of_scope"
            candidate.trust_level = "rejected"
        elif decision == "in_scope" and target.bbox_verified and candidate.has_coordinates:
            if candidate.scope_status != "out_of_scope":
                candidate.scope_status = "in_scope"
        elif decision in {"in_scope", "review"} and candidate.scope_status == "unknown":
            candidate.scope_status = "review"
        return True

    def _candidate_review_prompt(self, target: TargetContext, candidates: list[dict]) -> str:
        return (
            "Review candidate public-camera HLS streams semantically against the target context. "
            "Use source_url/title/coordinates/location text only as evidence. Do not validate whether streams are live, reachable, or decoded. "
            "Do not authorize trusted output. Return JSON: {\"candidates\":[{\"index\":0,\"decision\":\"in_scope|out_of_scope|review|unknown\","
            "\"confidence\":0.0,\"reason\":\"short reason\"}]}\n"
            f"Target: canonical={target.canonical_target!r}, scope={target.scope_type!r}, admin={target.admin_region!r}, country={target.country!r}, bbox_verified={target.bbox_verified}\n"
            f"Candidates: {candidates}"
        )
