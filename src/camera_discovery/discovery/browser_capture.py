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


class BrowserCaptureMixin:
    """Browser capture preflight, routing, budget, and dynamic-page extraction helpers."""

    def _run_browser_preflight(self) -> None:
        if self._browser_capture_summary.get("preflight_ok") is not None:
            return
        if not self.config.enable_browser_capture:
            self._browser_capture_summary["preflight_ok"] = None
            return
        # Resolve through the legacy service module at call time so existing
        # tests and external monkeypatches against services.discovery_engine
        # continue to affect the preflight hook.
        from camera_discovery.services import discovery_engine as legacy_discovery_engine

        result = legacy_discovery_engine.browser_backend_preflight(self.config.browser_backend)
        self._browser_capture_summary.update(result.to_dict())
        self._browser_capture_summary["preflight_ok"] = result.ok
        if not result.ok:
            self.config.enable_browser_capture = False
            self._browser_capture_summary["enabled"] = False
            self._browser_capture_summary["disabled_reason"] = result.disabled_reason
            write_jsonl(self.logs_dir / "browser_capture_preflight.jsonl", [result.to_dict()], append=True)
            self._emit_progress(
                "browser_capture_disabled",
                browser_backend=self.config.browser_backend,
                disabled_reason=result.disabled_reason,
                install_hint=result.install_hint,
            )
        else:
            self._browser_capture_summary["enabled"] = True
            write_jsonl(self.logs_dir / "browser_capture_preflight.jsonl", [result.to_dict()], append=True)

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
