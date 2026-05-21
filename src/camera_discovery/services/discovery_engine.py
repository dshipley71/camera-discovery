from __future__ import annotations

import concurrent.futures
import json
import math
import re
import threading
import time
import warnings
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from camera_discovery.core.models import CameraCandidate, CandidateSet, DiscoveryMode, RunConfig, TargetContext
from camera_discovery.llm.base import ChatMessage, LLMClient
from camera_discovery.llm.factory import build_candidate_review_client, build_location_inference_client
from camera_discovery.sources import SourceEntry, SourcePolicy, load_source_policy
from camera_discovery.utils.io import write_json, write_jsonl
from camera_discovery.utils.json_utils import extract_json_object

M3U8_RE = re.compile(r"https?://[^\s'\"<>]+?\.m3u8(?:\?[^\s'\"<>]*)?|['\"]([^'\"]+?\.m3u8(?:\?[^'\"]*)?)['\"]", re.I)
IMAGE_RE = re.compile(r"https?://[^\s'\"<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\s'\"<>]*)?|['\"]([^'\"]+?\.(?:jpg|jpeg|png|webp)(?:\?[^'\"]*)?)['\"]", re.I)
COORD_RE = re.compile(r"(?<!\d)([-+]?\d{1,2}\.\d{3,})\s*,\s*([-+]?\d{1,3}\.\d{3,})(?!\d)")
JSON_FEED_HINT_RE = re.compile(r"(?:\.json(?:\?|$)|/api/|/feed|/feeds|/layer|/layers|camera|cameras|mapserver|featureserver)", re.I)
MAP_LAYER_API_RE = re.compile(r"(?:/MapServer|/FeatureServer|/arcgis/|/api/cameras)", re.I)
DYNAMIC_PAGE_HINT_RE = re.compile(
    r"(?:__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__|leaflet|mapbox|openlayers|video\.js|hls\.js|jwplayer|clappr|arcgis|MapServer|FeatureServer|camera|cameras|webcam|webcams|cctv|live|snapshot)",
    re.I,
)
MAX_WORKERS = 8
URL_KEYS = {"url", "stream", "stream_url", "streamurl", "hls", "hls_url", "hlsurl", "video", "video_url", "src"}
IMAGE_KEYS = {"image", "image_url", "imageurl", "snapshot", "snapshot_url", "snapshoturl", "thumbnail", "thumbnail_url", "thumbnailurl", "preview", "preview_url", "poster", "poster_url"}
THUMBNAIL_IMAGE_KEYS = {"thumbnail", "thumbnail_url", "thumbnailurl", "thumb", "thumb_url", "preview", "preview_url", "poster", "poster_url"}
LAT_KEYS = {"lat", "latitude", "y", "data_lat", "data_latitude"}
LON_KEYS = {"lon", "lng", "long", "longitude", "x", "data_lon", "data_lng", "data_longitude"}
TITLE_KEYS = {"name", "title", "label", "description", "camera", "id"}


def _get_with_retry(client: httpx.Client, url: str, *, retries: int = 1) -> httpx.Response:
    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.get(url)
            if resp.status_code < 500:
                return resp
            if attempt < retries:
                time.sleep(2 ** attempt)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    if last_exc:
        raise last_exc
    if resp is not None:
        return resp
    raise httpx.ConnectError(f"No response returned for {url}")



def _html_soup(html: str) -> BeautifulSoup:
    """Parse HTML/XML-ish text without surfacing BeautifulSoup XML warnings.

    Some public feeds return XML/RSS/KML-ish content from URLs that the discovery
    crawler treats like pages. BeautifulSoup's HTML parser emits
    XMLParsedAsHTMLWarning for those responses; using the XML parser when the
    document clearly looks XML-like avoids noisy captured output while preserving
    real parsing.
    """
    prefix = (html or "").lstrip()[:200].lower()
    parser = "xml" if (prefix.startswith("<?xml") or prefix.startswith("<rss") or prefix.startswith("<feed") or prefix.startswith("<kml")) else "html.parser"
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        return BeautifulSoup(html, parser)

def _candidate_media_type(candidate: CameraCandidate) -> str:
    media_type = str((candidate.source_metadata or {}).get("media_type") or "").casefold()
    if media_type:
        return media_type
    if _looks_like_hls(candidate.stream_url):
        return "hls"
    return "image_snapshot"


