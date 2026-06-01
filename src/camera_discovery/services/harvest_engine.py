from __future__ import annotations

import concurrent.futures
from collections import Counter
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote_plus, urljoin, urlparse, urlsplit, urlunsplit

import httpx

from camera_discovery.core.models import (
    DiscoveryMode,
    DiscoveredEndpointRecord,
    HarvestConfig,
    HarvestResult,
    HarvestedCameraRecord,
    HarvestedMediaAsset,
    HarvestedUrlRecord,
    RunConfig,
)
from camera_discovery.extraction.html import _html_soup
from camera_discovery.extraction.http import _get_with_retry
from camera_discovery.extraction.media import _dedupe_strings, _looks_like_non_camera_asset
from camera_discovery.extraction.pagination import _expand_structured_endpoint_urls, _pagination_rows
from camera_discovery.extraction.search import parse_ddg_result_rows
from camera_discovery.extraction.browser import browser_backend_preflight
from camera_discovery.harvest.json_records import (
    count_json_records,
    extract_json_blobs,
    is_json_payload,
    json_context_metadata,
    json_record_metadata,
    merge_metadata,
    normalize_key,
    parse_json_payload,
    simple_metadata,
    text_value_variants,
    text_variants,
)
from camera_discovery.harvest.media_filter import (
    IMAGE_ASSET_FILTER_MODES,
    JSON_ENDPOINT_HINT_RE,
    QUOTED_MEDIA_RE,
    SUPPORTED_MEDIA_TYPES,
    URL_RE,
    MediaFilter,
    apply_image_asset_filter,
    canonical_media_url,
    classify_media_url,
    parse_media_filter,
)
from camera_discovery.harvest.outputs import (
    build_source_rows_summary,
    record_to_dict,
    write_csv,
    write_plain_urls,
)
from camera_discovery.harvest.records import (
    clean_extracted_url,
    dedupe_records,
    harvest_search_queries,
    record_from_candidate,
    record_from_media_asset,
    record_from_url,
    row_from_source_entry,
)
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.structured_camera_records import (
    camera_record_to_inventory,
    endpoint_type_for_url,
    extract_structured_camera_records,
    url_record_to_inventory,
)
from camera_discovery.sources import load_source_policy
from camera_discovery.utils.io import write_json, write_jsonl
from camera_discovery.utils.playlists import export_harvest_playlists


