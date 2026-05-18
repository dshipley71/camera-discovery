from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from camera_discovery.core.models import CameraCandidate, CandidateSet, DiscoveryMode, RunConfig, TargetContext
from camera_discovery.llm.base import ChatMessage, LLMClient
from camera_discovery.llm.factory import build_candidate_review_client
from camera_discovery.sources import SourceEntry, SourcePolicy, load_source_policy
from camera_discovery.utils.io import write_json, write_jsonl
from camera_discovery.utils.json_utils import extract_json_object

M3U8_RE = re.compile(r"https?://[^\s'\"<>]+?\.m3u8(?:\?[^\s'\"<>]*)?|['\"]([^'\"]+?\.m3u8(?:\?[^'\"]*)?)['\"]", re.I)
IMAGE_RE = re.compile(r"https?://[^\s'\"<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\s'\"<>]*)?|['\"]([^'\"]+?\.(?:jpg|jpeg|png|webp)(?:\?[^'\"]*)?)['\"]", re.I)
COORD_RE = re.compile(r"(?<!\d)([-+]?\d{1,2}\.\d{3,})\s*,\s*([-+]?\d{1,3}\.\d{3,})(?!\d)")
JSON_FEED_HINT_RE = re.compile(r"(?:\.json(?:\?|$)|/api/|/feed|/feeds|/layer|/layers|camera|cameras|mapserver|featureserver)", re.I)
URL_KEYS = {"url", "stream", "stream_url", "streamurl", "hls", "hls_url", "hlsurl", "video", "video_url", "src"}
IMAGE_KEYS = {"image", "image_url", "imageurl", "snapshot", "snapshot_url", "snapshoturl", "thumbnail", "thumbnail_url", "thumbnailurl", "preview", "preview_url", "poster", "poster_url"}
LAT_KEYS = {"lat", "latitude", "y"}
LON_KEYS = {"lon", "lng", "long", "longitude", "x"}
TITLE_KEYS = {"name", "title", "label", "description", "camera", "id"}