@dataclass
class PageDiscoverySignals:
    url: str
    source_provider: str = ""
    source_kind: str = ""
    status_code: int | None = None
    content_type: str = ""
    title: str = ""
    script_count: int = 0
    has_large_script_bundle: bool = False
    dynamic_signals: list[str] | None = None
    json_endpoint_hints: list[str] | None = None
    pagination_hints: list[str] | None = None
    camera_text_score: int = 0
    app_shell_score: int = 0
    has_hls_hint: bool = False
    static_candidate_count: int = 0

    def to_log_record(self, row: dict[str, str], phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "url": self.url,
            "source_provider": self.source_provider,
            "source_kind": self.source_kind,
            "source_name": row.get("source_name") or row.get("title"),
            "status_code": self.status_code,
            "content_type": self.content_type,
            "title": self.title,
            "script_count": self.script_count,
            "has_large_script_bundle": self.has_large_script_bundle,
            "dynamic_signals": self.dynamic_signals or [],
            "json_endpoint_hints": (self.json_endpoint_hints or [])[:20],
            "pagination_hints": (self.pagination_hints or [])[:20],
            "camera_text_score": self.camera_text_score,
            "app_shell_score": self.app_shell_score,
            "has_hls_hint": self.has_hls_hint,
            "static_candidate_count": self.static_candidate_count,
        }


@dataclass
class BrowserCaptureDecision:
    url: str
    source_provider: str
    source_kind: str
    selected: bool
    score: int
    reasons: list[str]
    skip_reason: str = ""
    host: str = ""
    phase: str = "primary"
    source_name: str = ""
    static_candidate_count: int = 0
    budget_remaining: dict[str, int] | None = None
    browser_backend: str = "playwright"

    def to_log_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BrowserCaptureResult:
    url: str
    backend: str = "playwright"
    captured_hls_urls: list[str] | None = None
    captured_json_urls: list[str] | None = None
    rendered_html_candidates: int = 0
    total_browser_candidates: int = 0
    network_events_sample: list[dict[str, Any]] | None = None
    elapsed_ms: int = 0
    timed_out: bool = False
    error: str = ""

    def to_log_record(self, row: dict[str, str], phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "url": self.url,
            "backend": self.backend,
            "browser_backend": self.backend,
            "source_provider": row.get("source_provider"),
            "source_kind": row.get("source_kind"),
            "source_name": row.get("source_name") or row.get("title"),
            "elapsed_ms": self.elapsed_ms,
            "captured_hls_urls": len(self.captured_hls_urls or []),
            "captured_json_urls": len(self.captured_json_urls or []),
            "rendered_html_candidates": self.rendered_html_candidates,
            "total_browser_candidates": self.total_browser_candidates,
            "timed_out": self.timed_out,
            "error": self.error,
            "network_events_sample": self.network_events_sample or [],
        }


class DirectorySourceProvider:
    """Expose user-approved directory sources from SOURCES.md as discovery inputs.

    `page`, `feed`, and `direct_hls` entries are used directly. `site` entries are
    expanded into target-aware candidate pages before the root URL is fetched. This
    keeps the simplified architecture intact while making directory mode useful for
    camera-directory home pages such as OpenCCTV: the source registry supplies the
    approved site, and this provider derives generic camera/location paths from the
    target context without adding source-specific crawling logic.
    """

    def __init__(self, policy: SourcePolicy):
        self.policy = policy

    def rows_for_target(self, target: TargetContext) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for entry in self.policy.enabled_allowed_sources():
            if self.policy.is_blocked(entry.url):
                continue
            if entry.source_type == "site":
                rows.extend(_target_aware_site_rows(entry, target))
            rows.append(_row_from_source_entry(entry, target))
        return _dedupe_rows(rows)


