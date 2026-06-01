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
from camera_discovery.harvest.media_filter import canonical_media_url


class CandidateExtractionMixin:
    """Static page, linked endpoint, text, HTML, and structured JSON candidate extraction helpers."""

    def _extract_from_source_row(self, row: dict[str, str], client: httpx.Client | None = None, *, phase: str = "primary") -> list[CameraCandidate]:
        url = row.get("url") or ""
        if self.source_policy.is_blocked(url):
            return []
        if _looks_like_hls(url):
            candidate = self._candidate_from_stream(url, url, row, "direct_hls")
            candidate.source_metadata["media_type"] = "hls"
            return [candidate]
        static_candidates, signals = self._extract_from_page_with_signals(url, row, client, phase=phase)
        decision = self._browser_capture_decision(row, static_candidates, signals, phase)
        self._log_browser_capture_decision(decision)
        if not decision.selected:
            return static_candidates
        self._emit_progress(
            "browser_capture_started",
            phase=phase,
            url=url,
            source_provider=decision.source_provider,
            source_kind=decision.source_kind,
            score=decision.score,
            browser_backend=self.config.browser_backend,
            reasons=decision.reasons,
        )
        try:
            payload = self._extract_from_dynamic_page(url, row, phase=phase, decision=decision, return_result=True)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            payload = self._extract_from_dynamic_page(url, row)
        if isinstance(payload, tuple):
            browser_candidates, result = payload
        else:
            browser_candidates = payload
            result = BrowserCaptureResult(url=url, total_browser_candidates=len(browser_candidates or []))
            self._record_browser_summary(row.get("source_provider") or "unknown", attempted=True, candidates=browser_candidates or [])
        self._log_browser_capture_result(result, row, phase)
        self._emit_progress(
            "browser_capture_page_complete",
            phase=phase,
            url=url,
            source_provider=decision.source_provider,
            candidates=result.total_browser_candidates,
            hls_urls=len(result.captured_hls_urls or []),
            json_urls=len(result.captured_json_urls or []),
            browser_backend=result.backend,
            timed_out=result.timed_out,
            error=bool(result.error),
        )
        return self._dedupe(static_candidates + (browser_candidates or []))

    def _extract_from_page(self, url: str, row: dict[str, str], client: httpx.Client | None = None) -> list[CameraCandidate]:
        candidates, _signals = self._extract_from_page_with_signals(url, row, client, phase="direct_static")
        return candidates

    def _extract_from_page_with_signals(
        self,
        url: str,
        row: dict[str, str],
        client: httpx.Client | None = None,
        *,
        phase: str = "primary",
    ) -> tuple[list[CameraCandidate], PageDiscoverySignals | None]:
        owns_client = client is None
        client = client or self._make_client()
        try:
            resp = _get_with_retry(client, url)
            resp.raise_for_status()
            text = resp.text
            content_type = resp.headers.get("content-type", "")
            out = self._extract_from_response(url, row, text, content_type)
            if "html" in content_type.lower() or "<html" in text[:1000].lower():
                out.extend(self._extract_from_linked_feeds(url, row, text, client))
            deduped = self._dedupe(out)
            signals = self._page_discovery_signals(url, row, text, content_type, resp.status_code, len(deduped))
            write_jsonl(self.logs_dir / "page_discovery_signals.jsonl", [signals.to_log_record(row, phase)], append=True)
            return deduped, signals
        except Exception as exc:
            signals = PageDiscoverySignals(
                url=url,
                source_provider=row.get("source_provider") or "",
                source_kind=row.get("source_kind") or "",
                dynamic_signals=["static_fetch_error"],
                static_candidate_count=0,
            )
            write_jsonl(
                self.logs_dir / "page_discovery_signals.jsonl",
                [{**signals.to_log_record(row, phase), "error": repr(exc)}],
                append=True,
            )
            return [], signals
        finally:
            if owns_client:
                client.close()

    def _extract_from_response(self, url: str, row: dict[str, str], text: str, content_type: str = "") -> list[CameraCandidate]:
        if _looks_like_json_response(url, content_type, text):
            data = self._parse_json_text(text)
            if data is not None:
                return self._extract_from_json_data(data, url, row, "json_endpoint")
        if "html" in content_type.casefold() or "<html" in text[:1000].casefold():
            structured_rows = self._extract_structured_from_html_text(url, row, text)
            text_rows = self._extract_from_text(url, row, text, include_image_regex=not structured_rows)
            html_rows = [] if structured_rows else self._extract_from_html(url, row, text)
            return self._dedupe(structured_rows + text_rows + html_rows)
        return self._extract_from_text(url, row, text)

    def _extract_from_text(self, url: str, row: dict[str, str], text: str, *, include_image_regex: bool = True) -> list[CameraCandidate]:
        out: list[CameraCandidate] = []
        out.extend(self._extract_hls_from_text(url, row, text, "hls_regex"))
        if include_image_regex:
            out.extend(self._extract_images_from_text(url, row, text, "image_snapshot_regex"))
        return self._dedupe(out)

    def _extract_structured_from_html_text(self, url: str, row: dict[str, str], text: str) -> list[CameraCandidate]:
        out: list[CameraCandidate] = []
        for blob in self._extract_json_blobs(text):
            out.extend(self._extract_from_json_data(blob, url, row, "javascript_config"))
        return self._dedupe(out)

    def _extract_from_html(self, url: str, row: dict[str, str], html: str) -> list[CameraCandidate]:
        """Extract camera candidates from structured HTML image/source tags.

        This captures alt/title/data attributes and nearby text that plain regex
        extraction loses. It also filters obvious site assets such as logos,
        OpenGraph images, and map tiles so they do not become camera candidates.
        """
        soup = _html_soup(html)
        out: list[CameraCandidate] = []
        for tag in soup.select("img, source, video"):
            urls = _media_urls_from_html_tag(tag, url)
            if not urls:
                continue
            metadata = _metadata_from_html_tag(tag)
            parent_text = _nearby_text(tag)
            coords = _record_lat_lon(metadata) or _record_lat_lon(_metadata_from_html_tag(tag.parent)) if getattr(tag, "parent", None) is not None else None
            title = _first_nonempty(metadata.get("alt"), metadata.get("title"), metadata.get("aria_label"), metadata.get("data_title"), _humanize_camera_slug_from_url(urls[0][0]))
            location_text = _first_nonempty(
                metadata.get("location"),
                metadata.get("data_location"),
                metadata.get("data_title"),
                metadata.get("alt"),
                metadata.get("title"),
                parent_text,
                _humanize_camera_slug_from_url(urls[0][0]),
            )
            for media_url, media_type in urls:
                if self.source_policy.is_blocked(media_url) or _looks_like_non_camera_asset(media_url):
                    continue
                candidate = self._candidate_from_stream(media_url, url, row, "html_media_tag")
                candidate.title = title or candidate.title
                candidate.location_text = location_text
                candidate.source_metadata.update(_simple_metadata(metadata))
                candidate.source_metadata["media_type"] = media_type
                if media_type == "image_snapshot":
                    candidate.source_metadata["snapshot_url"] = media_url
                if coords:
                    candidate.lat, candidate.lon = coords
                    candidate.coordinate_source = "html_media_tag_attribute"
                out.append(candidate)
        return self._dedupe(out)

    def _extract_from_linked_feeds(self, url: str, row: dict[str, str], html: str, client: httpx.Client) -> list[CameraCandidate]:
        soup = _html_soup(html)
        hrefs: list[str] = []
        for tag in soup.select("a[href], link[href], script[src]"):
            href = tag.get("href") or tag.get("src") or ""
            absolute = urljoin(url, href)
            if JSON_FEED_HINT_RE.search(absolute) and not self.source_policy.is_blocked(absolute):
                hrefs.append(absolute)
        for raw in re.findall(r'["\']([^"\']*(?:\.json|/api/|/feed|/feeds|/layer|/layers|MapServer|FeatureServer|/query)[^"\']*)["\']', html, flags=re.I):
            absolute = urljoin(url, raw)
            if absolute.startswith("http") and not self.source_policy.is_blocked(absolute):
                hrefs.append(absolute)
        out: list[CameraCandidate] = []
        endpoint_logs: list[dict[str, Any]] = []
        for feed_url in _dedupe_strings(_expand_structured_endpoint_urls(hrefs))[: self.config.max_structured_endpoints_per_page]:
            try:
                resp = client.get(feed_url)
                if resp.status_code >= 400:
                    endpoint_logs.append({"page_url": url, "endpoint_url": feed_url, "status": resp.status_code, "candidates": 0})
                    continue
                before = len(out)
                out.extend(self._extract_from_response(feed_url, row, resp.text, resp.headers.get("content-type", "")))
                endpoint_logs.append({"page_url": url, "endpoint_url": feed_url, "status": resp.status_code, "candidates": len(out) - before})
            except Exception as exc:
                endpoint_logs.append({"page_url": url, "endpoint_url": feed_url, "error": repr(exc), "candidates": 0})
                continue
        if endpoint_logs:
            write_jsonl(self.logs_dir / "structured_endpoint_discovery.jsonl", endpoint_logs, append=True)
        return self._dedupe(out)

    def _extract_hls_from_text(self, source_url: str, row: dict[str, str], text: str, method: str) -> list[CameraCandidate]:
        out: list[CameraCandidate] = []
        for match in M3U8_RE.finditer(text):
            raw = match.group(0).strip("'\"") if match.group(0).startswith("http") else (match.group(1) or "").strip("'\"")
            stream = urljoin(source_url, raw)
            if ".m3u8" in stream.lower() and not self.source_policy.is_blocked(stream):
                candidate = self._candidate_from_stream(stream, source_url, row, method)
                candidate.source_metadata["media_type"] = "hls"
                start = max(0, match.start() - 500)
                end = min(len(text), match.end() + 500)
                local_coords = self._extract_first_coord(text[start:end])
                if local_coords:
                    candidate.lat, candidate.lon = local_coords
                    candidate.coordinate_source = "proximity_text"
                out.append(candidate)
        return out

    def _extract_images_from_text(self, source_url: str, row: dict[str, str], text: str, method: str) -> list[CameraCandidate]:
        out: list[CameraCandidate] = []
        for match in IMAGE_RE.finditer(text):
            raw = match.group(0).strip("'\"") if match.group(0).startswith("http") else (match.group(1) or "").strip("'\"")
            image_url = urljoin(source_url, raw)
            if not self.source_policy.is_blocked(image_url) and not _looks_like_non_camera_asset(image_url):
                candidate = self._candidate_from_stream(image_url, source_url, row, method)
                slug_location = _humanize_camera_slug_from_url(image_url)
                if slug_location:
                    candidate.title = slug_location
                    candidate.location_text = slug_location
                    candidate.source_metadata["camera_id"] = _camera_id_from_url(image_url) or slug_location
                candidate.source_metadata["media_type"] = "image_snapshot"
                candidate.source_metadata["snapshot_url"] = image_url
                start = max(0, match.start() - 500)
                end = min(len(text), match.end() + 500)
                local_coords = self._extract_first_coord(text[start:end])
                if local_coords:
                    candidate.lat, candidate.lon = local_coords
                    candidate.coordinate_source = "proximity_text"
                out.append(candidate)
        return out

    def _parse_json_text(self, text: str) -> Any | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _extract_json_blobs(self, text: str) -> list[Any]:
        blobs: list[Any] = []
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\[{]", text):
            start = match.start()
            window = text[max(0, start - 80): start].casefold()
            if not any(hint in window for hint in ("camera", "cameras", "features", "layers", "markers", "data", "feed")):
                continue
            try:
                obj, end = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if end > 10:
                blobs.append(obj)
            if len(blobs) >= 20:
                break
        return blobs

    def _extract_from_json_data(self, data: Any, source_url: str, row: dict[str, str], method: str) -> list[CameraCandidate]:
        out: list[CameraCandidate] = []
        stats = {
            "endpoint": source_url,
            "method": method,
            "records_considered": 0,
            "records_with_media": 0,
            "hls_candidates": 0,
            "image_snapshot_candidates": 0,
            "other_media_candidates": 0,
            "records_with_authoritative_coordinates": 0,
            "records_with_refresh_metadata": 0,
            "records_with_camera_type": 0,
            "records_skipped_no_media": 0,
            "records_skipped_non_camera_asset": 0,
            "errors": 0,
        }
        try:
            self._walk_json(data, source_url, row, method, out, path="$", stats=stats)
        except Exception as exc:
            stats["errors"] += 1
            write_jsonl(self.logs_dir / "json_endpoint_extraction_errors.jsonl", [{"endpoint": source_url, "method": method, "error": repr(exc)}], append=True)
        write_jsonl(self.logs_dir / "json_endpoint_records.jsonl", [stats], append=True)
        self._update_json_endpoint_summary(stats)
        return self._dedupe(out)

    def _update_json_endpoint_summary(self, stats: dict[str, Any]) -> None:
        path = self.logs_dir / "json_endpoint_extraction_summary.json"
        with self._browser_capture_lock:
            try:
                existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except Exception:
                existing = {}
            summary = {
                "endpoints_seen": int(existing.get("endpoints_seen") or 0) + 1,
                "endpoints_parsed": int(existing.get("endpoints_parsed") or 0) + (1 if not stats.get("errors") else 0),
                "records_considered": int(existing.get("records_considered") or 0) + int(stats.get("records_considered") or 0),
                "records_with_media": int(existing.get("records_with_media") or 0) + int(stats.get("records_with_media") or 0),
                "hls_candidates": int(existing.get("hls_candidates") or 0) + int(stats.get("hls_candidates") or 0),
                "image_snapshot_candidates": int(existing.get("image_snapshot_candidates") or 0) + int(stats.get("image_snapshot_candidates") or 0),
                "other_media_candidates": int(existing.get("other_media_candidates") or 0) + int(stats.get("other_media_candidates") or 0),
                "records_with_authoritative_coordinates": int(existing.get("records_with_authoritative_coordinates") or 0) + int(stats.get("records_with_authoritative_coordinates") or 0),
                "records_with_refresh_metadata": int(existing.get("records_with_refresh_metadata") or 0) + int(stats.get("records_with_refresh_metadata") or 0),
                "records_with_camera_type": int(existing.get("records_with_camera_type") or 0) + int(stats.get("records_with_camera_type") or 0),
                "records_skipped_no_media": int(existing.get("records_skipped_no_media") or 0) + int(stats.get("records_skipped_no_media") or 0),
                "records_skipped_non_camera_asset": int(existing.get("records_skipped_non_camera_asset") or 0) + int(stats.get("records_skipped_non_camera_asset") or 0),
                "errors": int(existing.get("errors") or 0) + int(stats.get("errors") or 0),
            }
            write_json(path, summary)

    def _walk_json(
        self,
        value: Any,
        source_url: str,
        row: dict[str, str],
        method: str,
        out: list[CameraCandidate],
        *,
        path: str = "$",
        stats: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(value, dict):
            candidates = self._candidates_from_geojson_feature(value, source_url, row, method, record_path=path)
            if candidates:
                out.extend(candidates)
                if stats is not None:
                    _update_json_stats(stats, candidates, value)
            record_candidates = self._candidates_from_record(value, source_url, row, method, record_path=path)
            if record_candidates:
                out.extend(record_candidates)
                if stats is not None:
                    _update_json_stats(stats, record_candidates, value)
            elif stats is not None:
                if _record_looks_like_camera_record(value):
                    stats["records_considered"] += 1
                    stats["records_skipped_no_media"] += 1
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    self._walk_json(child, source_url, row, method, out, path=f"{path}.{key}", stats=stats)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                if isinstance(child, (dict, list)):
                    self._walk_json(child, source_url, row, method, out, path=f"{path}[{idx}]", stats=stats)

    def _candidates_from_geojson_feature(self, feature: dict[str, Any], source_url: str, row: dict[str, str], method: str, *, record_path: str = "") -> list[CameraCandidate]:
        if str(feature.get("type") or "").casefold() != "feature":
            return []
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        lat_lon = _lat_lon_from_geojson_coordinates(coords)
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        urls = _record_media_urls(props, source_url)
        if not urls:
            return []
        metadata = _json_camera_record_metadata(feature, source_url, record_path=record_path, schema_hint="geojson_feature")
        prop_metadata = _json_camera_record_metadata(props, source_url, record_path=f"{record_path}.properties", schema_hint="geojson_properties")
        metadata.update({k: v for k, v in prop_metadata.items() if k not in metadata or metadata[k] in (None, "")})
        out: list[CameraCandidate] = []
        for media_url, media_type in urls:
            if self.source_policy.is_blocked(media_url):
                continue
            candidate = self._candidate_from_stream(media_url, source_url, row, method + "_geojson_feature")
            if lat_lon:
                candidate.lat, candidate.lon = lat_lon
                candidate.coordinate_source = "json_geojson_geometry"
                candidate.reasons.append("coordinates_extracted_from_json_record")
            candidate.title = metadata.get("camera_name") or _record_title(props) or candidate.title
            candidate.location_text = metadata.get("location_display") or metadata.get("location_text") or _record_location_text(props)
            candidate.source_metadata.update(metadata)
            candidate.source_metadata["media_type"] = media_type
            candidate.source_metadata["media_url"] = media_url
            if media_type == "hls":
                candidate.source_metadata["stream_url"] = media_url
            elif media_type == "image_snapshot":
                candidate.source_metadata["snapshot_url"] = media_url
            candidate.source_metadata["camera_id"] = _stable_camera_id(candidate.source_metadata, media_url) or candidate.source_metadata.get("camera_id")
            if lat_lon:
                candidate.source_metadata.setdefault("coordinate_source", candidate.coordinate_source)
            out.append(candidate)
        return out

    def _candidate_from_geojson_feature(self, feature: dict[str, Any], source_url: str, row: dict[str, str], method: str) -> CameraCandidate | None:
        candidates = self._candidates_from_geojson_feature(feature, source_url, row, method)
        return candidates[0] if candidates else None

    def _candidates_from_record(self, record: dict[str, Any], source_url: str, row: dict[str, str], method: str, *, record_path: str = "") -> list[CameraCandidate]:
        flattened = _flatten_camera_record(record)
        urls = _record_media_urls(flattened, source_url)
        if not urls:
            return []
        metadata = _json_camera_record_metadata(record, source_url, record_path=record_path, schema_hint=_source_record_schema_hint(record))
        lat_lon = _record_lat_lon(flattened)
        out: list[CameraCandidate] = []
        for media_url, media_type in urls:
            if self.source_policy.is_blocked(media_url):
                continue
            candidate = self._candidate_from_stream(media_url, source_url, row, method + "_record")
            if lat_lon:
                candidate.lat, candidate.lon = lat_lon
                coordinate_source = str(metadata.get("coordinate_source") or "json_record")
                candidate.coordinate_source = coordinate_source
                candidate.reasons.append("coordinates_extracted_from_json_record")
            candidate.title = metadata.get("camera_name") or _record_title(flattened) or candidate.title
            candidate.location_text = metadata.get("location_display") or metadata.get("location_text") or _record_location_text(flattened)
            candidate.source_metadata.update(metadata)
            candidate.source_metadata["media_type"] = media_type
            candidate.source_metadata["media_url"] = media_url
            if media_type == "hls":
                candidate.source_metadata["stream_url"] = media_url
            elif media_type == "image_snapshot":
                candidate.source_metadata["snapshot_url"] = media_url
            candidate.source_metadata["camera_id"] = _stable_camera_id(candidate.source_metadata, media_url) or candidate.source_metadata.get("camera_id")
            if candidate.coordinate_source:
                candidate.source_metadata.setdefault("coordinate_source", candidate.coordinate_source)
            out.append(candidate)
        return out

    def _candidate_from_stream(self, stream_url: str, source_url: str, row: dict[str, str], method: str) -> CameraCandidate:
        stream_url = canonical_media_url(stream_url)
        metadata = {
            "source_provider": row.get("source_provider"),
            "source_kind": row.get("source_kind"),
            "source_name": row.get("source_name"),
            "source_scope_hint": row.get("source_scope_hint"),
            "source_notes": row.get("source_notes"),
            "query": row.get("query"),
        }
        return CameraCandidate(
            stream_url=stream_url,
            source_url=source_url,
            discovery_method=method,
            title=row.get("title") or row.get("source_name"),
            source_metadata={k: v for k, v in metadata.items() if v},
        )

    def _extract_first_coord(self, text: str) -> tuple[float, float] | None:
        for match in COORD_RE.finditer(text):
            lat, lon = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
        return None
