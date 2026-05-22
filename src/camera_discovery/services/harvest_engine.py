from __future__ import annotations

import concurrent.futures
import csv
import html
import json
import re
import threading
import time
from datetime import datetime, timezone
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse, urlsplit, urlunsplit

import httpx

from camera_discovery.core.models import (
    CameraCandidate,
    DiscoveryMode,
    DiscoveredEndpointRecord,
    HarvestConfig,
    HarvestResult,
    HarvestedCameraRecord,
    HarvestedMediaAsset,
    HarvestedUrlRecord,
    RunConfig,
)
from camera_discovery.services.structured_camera_records import (
    camera_record_to_inventory,
    endpoint_type_for_url,
    extract_structured_camera_records,
    url_record_to_inventory,
)
from camera_discovery.services.discovery_engine import (
    CandidateDiscoveryEngine,
    _dedupe_strings,
    _expand_structured_endpoint_urls,
    _get_with_retry,
    _html_soup,
    _looks_like_non_camera_asset,
    _pagination_rows,
)
from camera_discovery.sources import SourceEntry, SourcePolicy, load_source_policy
from camera_discovery.utils.io import write_json, write_jsonl

SUPPORTED_MEDIA_TYPES = ("hls", "mjpeg", "image_snapshot", "video_file", "stream", "unknown_media")
SUPPORTED_MEDIA_CATEGORIES = {
    "all",
    "*",
    "hls",
    "mjpeg",
    "image",
    "snapshot",
    "image_snapshot",
    "video",
    "video_file",
    "stream",
    "unknown",
    "unknown_media",
}
SUPPORTED_EXTENSIONS = {".m3u8", ".mjpg", ".mjpeg", ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".mov", ".m4v"}
CATEGORY_EXTENSIONS = {
    "hls": {".m3u8"},
    "mjpeg": {".mjpg", ".mjpeg"},
    "image_snapshot": {".jpg", ".jpeg", ".png", ".webp"},
    "video_file": {".mp4", ".webm", ".mov", ".m4v"},
    "stream": set(),
    "unknown_media": set(),
}
JSON_ENDPOINT_HINT_RE = re.compile(r"(?:\.json(?:\?|$)|/api/|/feed|/feeds|/layer|/layers|/query|MapServer|FeatureServer|camera|cameras)", re.I)
URL_RE = re.compile(r"https?://[^\s'\"<>\\)\]}]+", re.I)
QUOTED_MEDIA_RE = re.compile(
    r"[\"']([^\"']+\.(?:m3u8|mjpg|mjpeg|jpg|jpeg|png|webp|mp4|webm|mov|m4v)(?:\?[^\"']*)?)[\"']",
    re.I,
)
MEDIA_EXTENSION_RE = re.compile(r"\.(m3u8|mjpg|mjpeg|jpg|jpeg|png|webp|mp4|webm|mov|m4v)(?:$|[?#])", re.I)
JSON_MEDIA_KEYS = {
    "url",
    "src",
    "href",
    "stream",
    "streamurl",
    "stream_url",
    "streamingurl",
    "streaming_url",
    "hls",
    "hlsurl",
    "hls_url",
    "m3u8",
    "video",
    "videourl",
    "video_url",
    "media",
    "mediaurl",
    "media_url",
    "image",
    "imageurl",
    "image_url",
    "snapshot",
    "snapshoturl",
    "snapshot_url",
    "currentimage",
    "currentimageurl",
    "current_image_url",
    "mjpeg",
    "mjpegurl",
    "mjpeg_url",
}
JSON_METADATA_KEYS = {
    "id",
    "camera_id",
    "cameraid",
    "device_id",
    "deviceid",
    "name",
    "title",
    "label",
    "description",
    "location",
    "location_text",
    "intersection",
    "route",
    "road",
    "direction",
    "camera_direction",
    "facing",
    "bearing",
    "heading",
    "azimuth",
    "orientation",
    "latitude",
    "lat",
    "longitude",
    "lon",
    "lng",
    "x",
    "y",
    "coordinates",
    "geometry",
    "date",
    "time",
    "timestamp",
    "datetime",
    "last_updated",
    "last_update",
    "last_refresh",
    "capture_time",
    "captured_at",
    "agency",
    "owner",
    "operator",
    "provider",
    "city",
    "county",
    "state",
    "country",
    "refresh_rate",
    "refresh_interval",
    "refresh_seconds",
    "update_interval",
}

LATITUDE_KEYS = {"lat", "latitude", "cameralat", "cameralatitude", "gpslat", "gpslatitude"}
LONGITUDE_KEYS = {"lon", "lng", "long", "longitude", "cameralon", "cameralng", "cameralongitude", "gpslon", "gpslng", "gpslongitude"}
# Use x/y only when they appear as a pair and plausibly represent lon/lat.
X_LONGITUDE_KEYS = {"x", "coordx", "mapx", "longitudex"}
Y_LATITUDE_KEYS = {"y", "coordy", "mapy", "latitudey"}
DIRECTION_KEYS = {"direction", "cameradirection", "facing", "facingdirection", "viewdirection", "lookdirection", "orientation"}
BEARING_KEYS = {"bearing", "camerabearing", "azimuth", "angle", "viewangle"}
HEADING_KEYS = {"heading", "cameraheading", "viewheading"}
DATE_KEYS = {"date", "capturedate", "imagedate", "snapshotdate", "lastupdatedate", "updatedate"}
TIME_KEYS = {"time", "capturetime", "imagetime", "snapshottime", "lastupdatetime", "updatetime"}
TIMESTAMP_KEYS = {
    "timestamp",
    "datetime",
    "capturedat",
    "capturetimestamp",
    "imagetimestamp",
    "snapshottimestamp",
    "lastupdated",
    "lastupdate",
    "lastrefreshed",
    "lastrefresh",
    "updated",
    "updatetime",
    "updatetimestamp",
    "recordedat",
    "createdat",
    "observedat",
}


class MediaFilter:
    def __init__(self, requested: list[str], categories: set[str], extensions: set[str], all_media: bool) -> None:
        self.requested = requested
        self.categories = categories
        self.extensions = extensions
        self.all_media = all_media

    def matches(self, record: HarvestedUrlRecord) -> bool:
        if self.all_media:
            return True
        ext = media_extension(record.url)
        return record.media_type in self.categories or (ext in self.extensions if ext else False)