class DirectUrlSourceProvider:
    """Expose command-line seed URLs as discovery inputs while respecting global block rules."""

    def __init__(self, urls: list[str], policy: SourcePolicy):
        self.urls = urls
        self.policy = policy

    def rows_for_target(self, target: TargetContext) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for url in self.urls:
            if self.policy.is_blocked(url):
                continue
            entry = SourceEntry(name=url, url=url, source_type="direct_hls" if _looks_like_hls(url) else "page")
            rows.append(_row_from_source_entry(entry, target, provider="direct"))
        return rows


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
        self._walk_json(data, source_url, row, method, out)
        return self._dedupe(out)

    def _walk_json(self, value: Any, source_url: str, row: dict[str, str], method: str, out: list[CameraCandidate]) -> None:
        if isinstance(value, dict):
            feature_candidate = self._candidate_from_geojson_feature(value, source_url, row, method)
            if feature_candidate is not None:
                out.append(feature_candidate)
            out.extend(self._candidates_from_record(value, source_url, row, method))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    self._walk_json(child, source_url, row, method, out)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    self._walk_json(child, source_url, row, method, out)

    def _candidate_from_geojson_feature(self, feature: dict[str, Any], source_url: str, row: dict[str, str], method: str) -> CameraCandidate | None:
        if str(feature.get("type") or "").casefold() != "feature":
            return None
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        lat_lon = _lat_lon_from_geojson_coordinates(coords)
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        urls = _record_media_urls(props, source_url)
        if not urls:
            return None
        candidate = self._candidate_from_stream(urls[0][0], source_url, row, method + "_geojson_feature")
        if lat_lon:
            candidate.lat, candidate.lon = lat_lon
            candidate.coordinate_source = "geojson_geometry"
        candidate.title = _record_title(props) or candidate.title
        candidate.location_text = _record_location_text(props)
        candidate.source_metadata.update(_simple_metadata(props))
        candidate.source_metadata["media_type"] = urls[0][1]
        if urls[0][1] == "image_snapshot":
            candidate.source_metadata["snapshot_url"] = urls[0][0]
        return candidate

    def _candidates_from_record(self, record: dict[str, Any], source_url: str, row: dict[str, str], method: str) -> list[CameraCandidate]:
        flattened = _flatten_camera_record(record)
        lat_lon = _record_lat_lon(flattened)
        urls = _record_media_urls(flattened, source_url)
        if not urls:
            return []
        out: list[CameraCandidate] = []
        for media_url, media_type in urls:
            if self.source_policy.is_blocked(media_url):
                continue
            candidate = self._candidate_from_stream(media_url, source_url, row, method + "_record")
            if lat_lon:
                candidate.lat, candidate.lon = lat_lon
                candidate.coordinate_source = "source_record"
            candidate.title = _record_title(flattened) or candidate.title
            candidate.location_text = _record_location_text(flattened)
            candidate.source_metadata.update(_simple_metadata(flattened))
            candidate.source_metadata["media_type"] = media_type
            if media_type == "image_snapshot":
                candidate.source_metadata["snapshot_url"] = media_url
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
            if row.has_coordinates and not existing.has_coordinates:
                by_key[key] = row
            elif row.title and not existing.title:
                existing.title = row.title
            elif row.location_text and not existing.location_text:
                existing.location_text = row.location_text
            existing.source_metadata.update({k: v for k, v in row.source_metadata.items() if k not in existing.source_metadata or existing.source_metadata[k] in (None, "")})
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
        parts: list[str] = []
        for value in (candidate.location_text, candidate.title):
            if isinstance(value, str) and _specific_candidate_location_text(value, target):
                parts.append(value.strip())
        for key in ("city", "county", "route", "road", "cross_street", "intersection", "direction", "camera_id"):
            value = candidate.source_metadata.get(key)
            if isinstance(value, str) and _specific_candidate_location_text(value, target):
                parts.append(value.strip())
        parts = _dedupe_strings(parts)
        if not parts:
            return None
        suffix_parts = _dedupe_strings([part for part in (target.canonical_target, target.admin_region, target.country) if part])
        suffix = ", ".join(suffix_parts)
        query = ", ".join([parts[0], suffix]) if suffix and suffix.casefold() not in parts[0].casefold() else parts[0]
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



def _looks_like_json_response(url: str, content_type: str, text: str) -> bool:
    ctype = content_type.casefold()
    if "json" in ctype:
        return True
    if url.lower().split("?", 1)[0].endswith(".json"):
        return True
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _record_media_urls(record: dict[str, Any], base_url: str) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    for key, value in record.items():
        key_norm = str(key).replace("-", "_").casefold()
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str) or not item.strip():
                continue
            absolute = urljoin(base_url, item.strip())
            if _looks_like_hls(absolute) or key_norm in URL_KEYS and ".m3u8" in absolute.casefold():
                urls.append((absolute, "hls"))
            elif _looks_like_image(absolute) or key_norm in IMAGE_KEYS:
                # Preview/thumbnail fields are useful metadata when another real
                # stream URL exists, but they are not themselves refreshing camera
                # feeds. Do not promote thumbnail CDN/object-store assets to
                # stream_url candidates.
                if _looks_like_non_camera_asset(absolute) or _looks_like_thumbnail_asset(absolute) or key_norm in THUMBNAIL_IMAGE_KEYS:
                    continue
                urls.append((absolute, "image_snapshot"))
    return _dedupe_media_urls(urls)


def _flatten_camera_record(record: dict[str, Any]) -> dict[str, Any]:
    """Merge common map-layer record wrappers into one searchable mapping."""
    flattened: dict[str, Any] = dict(record)
    for key in ("attributes", "properties", "props"):
        value = record.get(key)
        if isinstance(value, dict):
            flattened.update(value)
    geometry = record.get("geometry")
    if isinstance(geometry, dict):
        flattened.setdefault("geometry", geometry)
        if "x" in geometry and "y" in geometry:
            flattened.setdefault("x", geometry.get("x"))
            flattened.setdefault("y", geometry.get("y"))
        if "longitude" in geometry and "latitude" in geometry:
            flattened.setdefault("longitude", geometry.get("longitude"))
            flattened.setdefault("latitude", geometry.get("latitude"))
        if "coordinates" in geometry:
            flattened.setdefault("coordinates", geometry.get("coordinates"))
    for key in ("location", "position", "point", "centroid"):
        value = record.get(key)
        if isinstance(value, dict):
            flattened.setdefault(key, value)
            for inner_key, inner_value in value.items():
                flattened.setdefault(str(inner_key), inner_value)
    return flattened


