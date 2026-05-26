from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, urlencode, urljoin, urlparse

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
from camera_discovery.extraction.browser import BrowserCaptureDecision, BrowserCaptureResult, PageDiscoverySignals
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


# Compatibility imports/re-exports are intentionally preserved for existing tests
# and external code that imported helper symbols from this legacy module.

class CandidateDiscoveryEngine:
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

    def _build_candidate_set(self, raw: list[CameraCandidate], unique: list[CameraCandidate]) -> CandidateSet:
        return CandidateSet(
            raw=raw,
            unique=unique,
            coordinate_bearing=[c for c in unique if c.has_coordinates],
            in_scope=[c for c in unique if c.scope_status == "in_scope"],
            review=[c for c in unique if c.scope_status in {"review", "unknown", "in_scope"}],
            rejected=[c for c in unique if c.scope_status == "out_of_scope"],
        )

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
        soup = _html_soup(html)
        results: list[dict[str, str]] = []
        for anchor in soup.select("a.result__a")[: self.config.max_search_results_per_query]:
            url = self._clean(anchor.get("href") or "")
            if url:
                results.append({"query": query, "title": anchor.get_text(" ", strip=True), "url": url, "snippet": "", "source_provider": "blind"})
        return results

    def _clean(self, href: str) -> str:
        if not href:
            return ""
        if "duckduckgo.com/l/" in href or href.startswith("//duckduckgo.com/l/"):
            parsed = urlparse(href if href.startswith("http") else "https:" + href)
            return unquote(parse_qs(parsed.query).get("uddg", [""])[0])
        return href

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

    def _page_discovery_signals(
        self,
        url: str,
        row: dict[str, str],
        text: str,
        content_type: str,
        status_code: int | None,
        static_candidate_count: int,
    ) -> PageDiscoverySignals:
        lowered = (text or "").casefold()
        soup = _html_soup(text) if ("html" in content_type.casefold() or "<html" in lowered[:1000]) else None
        title = ""
        script_count = 0
        large_script = False
        json_hints: list[str] = []
        pagination_hints: list[str] = []
        dynamic: list[str] = []
        if soup is not None:
            title_tag = soup.find("title")
            title = title_tag.get_text(" ", strip=True) if title_tag else ""
            script_tags = soup.select("script")
            script_count = len(script_tags)
            for tag in script_tags:
                src = tag.get("src") or ""
                inline_len = len(tag.get_text("", strip=False) or "")
                if src:
                    if any(part in src.casefold() for part in ("app", "bundle", "chunk", "static", "assets")):
                        large_script = True
                    if JSON_FEED_HINT_RE.search(src) or MAP_LAYER_API_RE.search(src):
                        json_hints.append(urljoin(url, src))
                if inline_len > 20000:
                    large_script = True
            for tag in soup.select("a[href], link[href]"):
                href = tag.get("href") or ""
                absolute = urljoin(url, href)
                if JSON_FEED_HINT_RE.search(absolute) or MAP_LAYER_API_RE.search(absolute):
                    json_hints.append(absolute)
                if _looks_like_pagination_url(absolute) or str(tag.get_text(" ", strip=True)).casefold() in {"next", "more", "older"}:
                    pagination_hints.append(absolute)
            if script_count >= 5:
                dynamic.append("multiple_script_tags")
            if large_script:
                dynamic.append("large_script_bundle")
        for name, pattern in (
            ("hls_hint", r"\.m3u8|application/x-mpegurl|application/vnd\.apple\.mpegurl"),
            ("map_library", r"leaflet|mapbox|openlayers|arcgis|MapServer|FeatureServer"),
            ("player_library", r"video\.js|hls\.js|jwplayer|clappr"),
            ("javascript_state", r"__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__"),
            ("json_api_hint", r"/api/|\.json|/feed|/feeds|/layer|/layers|MapServer|FeatureServer"),
        ):
            if re.search(pattern, text, flags=re.I):
                dynamic.append(name)
        camera_text_score = sum(lowered.count(term) for term in ("camera", "cameras", "webcam", "webcams", "cctv", "live", "snapshot"))
        app_shell_score = 0
        if soup is not None and script_count >= 5 and len(soup.get_text(" ", strip=True)) < 1500:
            app_shell_score += 2
            dynamic.append("app_shell")
        if row.get("source_kind") in {"dynamic", "site", "promoted_host", "site_target_page"}:
            dynamic.append(f"source_kind:{row.get('source_kind')}")
        return PageDiscoverySignals(
            url=url,
            source_provider=row.get("source_provider") or "",
            source_kind=row.get("source_kind") or "",
            status_code=status_code,
            content_type=content_type,
            title=title,
            script_count=script_count,
            has_large_script_bundle=large_script,
            dynamic_signals=_dedupe_strings(dynamic),
            json_endpoint_hints=_dedupe_strings(json_hints),
            pagination_hints=_dedupe_strings(pagination_hints),
            camera_text_score=camera_text_score,
            app_shell_score=app_shell_score,
            has_hls_hint="hls_hint" in dynamic,
            static_candidate_count=static_candidate_count,
        )

    def _browser_capture_decision(
        self,
        row: dict[str, str],
        static_candidates: list[CameraCandidate],
        signals: PageDiscoverySignals | None,
        phase: str,
    ) -> BrowserCaptureDecision:
        url = row.get("url") or ""
        host = urlparse(url).netloc.casefold()
        source_provider = row.get("source_provider") or "unknown"
        source_kind = row.get("source_kind") or ""
        reasons: list[str] = []
        score = 0
        if not self.config.enable_browser_capture:
            return self._browser_skip(row, phase, "browser_capture_disabled", score, reasons, len(static_candidates))
        if not url.startswith("http"):
            return self._browser_skip(row, phase, "invalid_url", score, reasons, len(static_candidates))
        if self.source_policy.is_blocked(url):
            return self._browser_skip(row, phase, "blocked_url", score, reasons, len(static_candidates))
        if _looks_like_hls(url) or _looks_like_image(url):
            return self._browser_skip(row, phase, "direct_media_url", score, reasons, len(static_candidates))
        if source_kind in {"direct_hls", "feed"} and not (signals and signals.dynamic_signals):
            return self._browser_skip(row, phase, "static_endpoint_already_handled", score, reasons, len(static_candidates))
        if self._candidate_budgets_full(static_candidates):
            return self._browser_skip(row, phase, "candidate_budget_full", score, reasons, len(static_candidates))
        if source_kind == "dynamic":
            score += 5
            reasons.append("explicit_dynamic_source_kind")
        if source_provider == "directory":
            score += 2
            reasons.append("directory_source")
        elif source_provider == "blind":
            score += 1
            reasons.append("blind_source")
        elif source_provider == "asset_host_promotion":
            score += 2
            reasons.append("promoted_asset_host")
        if signals:
            if signals.static_candidate_count == 0:
                score += 2
                reasons.append("static_zero_candidates")
            if signals.dynamic_signals:
                signal_weight = min(4, len(signals.dynamic_signals))
                score += signal_weight
                reasons.extend(signals.dynamic_signals[:6])
            if signals.camera_text_score >= 2:
                score += 2
                reasons.append("camera_text_signals")
            if signals.json_endpoint_hints:
                score += 1
                reasons.append("json_or_map_endpoint_hints")
            if signals.app_shell_score:
                score += signals.app_shell_score
                reasons.append("app_shell_score")
            if signals.has_hls_hint:
                score += 2
                reasons.append("hls_text_hint")
        row_text = " ".join(str(row.get(key) or "") for key in ("title", "snippet", "source_name", "source_notes")).casefold()
        if any(term in row_text for term in ("camera", "cameras", "webcam", "webcams", "cctv", "live", "snapshot")):
            score += 1
            reasons.append("row_camera_text")
        if static_candidates and not (source_kind == "dynamic" or (signals and (signals.dynamic_signals or signals.json_endpoint_hints))):
            return self._browser_skip(row, phase, "static_candidates_sufficient", score, reasons, len(static_candidates))
        if score < self.config.browser_capture_min_score:
            return self._browser_skip(row, phase, "score_below_threshold", score, reasons, len(static_candidates))
        return self._reserve_browser_capture(row, phase, score, _dedupe_strings(reasons), len(static_candidates))

    def _browser_skip(self, row: dict[str, str], phase: str, skip_reason: str, score: int, reasons: list[str], static_candidate_count: int) -> BrowserCaptureDecision:
        self._record_browser_summary(row.get("source_provider") or "unknown", considered=True, selected=False)
        return BrowserCaptureDecision(
            url=row.get("url") or "",
            source_provider=row.get("source_provider") or "unknown",
            source_kind=row.get("source_kind") or "",
            selected=False,
            score=score,
            reasons=_dedupe_strings(reasons),
            skip_reason=skip_reason,
            host=urlparse(row.get("url") or "").netloc.casefold(),
            phase=phase,
            source_name=row.get("source_name") or row.get("title") or "",
            static_candidate_count=static_candidate_count,
            budget_remaining=self._browser_budget_remaining(row.get("source_provider") or "unknown", urlparse(row.get("url") or "").netloc.casefold()),
            browser_backend=self.config.browser_backend,
        )

    def _reserve_browser_capture(self, row: dict[str, str], phase: str, score: int, reasons: list[str], static_candidate_count: int) -> BrowserCaptureDecision:
        source_provider = row.get("source_provider") or "unknown"
        host = urlparse(row.get("url") or "").netloc.casefold()
        with self._browser_capture_lock:
            skip_reason = ""
            if self._browser_capture_counts["total"] >= self.config.max_browser_capture_pages:
                skip_reason = "global_browser_budget_exhausted"
            elif source_provider == "blind" and self._browser_capture_counts.get("blind", 0) >= self.config.max_browser_capture_pages_blind:
                skip_reason = "blind_browser_budget_exhausted"
            elif source_provider == "directory" and self._browser_capture_counts.get("directory", 0) >= self.config.max_browser_capture_pages_directory:
                skip_reason = "directory_browser_budget_exhausted"
            elif self._browser_capture_host_counts.get(host, 0) >= self.config.max_browser_capture_pages_per_host:
                skip_reason = "host_browser_budget_exhausted"
            elif self._browser_capture_host_failures.get(host, 0) >= 2:
                skip_reason = "host_browser_cooldown"
            if skip_reason:
                self._record_browser_summary(source_provider, considered=True, selected=False)
                return BrowserCaptureDecision(
                    url=row.get("url") or "",
                    source_provider=source_provider,
                    source_kind=row.get("source_kind") or "",
                    selected=False,
                    score=score,
                    reasons=reasons,
                    skip_reason=skip_reason,
                    host=host,
                    phase=phase,
                    source_name=row.get("source_name") or row.get("title") or "",
                    static_candidate_count=static_candidate_count,
                    budget_remaining=self._browser_budget_remaining(source_provider, host),
                    browser_backend=self.config.browser_backend,
                )
            self._browser_capture_counts["total"] += 1
            self._browser_capture_counts[source_provider] = self._browser_capture_counts.get(source_provider, 0) + 1
            self._browser_capture_host_counts[host] = self._browser_capture_host_counts.get(host, 0) + 1
            self._record_browser_summary(source_provider, considered=True, selected=True)
            return BrowserCaptureDecision(
                url=row.get("url") or "",
                source_provider=source_provider,
                source_kind=row.get("source_kind") or "",
                selected=True,
                score=score,
                reasons=reasons,
                host=host,
                phase=phase,
                source_name=row.get("source_name") or row.get("title") or "",
                static_candidate_count=static_candidate_count,
                budget_remaining=self._browser_budget_remaining(source_provider, host),
                browser_backend=self.config.browser_backend,
            )

    def _browser_budget_remaining(self, source_provider: str, host: str) -> dict[str, int]:
        return {
            "global": max(0, self.config.max_browser_capture_pages - self._browser_capture_counts.get("total", 0)),
            "blind": max(0, self.config.max_browser_capture_pages_blind - self._browser_capture_counts.get("blind", 0)),
            "directory": max(0, self.config.max_browser_capture_pages_directory - self._browser_capture_counts.get("directory", 0)),
            "host": max(0, self.config.max_browser_capture_pages_per_host - self._browser_capture_host_counts.get(host, 0)),
        }

    def _record_browser_summary(self, source_provider: str, *, considered: bool = False, selected: bool = False, candidates: list[CameraCandidate] | None = None, error: bool = False, timeout: bool = False, attempted: bool = False) -> None:
        with self._browser_capture_lock:
            provider_summary = self._browser_capture_summary["by_source_provider"].setdefault(
                source_provider,
                {"considered": 0, "selected": 0, "attempted": 0, "candidates": 0, "hls_candidates": 0, "image_snapshot_candidates": 0, "errors": 0, "timeouts": 0},
            )
            if considered:
                self._browser_capture_summary["rows_considered"] += 1
                provider_summary["considered"] += 1
            if selected:
                self._browser_capture_summary["rows_selected"] += 1
                provider_summary["selected"] += 1
            elif considered:
                self._browser_capture_summary["rows_skipped"] += 1
            if attempted:
                self._browser_capture_summary["pages_attempted"] += 1
                provider_summary["attempted"] += 1
            if candidates:
                hls = sum(1 for c in candidates if _candidate_media_type(c) == "hls")
                snapshots = len(candidates) - hls
                self._browser_capture_summary["candidates"] += len(candidates)
                self._browser_capture_summary["hls_candidates"] += hls
                self._browser_capture_summary["image_snapshot_candidates"] += snapshots
                provider_summary["candidates"] += len(candidates)
                provider_summary["hls_candidates"] += hls
                provider_summary["image_snapshot_candidates"] += snapshots
            if error:
                self._browser_capture_summary["errors"] += 1
                provider_summary["errors"] += 1
            if timeout:
                self._browser_capture_summary["timeouts"] += 1
                provider_summary["timeouts"] += 1

    def _log_browser_capture_decision(self, decision: BrowserCaptureDecision) -> None:
        write_jsonl(self.logs_dir / "browser_capture_decisions.jsonl", [decision.to_log_record()], append=True)
        if decision.skip_reason in {"global_browser_budget_exhausted", "blind_browser_budget_exhausted", "directory_browser_budget_exhausted", "host_browser_budget_exhausted"}:
            self._emit_progress("browser_capture_budget_exhausted", phase=decision.phase, skip_reason=decision.skip_reason, source_provider=decision.source_provider, host=decision.host)

    def _log_browser_capture_result(self, result: BrowserCaptureResult, row: dict[str, str], phase: str) -> None:
        write_jsonl(self.logs_dir / "browser_capture_results.jsonl", [result.to_log_record(row, phase)], append=True)
        if result.error:
            error_record = {**result.to_log_record(row, phase), "error": result.error}
            write_jsonl(self.logs_dir / "browser_capture_errors.jsonl", [error_record], append=True)
            write_jsonl(self.logs_dir / "playwright_network_capture_errors.jsonl", [error_record], append=True)

    def _browser_backend_install_hint(self) -> str:
        if self.config.browser_backend == "cloakbrowser":
            return "Install with: pip install -e .[cloakbrowser]"
        return "Install with: pip install -e .[playwright] and run: python -m playwright install chromium"

    @contextmanager
    def _browser_capture_session(self):
        backend = self.config.browser_backend
        browser = None
        if backend == "cloakbrowser":
            try:
                from cloakbrowser import launch
            except ImportError as exc:
                raise ImportError(f"CloakBrowser backend selected but cloakbrowser is not installed. {self._browser_backend_install_hint()}") from exc
            browser = launch(headless=True)
            try:
                yield browser
            finally:
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
            return
        if backend == "playwright":
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise ImportError(f"Playwright backend selected but playwright is not installed. {self._browser_backend_install_hint()}") from exc
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    yield browser
                finally:
                    try:
                        if browser is not None:
                            browser.close()
                    except Exception:
                        pass
            return
        raise ValueError(f"Unsupported browser backend: {backend!r}")

    def _extract_from_dynamic_page(
        self,
        url: str,
        row: dict[str, str],
        *,
        phase: str = "primary",
        decision: BrowserCaptureDecision | None = None,
        return_result: bool = False,
    ) -> list[CameraCandidate] | tuple[list[CameraCandidate], BrowserCaptureResult]:
        start = time.monotonic()
        backend = self.config.browser_backend

        collected_hls: set[str] = set()
        collected_json: set[str] = set()
        network_events: list[dict[str, Any]] = []
        rendered_html = ""
        timed_out = False
        try:
            with self._browser_capture_session() as browser:
                page = browser.new_page(user_agent=self.config.user_agent)

                def collect_url(candidate_url: str, content_type: str = "", event_type: str = "network") -> None:
                    if not candidate_url or self.source_policy.is_blocked(candidate_url):
                        return
                    lowered_type = content_type.casefold()
                    if len(network_events) < self.config.max_browser_network_events_logged_per_page:
                        network_events.append({"event": event_type, "url": candidate_url, "content_type": content_type[:120]})
                    if _looks_like_hls(candidate_url) or "application/x-mpegurl" in lowered_type or "application/vnd.apple.mpegurl" in lowered_type:
                        collected_hls.add(candidate_url)
                    if JSON_FEED_HINT_RE.search(candidate_url) or MAP_LAYER_API_RE.search(candidate_url):
                        collected_json.add(candidate_url)

                page.on("request", lambda request: collect_url(request.url, str(request.headers.get("content-type", "")), "request"))
                page.on("response", lambda response: collect_url(response.url, str(response.headers.get("content-type", "")), "response"))
                page.goto(url, wait_until="networkidle", timeout=self.config.browser_capture_timeout_ms)
                if self.config.browser_capture_settle_ms:
                    page.wait_for_timeout(self.config.browser_capture_settle_ms)
                if self.config.browser_capture_scroll:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    if self.config.browser_capture_settle_ms:
                        page.wait_for_timeout(min(self.config.browser_capture_settle_ms, 1500))
                rendered_html = page.content()
        except Exception as exc:
            timed_out = "timeout" in exc.__class__.__name__.casefold()
            result = BrowserCaptureResult(
                url=url,
                backend=backend,
                elapsed_ms=int((time.monotonic() - start) * 1000),
                timed_out=timed_out,
                error=repr(exc),
                network_events_sample=network_events,
            )
            self._record_browser_failure(url, row, result)
            return ([], result) if return_result else []

        out: list[CameraCandidate] = []
        for stream_url in sorted(collected_hls):
            if self.source_policy.is_blocked(stream_url):
                continue
            candidate = self._candidate_from_stream(stream_url, url, row, "browser_network_capture")
            candidate.source_metadata["media_type"] = "hls"
            self._apply_browser_metadata(candidate, url, decision, "browser_network_capture")
            out.append(candidate)
        if rendered_html:
            rendered_candidates = self._extract_from_response(url, row, rendered_html, "text/html")
            for candidate in rendered_candidates:
                self._apply_browser_metadata(candidate, url, decision, "browser_rendered_html")
                if candidate.discovery_method not in {"browser_network_capture", "browser_json_endpoint"}:
                    candidate.discovery_method = "browser_rendered_html"
            out.extend(rendered_candidates)
        if collected_json:
            client = self._make_client()
            try:
                for feed_url in sorted(collected_json)[: self.config.max_browser_json_endpoints_per_page]:
                    if self.source_policy.is_blocked(feed_url):
                        continue
                    try:
                        resp = _get_with_retry(client, feed_url)
                        if resp.status_code >= 400:
                            continue
                        json_candidates = self._extract_from_response(feed_url, row, resp.text, resp.headers.get("content-type", ""))
                        for candidate in json_candidates:
                            self._apply_browser_metadata(candidate, url, decision, "browser_json_endpoint")
                            candidate.discovery_method = "browser_json_endpoint"
                        out.extend(json_candidates)
                    except Exception:
                        continue
            finally:
                client.close()
        out = self._dedupe(out)
        result = BrowserCaptureResult(
            url=url,
            backend=backend,
            captured_hls_urls=sorted(collected_hls),
            captured_json_urls=sorted(collected_json),
            rendered_html_candidates=sum(1 for c in out if c.discovery_method == "browser_rendered_html"),
            total_browser_candidates=len(out),
            network_events_sample=network_events,
            elapsed_ms=int((time.monotonic() - start) * 1000),
            timed_out=timed_out,
        )
        self._record_browser_summary(row.get("source_provider") or "unknown", attempted=True, candidates=out)
        return (out, result) if return_result else out

    def _apply_browser_metadata(self, candidate: CameraCandidate, capture_url: str, decision: BrowserCaptureDecision | None, method: str) -> None:
        candidate.source_metadata["browser_backend"] = self.config.browser_backend
        candidate.source_metadata["browser_capture_url"] = capture_url
        candidate.source_metadata["browser_capture_reason"] = ",".join((decision.reasons if decision else [])[:10])
        candidate.source_metadata.setdefault("discovery_method", method)
        if _looks_like_hls(candidate.stream_url):
            candidate.source_metadata.setdefault("media_type", "hls")
        else:
            candidate.source_metadata.setdefault("media_type", "image_snapshot")

    def _record_browser_failure(self, url: str, row: dict[str, str], result: BrowserCaptureResult) -> None:
        host = urlparse(url).netloc.casefold()
        with self._browser_capture_lock:
            self._browser_capture_host_failures[host] = self._browser_capture_host_failures.get(host, 0) + 1
        self._record_browser_summary(row.get("source_provider") or "unknown", attempted=True, error=bool(result.error), timeout=result.timed_out)

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

    def _dedupe(self, rows: list[CameraCandidate]) -> list[CameraCandidate]:
        by_key: dict[str, CameraCandidate] = {}
        order: list[str] = []
        for row in rows:
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
        for candidate in candidates:
            if candidate.has_coordinates and bbox:
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