class DirectorySourceProvider:
    """Expose user-approved directory sources from SOURCES.md as discovery inputs."""

    def __init__(self, policy: SourcePolicy):
        self.policy = policy

    def rows_for_target(self, target: TargetContext) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for entry in self.policy.enabled_allowed_sources():
            if self.policy.is_blocked(entry.url):
                continue
            rows.append(_row_from_source_entry(entry, target))
        return rows


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

    def __init__(self, config: RunConfig, semantic_review_client: LLMClient | None = None):
        self.config = config
        self.semantic_review_client = semantic_review_client
        self.logs_dir = config.output_dir / "logs"
        self.candidates_dir = config.output_dir / "candidates"
        self.source_policy = load_source_policy(config.sources_file, config.block_patterns)
        self.directory_provider = DirectorySourceProvider(self.source_policy)
        self.direct_provider = DirectUrlSourceProvider(config.seed_urls, self.source_policy)

    def discover(self, target: TargetContext) -> CandidateSet:
        queries = self._search_queries(target) if self.config.discovery_mode in {DiscoveryMode.BLIND, DiscoveryMode.BOTH} else []
        results = self._source_rows(target, queries)
        raw: list[CameraCandidate] = []
        for row in self._select_rows(results)[: self.config.max_pages]:
            raw.extend(self._extract_from_source_row(row))
            if len(raw) >= self.config.max_streams:
                break
        raw = raw[: self.config.max_streams]
        unique = self._dedupe(raw)
        for c in raw:
            c.target_id = target.target_id
            c.target_index = target.target_index
            c.target_label = target.target_label or target.canonical_target
        for c in unique:
            c.target_id = target.target_id
            c.target_index = target.target_index
            c.target_label = target.target_label or target.canonical_target
        self._enrich_candidate_coordinates(unique, target)
        self._scope_candidates(unique, target)
        self._apply_llm_candidate_review(unique, target)
        cs = self._build_candidate_set(raw, unique)
        self._write_artifacts(queries, results, cs, target)
        return cs

    def _source_rows(self, target: TargetContext, queries: list[str]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        if self.config.discovery_mode in {DiscoveryMode.BLIND, DiscoveryMode.BOTH}:
            rows.extend(self._blind_search(queries))
        if self.config.discovery_mode in {DiscoveryMode.DIRECTORY, DiscoveryMode.BOTH}:
            rows.extend(self.directory_provider.rows_for_target(target))
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
        camera_intent = (target.intent.camera_type_intent or "public_live").replace("_", " ")
        candidates = [
            f"{base} {camera_intent} cameras",
            f"{base} public camera feed json",
            f"{base} public live cameras m3u8",
            f"{base} traffic cameras live stream",
            f"{base} webcam HLS",
            f"{base} camera map layer feed",
            f"{base} camera snapshots",
        ]
        return _dedupe_strings(candidates)[: self.config.max_search_queries]

    def _blind_search(self, queries: list[str]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
            for query in queries:
                try:
                    resp = client.get(f"https://duckduckgo.com/html/?q={quote_plus(query)}")
                    resp.raise_for_status()
                    rows.extend(self._parse_ddg(query, resp.text))
                except Exception as exc:
                    rows.append({"query": query, "url": "", "title": "", "error": repr(exc), "source_provider": "blind"})
        return rows

    def _parse_ddg(self, query: str, html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
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
        write_jsonl(self.logs_dir / "blocked_source_rows.jsonl", blocked_rows)
        return selected

    def _extract_from_source_row(self, row: dict[str, str]) -> list[CameraCandidate]:
        url = row.get("url") or ""
        if self.source_policy.is_blocked(url):
            return []
        if _looks_like_hls(url):
            return [self._candidate_from_stream(url, url, row, "direct_hls")]
        return self._extract_from_page(url, row)

    def _extract_from_page(self, url: str, row: dict[str, str]) -> list[CameraCandidate]:
        try:
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                text = resp.text
                content_type = resp.headers.get("content-type", "")
                out = self._extract_from_response(url, row, text, content_type)
                if "html" in content_type.lower() or "<html" in text[:1000].lower():
                    out.extend(self._extract_from_linked_feeds(url, row, text, client))
                return self._dedupe(out)
        except Exception:
            return []

    def _extract_from_response(self, url: str, row: dict[str, str], text: str, content_type: str = "") -> list[CameraCandidate]:
        if _looks_like_json_response(url, content_type, text):
            data = self._parse_json_text(text)
            if data is not None:
                return self._extract_from_json_data(data, url, row, "json_endpoint")
        return self._extract_from_text(url, row, text)

    def _extract_from_text(self, url: str, row: dict[str, str], text: str) -> list[CameraCandidate]:
        coords = self._extract_first_coord(text)
        out: list[CameraCandidate] = []
        out.extend(self._extract_hls_from_text(url, row, text, coords, "hls_regex"))
        out.extend(self._extract_images_from_text(url, row, text, coords, "image_snapshot_regex"))
        for blob in self._extract_json_blobs(text):
            out.extend(self._extract_from_json_data(blob, url, row, "javascript_config"))
        return self._dedupe(out)

    def _extract_from_linked_feeds(self, url: str, row: dict[str, str], html: str, client: httpx.Client) -> list[CameraCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        hrefs: list[str] = []
        for tag in soup.select("a[href], link[href], script[src]"):
            href = tag.get("href") or tag.get("src") or ""
            absolute = urljoin(url, href)
            if JSON_FEED_HINT_RE.search(absolute) and not self.source_policy.is_blocked(absolute):
                hrefs.append(absolute)
        out: list[CameraCandidate] = []
        for feed_url in _dedupe_strings(hrefs)[:8]:
            try:
                resp = client.get(feed_url)
                if resp.status_code >= 400:
                    continue
                out.extend(self._extract_from_response(feed_url, row, resp.text, resp.headers.get("content-type", "")))
            except Exception:
                continue
        return self._dedupe(out)

    def _extract_hls_from_text(self, source_url: str, row: dict[str, str], text: str, coords: tuple[float, float] | None, method: str) -> list[CameraCandidate]:
        out: list[CameraCandidate] = []
        for match in M3U8_RE.finditer(text):
            raw = match.group(0).strip("'\"") if match.group(0).startswith("http") else (match.group(1) or "").strip("'\"")
            stream = urljoin(source_url, raw)
            if ".m3u8" in stream.lower() and not self.source_policy.is_blocked(stream):
                candidate = self._candidate_from_stream(stream, source_url, row, method)
                candidate.source_metadata["media_type"] = "hls"
                if coords:
                    candidate.lat, candidate.lon = coords
                    candidate.coordinate_source = "page_text_coordinate"
                out.append(candidate)
        return out

    def _extract_images_from_text(self, source_url: str, row: dict[str, str], text: str, coords: tuple[float, float] | None, method: str) -> list[CameraCandidate]:
        out: list[CameraCandidate] = []
        for match in IMAGE_RE.finditer(text):
            raw = match.group(0).strip("'\"") if match.group(0).startswith("http") else (match.group(1) or "").strip("'\"")
            image_url = urljoin(source_url, raw)
            if not self.source_policy.is_blocked(image_url):
                candidate = self._candidate_from_stream(image_url, source_url, row, method)
                candidate.source_metadata["media_type"] = "image_snapshot"
                candidate.source_metadata["snapshot_url"] = image_url
                if coords:
                    candidate.lat, candidate.lon = coords
                    candidate.coordinate_source = "page_text_coordinate"
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
            if row.has_coordinates and not existing.has_coordinates:
                by_key[key] = row
            elif row.title and not existing.title:
                existing.title = row.title
            elif row.location_text and not existing.location_text:
                existing.location_text = row.location_text
            existing.source_metadata.update({k: v for k, v in row.source_metadata.items() if k not in existing.source_metadata or existing.source_metadata[k] in (None, "")})
        return [by_key[key] for key in order]

    def _enrich_candidate_coordinates(self, candidates: list[CameraCandidate], target: TargetContext) -> None:
        """Populate real candidate coordinates from source metadata or geocoding.

        The enrichment step never invents coordinates. It first extracts lat/lon
        that already exist in source metadata, URL query parameters, or structured
        records. If still missing, it optionally geocodes sufficiently specific
        candidate location text through the same public geocoder path used for
        target resolution. Geocoded points must satisfy the verified target bbox
        when one is available.
        """
        metadata_enriched = 0
        geocode_attempted = 0
        geocode_enriched = 0
        geocode_skipped = 0
        diagnostics: list[dict[str, Any]] = []
        geocode_cache: dict[str, tuple[float, float, str] | None] = {}
        for candidate in candidates:
            if not candidate.has_coordinates:
                lat_lon = self._candidate_lat_lon_from_existing_evidence(candidate)
                if lat_lon:
                    candidate.lat, candidate.lon = lat_lon
                    candidate.coordinate_source = candidate.coordinate_source or "candidate_metadata"
                    candidate.reasons.append("coordinates_extracted_from_candidate_metadata")
                    metadata_enriched += 1
            if candidate.has_coordinates or not self.config.enable_candidate_geocoding:
                continue
            if geocode_attempted >= self.config.max_candidate_geocodes:
                geocode_skipped += 1
                continue
            query = self._candidate_geocode_query(candidate, target)
            if not query:
                geocode_skipped += 1
                continue
            geocode_attempted += 1
            if query not in geocode_cache:
                geocode_cache[query] = self._geocode_candidate_location(query)
            result = geocode_cache[query]
            if result is None:
                diagnostics.append({"stream_url": candidate.stream_url, "query": query, "status": "not_resolved"})
                continue
            lat, lon, display_name = result
            if target.bbox_verified and target.bbox and not _point_in_bbox(lat, lon, target.bbox):
                candidate.reasons.append("candidate_geocode_outside_verified_target_bbox")
                diagnostics.append({"stream_url": candidate.stream_url, "query": query, "status": "outside_target_bbox", "display_name": display_name})
                continue
            candidate.lat = lat
            candidate.lon = lon
            candidate.coordinate_source = "candidate_geocoder"
            candidate.geocoded_query = query
            candidate.geocoded_display_name = display_name
            candidate.reasons.append("coordinates_geocoded_from_candidate_metadata")
            geocode_enriched += 1
            diagnostics.append({"stream_url": candidate.stream_url, "query": query, "status": "resolved", "display_name": display_name, "lat": lat, "lon": lon})
        write_json(
            self.logs_dir / "candidate_coordinate_enrichment.json",
            {
                "candidates": len(candidates),
                "already_coordinate_bearing": sum(1 for c in candidates if c.has_coordinates) - metadata_enriched - geocode_enriched,
                "metadata_enriched": metadata_enriched,
                "geocode_attempted": geocode_attempted,
                "geocode_enriched": geocode_enriched,
                "geocode_skipped": geocode_skipped,
                "max_candidate_geocodes": self.config.max_candidate_geocodes,
                "enable_candidate_geocoding": self.config.enable_candidate_geocoding,
                "diagnostics": diagnostics[:200],
            },
        )

    def _candidate_lat_lon_from_existing_evidence(self, candidate: CameraCandidate) -> tuple[float, float] | None:
        for mapping in (candidate.source_metadata, _url_query_mapping(candidate.stream_url), _url_query_mapping(candidate.source_url or "")):
            lat_lon = _record_lat_lon(mapping)
            if lat_lon:
                return lat_lon
        return None

    def _candidate_geocode_query(self, candidate: CameraCandidate, target: TargetContext) -> str | None:
        parts: list[str] = []
        for value in (candidate.location_text, candidate.title):
            if isinstance(value, str) and _specific_location_text(value):
                parts.append(value.strip())
        for key in ("city", "county", "route", "road", "cross_street", "direction", "source_name"):
            value = candidate.source_metadata.get(key)
            if isinstance(value, str) and _specific_location_text(value):
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
        if not candidates:
            return
        client = self.semantic_review_client or build_candidate_review_client(self.config)
        reviewable = [candidate for candidate in candidates if not (candidate.scope_status == "out_of_scope" and candidate.trust_level == "rejected")][:50]
        if not reviewable:
            return
        payload = [
            {
                "index": candidates.index(candidate),
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
            for candidate in reviewable
        ]
        raw = client.chat(
            [
                ChatMessage("system", "Return strict JSON only. You are an advisory semantic reviewer, not a stream validator."),
                ChatMessage("user", self._candidate_review_prompt(target, payload)),
            ],
            temperature=0.0,
        )
        data = extract_json_object(raw)
        write_json(self.logs_dir / "candidate_semantic_review_llm_raw.json", {"raw": raw, "model": getattr(client, "model", None)})
        write_json(self.logs_dir / "candidate_semantic_review.json", data)
        rows = data.get("candidates") if isinstance(data.get("candidates"), list) else []
        by_index = {index: candidate for index, candidate in enumerate(candidates)}
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = _int_or_none(row.get("index"))
            if index is None or index not in by_index:
                continue
            candidate = by_index[index]
            decision = str(row.get("decision") or "review").casefold()
            if decision not in {"in_scope", "out_of_scope", "review", "unknown"}:
                decision = "review"
            candidate.llm_semantic_decision = decision  # type: ignore[assignment]
            candidate.llm_semantic_confidence = _float_or_none(row.get("confidence"))
            candidate.llm_semantic_reason = str(row.get("reason") or "")[:500]
            candidate.reasons.append(f"llm_semantic_review:{decision}")
            if candidate.scope_status == "out_of_scope" and candidate.trust_level == "rejected":
                continue
            if decision == "out_of_scope" and (candidate.llm_semantic_confidence or 0.0) >= 0.75:
                candidate.scope_status = "out_of_scope"
                candidate.trust_level = "rejected"
            elif decision == "in_scope" and target.bbox_verified and candidate.has_coordinates:
                if candidate.scope_status != "out_of_scope":
                    candidate.scope_status = "in_scope"
            elif decision in {"in_scope", "review"} and candidate.scope_status == "unknown":
                candidate.scope_status = "review"

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
        }
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


def _specific_location_text(value: str) -> bool:
    text = value.strip()
    if not text or len(text) < 4:
        return False
    lowered = text.casefold()
    if lowered in {"camera", "cameras", "traffic", "webcam", "snapshot", "image"}:
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:/?=&%-]+", text) and "/" in text:
        return False
    return any(ch.isalpha() for ch in text)


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