def _lat_lon_from_sequence_or_mapping(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        return _record_lat_lon(value)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        first = _float_or_none(value[0])
        second = _float_or_none(value[1])
        if _valid_lat_lon(first, second):
            return first, second
        # GeoJSON and many map APIs use [lon, lat].
        if _valid_lat_lon(second, first):
            return second, first
    return None

def _record_lat_lon(record: dict[str, Any]) -> tuple[float, float] | None:
    lat = None
    lon = None
    for key, value in record.items():
        key_norm = str(key).replace("-", "_").casefold()
        if key_norm in LAT_KEYS:
            lat = _float_or_none(value)
        elif key_norm in LON_KEYS:
            lon = _float_or_none(value)
    if _valid_lat_lon(lat, lon):
        return lat, lon
    for key in ("coordinates", "coords", "latlon", "lat_lng", "latlng"):
        value = record.get(key)
        lat_lon = _lat_lon_from_sequence_or_mapping(value)
        if lat_lon:
            return lat_lon
    for key in ("geometry", "location", "position", "point", "centroid"):
        value = record.get(key)
        if isinstance(value, dict):
            nested = _record_lat_lon(value)
            if nested:
                return nested
        else:
            nested = _lat_lon_from_sequence_or_mapping(value)
            if nested:
                return nested
    return None


def _lat_lon_from_geojson_coordinates(coords: Any) -> tuple[float, float] | None:
    if isinstance(coords, list) and len(coords) >= 2 and not isinstance(coords[0], list):
        lon = _float_or_none(coords[0])
        lat = _float_or_none(coords[1])
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None


def _record_title(record: dict[str, Any]) -> str | None:
    for key in TITLE_KEYS:
        for actual, value in record.items():
            if str(actual).replace("-", "_").casefold() == key and value not in (None, ""):
                return str(value)[:200]
    return None


def _record_location_text(record: dict[str, Any]) -> str | None:
    for key in ("location", "location_text", "road", "route", "city", "county", "district"):
        for actual, value in record.items():
            if str(actual).replace("-", "_").casefold() == key and value not in (None, ""):
                return str(value)[:300]
    return None


def _simple_metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[str(key)] = value
    return metadata


def _media_urls_from_html_tag(tag: Any, base_url: str) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    for attr in ("src", "data-src", "data-original", "data-image", "data-url", "poster"):
        value = tag.get(attr) if hasattr(tag, "get") else None
        if isinstance(value, str) and value.strip():
            urls.extend(_media_urls_from_attribute(value, base_url))
    srcset = tag.get("srcset") if hasattr(tag, "get") else None
    if isinstance(srcset, str):
        for part in srcset.split(","):
            candidate = part.strip().split(" ", 1)[0]
            urls.extend(_media_urls_from_attribute(candidate, base_url))
    return _dedupe_media_urls(urls)


def _media_urls_from_attribute(value: str, base_url: str) -> list[tuple[str, str]]:
    absolute = urljoin(base_url, value.strip())
    if _looks_like_hls(absolute):
        return [(absolute, "hls")]
    if _looks_like_image(absolute):
        return [(absolute, "image_snapshot")]
    return []


def _metadata_from_html_tag(tag: Any) -> dict[str, Any]:
    if tag is None or not hasattr(tag, "attrs"):
        return {}
    out: dict[str, Any] = {}
    for raw_key, raw_value in dict(tag.attrs).items():
        key = str(raw_key).replace("-", "_").casefold()
        if isinstance(raw_value, list):
            value: Any = " ".join(str(part) for part in raw_value)
        else:
            value = raw_value
        if isinstance(value, (str, int, float, bool)):
            out[key] = value
    return out


def _nearby_text(tag: Any) -> str | None:
    parent = getattr(tag, "parent", None)
    if parent is None or not hasattr(parent, "get_text"):
        return None
    text = " ".join(parent.get_text(" ", strip=True).split())
    if not text or len(text) > 180:
        return None
    return text


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    return None


def _looks_like_non_camera_asset(url: str) -> bool:
    lower = url.casefold()
    asset_markers = (
        "og-default", "open_graph", "opengraph", "favicon", "logo", "sprite", "placeholder",
        "avatar", "basemap", "/dark_all/", "/light_all/", "/tile/", "/tiles/", "cartocdn.com",
        "openstreetmap.org/", "leaflet", "mapbox", "googleapis.com", "gstatic.com",
        "apple-touch-icon", "mstile", "mask-icon", "site-icon", "site_icon", "seal_", "/seal",
        "/assets/", "/static/", "/template", "/templates/", "/banner", "/banners/",
        "/icons/", "/icon/", "/images/icons/", "retail", "store-logo", "store_logo",
    )
    if any(marker in lower for marker in asset_markers):
        return True
    if _looks_like_thumbnail_asset(url):
        return True
    path = urlparse(url).path.casefold()
    name = path.rsplit("/", 1)[-1]
    if name in {"default.png", "default.jpg", "blank.png", "blank.jpg", "loading.gif"}:
        return True
    return False


def _looks_like_thumbnail_asset(url: str) -> bool:
    """Return True for preview thumbnails that should not become camera streams.

    Camera directories often include preview images, retail/service thumbnails,
    OpenGraph thumbnails, and CDN/object-store thumbnails. Those may be useful
    as metadata when attached to an already-discovered camera, but they are not
    refreshable camera snapshot endpoints and should not consume image-snapshot
    candidate budget.
    """
    path = unquote(urlparse(url).path).casefold()
    segments = [part for part in path.split("/") if part]
    if any(part in {"thumb", "thumbs", "thumbnail", "thumbnails"} for part in segments):
        return True
    thumbnail_markers = (
        "/services/thumb/", "/services/thumbs/", "/service/thumb/", "/service/thumbnail/",
        "/preview/thumb/", "/previews/thumb/", "/cdn/thumb/", "/cdn-cgi/image/",
    )
    if any(marker in path for marker in thumbnail_markers):
        return True
    name = segments[-1] if segments else ""
    if re.search(r"(?:^|[-_])(thumb|thumbnail|preview)(?:[-_]|$)", name):
        return True
    return False


def _camera_id_from_url(url: str) -> str | None:
    stem = urlparse(url).path.rsplit("/", 1)[-1].split(".", 1)[0]
    stem = unquote(stem).strip()
    return stem or None


def _humanize_camera_slug_from_url(url: str) -> str | None:
    stem = (_camera_id_from_url(url) or "").casefold()
    if not stem or len(stem) < 4:
        return None
    if _looks_like_non_camera_asset(url):
        return None
    text = re.sub(r"[_\-]+", " ", stem)
    # Compact highway identifiers such as sr99/us101/i80 are common in camera image paths.
    text = re.sub(r"sr(\d{1,3})(\d+(?:st|nd|rd|th))", r"SR \1 \2", text)
    text = re.sub(r"\bsr\s*(\d+)", r"SR \1 ", text)
    text = re.sub(r"\bus\s*(\d+)", r"US \1 ", text)
    text = re.sub(r"\bi\s*(\d+)", r"I-\1 ", text)
    text = re.sub(r"\b(nb|sb|eb|wb)\b", lambda m: m.group(1).upper(), text)
    text = re.sub(r"(?<=\d)(nb|sb|eb|wb)", lambda m: " " + m.group(1).upper() + " ", text)
    text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1\2 ", text)
    text = re.sub(r"\bst\b", "St", text)
    text = re.sub(r"\brd\b", "Rd", text)
    text = re.sub(r"\bave\b", "Ave", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not any(re.search(pattern, text, re.I) for pattern in (r"\b(?:I-|SR|US)\s*\d+\b", r"\b\d+(?:st|nd|rd|th)\b", r"\b(?:NB|SB|EB|WB)\b", r"\b(?:St|Rd|Ave)\b")):
        return None
    return text[:120]


def _looks_like_image(url: str) -> bool:
    return bool(re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", url, re.I))


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _dedupe_media_urls(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for url, media_type in values:
        key = url.split("#", 1)[0]
        if key not in seen:
            seen.add(key)
            out.append((key, media_type))
    return out





def _pagination_rows(row: dict[str, str], max_pages: int) -> list[dict[str, str]]:
    url = row.get("url") or ""
    if max_pages <= 1 or not _looks_like_paginated_directory_url(url):
        return []
    rows: list[dict[str, str]] = []
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for page in range(2, max_pages + 1):
        new_query = {key: values[:] for key, values in query.items()}
        new_query["page"] = [str(page)]
        qs = urlencode(new_query, doseq=True)
        page_url = parsed._replace(query=qs).geturl()
        new_row = dict(row)
        new_row["url"] = page_url
        new_row["source_kind"] = row.get("source_kind") or "paginated_page"
        new_row["discovery_note"] = f"pagination_page_{page}"
        rows.append(new_row)
    return rows


def _looks_like_pagination_url(url: str) -> bool:
    lower = url.casefold()
    return any(token in lower for token in ("page=", "/page/", "offset=", "start=", "next", "camera", "webcam", "cctv"))


def _looks_like_paginated_directory_url(url: str) -> bool:
    lower = url.casefold()
    if not lower.startswith("http"):
        return False
    return any(token in lower for token in ("/camera", "/cameras", "/traffic", "/category/", "/livet", "webcam", "cctv"))


def _expand_structured_endpoint_urls(urls: list[str]) -> list[str]:
    expanded: list[str] = []
    for url in urls:
        expanded.append(url)
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if re.search(r"/(?:MapServer|FeatureServer)(?:/\d+)?$", path, re.I):
            base = parsed._replace(query="", fragment="").geturl().rstrip("/")
            if re.search(r"/(?:MapServer|FeatureServer)$", path, re.I):
                # Try a small generic range of layer IDs. Non-existing layers are harmless and logged.
                for layer in range(0, 8):
                    expanded.append(f"{base}/{layer}/query?where=1%3D1&outFields=*&returnGeometry=true&f=json")
            else:
                expanded.append(f"{base}/query?where=1%3D1&outFields=*&returnGeometry=true&f=json")
        elif "/query" in path.casefold() and not parsed.query:
            expanded.append(parsed._replace(query="where=1%3D1&outFields=*&returnGeometry=true&f=json").geturl())
    return _dedupe_strings(expanded)


def _asset_host_discovery_urls(host: str, target: TargetContext) -> list[str]:
    scheme_host = f"https://{host}"
    slugs = _target_region_slugs(target)[:3]
    category_slugs = _camera_category_slugs(target)[:3]
    urls = [scheme_host, f"{scheme_host}/cameras", f"{scheme_host}/camera", f"{scheme_host}/traffic", f"{scheme_host}/cctv"]
    for slug in slugs:
        urls.extend([f"{scheme_host}/{slug}", f"{scheme_host}/cameras/{slug}", f"{scheme_host}/traffic/{slug}"])
        for category in category_slugs:
            urls.append(f"{scheme_host}/cameras/{slug}/category/{category}")
    return _dedupe_strings(urls)

def _target_aware_site_rows(entry: SourceEntry, target: TargetContext) -> list[dict[str, str]]:
    """Generate generic target-aware pages for approved camera-directory sites.

    This is intentionally not a source-specific parser. It derives common public
    camera-directory URL shapes from the resolved target and camera intent, then
    lets the normal fetch/extract pipeline decide which pages actually exist.
    """
    base = entry.url.rstrip("/") + "/"
    region_slugs = _target_region_slugs(target)
    country_slugs = _target_country_slugs(target)
    category_slugs = _camera_category_slugs(target)
    urls: list[str] = []
    for country in country_slugs:
        for region in region_slugs:
            urls.extend(
                [
                    urljoin(base, f"cameras/{country}/{region}"),
                    urljoin(base, f"livetraffic/{country}/{region}"),
                ]
            )
            for category in category_slugs:
                urls.append(urljoin(base, f"cameras/{country}/{region}/category/{category}"))
                for page in range(1, 6):
                    urls.append(urljoin(base, f"cameras/{country}/{region}/category/{category}?page={page}"))
    rows = []
    for url in _dedupe_strings(urls):
        if not url.startswith("http"):
            continue
        row = _row_from_source_entry(entry, target, provider="directory")
        row["url"] = url
        row["source_type"] = "site_target_page"
        rows.append(row)
    return rows


def _target_region_slugs(target: TargetContext) -> list[str]:
    values = [target.admin_region, target.canonical_target, target.target_label, target.intent.place_name]
    # For state/county/region targets, canonical labels often include country
    # punctuation. Keep only useful place fragments and dedupe after slugging.
    slugs: list[str] = []
    for value in values:
        if not value:
            continue
        fragment = str(value).split(",", 1)[0]
        slug = _slugify(fragment)
        if slug and slug not in {"traffic", "traffic-cameras", "cameras", "live-cameras"}:
            slugs.append(slug)
    return _dedupe_strings(slugs) or ["all"]


def _target_country_slugs(target: TargetContext) -> list[str]:
    values = [target.country]
    # Include country fragments from canonical strings such as
    # "California, United States" without assuming a specific test location.
    if target.canonical_target and "," in target.canonical_target:
        values.append(target.canonical_target.rsplit(",", 1)[-1].strip())
    slugs = [_slugify(v) for v in values if v]
    return _dedupe_strings([s for s in slugs if s]) or ["world"]


def _camera_category_slugs(target: TargetContext) -> list[str]:
    intent = (target.intent.camera_type_intent or "camera").casefold().replace("_", " ")
    categories = [intent, "traffic" if "traffic" in intent else "camera"]
    return _dedupe_strings([_slugify(c) for c in categories if c])


def _slugify(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).casefold().strip()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        url = (row.get("url") or "").split("#", 1)[0]
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({**row, "url": url})
    return out

def _row_from_source_entry(entry: SourceEntry, target: TargetContext, provider: str = "directory") -> dict[str, str]:
    return {
        "query": f"{provider}:{target.target_id}",
        "title": entry.name,
        "url": entry.url,
        "snippet": entry.notes or "",
        "source_provider": provider,
        "source_kind": entry.source_type,
        "source_name": entry.name,
        "source_scope_hint": entry.scope_hint or "",
        "source_notes": entry.notes or "",
    }


def _url_query_mapping(url: str) -> dict[str, Any]:
    if not url:
        return {}
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return {key: values[0] for key, values in qs.items() if values}


def _specific_candidate_location_text(value: str, target: TargetContext) -> bool:
    text = value.strip()
    if not text or len(text) < 4:
        return False
    lowered = text.casefold()
    if lowered in {"camera", "cameras", "traffic", "webcam", "snapshot", "image"}:
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:/?=&%-]+", text) and "/" in text:
        return False
    target_bits = [bit.casefold() for bit in (target.canonical_target, target.target_label, target.admin_region, target.country) if isinstance(bit, str)]
    generic_camera_page = any(bit and bit in lowered for bit in target_bits) and any(phrase in lowered for phrase in ("live traffic cameras", "traffic cameras", "road conditions", "camera map", "webcams"))
    has_specific_clue = any(
        re.search(pattern, text, re.I)
        for pattern in (
            r"\b(?:I-|I\s*|SR\s*|US\s*)\d+\b",
            r"\b(?:at|near|and|@)\b",
            r"\b(?:NB|SB|EB|WB|northbound|southbound|eastbound|westbound)\b",
            r"\b\d+(?:st|nd|rd|th)\b",
            r"\b(?:St|Street|Rd|Road|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Hwy|Highway)\b",
        )
    )
    if generic_camera_page and "road conditions" in lowered and not re.search(r"\b(?:at|near|@|I-|SR\s*|US\s*)\d*", text, re.I):
        return False
    if generic_camera_page and not has_specific_clue:
        return False
    return any(ch.isalpha() for ch in text) and (has_specific_clue or not generic_camera_page)



def _limited_scalar_metadata(metadata: dict[str, Any], *, max_items: int = 40, max_value_len: int = 500) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        if len(out) >= max_items:
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = value if not isinstance(value, str) else value[:max_value_len]
            out[str(key)] = text
        elif isinstance(value, list):
            scalar_items = [item for item in value if isinstance(item, (str, int, float, bool))]
            if scalar_items:
                out[str(key)] = scalar_items[:10]
        elif isinstance(value, dict):
            nested = _limited_scalar_metadata(value, max_items=10, max_value_len=120)
            if nested:
                out[str(key)] = nested
    return out


def _candidate_location_inference_evidence_text(candidate: CameraCandidate) -> str:
    values: list[str] = [candidate.stream_url, candidate.source_url or "", candidate.title or "", candidate.location_text or ""]
    for key, value in _limited_scalar_metadata(candidate.source_metadata).items():
        if isinstance(value, str):
            values.extend([str(key), value])
        elif isinstance(value, (int, float, bool)):
            values.extend([str(key), str(value)])
        elif isinstance(value, list):
            values.extend([str(key), " ".join(str(item) for item in value)])
        elif isinstance(value, dict):
            values.extend([str(key), json.dumps(value, ensure_ascii=False)])
    return " ".join(values)


def _candidate_has_location_inference_evidence(candidate: CameraCandidate) -> bool:
    text = _candidate_location_inference_evidence_text(candidate)
    parsed = urlparse(candidate.stream_url)
    path_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", unquote(parsed.path))
    metadata_text = " ".join([candidate.title or "", candidate.location_text or "", str(candidate.source_metadata.get("source_name") or "")])
    return bool(path_tokens or re.search(r"[A-Za-z][A-Za-z0-9_-]{2,}", metadata_text) or re.search(r"[A-Za-z][A-Za-z0-9_-]{2,}", text))


def _normalize_location_inference_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        query = row.get("query")
        if not isinstance(query, str) or not _is_safe_geocode_query(query):
            continue
        variants_value = row.get("variants")
        variants = [v.strip() for v in variants_value if isinstance(v, str) and _is_safe_geocode_query(v)] if isinstance(variants_value, list) else []
        evidence_value = row.get("evidence")
        evidence = [str(v).strip()[:120] for v in evidence_value if isinstance(v, (str, int, float)) and str(v).strip()] if isinstance(evidence_value, list) else []
        confidence = max(0.0, min(1.0, _float_or_none(row.get("confidence")) or 0.0))
        reason = str(row.get("reason") or "")[:500]
        precision = str(row.get("precision") or "unknown")[:80]
        normalized.append(
            {
                "query": query.strip()[:300],
                "variants": _dedupe_strings(variants)[:5],
                "confidence": confidence,
                "evidence": _dedupe_strings(evidence)[:12],
                "reason": reason,
                "precision": precision,
            }
        )
    normalized.sort(key=lambda item: item.get("confidence", 0.0), reverse=True)
    return normalized[:5]


def _is_safe_geocode_query(value: str) -> bool:
    text = value.strip()
    if not text or len(text) < 3 or len(text) > 300:
        return False
    if COORD_RE.search(text):
        return False
    lowered = text.casefold()
    if any(marker in lowered for marker in ("latitude", "longitude", " lat ", " lon ")):
        return False
    if re.fullmatch(r"https?://\S+", text):
        return False
    return any(ch.isalpha() for ch in text)


def _llm_location_evidence_supported(candidate: CameraCandidate, row: dict[str, Any]) -> bool:
    evidence = row.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    haystack = _candidate_location_inference_evidence_text(candidate).casefold()
    supported = 0
    for token in evidence:
        text = str(token).strip().casefold()
        if len(text) < 2:
            continue
        compact = re.sub(r"[^a-z0-9]+", "", text)
        haystack_compact = re.sub(r"[^a-z0-9]+", "", haystack)
        if text in haystack or (compact and compact in haystack_compact):
            supported += 1
    return supported > 0


def _append_target_context_to_query(query: str, target: TargetContext) -> str:
    parts = [query.strip()]
    for value in (target.canonical_target, target.admin_region, target.country):
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if value.casefold() not in ", ".join(parts).casefold():
            parts.append(value)
    return ", ".join(_dedupe_strings(parts))[:300]


def _candidate_location_enrichment_sort_key(candidate: CameraCandidate) -> tuple[int, str]:
    """Prioritize expensive location inference toward likely camera HLS URLs."""
    media_type = _candidate_media_type(candidate)
    has_slug = _url_has_location_like_slug(candidate.stream_url)
    if media_type == "hls" and has_slug:
        return (0, candidate.stream_url)
    if media_type == "hls":
        return (1, candidate.stream_url)
    if media_type == "image_snapshot" and _candidate_has_location_inference_evidence(candidate):
        return (2, candidate.stream_url)
    return (3, candidate.stream_url)


def _url_has_location_like_slug(url: str) -> bool:
    parsed = urlparse(url or "")
    path = unquote(parsed.path or "")
    tokens = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", path) if t]
    generic = {"stream", "playlist", "m3u8", "camera", "cameras", "video", "live", "image", "snapshot", "jpg", "jpeg", "png", "webp"}
    return any(token.casefold() not in generic for token in tokens)


def _is_broad_or_target_level_inference(row: dict[str, Any], query: str, display_name: str, target: TargetContext) -> bool:
    precision = str(row.get("precision") or "").casefold()
    if precision in {"state", "country", "region", "county", "province", "administrative", "admin"}:
        return True
    target_values = [
        str(value).strip()
        for value in (target.canonical_target, target.target_label, target.admin_region, target.country, "United States", "USA")
        if isinstance(value, str) and value.strip()
    ]
    normalized_targets = {_normalize_place_token(value) for value in target_values if value}
    normalized_query = _normalize_place_token(query)
    normalized_display = _normalize_place_token(display_name)
    if normalized_query in normalized_targets or normalized_display in normalized_targets:
        return True
    residual = normalized_query
    for value in sorted(normalized_targets, key=len, reverse=True):
        residual = residual.replace(value, " ")
    residual_tokens = [tok for tok in residual.split() if len(tok) >= 3]
    return not residual_tokens


def _normalize_place_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _haversine_km(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if None in {lat1, lon1, lat2, lon2}:
        return None
    if not (_valid_lat_lon(lat1, lon1) and _valid_lat_lon(lat2, lon2)):
        return None
    radius_km = 6371.0088
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _valid_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def _point_in_bbox(lat: float, lon: float, bbox: dict[str, float]) -> bool:
    return bbox["min_lat"] <= lat <= bbox["max_lat"] and bbox["min_lon"] <= lon <= bbox["max_lon"]


def _looks_like_hls(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".m3u8")


def _float_or_none(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value):
    try:
        return None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None


def _chunks(values: list[CameraCandidate], size: int) -> list[list[CameraCandidate]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