class CameraUrlHarvestEngine:
    """Extraction-only URL harvester for public camera/media URLs.

    This service deliberately avoids TargetResolver, geocoding, scope checks,
    validation, trust classification, LLM calls, GeoJSON, maps, cameras.md, and
    review-package generation. It reuses public source policy and safe generic
    extraction helpers only.
    """

    def __init__(self, config: HarvestConfig, progress_callback: Callable[[str, dict[str, Any]], None] | None = None):
        self.config = config
        self.progress_callback = progress_callback
        self.output_dir = config.output_dir
        self.logs_dir = self.output_dir / "logs"
        self.source_policy = load_source_policy(config.sources_file, config.block_patterns)
        self.media_filter = parse_media_filter(config.media)
        self._lock = threading.RLock()
        self._warnings: list[str] = []
        self._errors: list[dict[str, Any]] = []
        self._browser_host_counts: dict[str, int] = {}
        self._browser_pages_attempted = 0
        self._camera_records: dict[str, HarvestedCameraRecord] = {}
        self._media_assets: dict[str, HarvestedMediaAsset] = {}
        self._discovered_endpoints: dict[str, DiscoveredEndpointRecord] = {}
        self._blocked_source_rows: list[dict[str, Any]] = []
        self._source_rows_summary: dict[str, Any] = {}
        self._browser_summary: dict[str, Any] = {
            "enabled": config.enable_browser_capture,
            "backend": config.browser_backend,
            "pages_attempted": 0,
            "media_records": 0,
            "json_endpoints": 0,
            "errors": 0,
            "timeouts": 0,
            "network_events_sample": [],
        }

    def harvest(self) -> HarvestResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._emit("harvest_started", query=self.config.query, discovery_mode=self.config.discovery_mode.value)
        rows = self._source_rows()
        write_jsonl(self.output_dir / "source_rows.jsonl", rows)
        write_json(self.logs_dir / "source_rows_summary.json", self._source_rows_summary)
        self._emit("harvest_source_rows_ready", rows=len(rows), source_rows_summary=self._source_rows_summary)

        raw_records: list[HarvestedUrlRecord] = []
        client = self._make_client()
        try:
            records_by_index: list[list[HarvestedUrlRecord]] = [[] for _ in rows]
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, max(1, len(rows)))) as pool:
                futures = {pool.submit(self._extract_from_row, row, client): (idx, row) for idx, row in enumerate(rows)}
                processed = 0
                completed_raw_records = 0
                for future in concurrent.futures.as_completed(futures):
                    idx, row = futures[future]
                    try:
                        records = future.result()
                    except Exception as exc:  # pragma: no cover - defensive guard
                        records = []
                        self._log_error("row_extraction_error", row.get("url"), exc)
                    records_by_index[idx] = records
                    processed += 1
                    completed_raw_records += len(records)
                    self._emit(
                        "harvest_source_row_processed",
                        processed_rows=processed,
                        rows=len(rows),
                        source_url=row.get("url"),
                        records_found=len(records),
                        raw_records=completed_raw_records,
                    )
            for records in records_by_index:
                raw_records.extend(records)
        finally:
            client.close()

        blocked_filtered = [record for record in raw_records if self._record_block_reason(record)]
        unblocked = [record for record in raw_records if not self._record_block_reason(record)]
        unique = dedupe_records(unblocked)
        pre_filter_unique = len(unique)
        filtered = [record for record in unique if self.media_filter.matches(record)]
        media_filtered = len(filtered)
        written = filtered if self.config.max_urls == 0 else filtered[: self.config.max_urls]
        self._emit("harvest_dedupe_complete", raw_records=len(raw_records), unique_urls=len(unique), media_filtered_urls=media_filtered)
        outputs = self._write_outputs(written, raw_records=len(raw_records), unique=unique, pre_filter_unique=pre_filter_unique, media_filtered=media_filtered, blocked_or_filtered=len(blocked_filtered))
        self._emit("harvest_outputs_written", outputs=outputs, written_urls=len(written))
        result = HarvestResult(
            raw_count=len(raw_records),
            unique_count=len(unique),
            written_count=len(written),
            records=written,
            by_media_type=dict(Counter(record.media_type for record in written)),
            by_source_provider=dict(Counter(record.source_provider or "unknown" for record in written)),
            by_source_host=dict(Counter(urlparse(record.source_url or record.url).netloc.casefold() or "unknown" for record in written)),
            output_files=outputs,
            camera_records=list(self._camera_records.values()),
            media_assets=list(self._media_assets.values()),
            discovered_endpoints=list(self._discovered_endpoints.values()),
            warnings=self._warnings,
        )
        self._emit("harvest_complete", raw_records=result.raw_count, unique_urls=result.unique_count, written_urls=result.written_count)
        return result

    def _make_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True)

    def _emit(self, event: str, **payload: Any) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(event, payload)
        except Exception:
            return

    def _source_rows(self) -> list[dict[str, str]]:
        directory_rows: list[dict[str, str]] = []
        blind_rows: list[dict[str, str]] = []
        direct_rows: list[dict[str, str]] = []
        if self.config.discovery_mode in {DiscoveryMode.DIRECTORY, DiscoveryMode.BOTH}:
            directory_rows = self._directory_rows()
        if self.config.discovery_mode in {DiscoveryMode.BLIND, DiscoveryMode.BOTH}:
            blind_rows = self._blind_rows()
        if self.config.discovery_mode in {DiscoveryMode.DIRECT, DiscoveryMode.BOTH, DiscoveryMode.BLIND, DiscoveryMode.DIRECTORY}:
            direct_rows = self._direct_seed_rows()
        rows = [*directory_rows, *blind_rows, *direct_rows]
        selected_before_budget = self._select_rows(rows)
        selected = selected_before_budget
        max_source_rows_applied = False
        if self.config.max_source_rows > 0 and len(selected_before_budget) > self.config.max_source_rows:
            selected = selected_before_budget[: self.config.max_source_rows]
            max_source_rows_applied = True
        self._source_rows_summary = build_source_rows_summary(
            config=self.config,
            source_policy=self.source_policy,
            directory_rows=directory_rows,
            blind_rows=blind_rows,
            direct_rows=direct_rows,
            selected_before_budget=selected_before_budget,
            selected=selected,
            blocked_rows=self._blocked_source_rows,
            max_source_rows_applied=max_source_rows_applied,
        )
        return selected

    def _directory_rows(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for entry in self.source_policy.enabled_allowed_sources():
            if self.source_policy.is_blocked(entry.url):
                continue
            out.append(row_from_source_entry(entry, self.config.query, provider="directory"))
        return out

    def _direct_seed_rows(self) -> list[dict[str, str]]:
        urls = list(self.config.seed_urls)
        if self.config.seed_file:
            try:
                urls.extend(line.strip() for line in self.config.seed_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#"))
            except Exception as exc:
                self._warnings.append(f"Could not read seed file {self.config.seed_file}: {exc!r}")
        out: list[dict[str, str]] = []
        for url in urls:
            if self.source_policy.is_blocked(url):
                continue
            media_type = classify_media_url(url)
            out.append(
                {
                    "query": self.config.query,
                    "title": url,
                    "url": url,
                    "source_provider": "direct",
                    "source_kind": "direct_media" if media_type else "page",
                    "source_name": url,
                }
            )
        return out

    def _blind_rows(self) -> list[dict[str, str]]:
        queries = harvest_search_queries(self.config.query, self.config.max_search_queries)
        rows: list[dict[str, str]] = []
        client = self._make_client()
        try:
            for query in queries:
                try:
                    resp = _get_with_retry(client, f"https://duckduckgo.com/html/?q={quote_plus(query)}")
                    resp.raise_for_status()
                    rows.extend(self._parse_ddg(query, resp.text))
                except Exception as exc:
                    self._log_error("blind_search_error", query, exc)
        finally:
            client.close()
        return rows

    def _parse_ddg(self, query: str, text: str) -> list[dict[str, str]]:
        soup = _html_soup(text)
        rows: list[dict[str, str]] = []
        for anchor in soup.select("a.result__a")[: self.config.max_search_results_per_query]:
            url = clean_ddg_url(anchor.get("href") or "")
            if not url:
                continue
            rows.append({"query": query, "title": anchor.get_text(" ", strip=True), "url": url, "snippet": "", "source_provider": "blind", "source_kind": "search_result", "source_name": "DuckDuckGo"})
        return rows

    def _select_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        selected: list[dict[str, str]] = []
        blocked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            url = (row.get("url") or "").split("#", 1)[0]
            if not url.startswith(("http://", "https://")):
                continue
            reason = self.source_policy.block_reason(url)
            if reason:
                blocked.append({**row, "blocked_reason": reason})
                continue
            if url in seen:
                continue
            seen.add(url)
            base_row = {**row, "url": url, "original_query": row.get("query") or self.config.query}
            selected.append(base_row)
            max_pages = max(1, self.config.max_pages_per_source)
            for page_row in _pagination_rows(base_row, max_pages):
                page_url = (page_row.get("url") or "").split("#", 1)[0]
                if page_url and page_url not in seen and not self.source_policy.block_reason(page_url):
                    seen.add(page_url)
                    selected.append(page_row)
        self._blocked_source_rows = blocked
        write_jsonl(self.logs_dir / "harvest_blocked_source_rows.jsonl", blocked)
        return selected

    def _extract_from_row(self, row: dict[str, str], client: httpx.Client) -> list[HarvestedUrlRecord]:
        url = row.get("url") or ""
        if not url or self.source_policy.is_blocked(url):
            return []
        direct_media_type = classify_media_url(url, key_hint=row.get("source_kind") or "")
        records: list[HarvestedUrlRecord] = []
        if direct_media_type:
            records.append(record_from_url(url, direct_media_type, source_url=url, row=row, method="direct_media_url"))
        # Direct media URLs can still be playlist or endpoint pages in some source registries,
        # so only skip fetching when the source kind explicitly says direct_media.
        if row.get("source_kind") == "direct_media":
            return records
        try:
            resp = _get_with_retry(client, url)
            if resp.status_code >= 400:
                return records
            text = resp.text
            content_type = resp.headers.get("content-type", "")
            records.extend(self._extract_from_payload(url, row, text, content_type, method="source_payload"))
            if "html" in content_type.casefold() or "<html" in text[:1000].casefold():
                records.extend(self._extract_linked_endpoints(url, row, text, client))
                if self.config.enable_browser_capture:
                    records.extend(self._extract_from_browser(url, row))
        except Exception as exc:
            self._log_error("source_fetch_error", url, exc)
        return dedupe_records(records)

    def _extract_from_payload(self, source_url: str, row: dict[str, str], text: str, content_type: str = "", *, method: str = "payload") -> list[HarvestedUrlRecord]:
        records: list[HarvestedUrlRecord] = []
        # Reuse inventory extraction for structured metadata, but harvest output is normalized separately.
        records.extend(self._extract_with_inventory_helpers(source_url, row, text, content_type))
        json_data = parse_json_payload(text) if is_json_payload(source_url, content_type, text) else None
        if json_data is not None:
            structured_records = extract_structured_camera_records(
                json_data,
                endpoint_url=source_url,
                source_page_url=row.get("url") if row.get("url") != source_url else None,
                source_provider=row.get("source_provider"),
                source_name=row.get("source_name") or row.get("title"),
            )
            self._register_endpoint(
                source_url,
                content_type=content_type,
                source_page_url=row.get("url") if row.get("url") != source_url else None,
                row=row,
                method=method,
                record_count=count_json_records(json_data),
                camera_records=structured_records,
            )
            self._register_camera_records(structured_records)
            for camera_record in structured_records:
                self._emit("harvest_camera_record_found", camera_record_id=camera_record.camera_record_id, media_assets=len(camera_record.media_assets))
                for asset in camera_record.media_assets:
                    if self.source_policy.is_blocked(asset.url):
                        continue
                    self._emit("harvest_media_asset_found", asset_id=asset.asset_id, camera_record_id=asset.camera_record_id, media_type=asset.media_type)
                    records.append(record_from_media_asset(asset, camera_record, row=row))
            records.extend(self._extract_from_json_data(json_data, source_url, row, method=f"{method}_json"))
        records.extend(self._extract_from_text_variants(source_url, row, text, method=f"{method}_text"))
        if "html" in content_type.casefold() or "<html" in text[:1000].casefold():
            records.extend(self._extract_from_html_tags(source_url, row, text, method=f"{method}_html"))
            for blob in extract_json_blobs(text):
                records.extend(self._extract_from_json_data(blob, source_url, row, method=f"{method}_javascript_config"))
        return dedupe_records(records)

    def _extract_with_inventory_helpers(self, source_url: str, row: dict[str, str], text: str, content_type: str) -> list[HarvestedUrlRecord]:
        run_cfg = RunConfig(
            query=self.config.query,
            output_dir=self.config.output_dir,
            max_structured_endpoints_per_page=self.config.max_structured_endpoints_per_page,
            enable_browser_capture=False,
            browser_backend=self.config.browser_backend,
            http_timeout=self.config.http_timeout,
            user_agent=self.config.user_agent,
            sources_file=self.config.sources_file,
            block_patterns=self.config.block_patterns,
        )
        engine = CandidateDiscoveryEngine(run_cfg)
        try:
            candidates = engine._extract_from_response(source_url, row, text, content_type)
        except Exception as exc:
            self._log_error("inventory_helper_extract_error", source_url, exc)
            return []
        return [record_from_candidate(candidate, include_metadata=self.config.include_source_metadata) for candidate in candidates]

    def _extract_from_text_variants(self, source_url: str, row: dict[str, str], text: str, *, method: str) -> list[HarvestedUrlRecord]:
        records: list[HarvestedUrlRecord] = []
        seen_matches: set[str] = set()
        for variant_name, variant in text_variants(text):
            for candidate in URL_RE.findall(variant):
                cleaned = clean_extracted_url(candidate)
                media_type = classify_media_url(cleaned)
                if not media_type:
                    continue
                absolute = urljoin(source_url, cleaned)
                if absolute in seen_matches or self.source_policy.is_blocked(absolute):
                    continue
                if media_type == "image_snapshot" and _looks_like_non_camera_asset(absolute):
                    continue
                seen_matches.add(absolute)
                records.append(record_from_url(absolute, media_type, source_url=source_url, row=row, method=method, metadata={"text_variant": variant_name}))
            for match in QUOTED_MEDIA_RE.finditer(variant):
                cleaned = clean_extracted_url(match.group(1))
                absolute = urljoin(source_url, cleaned)
                media_type = classify_media_url(absolute)
                if not media_type or absolute in seen_matches or self.source_policy.is_blocked(absolute):
                    continue
                if media_type == "image_snapshot" and _looks_like_non_camera_asset(absolute):
                    continue
                seen_matches.add(absolute)
                records.append(record_from_url(absolute, media_type, source_url=source_url, row=row, method=method, metadata={"text_variant": variant_name}))
        return records

    def _extract_from_html_tags(self, source_url: str, row: dict[str, str], text: str, *, method: str) -> list[HarvestedUrlRecord]:
        soup = _html_soup(text)
        records: list[HarvestedUrlRecord] = []
        title = soup.find("title")
        page_title = title.get_text(" ", strip=True) if title else None
        for tag in soup.select("img, source, video, a[href], link[href]"):
            attrs = dict(getattr(tag, "attrs", {}) or {})
            tag_text = tag.get_text(" ", strip=True)[:300] if hasattr(tag, "get_text") else ""
            for attr in ("src", "href", "data-src", "data-original", "data-image", "data-url", "poster"):
                value = tag.get(attr) if hasattr(tag, "get") else None
                if not isinstance(value, str) or not value.strip():
                    continue
                absolute = urljoin(source_url, value.strip())
                media_type = classify_media_url(absolute, key_hint=attr)
                if not media_type or self.source_policy.is_blocked(absolute):
                    continue
                if media_type == "image_snapshot" and _looks_like_non_camera_asset(absolute):
                    continue
                metadata = simple_metadata(attrs)
                metadata["html_tag"] = getattr(tag, "name", "")
                if page_title:
                    metadata.setdefault("page_title", page_title)
                records.append(record_from_url(absolute, media_type, source_url=source_url, row=row, method=method, title=tag.get("title") or tag.get("alt") or tag_text or page_title, metadata=metadata))
            srcset = tag.get("srcset") if hasattr(tag, "get") else None
            if isinstance(srcset, str):
                for part in srcset.split(","):
                    candidate = part.strip().split(" ", 1)[0]
                    absolute = urljoin(source_url, candidate)
                    media_type = classify_media_url(absolute, key_hint="srcset")
                    if media_type and not self.source_policy.is_blocked(absolute):
                        records.append(record_from_url(absolute, media_type, source_url=source_url, row=row, method=method, title=tag.get("title") or tag.get("alt") or page_title, metadata={"html_tag": getattr(tag, "name", ""), "html_attr": "srcset"}))
        return dedupe_records(records)

    def _extract_from_json_data(self, data: Any, source_url: str, row: dict[str, str], *, method: str) -> list[HarvestedUrlRecord]:
        records: list[HarvestedUrlRecord] = []
        self._walk_json(data, source_url, row, method=method, path="$", records=records, context_metadata=None)
        return records

    def _walk_json(
        self,
        value: Any,
        source_url: str,
        row: dict[str, str],
        *,
        method: str,
        path: str,
        records: list[HarvestedUrlRecord],
        context_metadata: dict[str, Any] | None,
    ) -> None:
        if isinstance(value, dict):
            local_context = merge_metadata(context_metadata, json_context_metadata(value, source_url, path))
            for key, child in value.items():
                key_norm = normalize_key(key)
                if isinstance(child, str) and child.strip():
                    for decoded in text_value_variants(child.strip()):
                        absolute = urljoin(source_url, decoded)
                        media_type = classify_media_url(absolute, key_hint=key_norm)
                        if not media_type or self.source_policy.is_blocked(absolute):
                            continue
                        if media_type == "image_snapshot" and _looks_like_non_camera_asset(absolute):
                            continue
                        metadata = json_record_metadata(value, source_url, path, key_norm, context_metadata=local_context)
                        records.append(
                            record_from_url(
                                absolute,
                                media_type,
                                source_url=source_url,
                                row=row,
                                method=method,
                                title=metadata.get("title") or metadata.get("name"),
                                location_text=metadata.get("location_text") or metadata.get("location"),
                                camera_id=metadata.get("camera_id") or metadata.get("id"),
                                metadata=metadata,
                            )
                        )
                if isinstance(child, (dict, list)):
                    child_context = local_context
                    # GeoJSON/ArcGIS features often keep media URLs in properties/attributes
                    # and coordinates in sibling geometry. Carry that deterministic
                    # coordinate evidence into the child record metadata.
                    if key_norm in {"attributes", "properties"}:
                        child_context = merge_metadata(local_context, json_context_metadata(value, source_url, path))
                    self._walk_json(child, source_url, row, method=method, path=f"{path}.{key}", records=records, context_metadata=child_context)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                if isinstance(child, (dict, list)):
                    self._walk_json(child, source_url, row, method=method, path=f"{path}[{idx}]", records=records, context_metadata=context_metadata)

    def _extract_linked_endpoints(self, source_url: str, row: dict[str, str], text: str, client: httpx.Client) -> list[HarvestedUrlRecord]:
        hrefs: list[str] = []
        soup = _html_soup(text)
        for tag in soup.select("a[href], link[href], script[src]"):
            raw = tag.get("href") or tag.get("src") or ""
            absolute = urljoin(source_url, raw)
            if JSON_ENDPOINT_HINT_RE.search(absolute) and not self.source_policy.is_blocked(absolute):
                hrefs.append(absolute)
        for variant_name, variant in text_variants(text):
            for raw in re.findall(r"[\"']([^\"']*(?:\.json|/api/|/feed|/feeds|/layer|/layers|/query|MapServer|FeatureServer)[^\"']*)[\"']", variant, flags=re.I):
                absolute = urljoin(source_url, clean_extracted_url(raw))
                if absolute.startswith(("http://", "https://")) and not self.source_policy.is_blocked(absolute):
                    hrefs.append(absolute)
        records: list[HarvestedUrlRecord] = []
        endpoint_logs: list[dict[str, Any]] = []
        for endpoint in _dedupe_strings(_expand_structured_endpoint_urls(hrefs))[: self.config.max_structured_endpoints_per_page]:
            if self.source_policy.is_blocked(endpoint):
                continue
            try:
                resp = client.get(endpoint)
                if resp.status_code >= 400:
                    endpoint_logs.append({"page_url": source_url, "endpoint_url": endpoint, "status": resp.status_code, "records": 0})
                    continue
                before = len(records)
                records.extend(self._extract_from_payload(endpoint, row, resp.text, resp.headers.get("content-type", ""), method="linked_endpoint"))
                endpoint_logs.append({"page_url": source_url, "endpoint_url": endpoint, "status": resp.status_code, "records": len(records) - before})
            except Exception as exc:
                endpoint_logs.append({"page_url": source_url, "endpoint_url": endpoint, "error": repr(exc), "records": 0})
        if endpoint_logs:
            write_jsonl(self.logs_dir / "harvest_structured_endpoint_discovery.jsonl", endpoint_logs, append=True)
        return dedupe_records(records)

    def _extract_from_browser(self, source_url: str, row: dict[str, str]) -> list[HarvestedUrlRecord]:
        if not self._reserve_browser_page(source_url):
            return []
        start = time.monotonic()
        network_events: list[dict[str, Any]] = []
        captured_json: set[str] = set()
        captured_media: dict[str, str] = {}
        rendered_html = ""
        try:
            with self._browser_capture_session() as browser:
                page = browser.new_page(user_agent=self.config.user_agent)

                def collect(candidate_url: str, content_type: str = "", event_type: str = "network") -> None:
                    if not candidate_url or self.source_policy.is_blocked(candidate_url):
                        return
                    lowered_type = content_type.casefold()
                    media_type = classify_media_url(candidate_url, content_type=lowered_type)
                    if media_type:
                        captured_media[candidate_url] = media_type
                    if JSON_ENDPOINT_HINT_RE.search(candidate_url):
                        captured_json.add(candidate_url)
                    if len(network_events) < self.config.max_browser_network_events_logged_per_page:
                        network_events.append({"event": event_type, "url": candidate_url, "content_type": content_type[:120]})

                page.on("request", lambda request: collect(request.url, str(request.headers.get("content-type", "")), "request"))
                page.on("response", lambda response: collect(response.url, str(response.headers.get("content-type", "")), "response"))
                page.goto(source_url, wait_until="networkidle", timeout=self.config.browser_capture_timeout_ms)
                if self.config.browser_capture_settle_ms:
                    page.wait_for_timeout(self.config.browser_capture_settle_ms)
                if self.config.browser_capture_scroll:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    if self.config.browser_capture_settle_ms:
                        page.wait_for_timeout(min(self.config.browser_capture_settle_ms, 1500))
                rendered_html = page.content()
        except Exception as exc:
            with self._lock:
                self._browser_summary["errors"] += 1
                if "timeout" in exc.__class__.__name__.casefold():
                    self._browser_summary["timeouts"] += 1
            self._log_error("browser_capture_error", source_url, exc)
            return []

        records = [record_from_url(url, media_type, source_url=source_url, row=row, method="browser_network_capture", metadata={"browser_backend": self.config.browser_backend}) for url, media_type in captured_media.items()]
        if rendered_html:
            records.extend(self._extract_from_payload(source_url, row, rendered_html, "text/html", method="browser_rendered_html"))
        if captured_json:
            client = self._make_client()
            try:
                for endpoint in sorted(captured_json)[: self.config.max_browser_json_endpoints_per_page]:
                    try:
                        resp = client.get(endpoint)
                        if resp.status_code < 400:
                            records.extend(self._extract_from_payload(endpoint, row, resp.text, resp.headers.get("content-type", ""), method="browser_json_endpoint"))
                    except Exception as exc:
                        self._log_error("browser_json_endpoint_error", endpoint, exc)
            finally:
                client.close()
        with self._lock:
            self._browser_summary["pages_attempted"] += 1
            self._browser_summary["media_records"] += len(records)
            self._browser_summary["json_endpoints"] += len(captured_json)
            self._browser_summary["network_events_sample"].extend(network_events[: max(0, 100 - len(self._browser_summary["network_events_sample"]))])
        write_json(self.logs_dir / "browser_capture_summary.json", self._browser_summary)
        self._emit("harvest_browser_capture_page_complete", source_url=source_url, records=len(records), elapsed_ms=int((time.monotonic() - start) * 1000))
        return dedupe_records(records)

    def _reserve_browser_page(self, source_url: str) -> bool:
        host = urlparse(source_url).netloc.casefold()
        with self._lock:
            if self.config.max_browser_pages and self._browser_pages_attempted >= self.config.max_browser_pages:
                return False
            if self.config.max_browser_pages_per_host and self._browser_host_counts.get(host, 0) >= self.config.max_browser_pages_per_host:
                return False
            self._browser_pages_attempted += 1
            self._browser_host_counts[host] = self._browser_host_counts.get(host, 0) + 1
            return True

    def _browser_capture_session(self):
        backend = self.config.browser_backend
        if backend == "cloakbrowser":
            from cloakbrowser import launch  # type: ignore[import-not-found]

            class CloakContext:
                def __enter__(self_inner):
                    self_inner.browser = launch(headless=True)
                    return self_inner.browser

                def __exit__(self_inner, exc_type, exc, tb):
                    try:
                        self_inner.browser.close()
                    except Exception:
                        pass

            return CloakContext()
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        class PlaywrightContext:
            def __enter__(self_inner):
                self_inner.playwright = sync_playwright().start()
                self_inner.browser = self_inner.playwright.chromium.launch(headless=True)
                return self_inner.browser

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    self_inner.browser.close()
                finally:
                    self_inner.playwright.stop()

        return PlaywrightContext()


    def _register_camera_records(self, records: list[HarvestedCameraRecord]) -> None:
        if not records:
            return
        with self._lock:
            for record in records:
                existing = self._camera_records.setdefault(record.camera_record_id, record)
                for asset in record.media_assets:
                    if not self.source_policy.is_blocked(asset.url):
                        self._media_assets.setdefault(asset.asset_id, asset)
                if existing is not record:
                    for asset in record.media_assets:
                        if not self.source_policy.is_blocked(asset.url):
                            self._media_assets.setdefault(asset.asset_id, asset)

    def _register_endpoint(
        self,
        endpoint_url: str,
        *,
        content_type: str = "",
        source_page_url: str | None,
        row: dict[str, str],
        method: str,
        record_count: int = 0,
        camera_records: list[HarvestedCameraRecord] | None = None,
        status: int | None = None,
        error: str | None = None,
    ) -> None:
        if not endpoint_url or self.source_policy.is_blocked(endpoint_url):
            return
        camera_records = camera_records or []
        endpoint = DiscoveredEndpointRecord(
            endpoint_url=endpoint_url,
            endpoint_type=endpoint_type_for_url(endpoint_url, content_type),
            source_page_url=source_page_url,
            source_provider=row.get("source_provider"),
            source_name=row.get("source_name") or row.get("title"),
            first_seen_method=method,
            record_count=record_count,
            camera_record_count=len(camera_records),
            media_asset_count=sum(len(record.media_assets) for record in camera_records),
            has_coordinates=any(record.lat is not None and record.lon is not None for record in camera_records),
            has_timestamps=any(record.timestamp or record.date or record.time or record.last_updated or record.last_refresh for record in camera_records),
            has_service_status=any(record.in_service is not None or record.status for record in camera_records),
            has_refresh_metadata=any(record.current_image_update_frequency is not None or record.reference_image_update_frequency is not None for record in camera_records),
            metadata={k: v for k, v in {"status": status, "error": error, "content_type": content_type}.items() if v not in (None, "")},
        )
        with self._lock:
            existing = self._discovered_endpoints.get(endpoint_url)
            if existing is None:
                self._discovered_endpoints[endpoint_url] = endpoint
            else:
                existing.record_count = max(existing.record_count, endpoint.record_count)
                existing.camera_record_count = max(existing.camera_record_count, endpoint.camera_record_count)
                existing.media_asset_count = max(existing.media_asset_count, endpoint.media_asset_count)
                existing.has_coordinates = existing.has_coordinates or endpoint.has_coordinates
                existing.has_timestamps = existing.has_timestamps or endpoint.has_timestamps
                existing.has_service_status = existing.has_service_status or endpoint.has_service_status
                existing.has_refresh_metadata = existing.has_refresh_metadata or endpoint.has_refresh_metadata
                existing.metadata.update(endpoint.metadata)
        self._emit("harvest_endpoint_discovered", endpoint_url=endpoint_url, endpoint_type=endpoint.endpoint_type)
        if camera_records or status is not None or error:
            self._emit("harvest_endpoint_parsed", endpoint_url=endpoint_url, camera_records=len(camera_records), media_assets=endpoint.media_asset_count, status=status)

    def _record_block_reason(self, record: HarvestedUrlRecord) -> str | None:
        return self.source_policy.block_reason(record.url) or self.source_policy.block_reason(record.source_url)

    def _log_error(self, stage: str, subject: str | None, exc: Exception) -> None:
        record = {"stage": stage, "subject": subject, "error": repr(exc)}
        with self._lock:
            self._errors.append(record)
        write_jsonl(self.logs_dir / "harvest_errors.jsonl", [record], append=True)

    def _write_outputs(
        self,
        records: list[HarvestedUrlRecord],
        *,
        raw_records: int,
        unique: list[HarvestedUrlRecord],
        pre_filter_unique: int,
        media_filtered: int,
        blocked_or_filtered: int,
    ) -> dict[str, str]:
        outputs: dict[str, str] = {}
        write_plain_urls(self.output_dir / "camera_urls.txt", records)
        outputs["camera_urls_txt"] = str(self.output_dir / "camera_urls.txt")
        write_csv(self.output_dir / "camera_urls.csv", records)
        outputs["camera_urls_csv"] = str(self.output_dir / "camera_urls.csv")
        url_dicts = [record_to_dict(record) for record in records]
        write_jsonl(self.output_dir / "camera_urls.jsonl", url_dicts)
        outputs["camera_urls_jsonl"] = str(self.output_dir / "camera_urls.jsonl")
        for media_type in SUPPORTED_MEDIA_TYPES:
            typed = [record for record in records if record.media_type == media_type]
            path = self.output_dir / f"{media_type}_urls.txt"
            write_plain_urls(path, typed)
            outputs[f"{media_type}_urls_txt"] = str(path)

        camera_records = list(self._camera_records.values())
        media_assets = [asset for asset in self._media_assets.values() if not self.source_policy.is_blocked(asset.url)]
        endpoints = [endpoint for endpoint in self._discovered_endpoints.values() if not self.source_policy.is_blocked(endpoint.endpoint_url)]

        camera_record_dicts = [asdict(record) for record in camera_records]
        media_asset_dicts = [asdict(asset) for asset in media_assets]
        endpoint_dicts = [asdict(endpoint) for endpoint in endpoints]
        write_jsonl(self.output_dir / "camera_records.jsonl", camera_record_dicts)
        outputs["camera_records_jsonl"] = str(self.output_dir / "camera_records.jsonl")
        write_jsonl(self.output_dir / "camera_media_assets.jsonl", media_asset_dicts)
        outputs["camera_media_assets_jsonl"] = str(self.output_dir / "camera_media_assets.jsonl")
        write_jsonl(self.output_dir / "discovered_endpoints.jsonl", endpoint_dicts)
        outputs["discovered_endpoints_jsonl"] = str(self.output_dir / "discovered_endpoints.jsonl")

        structured_camera_ids = {record.camera_record_id for record in camera_records}
        inventory_rows = [camera_record_to_inventory(record) for record in camera_records]
        for record in records:
            if record.camera_record_id and record.camera_record_id in structured_camera_ids:
                continue
            inventory_rows.append(url_record_to_inventory(record_to_dict(record)))
        write_jsonl(self.output_dir / "harvest_camera_inventory.jsonl", inventory_rows)
        outputs["harvest_camera_inventory_jsonl"] = str(self.output_dir / "harvest_camera_inventory.jsonl")

        handoff = {
            "schema_version": "harvest-handoff/v1",
            "query": self.config.query,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "mode": "harvest",
            "source_provided_only": True,
            "validated": False,
            "geocoded": False,
            "scope_filtered": False,
            "trusted": False,
            "llm_reviewed": False,
            "files": {
                "harvest_camera_inventory": "harvest_camera_inventory.jsonl",
                "camera_records": "camera_records.jsonl",
                "camera_media_assets": "camera_media_assets.jsonl",
                "camera_urls_jsonl": "camera_urls.jsonl",
                "discovered_endpoints": "discovered_endpoints.jsonl",
            },
            "counts": {
                "camera_records": len(camera_records),
                "media_assets": len(media_assets),
                "url_records": len(records),
                "endpoints": len(endpoints),
                "records_with_coordinates": sum(1 for record in camera_records if record.lat is not None and record.lon is not None),
                "records_with_in_service": sum(1 for record in camera_records if record.in_service is not None),
                "records_with_timestamps": sum(1 for record in camera_records if record.timestamp or record.date or record.time or record.last_updated or record.last_refresh),
                "records_with_update_frequency": sum(1 for record in camera_records if record.current_image_update_frequency is not None or record.reference_image_update_frequency is not None),
            },
            "source_rows": self._source_rows_summary,
            "warnings": self._warnings,
        }
        write_json(self.output_dir / "harvest_handoff.json", handoff)
        write_json(self.logs_dir / "handoff_summary.json", handoff)
        outputs["harvest_handoff_json"] = str(self.output_dir / "harvest_handoff.json")
        self._emit("harvest_handoff_written", outputs=outputs, camera_records=len(camera_records), media_assets=len(media_assets))

        summary = {
            "query": self.config.query,
            "discovery_mode": self.config.discovery_mode.value,
            "raw_records": raw_records,
            "unique_urls": len(unique),
            "written_urls": len(records),
            "max_urls": self.config.max_urls,
            "unlimited": self.config.max_urls == 0,
            "media_filter": self.media_filter.requested,
            "pre_filter_unique_urls": pre_filter_unique,
            "media_filtered_urls": media_filtered,
            "by_media_type": dict(Counter(record.media_type for record in records)),
            "by_source_provider": dict(Counter(record.source_provider or "unknown" for record in records)),
            "by_source_host": dict(Counter(urlparse(record.source_url or record.url).netloc.casefold() or "unknown" for record in records)),
            "structured_camera_records": len(camera_records),
            "media_assets": len(media_assets),
            "url_only_records": sum(1 for record in records if not record.camera_record_id),
            "endpoints_discovered": len(endpoints),
            "endpoints_parsed": sum(1 for endpoint in endpoints if endpoint.camera_record_count or endpoint.media_asset_count),
            "records_with_coordinates": sum(1 for record in records if record.lat is not None and record.lon is not None),
            "records_with_orientation": sum(1 for record in records if record.direction or record.bearing is not None or record.heading is not None or record.orientation),
            "records_with_datetime": sum(1 for record in records if record.date or record.time or record.timestamp or record.last_updated or record.last_refresh),
            "records_with_in_service": sum(1 for record in records if record.in_service is not None),
            "records_in_service_true": sum(1 for record in records if record.in_service is True),
            "records_in_service_false": sum(1 for record in records if record.in_service is False),
            "records_with_update_frequency": sum(1 for record in records if record.current_image_update_frequency is not None or record.reference_image_update_frequency is not None),
            "records_with_streaming_video": sum(1 for record in records if record.asset_role in {"streaming_video", "hls_stream", "mjpeg_stream"}),
            "records_with_current_image": sum(1 for record in records if record.asset_role == "current_image_snapshot"),
            "records_with_reference_image": sum(1 for record in records if record.asset_role == "reference_image_snapshot"),
            "records_missing_media_url": sum(1 for record in camera_records if not record.media_assets),
            "blocked_or_filtered_urls": blocked_or_filtered,
            "source_rows": self._source_rows_summary,
            "source_rows_total": self._source_rows_summary.get("selected_rows", 0),
            "source_rows_by_provider": self._source_rows_summary.get("selected_by_provider", {}),
            "source_rows_by_kind": self._source_rows_summary.get("selected_by_kind", {}),
            "sources_file": self._source_rows_summary.get("sources_file"),
            "sources_file_exists": self._source_rows_summary.get("sources_file_exists", False),
            "sources_file_used": self._source_rows_summary.get("sources_file_used", False),
            "directory_sources_configured": self._source_rows_summary.get("directory_sources_configured", 0),
            "directory_sources_enabled": self._source_rows_summary.get("directory_sources_enabled", 0),
            "directory_source_rows_selected": self._source_rows_summary.get("selected_by_provider", {}).get("directory", 0),
            "blind_source_rows_selected": self._source_rows_summary.get("selected_by_provider", {}).get("blind", 0),
            "direct_source_rows_selected": self._source_rows_summary.get("selected_by_provider", {}).get("direct", 0),
            "outputs": outputs,
            "warnings": self._warnings,
            "browser_capture": self._browser_summary,
        }
        write_json(self.output_dir / "harvest_summary.json", summary)
        write_json(self.logs_dir / "harvest_summary.json", summary)
        write_json(self.logs_dir / "browser_capture_summary.json", self._browser_summary)
        write_json(self.logs_dir / "endpoint_catalog_summary.json", {"endpoints": len(endpoints), "records": endpoint_dicts})
        outputs["harvest_summary_json"] = str(self.output_dir / "harvest_summary.json")
        return outputs


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
        "max_source_rows": config.max_source_rows,
        "max_source_rows_applied": max_source_rows_applied,
    }
    return summary


def count_rows_by_key(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row.get(key) or "unknown") for row in rows)
    return dict(sorted(counts.items()))