# Compatibility imports/re-exports are intentionally preserved for existing tests
# and external code that imported harvest helper symbols from this legacy module.

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
        if self.config.image_asset_filter not in IMAGE_ASSET_FILTER_MODES:
            allowed = ", ".join(sorted(IMAGE_ASSET_FILTER_MODES))
            raise ValueError(f"Invalid image asset filter {self.config.image_asset_filter!r}; expected one of: {allowed}")
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
        self._blind_search_diagnostics: list[dict[str, Any]] = []
        self._browser_summary: dict[str, Any] = {
            "enabled": config.enable_browser_capture,
            "backend": config.browser_backend,
            "pages_attempted": 0,
            "media_records": 0,
            "json_endpoints": 0,
            "errors": 0,
            "timeouts": 0,
            "network_events_sample": [],
            "preflight_ok": None,
            "disabled_reason": "",
            "install_hint": "",
        }

    def harvest(self) -> HarvestResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._run_browser_preflight()
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
        image_filtered, image_filter_summary = apply_image_asset_filter(filtered, self.config.image_asset_filter)
        written = image_filtered if self.config.max_urls == 0 else image_filtered[: self.config.max_urls]
        self._emit(
            "harvest_dedupe_complete",
            raw_records=len(raw_records),
            unique_urls=len(unique),
            media_filtered_urls=media_filtered,
            image_filtered_urls=len(image_filtered),
        )
        outputs = self._write_outputs(
            written,
            raw_records_count=len(raw_records),
            raw_media_records=unblocked,
            unique=unique,
            media_filtered_records=filtered,
            image_filtered_records=image_filtered,
            image_filter_summary=image_filter_summary,
            pre_filter_unique=pre_filter_unique,
            media_filtered=media_filtered,
            blocked_or_filtered=len(blocked_filtered),
        )
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


    def _run_browser_preflight(self) -> None:
        if self._browser_summary.get("preflight_ok") is not None:
            return
        if not self.config.enable_browser_capture:
            self._browser_summary["preflight_ok"] = None
            return
        result = browser_backend_preflight(self.config.browser_backend)
        self._browser_summary.update(result.to_dict())
        self._browser_summary["preflight_ok"] = result.ok
        if not result.ok:
            self.config.enable_browser_capture = False
            self._browser_summary["enabled"] = False
            self._browser_summary["disabled_reason"] = result.disabled_reason
            self._warnings.append(f"Browser capture disabled: {result.disabled_reason}. {result.install_hint}")
            write_jsonl(self.logs_dir / "browser_capture_preflight.jsonl", [result.to_dict()], append=True)
            self._emit(
                "harvest_browser_capture_disabled",
                browser_backend=self.config.browser_backend,
                disabled_reason=result.disabled_reason,
                install_hint=result.install_hint,
            )
        else:
            self._browser_summary["enabled"] = True
            write_jsonl(self.logs_dir / "browser_capture_preflight.jsonl", [result.to_dict()], append=True)

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
            blind_search_diagnostics=self._blind_search_diagnostics,
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
        diagnostics: list[dict[str, Any]] = []
        client = self._make_client()
        try:
            for query in queries:
                search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
                try:
                    resp = _get_with_retry(client, search_url)
                    resp.raise_for_status()
                    parsed = self._parse_ddg(query, resp.text)
                    diagnostics.append(
                        {
                            "query": query,
                            "url": search_url,
                            "status_code": resp.status_code,
                            "response_bytes": len(resp.content or b""),
                            "parsed_rows": len(parsed),
                        }
                    )
                    rows.extend(parsed)
                except Exception as exc:
                    diagnostics.append({"query": query, "url": search_url, "error": repr(exc), "parsed_rows": 0})
                    self._log_error("blind_search_error", query, exc)
        finally:
            client.close()
        if diagnostics:
            write_jsonl(self.logs_dir / "harvest_blind_search_diagnostics.jsonl", diagnostics)
        self._blind_search_diagnostics = diagnostics
        return rows

    def _parse_ddg(self, query: str, text: str) -> list[dict[str, str]]:
        return parse_ddg_result_rows(
            query,
            text,
            max_results=self.config.max_search_results_per_query,
            include_source_kind=True,
        )

    def _select_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        selected: list[dict[str, str]] = []
        blocked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            url = (row.get("url") or "").split("#", 1)[0]
            if not url.startswith(("http://", "https://", "rtsp://", "rtsps://")):
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
            if url.startswith(("rtsp://", "rtsps://")):
                continue
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
                absolute = canonical_media_url(urljoin(source_url, cleaned))
                if absolute in seen_matches or self.source_policy.is_blocked(absolute):
                    continue
                if media_type == "image_snapshot" and _looks_like_non_camera_asset(absolute):
                    continue
                seen_matches.add(absolute)
                records.append(record_from_url(absolute, media_type, source_url=source_url, row=row, method=method, metadata={"text_variant": variant_name}))
            for match in QUOTED_MEDIA_RE.finditer(variant):
                cleaned = clean_extracted_url(match.group(1))
                absolute = canonical_media_url(urljoin(source_url, cleaned))
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
                absolute = canonical_media_url(urljoin(source_url, value.strip()))
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
                    absolute = canonical_media_url(urljoin(source_url, candidate))
                    media_type = classify_media_url(absolute, key_hint="srcset")
                    if media_type and not self.source_policy.is_blocked(absolute):
                        records.append(record_from_url(absolute, media_type, source_url=source_url, row=row, method=method, title=tag.get("title") or tag.get("alt") or page_title, metadata={"html_tag": getattr(tag, "name", ""), "html_attr": "srcset"}))
        return dedupe_records(records)

    def _extract_from_json_data(self, data: Any, source_url: str, row: dict[str, str], *, method: str) -> list[HarvestedUrlRecord]:
        records: list[HarvestedUrlRecord] = []
        self._walk_json(data, source_url, row, method=method, path="$", records=records, context_metadata=None)
        return dedupe_records(records)

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
                        absolute = canonical_media_url(urljoin(source_url, decoded))
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
        raw_records_count: int,
        raw_media_records: list[HarvestedUrlRecord],
        unique: list[HarvestedUrlRecord],
        media_filtered_records: list[HarvestedUrlRecord],
        image_filtered_records: list[HarvestedUrlRecord],
        image_filter_summary: dict[str, Any],
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

        playlist_summary = export_harvest_playlists(self.output_dir, records, source_policy=self.source_policy)
        write_json(self.logs_dir / "playlist_export_summary.json", playlist_summary)
        outputs["playlist_export_summary_json"] = str(self.logs_dir / "playlist_export_summary.json")
        for key, rel_path in playlist_summary.get("files", {}).items():
            outputs[f"playlist_{key}"] = str(self.output_dir / rel_path)

        intermediate_outputs = self._write_intermediate_records(
            raw_media_records=raw_media_records,
            unique_records=unique,
            media_filtered_records=media_filtered_records,
            image_filtered_records=image_filtered_records,
        )
        outputs.update(intermediate_outputs)

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
            "schema_version": "harvest-handoff/v2",
            "query": self.config.query,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "mode": "harvest",
            "source_provided_only": True,
            "validated": False,
            "geocoded": False,
            "scope_filtered": False,
            "trusted": False,
            "llm_reviewed": False,
            "media_filter": list(self.media_filter.requested),
            "handoff_default_scope": "filtered_media_records" if not self.media_filter.all_media else "structured_inventory_records",
            "files": {
                "filtered_media_records": "camera_urls.jsonl",
                "harvest_camera_inventory": "harvest_camera_inventory.jsonl",
                "camera_records": "camera_records.jsonl",
                "camera_media_assets": "camera_media_assets.jsonl",
                "camera_urls_jsonl": "camera_urls.jsonl",
                "discovered_endpoints": "discovered_endpoints.jsonl",
                "playlist_export_summary": "logs/playlist_export_summary.json",
            },
            "counts": {
                "camera_records": len(camera_records),
                "media_assets": len(media_assets),
                "url_records": len(records),
                "filtered_media_records": len(records),
                "endpoints": len(endpoints),
                "records_with_coordinates": sum(1 for record in camera_records if record.lat is not None and record.lon is not None),
                "filtered_records_with_coordinates": sum(1 for record in records if record.lat is not None and record.lon is not None),
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
            "raw_records": raw_records_count,
            "unique_urls": len(unique),
            "written_urls": len(records),
            "max_urls": self.config.max_urls,
            "unlimited": self.config.max_urls == 0,
            "media_filter": self.media_filter.requested,
            "pre_filter_unique_urls": pre_filter_unique,
            "media_filtered_urls": media_filtered,
            "image_asset_filter": self.config.image_asset_filter,
            "image_asset_filter_removed": image_filter_summary.get("removed", 0),
            "image_asset_filter_kept": image_filter_summary.get("kept", len(records)),
            "image_asset_filter_removed_by_reason": image_filter_summary.get("removed_by_reason", {}),
            "pre_image_filter_records": image_filter_summary.get("pre_image_filter_records", media_filtered),
            "post_image_filter_records": image_filter_summary.get("post_image_filter_records", len(records)),
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
            "intermediate_records_written": self.config.write_intermediate_records,
            "intermediate_record_counts": {
                "raw_media_records": len(raw_media_records),
                "unique_media_records": len(unique),
                "media_filtered_records": len(media_filtered_records),
                "image_filtered_records": len(image_filtered_records),
            },
            "intermediate_record_files": {
                key: value
                for key, value in outputs.items()
                if key in {"raw_media_records_jsonl", "unique_media_records_jsonl", "media_filtered_records_jsonl", "image_filtered_records_jsonl"}
            },
            "outputs": outputs,
            "warnings": self._warnings,
            "browser_capture": self._browser_summary,
            "playlist_exports": playlist_summary,
        }
        write_json(self.output_dir / "harvest_summary.json", summary)
        write_json(self.logs_dir / "harvest_summary.json", summary)
        write_json(self.logs_dir / "browser_capture_summary.json", self._browser_summary)
        write_json(self.logs_dir / "endpoint_catalog_summary.json", {"endpoints": len(endpoints), "records": endpoint_dicts})
        outputs["harvest_summary_json"] = str(self.output_dir / "harvest_summary.json")
        return outputs

    def _write_intermediate_records(
        self,
        *,
        raw_media_records: list[HarvestedUrlRecord],
        unique_records: list[HarvestedUrlRecord],
        media_filtered_records: list[HarvestedUrlRecord],
        image_filtered_records: list[HarvestedUrlRecord],
    ) -> dict[str, str]:
        """Optionally write debug/analysis records for each harvest reduction stage.

        These files are intentionally opt-in because raw harvest runs can produce
        large outputs. Raw debug records are written after block-policy filtering
        and before deduplication so blocked URLs are not persisted.
        """

        if not self.config.write_intermediate_records:
            return {}
        stage_records = {
            "raw_media_records_jsonl": ("raw_media_records.jsonl", raw_media_records),
            "unique_media_records_jsonl": ("unique_media_records.jsonl", unique_records),
            "media_filtered_records_jsonl": ("media_filtered_records.jsonl", media_filtered_records),
            "image_filtered_records_jsonl": ("image_filtered_records.jsonl", image_filtered_records),
        }
        outputs: dict[str, str] = {}
        for output_key, (filename, records) in stage_records.items():
            path = self.output_dir / filename
            write_jsonl(path, [record_to_dict(record) for record in records])
            outputs[output_key] = str(path)
        write_json(
            self.logs_dir / "intermediate_records_summary.json",
            {
                "enabled": True,
                "raw_media_records": len(raw_media_records),
                "unique_media_records": len(unique_records),
                "media_filtered_records": len(media_filtered_records),
                "image_filtered_records": len(image_filtered_records),
                "files": outputs,
                "note": "raw_media_records are block-policy-filtered records before deduplication; media_filtered_records are after --media and before image filtering; image_filtered_records are before the final --max-urls cap.",
            },
        )
        return outputs