def parse_media_filter(values: Iterable[str] | None) -> MediaFilter:
    tokens: list[str] = []
    for value in values or []:
        for part in str(value).split(","):
            cleaned = part.strip().casefold()
            if cleaned:
                tokens.append(cleaned)
    if not tokens or any(token in {"all", "*"} for token in tokens):
        return MediaFilter(requested=tokens or ["all"], categories=set(SUPPORTED_MEDIA_TYPES), extensions=set(SUPPORTED_EXTENSIONS), all_media=True)
    categories: set[str] = set()
    extensions: set[str] = set()
    invalid: list[str] = []
    for token in tokens:
        normalized = normalize_media_token(token)
        if normalized.startswith("."):
            if normalized not in SUPPORTED_EXTENSIONS:
                invalid.append(token)
            else:
                extensions.add(normalized)
            continue
        if normalized not in SUPPORTED_MEDIA_TYPES:
            invalid.append(token)
        else:
            categories.add(normalized)
            extensions.update(CATEGORY_EXTENSIONS.get(normalized, set()))
    if invalid:
        examples = ".m3u8, .m3u8,mp4, hls, image,stream, video_file"
        allowed = ", ".join(sorted(SUPPORTED_MEDIA_CATEGORIES | {ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS} | SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported --media value(s): {', '.join(invalid)}. Supported values include: {allowed}. Examples: {examples}")
    return MediaFilter(requested=tokens, categories=categories, extensions=extensions, all_media=False)


def normalize_media_token(token: str) -> str:
    token = token.strip().casefold()
    if not token:
        return "all"
    if token in {"all", "*"}:
        return "all"
    if token.startswith("."):
        return token
    if token in {"jpg", "jpeg", "png", "webp", "m3u8", "mjpg", "mjpeg", "mp4", "webm", "mov", "m4v"}:
        return "." + token
    if token == "image":
        return "image_snapshot"
    if token == "snapshot":
        return "image_snapshot"
    if token == "video":
        return "video_file"
    if token == "unknown":
        return "unknown_media"
    return token


def classify_media_url(url: str, *, key_hint: str = "", content_type: str = "") -> str | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    lowered = url.casefold()
    path = urlparse(url).path.casefold()
    ctype = content_type.casefold()
    if path.endswith(".m3u8") or ".m3u8" in lowered or "mpegurl" in ctype:
        return "hls"
    if path.endswith((".mjpg", ".mjpeg")) or "multipart/x-mixed-replace" in ctype:
        return "mjpeg"
    if path.endswith((".mp4", ".webm", ".mov", ".m4v")):
        return "video_file"
    if path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "image_snapshot"
    if any(token in key_hint.casefold() for token in ("stream", "video", "media", "mjpeg")) and url.startswith(("http://", "https://")):
        return "stream"
    if any(token in lowered for token in ("/stream", "stream=", "/video", "video=", "/media", "media=")) and not MEDIA_EXTENSION_RE.search(url):
        return "stream"
    return None


def media_extension(url: str) -> str | None:
    path = urlparse(url).path.casefold()
    for ext in sorted(SUPPORTED_EXTENSIONS, key=len, reverse=True):
        if path.endswith(ext):
            return ext
    return None


def canonical_media_url(url: str) -> str:
    split = urlsplit(url.strip())
    scheme = split.scheme.casefold()
    netloc = split.netloc.casefold()
    return urlunsplit((scheme, netloc, split.path, split.query, ""))


def dedupe_records(records: list[HarvestedUrlRecord]) -> list[HarvestedUrlRecord]:
    by_key: dict[str, HarvestedUrlRecord] = {}
    order: list[str] = []
    for record in records:
        key = canonical_media_url(record.url)
        existing = by_key.get(key)
        if existing is None:
            record.url = key
            by_key[key] = record
            order.append(key)
            continue
        merge_record(existing, record)
    return [by_key[key] for key in order]


def merge_record(existing: HarvestedUrlRecord, duplicate: HarvestedUrlRecord) -> None:
    if not existing.title and duplicate.title:
        existing.title = duplicate.title
    if not existing.location_text and duplicate.location_text:
        existing.location_text = duplicate.location_text
    if not existing.camera_id and duplicate.camera_id:
        existing.camera_id = duplicate.camera_id
    if not existing.source_url and duplicate.source_url:
        existing.source_url = duplicate.source_url
    if not existing.source_name and duplicate.source_name:
        existing.source_name = duplicate.source_name
    if not existing.source_provider and duplicate.source_provider:
        existing.source_provider = duplicate.source_provider
    if existing.media_type == "unknown_media" and duplicate.media_type != "unknown_media":
        existing.media_type = duplicate.media_type
    for attr in ("camera_record_id", "asset_id", "asset_role", "asset_field", "field_path", "source_endpoint_url", "source_page_url", "json_record_path", "lat", "lon", "coordinate_source", "direction", "bearing", "heading", "orientation", "in_service", "status", "date", "time", "timestamp", "last_updated", "last_refresh", "image_description", "current_image_update_frequency", "reference_image_update_frequency"):
        if getattr(existing, attr) in (None, "") and getattr(duplicate, attr) not in (None, ""):
            setattr(existing, attr, getattr(duplicate, attr))
    for key, value in duplicate.metadata.items():
        if value in (None, "", [], {}):
            continue
        existing.metadata.setdefault(key, value)
    duplicate_sources = existing.metadata.setdefault("duplicate_sources", [])
    if duplicate.source_url and duplicate.source_url not in duplicate_sources and duplicate.source_url != existing.source_url:
        duplicate_sources.append(duplicate.source_url)


def record_from_candidate(candidate: CameraCandidate, *, include_metadata: bool = True) -> HarvestedUrlRecord:
    metadata = dict(candidate.source_metadata or {}) if include_metadata else {}
    if candidate.lat is not None:
        metadata.setdefault("lat", candidate.lat)
    if candidate.lon is not None:
        metadata.setdefault("lon", candidate.lon)
    if candidate.coordinate_source:
        metadata.setdefault("coordinate_source", candidate.coordinate_source)
    promoted = promoted_metadata_fields(metadata)
    media_type = normalize_candidate_media_type(metadata.get("media_type"), candidate.stream_url)
    return HarvestedUrlRecord(
        url=candidate.stream_url,
        media_type=media_type,
        source_url=candidate.source_url,
        discovery_method=candidate.discovery_method,
        title=candidate.title or metadata.get("camera_name"),
        location_text=candidate.location_text or metadata.get("location_display") or metadata.get("location_text"),
        camera_id=str(metadata.get("camera_id")) if metadata.get("camera_id") not in (None, "") else None,
        source_name=metadata.get("source_name"),
        source_provider=metadata.get("source_provider"),
        camera_record_id=metadata.get("camera_record_id"),
        asset_id=metadata.get("asset_id"),
        asset_role=metadata.get("asset_role"),
        asset_field=metadata.get("asset_field"),
        field_path=metadata.get("field_path"),
        source_endpoint_url=metadata.get("source_endpoint_url") or metadata.get("json_endpoint_url"),
        source_page_url=metadata.get("source_page_url"),
        json_record_path=metadata.get("json_record_path"),
        in_service=coerce_bool(metadata.get("in_service") if "in_service" in metadata else metadata.get("inService")),
        status=str(metadata.get("status")) if metadata.get("status") not in (None, "") else None,
        last_updated=str(metadata.get("last_updated") or metadata.get("lastUpdated")) if (metadata.get("last_updated") or metadata.get("lastUpdated")) not in (None, "") else None,
        last_refresh=str(metadata.get("last_refresh") or metadata.get("lastRefresh")) if (metadata.get("last_refresh") or metadata.get("lastRefresh")) not in (None, "") else None,
        image_description=str(metadata.get("imageDescription") or metadata.get("image_description")) if (metadata.get("imageDescription") or metadata.get("image_description")) not in (None, "") else None,
        current_image_update_frequency=metadata.get("currentImageUpdateFrequency") or metadata.get("current_image_update_frequency"),
        reference_image_update_frequency=metadata.get("referenceImageUpdateFrequency") or metadata.get("reference_image_update_frequency"),
        lat=promoted.get("lat"),
        lon=promoted.get("lon"),
        coordinate_source=promoted.get("coordinate_source"),
        direction=promoted.get("direction"),
        bearing=promoted.get("bearing"),
        heading=promoted.get("heading"),
        date=promoted.get("date"),
        time=promoted.get("time"),
        timestamp=promoted.get("timestamp"),
        metadata=metadata,
    )


def normalize_candidate_media_type(value: Any, url: str) -> str:
    text = str(value or "").strip().casefold()
    if text in {"hls", "mjpeg", "image_snapshot", "video_file", "stream", "unknown_media"}:
        return text
    if text == "other":
        return "stream"
    return classify_media_url(url) or "unknown_media"



def record_from_media_asset(asset: HarvestedMediaAsset, camera_record: HarvestedCameraRecord, *, row: dict[str, str]) -> HarvestedUrlRecord:
    metadata = dict(camera_record.metadata or {})
    metadata.update(asset.metadata or {})
    metadata.setdefault("source_provided_only", True)
    metadata.setdefault("validated", False)
    metadata.setdefault("trusted", False)
    metadata.setdefault("llm_reviewed", False)
    metadata.setdefault("camera_record_id", camera_record.camera_record_id)
    metadata.setdefault("asset_id", asset.asset_id)
    metadata.setdefault("asset_role", asset.asset_role)
    metadata.setdefault("asset_field", asset.asset_field)
    metadata.setdefault("field_path", asset.field_path)
    metadata.setdefault("source_endpoint_url", asset.source_endpoint_url)
    metadata.setdefault("json_record_path", asset.json_record_path)
    return HarvestedUrlRecord(
        url=asset.url,
        media_type=asset.media_type,
        source_url=asset.source_url or asset.source_endpoint_url or asset.source_page_url,
        discovery_method=asset.discovery_method,
        title=camera_record.title,
        description=camera_record.description,
        location_text=camera_record.location_text,
        camera_id=camera_record.camera_id,
        source_name=asset.source_name or camera_record.source_name or row.get("source_name") or row.get("title"),
        source_provider=asset.source_provider or camera_record.source_provider or row.get("source_provider"),
        camera_record_id=camera_record.camera_record_id,
        asset_id=asset.asset_id,
        asset_role=asset.asset_role,
        asset_field=asset.asset_field,
        field_path=asset.field_path,
        source_endpoint_url=asset.source_endpoint_url,
        source_page_url=asset.source_page_url,
        json_record_path=asset.json_record_path,
        lat=camera_record.lat,
        lon=camera_record.lon,
        coordinate_source=camera_record.coordinate_source,
        direction=camera_record.direction,
        bearing=camera_record.bearing,
        heading=camera_record.heading,
        orientation=camera_record.orientation,
        in_service=camera_record.in_service,
        status=camera_record.status,
        date=camera_record.date,
        time=camera_record.time,
        timestamp=camera_record.timestamp,
        last_updated=camera_record.last_updated,
        last_refresh=camera_record.last_refresh,
        image_description=camera_record.image_description,
        current_image_update_frequency=camera_record.current_image_update_frequency,
        reference_image_update_frequency=camera_record.reference_image_update_frequency,
        metadata={k: v for k, v in metadata.items() if v not in (None, "", [], {})},
    )

def record_from_url(
    url: str,
    media_type: str,
    *,
    source_url: str | None,
    row: dict[str, str],
    method: str,
    title: str | None = None,
    location_text: str | None = None,
    camera_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> HarvestedUrlRecord:
    metadata = dict(metadata or {})
    metadata.setdefault("source_row_url", row.get("url"))
    metadata.setdefault("original_query", row.get("original_query") or row.get("query"))
    metadata.setdefault("source_kind", row.get("source_kind"))
    metadata.setdefault("media_extension", media_extension(url))
    cleaned_metadata = {k: v for k, v in metadata.items() if v not in (None, "", [], {})}
    promoted = promoted_metadata_fields(cleaned_metadata)
    return HarvestedUrlRecord(
        url=url,
        media_type=media_type,
        source_url=source_url,
        discovery_method=method,
        title=title or row.get("title") or row.get("source_name"),
        location_text=location_text,
        camera_id=camera_id,
        source_name=row.get("source_name") or row.get("title"),
        source_provider=row.get("source_provider"),
        camera_record_id=cleaned_metadata.get("camera_record_id"),
        asset_id=cleaned_metadata.get("asset_id"),
        asset_role=cleaned_metadata.get("asset_role"),
        asset_field=cleaned_metadata.get("asset_field") or cleaned_metadata.get("json_media_key"),
        field_path=cleaned_metadata.get("field_path"),
        source_endpoint_url=cleaned_metadata.get("source_endpoint_url") or cleaned_metadata.get("json_endpoint_url"),
        source_page_url=cleaned_metadata.get("source_page_url"),
        json_record_path=cleaned_metadata.get("json_record_path"),
        in_service=coerce_bool(cleaned_metadata.get("in_service") if "in_service" in cleaned_metadata else cleaned_metadata.get("inService")),
        status=str(cleaned_metadata.get("status")) if cleaned_metadata.get("status") not in (None, "") else None,
        orientation=str(cleaned_metadata.get("orientation")) if cleaned_metadata.get("orientation") not in (None, "") else None,
        last_updated=str(cleaned_metadata.get("last_updated") or cleaned_metadata.get("lastUpdated")) if (cleaned_metadata.get("last_updated") or cleaned_metadata.get("lastUpdated")) not in (None, "") else None,
        last_refresh=str(cleaned_metadata.get("last_refresh") or cleaned_metadata.get("lastRefresh")) if (cleaned_metadata.get("last_refresh") or cleaned_metadata.get("lastRefresh")) not in (None, "") else None,
        image_description=str(cleaned_metadata.get("imageDescription") or cleaned_metadata.get("image_description")) if (cleaned_metadata.get("imageDescription") or cleaned_metadata.get("image_description")) not in (None, "") else None,
        current_image_update_frequency=cleaned_metadata.get("currentImageUpdateFrequency") or cleaned_metadata.get("current_image_update_frequency"),
        reference_image_update_frequency=cleaned_metadata.get("referenceImageUpdateFrequency") or cleaned_metadata.get("reference_image_update_frequency"),
        lat=promoted.get("lat"),
        lon=promoted.get("lon"),
        coordinate_source=promoted.get("coordinate_source"),
        direction=promoted.get("direction"),
        bearing=promoted.get("bearing"),
        heading=promoted.get("heading"),
        date=promoted.get("date"),
        time=promoted.get("time"),
        timestamp=promoted.get("timestamp"),
        metadata=cleaned_metadata,
    )


def row_from_source_entry(entry: SourceEntry, query: str, *, provider: str) -> dict[str, str]:
    return {
        "query": query,
        "title": entry.name,
        "url": entry.url,
        "snippet": entry.notes or "",
        "source_provider": provider,
        "source_kind": entry.source_type,
        "source_name": entry.name,
        "source_scope_hint": entry.scope_hint or "",
        "source_notes": entry.notes or "",
    }


def harvest_search_queries(query: str, max_queries: int) -> list[str]:
    candidates = [
        query,
        f"{query} public cameras",
        f"{query} live cameras",
        f"{query} webcams",
        f"{query} camera map",
        f"{query} camera feed json",
        f"{query} public camera API json",
        f"{query} camera MapServer FeatureServer",
        f"{query} m3u8",
        f"{query} snapshot camera",
    ]
    return _dedupe_strings(candidates)[:max_queries] if max_queries else []


def clean_ddg_url(href: str) -> str:
    if not href:
        return ""
    if "duckduckgo.com/l/" in href or href.startswith("//duckduckgo.com/l/"):
        parsed = urlparse(href if href.startswith("http") else "https:" + href)
        return unquote(parse_qs(parsed.query).get("uddg", [""])[0])
    return href


def clean_extracted_url(value: str) -> str:
    return value.strip().strip("'\"),;]")


def text_value_variants(value: str) -> list[str]:
    variants = []
    for candidate in (value, html.unescape(value), value.replace(r"\/", "/"), value.replace(r"\u002F", "/").replace(r"\u002f", "/")):
        if candidate not in variants:
            variants.append(candidate)
    decoded = value
    for _ in range(2):
        next_value = unquote(decoded)
        if next_value == decoded or len(next_value) > max(200000, len(value) * 20):
            break
        if next_value not in variants:
            variants.append(next_value)
        decoded = next_value
    return variants


def text_variants(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, value in (
        ("raw", text),
        ("html_unescaped", html.unescape(text)),
        ("json_slash_unescaped", text.replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/")),
    ):
        if value and all(value != existing for _, existing in out):
            out.append((name, value))
    decoded = text
    for idx in range(2):
        next_value = unquote(decoded)
        if next_value == decoded or len(next_value) > max(2_000_000, len(text) * 20):
            break
        if all(next_value != existing for _, existing in out):
            out.append(("url_decoded" if idx == 0 else "double_url_decoded", next_value))
        decoded = next_value
    return out


def is_json_payload(source_url: str, content_type: str, text: str) -> bool:
    lowered = content_type.casefold()
    stripped = (text or "").lstrip()
    return "json" in lowered or source_url.casefold().split("?", 1)[0].endswith(".json") or stripped.startswith(("{", "["))


def parse_json_payload(text: str) -> Any | None:
    for variant in text_value_variants(text):
        try:
            return json.loads(variant)
        except Exception:
            continue
    return None


def extract_json_blobs(text: str) -> list[Any]:
    blobs: list[Any] = []
    decoder = json.JSONDecoder()
    for _variant_name, variant in text_variants(text):
        for match in re.finditer(r"[\[{]", variant):
            start = match.start()
            window = variant[max(0, start - 100): start].casefold()
            if window and not any(hint in window for hint in ("camera", "cameras", "features", "layers", "markers", "data", "feed", "stream", "video")):
                continue
            try:
                obj, end = decoder.raw_decode(variant[start:])
            except json.JSONDecodeError:
                continue
            if end > 10:
                blobs.append(obj)
            if len(blobs) >= 25:
                return blobs
    return blobs


def normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key).casefold())


def merge_metadata(*parts: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        if not part:
            continue
        for key, value in part.items():
            if value in (None, "", [], {}):
                continue
            merged.setdefault(key, value)
    return merged


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().strip("°")
        if not cleaned:
            return None
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None



def coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "active", "enabled", "online", "inservice", "in service"}:
        return True
    if text in {"0", "false", "no", "n", "inactive", "disabled", "offline", "outofservice", "out of service"}:
        return False
    return None


def count_json_records(value: Any) -> int:
    if isinstance(value, list):
        return len(value) + sum(count_json_records(item) for item in value if isinstance(item, (dict, list)))
    if isinstance(value, dict):
        return 1 + sum(count_json_records(item) for item in value.values() if isinstance(item, (dict, list)))
    return 0

def plausible_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def value_by_normalized_key(metadata: dict[str, Any], keys: set[str]) -> tuple[str | None, Any]:
    for key, value in metadata.items():
        if normalize_key(key) in keys and value not in (None, "", [], {}):
            return str(key), value
    return None, None


def coordinates_from_sequence(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None, None
    first = value[0]
    # GeoJSON polygons/lines may be nested. Follow the first coordinate pair.
    while isinstance(first, (list, tuple)) and first:
        value = first
        first = value[0]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None, None
    a = coerce_float(value[0])
    b = coerce_float(value[1])
    # GeoJSON order is lon, lat. Fall back to lat, lon only when that is the
    # only plausible interpretation.
    if plausible_lat_lon(b, a):
        return b, a
    if plausible_lat_lon(a, b):
        return a, b
    return None, None


def coordinates_from_geometry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    x_key, x_value = value_by_normalized_key(value, X_LONGITUDE_KEYS | LONGITUDE_KEYS)
    y_key, y_value = value_by_normalized_key(value, Y_LATITUDE_KEYS | LATITUDE_KEYS)
    lat = coerce_float(y_value)
    lon = coerce_float(x_value)
    if plausible_lat_lon(lat, lon):
        out["lat"] = lat
        out["lon"] = lon
        out["coordinate_source"] = f"geometry:{y_key},{x_key}"
    coords_key, coords_value = value_by_normalized_key(value, {"coordinates", "coordinate", "coords"})
    if "lat" not in out and coords_key:
        seq_lat, seq_lon = coordinates_from_sequence(coords_value)
        if plausible_lat_lon(seq_lat, seq_lon):
            out["lat"] = seq_lat
            out["lon"] = seq_lon
            out["coordinate_source"] = f"geometry:{coords_key}"
    return out


def json_context_metadata(record: dict[str, Any], source_url: str, path: str) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if isinstance(record.get("geometry"), dict):
        geometry = record["geometry"]
        context["geometry"] = geometry
        context["geometry_json_endpoint_url"] = source_url
        context["geometry_json_record_path"] = f"{path}.geometry"
        context.update(coordinates_from_geometry(geometry))
    elif isinstance(record.get("coordinates"), (list, tuple)):
        context["coordinates"] = record["coordinates"]
        lat, lon = coordinates_from_sequence(record["coordinates"])
        if plausible_lat_lon(lat, lon):
            context["lat"] = lat
            context["lon"] = lon
            context["coordinate_source"] = f"json:{path}.coordinates"
    x_key, x_value = value_by_normalized_key(record, X_LONGITUDE_KEYS | LONGITUDE_KEYS)
    y_key, y_value = value_by_normalized_key(record, Y_LATITUDE_KEYS | LATITUDE_KEYS)
    lat = coerce_float(y_value)
    lon = coerce_float(x_value)
    if plausible_lat_lon(lat, lon):
        context.setdefault("lat", lat)
        context.setdefault("lon", lon)
        context.setdefault("coordinate_source", f"json:{path}:{y_key},{x_key}")
    return context


def promoted_metadata_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lat_key, lat_value = value_by_normalized_key(metadata, LATITUDE_KEYS)
    lon_key, lon_value = value_by_normalized_key(metadata, LONGITUDE_KEYS)
    lat = coerce_float(lat_value)
    lon = coerce_float(lon_value)
    if not plausible_lat_lon(lat, lon):
        x_key, x_value = value_by_normalized_key(metadata, X_LONGITUDE_KEYS)
        y_key, y_value = value_by_normalized_key(metadata, Y_LATITUDE_KEYS)
        lat = coerce_float(y_value)
        lon = coerce_float(x_value)
        lat_key = y_key
        lon_key = x_key
    if not plausible_lat_lon(lat, lon) and isinstance(metadata.get("geometry"), dict):
        geo = coordinates_from_geometry(metadata["geometry"])
        lat = geo.get("lat")
        lon = geo.get("lon")
        if geo.get("coordinate_source"):
            out["coordinate_source"] = geo["coordinate_source"]
    if not plausible_lat_lon(lat, lon) and isinstance(metadata.get("coordinates"), (list, tuple)):
        lat, lon = coordinates_from_sequence(metadata["coordinates"])
        if plausible_lat_lon(lat, lon):
            out["coordinate_source"] = "metadata:coordinates"
    if plausible_lat_lon(lat, lon):
        out["lat"] = lat
        out["lon"] = lon
        out.setdefault("coordinate_source", str(metadata.get("coordinate_source") or f"metadata:{lat_key},{lon_key}"))

    direction_key, direction_value = value_by_normalized_key(metadata, DIRECTION_KEYS)
    if direction_value not in (None, "", [], {}):
        out["direction"] = str(direction_value)
    bearing_key, bearing_value = value_by_normalized_key(metadata, BEARING_KEYS)
    bearing = coerce_float(bearing_value)
    if bearing is not None:
        out["bearing"] = bearing
    heading_key, heading_value = value_by_normalized_key(metadata, HEADING_KEYS)
    heading = coerce_float(heading_value)
    if heading is not None:
        out["heading"] = heading
    # Some feeds use numeric direction/orientation as an angle. Keep the raw
    # direction string above and also expose it as bearing when useful.
    if "bearing" not in out and direction_key:
        maybe_bearing = coerce_float(direction_value)
        if maybe_bearing is not None:
            out["bearing"] = maybe_bearing

    timestamp_key, timestamp_value = value_by_normalized_key(metadata, TIMESTAMP_KEYS)
    if timestamp_value not in (None, "", [], {}):
        out["timestamp"] = str(timestamp_value)
    date_key, date_value = value_by_normalized_key(metadata, DATE_KEYS)
    if date_value not in (None, "", [], {}):
        out["date"] = str(date_value)
    time_key, time_value = value_by_normalized_key(metadata, TIME_KEYS)
    if time_value not in (None, "", [], {}):
        out["time"] = str(time_value)
    return out


def simple_metadata(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        key_norm = normalize_key(key)
        if isinstance(value, list):
            # Preserve coordinate arrays as structured metadata; other lists are
            # collapsed for compact CSV/JSONL readability.
            if key_norm in {"coordinates", "coordinate", "coords"}:
                out[str(key)] = value
            else:
                out[str(key)] = " ".join(str(part) for part in value)
            continue
        if isinstance(value, dict):
            if key_norm == "geometry":
                out[str(key)] = value
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value
    return out


def json_record_metadata(
    record: dict[str, Any],
    source_url: str,
    path: str,
    media_key: str,
    *,
    context_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = merge_metadata(context_metadata, simple_metadata(record))
    metadata["json_endpoint_url"] = source_url
    metadata["json_record_path"] = path
    metadata["json_media_key"] = media_key
    for key, value in list(record.items()):
        key_norm = normalize_key(key)
        if isinstance(value, (dict, list)) and key_norm not in {"geometry", "coordinates", "coordinate", "coords"}:
            continue
        if key_norm in JSON_METADATA_KEYS or key_norm in JSON_MEDIA_KEYS:
            metadata.setdefault(str(key), value)
    metadata = merge_metadata(metadata, json_context_metadata(record, source_url, path))
    promoted = promoted_metadata_fields(metadata)
    for key, value in promoted.items():
        metadata.setdefault(key, value)
    # Friendly aliases used by output records.
    for candidate_key in ("camera_id", "cameraid", "id", "device_id", "deviceid"):
        if candidate_key in metadata:
            metadata.setdefault("camera_id", str(metadata[candidate_key]))
            break
    for candidate_key in ("location_text", "location", "intersection", "description"):
        if candidate_key in metadata:
            metadata.setdefault("location_text", str(metadata[candidate_key]))
            break
    return {k: v for k, v in metadata.items() if v not in (None, "", [], {})}


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
