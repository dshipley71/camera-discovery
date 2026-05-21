from __future__ import annotations

import csv
from dataclasses import asdict
import time
from urllib.parse import urlencode, urljoin, urlparse, urlunparse, parse_qsl
from zipfile import ZIP_DEFLATED, ZipFile

import httpx

from camera_discovery.core.models import (
    CameraCandidate,
    CandidateSet,
    OutputSummary,
    RunConfig,
    TargetContext,
    TrustPolicy,
    ValidationSummary,
)
from camera_discovery.utils.geojson_viewer import write_embedded_camera_map
from camera_discovery.utils.io import write_json, write_jsonl


class ReviewAndValidationPipeline:
    """Validate candidates and write final trusted/untrusted artifacts.

    LLM semantic review may have labeled candidates earlier, but this final stage
    uses deterministic/tool evidence only for stream validation and trusted output
    authorization. Multi-target runs are supported by carrying target_id metadata
    on each candidate and checking each candidate against its target's trust policy.
    """

    def __init__(self, config: RunConfig):
        self.config = config
        self.logs_dir = config.output_dir / "logs"
        self.candidates_dir = config.output_dir / "candidates"

    def run(self, target: TargetContext | list[TargetContext], candidates: CandidateSet):
        targets = target if isinstance(target, list) else [target]
        target_map = {t.target_id: t for t in targets}
        v = ValidationSummary(validation_enabled=self.config.validation_enabled, ffprobe_enabled=self.config.ffprobe_enabled)
        if self.config.validation_enabled and any(t.trust_policy == TrustPolicy.TRUSTED_ALLOWED for t in targets):
            self._validate(candidates, v)
        else:
            v.skipped = len(candidates.unique)
            for c in candidates.review:
                c.validation_status = "not_validated"
                c.trust_level = "untrusted"
        return v, self._write_outputs(targets, target_map, candidates, v)

    def _validate(self, candidates: CandidateSet, v: ValidationSummary) -> None:
        rows = candidates.in_scope or candidates.review
        for c in rows:
            v.attempted += 1
            status = self._validate_candidate(c)
            c.validation_status = status
            if status in {"active_live_unknown", "active_live_verified", "active_image_snapshot_refreshing"}:
                v.live += 1
                c.trust_level = "trusted" if c.scope_status == "in_scope" else "untrusted"
            elif status in {"dead_link", "offline_http", "restricted_http", "active_playlist_dead_segments", "static_image_asset", "image_snapshot_not_image"}:
                v.dead += 1
                c.trust_level = "rejected"
            else:
                v.unknown += 1
                c.trust_level = "untrusted"

    def _validate_candidate(self, candidate: CameraCandidate) -> str:
        media_type = str((candidate.source_metadata or {}).get("media_type") or "").casefold()
        if media_type == "image_snapshot":
            return self._validate_image_snapshot(candidate.stream_url, candidate.source_metadata or {})
        if media_type and media_type not in {"hls", "hls_stream", "video", "unknown"} and ".m3u8" not in candidate.stream_url.casefold():
            return "not_validated_media_type"
        return self._validate_hls(candidate.stream_url)

    def _validate_hls(self, url: str) -> str:
        try:
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
                r = client.get(url)
                if r.status_code in {401, 403}:
                    return "restricted_http"
                if r.status_code >= 400:
                    return "offline_http"
                if "#EXTM3U" not in r.text[:4096]:
                    return "decode_failed"
                if not self.config.ffprobe_enabled:
                    return "active_live_unknown"
                segment_url = self._first_playlist_segment_url(url, r.text)
                if not segment_url:
                    return "active_live_unknown"
                try:
                    segment = client.head(segment_url)
                    if 200 <= segment.status_code < 300:
                        return "active_live_verified"
                    return "active_playlist_dead_segments"
                except Exception:
                    return "active_playlist_dead_segments"
        except Exception:
            return "dead_link"

    def _first_playlist_segment_url(self, playlist_url: str, playlist_body: str) -> str | None:
        for line in playlist_body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            clean = stripped.split("?", 1)[0].casefold()
            if clean.endswith(".ts") or clean.endswith(".m3u8"):
                return urljoin(playlist_url, stripped)
        return None

    def _validate_image_snapshot(self, url: str, metadata: dict | None = None) -> str:
        """Validate that an image snapshot endpoint is a real image and appears refreshable.

        This performs live HTTP checks. Static web assets are rejected; image
        endpoints that return a valid image but do not change during the sampling
        window remain untrusted/unknown rather than being promoted to live.
        """
        if _looks_like_static_snapshot_asset(url):
            return "static_image_asset"
        try:
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
                first = client.get(_cache_busted_url(url), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
                first_status = _snapshot_http_status(first)
                if first_status:
                    return first_status
                if _headers_indicate_static_asset(first.headers):
                    return "static_image_asset"
                delay_value = _camera_refresh_rate_seconds(metadata or {})
                delay = max(0.0, float(delay_value if delay_value is not None else getattr(self.config, "image_snapshot_refresh_delay_seconds", 2.0)))
                if delay:
                    time.sleep(delay)
                second = client.get(_cache_busted_url(url), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
                second_status = _snapshot_http_status(second)
                if second_status:
                    return second_status
                if _headers_indicate_static_asset(second.headers):
                    return "static_image_asset"
                if _snapshot_responses_differ(first, second):
                    return "active_image_snapshot_refreshing"
                return "active_image_snapshot_static_unverified"
        except Exception:
            return "dead_link"

    def _write_outputs(self, targets: list[TargetContext], target_map: dict[str, TargetContext], candidates: CandidateSet, v: ValidationSummary) -> OutputSummary:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        trusted_allowed = {t.target_id for t in targets if t.trust_policy == TrustPolicy.TRUSTED_ALLOWED and t.bbox_verified}
        trusted = [
            c for c in candidates.unique
            if c.trust_level == "trusted" and c.scope_status == "in_scope" and c.has_coordinates and c.target_id in trusted_allowed
        ]
        trusted_keys = {(c.stream_url, c.target_id) for c in trusted}
        coordinate_bearing = [c for c in candidates.unique if c.has_coordinates]
        review = [c for c in coordinate_bearing if (c.stream_url, c.target_id) not in trusted_keys]
        out = OutputSummary()
        out.coordinate_bearing_candidates = len(coordinate_bearing)
        if trusted:
            out.trusted_geojson_created = True
            out.trusted_geojson_features_written = len(trusted)
            self._write_geojson(self.config.output_dir / "camera.geojson", trusted, trusted=True, target_map=target_map)
            write_jsonl(self.config.output_dir / "camera_inventory.jsonl", [asdict(c) for c in trusted])
            self._write_cameras_md(trusted)
        elif (self.config.output_dir / "camera.geojson").exists():
            (self.config.output_dir / "camera.geojson").unlink()
        if review and self.config.allow_untrusted_review_output:
            out.untrusted_geojson_created = True
            out.untrusted_geojson_features_written = len(review)
            self._write_geojson(self.config.output_dir / "untrusted_camera_candidates.geojson", review, trusted=False, target_map=target_map)
            write_jsonl(self.candidates_dir / "untrusted_camera_candidates_source_rows.jsonl", [asdict(c) for c in review])
        elif (self.config.output_dir / "untrusted_camera_candidates.geojson").exists():
            (self.config.output_dir / "untrusted_camera_candidates.geojson").unlink()
        out.coordinate_bearing_geojson_features_written = out.trusted_geojson_features_written + out.untrusted_geojson_features_written
        out.coordinate_bearing_without_geojson = max(0, out.coordinate_bearing_candidates - out.coordinate_bearing_geojson_features_written)
        table_path = self._write_candidate_table(candidates.unique)
        out.camera_candidates_table_csv = str(table_path)
        out.camera_candidates_table_rows = len(candidates.unique)
        write_jsonl(self.logs_dir / "validation_results.jsonl", [asdict(c) for c in candidates.unique])
        write_json(self.logs_dir / "validation_summary.json", asdict(v))
        out.map_html = str(self._write_map())
        out.review_artifacts_zip = str(self.config.output_dir / "review_artifacts.zip")
        self._write_run_explanation(targets, candidates, v, out)
        out.review_artifacts_zip = str(self._package_review_artifacts())
        write_json(self.logs_dir / "output_summary.json", asdict(out))
        return out

    def _write_run_explanation(self, targets: list[TargetContext], candidates: CandidateSet, v: ValidationSummary, out: OutputSummary) -> None:
        media_counts: dict[str, int] = {}
        provider_counts: dict[str, int] = {}
        missing_coordinates = 0
        for candidate in candidates.unique:
            metadata = candidate.source_metadata or {}
            media = str(metadata.get("media_type") or "unknown")
            provider = str(metadata.get("source_provider") or candidate.discovery_method or "unknown")
            media_counts[media] = media_counts.get(media, 0) + 1
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            if not candidate.has_coordinates:
                missing_coordinates += 1
        explanation = {
            "plain_language_summary": [
                f"Resolved {len(targets)} target(s): " + ", ".join(t.canonical_target or t.target_label or t.target_id for t in targets),
                f"Found {len(candidates.unique)} unique candidate camera record(s).",
                f"{out.coordinate_bearing_candidates} candidate(s) had real coordinates; {missing_coordinates} remain table-only because no verified coordinate was extracted or geocoded.",
                f"Trusted camera.geojson created: {out.trusted_geojson_created} ({out.trusted_geojson_features_written} feature(s)).",
                f"Untrusted review GeoJSON created: {out.untrusted_geojson_created} ({out.untrusted_geojson_features_written} feature(s)).",
                f"Coordinate-bearing GeoJSON coverage: {out.coordinate_bearing_geojson_features_written}/{out.coordinate_bearing_candidates} feature(s) written; {out.coordinate_bearing_without_geojson} coordinate-bearing candidate(s) were not written to a GeoJSON artifact.",
                "Fast profile is review-only; use balanced/full validation when you want stream validation and trusted output authorization.",
            ],
            "media_type_counts": media_counts,
            "source_provider_counts": provider_counts,
            "geojson_metrics": {
                "coordinate_bearing_candidates": out.coordinate_bearing_candidates,
                "trusted_geojson_features": out.trusted_geojson_features_written,
                "untrusted_geojson_features": out.untrusted_geojson_features_written,
                "coordinate_bearing_geojson_features_written": out.coordinate_bearing_geojson_features_written,
                "coordinate_bearing_without_geojson": out.coordinate_bearing_without_geojson,
            },
            "validation": asdict(v),
            "outputs": asdict(out),
            "interpretation": {
                "camera_geojson": "Trusted, validated, in-scope coordinate-bearing camera inventory. Not written when validation is disabled or no trusted records exist.",
                "untrusted_camera_candidates_geojson": "Every coordinate-bearing candidate not written to trusted camera.geojson. These are not trusted inventory and may include rejected, out-of-scope, unknown, or review-only records for audit/map analysis.",
                "camera_candidates_table_csv": "All non-rejected review candidates, including rows without coordinates that cannot be mapped yet.",
                "map_html": "Interactive map for coordinate-bearing trusted/untrusted GeoJSON only.",
            },
        }
        write_json(self.logs_dir / "run_explanation.json", explanation)
        lines = ["# Camera Discovery Run Explanation", ""]
        lines.extend(f"- {item}" for item in explanation["plain_language_summary"])
        lines.append("")
        lines.append("## Media types")
        lines.extend(f"- {key}: {value}" for key, value in sorted(media_counts.items()))
        lines.append("")
        lines.append("## Source providers")
        lines.extend(f"- {key}: {value}" for key, value in sorted(provider_counts.items()))
        lines.append("")
        lines.append("## Output meaning")
        for key, value in explanation["interpretation"].items():
            lines.append(f"- `{key}`: {value}")
        (self.config.output_dir / "RUN_EXPLANATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_candidate_table(self, rows: list[CameraCandidate]):
        """Write a CSV table from all non-rejected candidates, including rows without coordinates."""
        path = self.config.output_dir / "camera_candidates_table.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "name",
            "target_label",
            "location_text",
            "location_display",
            "camera_type",
            "raw_camera_type",
            "camera_id",
            "route",
            "direction",
            "city",
            "county",
            "district",
            "owner",
            "agency",
            "json_endpoint_url",
            "json_record_path",
            "json_record_schema_hint",
            "geocode_query_basis",
            "stream_url",
            "source_url",
            "latitude",
            "longitude",
            "coordinate_source",
            "geocoded_query",
            "geocoded_display_name",
            "thumbnail_url",
            "camera_refresh_rate",
            "map_refresh_rate_seconds",
            "media_type",
            "trust_level",
            "validation_status",
            "scope_status",
            "discovery_method",
            "review_required",
            "target_id",
            "llm_semantic_decision",
            "llm_semantic_reason",
            "reasons",
        ]
        visible = [row for row in rows if row.trust_level != "rejected"]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in visible:
                metadata = row.source_metadata or {}
                media_type = metadata.get("media_type")
                writer.writerow(
                    {
                        "name": row.title or metadata.get("source_name") or "Camera candidate",
                        "target_label": row.target_label,
                        "location_text": row.location_text,
                        "location_display": _camera_location_display(row, None),
                        "camera_type": metadata.get("camera_type"),
                        "raw_camera_type": metadata.get("raw_camera_type"),
                        "camera_id": metadata.get("camera_id") or metadata.get("id"),
                        "route": metadata.get("route") or metadata.get("road"),
                        "direction": metadata.get("direction"),
                        "city": metadata.get("city"),
                        "county": metadata.get("county"),
                        "district": metadata.get("district") or metadata.get("region"),
                        "owner": metadata.get("owner"),
                        "agency": metadata.get("agency"),
                        "json_endpoint_url": metadata.get("json_endpoint_url"),
                        "json_record_path": metadata.get("json_record_path"),
                        "json_record_schema_hint": metadata.get("json_record_schema_hint"),
                        "geocode_query_basis": "; ".join(metadata.get("geocode_query_basis") or []) if isinstance(metadata.get("geocode_query_basis"), list) else metadata.get("geocode_query_basis"),
                        "stream_url": row.stream_url,
                        "source_url": row.source_url,
                        "latitude": row.lat,
                        "longitude": row.lon,
                        "coordinate_source": row.coordinate_source,
                        "geocoded_query": row.geocoded_query,
                        "geocoded_display_name": row.geocoded_display_name,
                        "thumbnail_url": metadata.get("snapshot_url") or metadata.get("thumbnail_url") or metadata.get("image_url"),
                        "camera_refresh_rate": _camera_refresh_rate(metadata),
                        "map_refresh_rate_seconds": _camera_map_refresh_rate_seconds(metadata, self.config.image_snapshot_refresh_delay_seconds) if media_type == "image_snapshot" else None,
                        "media_type": media_type,
                        "trust_level": row.trust_level,
                        "validation_status": row.validation_status,
                        "scope_status": row.scope_status,
                        "discovery_method": row.discovery_method,
                        "review_required": row.trust_level != "trusted",
                        "target_id": row.target_id,
                        "llm_semantic_decision": row.llm_semantic_decision,
                        "llm_semantic_reason": row.llm_semantic_reason,
                        "reasons": "; ".join(row.reasons),
                    }
                )
        write_json(
            self.logs_dir / "camera_candidates_table_status.json",
            {"path": str(path), "rows": len(visible), "includes_rows_without_coordinates": True},
        )
        return path

    def _write_geojson(self, path, rows: list[CameraCandidate], *, trusted: bool, target_map: dict[str, TargetContext]) -> None:
        feats = []
        for c in rows:
            if not c.has_coordinates:
                continue
            target = target_map.get(c.target_id or "")
            props = asdict(c)
            metadata = c.source_metadata or {}
            media_type = metadata.get("media_type") or ("hls" if ".m3u8" in c.stream_url.casefold() else None)
            snapshot_url = metadata.get("snapshot_url") or metadata.get("thumbnail_url") or metadata.get("image_url")
            if media_type == "image_snapshot" and not snapshot_url:
                snapshot_url = c.stream_url
            camera_refresh_rate = _camera_refresh_rate(metadata)
            map_refresh_rate = _camera_map_refresh_rate_seconds(metadata, self.config.image_snapshot_refresh_delay_seconds) if media_type == "image_snapshot" else None
            props.update(
                {
                    "name": c.title or metadata.get("source_name") or "Camera candidate",
                    "location_display": _camera_location_display(c, target),
                    "camera_type": metadata.get("camera_type"),
                    "raw_camera_type": metadata.get("raw_camera_type"),
                    "camera_id": metadata.get("camera_id") or metadata.get("id"),
                    "camera_name": metadata.get("camera_name"),
                    "route": metadata.get("route") or metadata.get("road"),
                    "direction": metadata.get("direction"),
                    "intersection": metadata.get("intersection"),
                    "cross_street": metadata.get("cross_street"),
                    "city": metadata.get("city"),
                    "county": metadata.get("county"),
                    "district": metadata.get("district") or metadata.get("region"),
                    "camera_status": metadata.get("camera_status"),
                    "owner": metadata.get("owner"),
                    "agency": metadata.get("agency"),
                    "json_endpoint_url": metadata.get("json_endpoint_url"),
                    "json_record_path": metadata.get("json_record_path"),
                    "json_record_schema_hint": metadata.get("json_record_schema_hint"),
                    "media_type": media_type,
                    "snapshot_url": snapshot_url,
                    "thumbnail_url": snapshot_url,
                    "camera_refresh_rate": camera_refresh_rate,
                    "map_refresh_rate_seconds": map_refresh_rate,
                    "image_snapshot_refresh_delay_seconds": map_refresh_rate,
                    "trust_level": "trusted" if trusted else (c.trust_level or "untrusted"),
                    "output_policy": "trusted" if trusted else "review_only",
                    "review_required": not trusted,
                    "trusted_inventory_candidate": trusted,
                    "trusted_geojson_candidate": trusted,
                    "untrusted_reason": None if trusted else _untrusted_reason(c, target),
                    "target_bbox_trusted": bool(target and target.bbox_verified),
                    "target_id": c.target_id,
                    "target_label": c.target_label,
                    "target_index": c.target_index,
                }
            )
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c.lon, c.lat]}, "properties": props})
        write_json(path, {"type": "FeatureCollection", "features": feats})
        write_json(
            self.logs_dir / ("trusted_camera_geojson_status.json" if trusted else "untrusted_camera_candidates_geojson_status.json"),
            {"created": bool(feats), "features": len(feats), "path": str(path)},
        )

    def _write_cameras_md(self, rows: list[CameraCandidate]) -> None:
        lines = [
            "# Trusted Camera Inventory\n",
            "<!-- Legacy columns: | Name | Location | Latitude | Longitude | Stream URL | Source URL | -->",
            "| Name | Location | Camera Type | Camera ID | Media Type | Refresh Rate | Latitude | Longitude | Stream/Media URL | Source URL |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            metadata = r.source_metadata or {}
            media_type = metadata.get("media_type") or ("hls" if ".m3u8" in r.stream_url.casefold() else "")
            values = [
                r.title or metadata.get("camera_name") or "Camera",
                _camera_location_display(r, None) or "",
                metadata.get("camera_type") or "",
                metadata.get("camera_id") or metadata.get("id") or "",
                media_type or "",
                _camera_refresh_rate(metadata) or "",
                str(r.lat) if r.lat is not None else "",
                str(r.lon) if r.lon is not None else "",
                r.stream_url,
                r.source_url or metadata.get("json_endpoint_url") or "",
            ]
            escaped = [str(value).replace("|", "\\|") for value in values]
            lines.append("| " + " | ".join(escaped) + " |")
        (self.config.output_dir / "cameras.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def _write_map(self):
        return write_embedded_camera_map(self.config.output_dir, output_name="map.html")

    def _package_review_artifacts(self):
        zpath = self.config.output_dir / "review_artifacts.zip"
        with ZipFile(zpath, "w", ZIP_DEFLATED) as z:
            for rel in ["camera.geojson", "untrusted_camera_candidates.geojson", "camera_inventory.jsonl", "cameras.md", "map.html", "camera_candidates_table.csv", "RUN_EXPLANATION.md"]:
                p = self.config.output_dir / rel
                if p.exists():
                    z.write(p, rel)
            for sub in ["logs", "candidates"]:
                folder = self.config.output_dir / sub
                if folder.exists():
                    for p in folder.rglob("*"):
                        if p.is_file():
                            z.write(p, str(p.relative_to(self.config.output_dir)))
        return zpath


def _camera_location_display(candidate: CameraCandidate, target: TargetContext | None) -> str | None:
    metadata = candidate.source_metadata or {}
    for value in [
        candidate.location_text,
        metadata.get("location_display"),
        candidate.geocoded_display_name,
        metadata.get("location"),
        metadata.get("location_text"),
        metadata.get("intersection"),
        metadata.get("cross_street"),
        metadata.get("road"),
        metadata.get("route"),
        metadata.get("direction"),
        metadata.get("city"),
        metadata.get("county"),
        metadata.get("district"),
        metadata.get("camera_name"),
        candidate.title,
    ]:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    if target:
        for value in [target.canonical_target, target.target_label]:
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _camera_refresh_rate(metadata: dict) -> str | int | float | None:
    for key in (
        "camera_refresh_rate",
        "refresh_rate_seconds",
        "refresh_rate",
        "refresh_interval",
        "refresh_interval_seconds",
        "update_interval",
        "update_interval_seconds",
        "currentImageUpdateFrequency",
        "referenceImageUpdateFrequency",
        "currentimageupdatefrequency",
        "referenceimageupdatefrequency",
        "updateFrequency",
        "update_frequency",
        "image_snapshot_refresh_delay_seconds",
        "map_refresh_rate_seconds",
    ):
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _camera_refresh_rate_seconds(metadata: dict) -> float | None:
    value = _camera_refresh_rate(metadata)
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    import re
    match = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b", text, re.I)
    if match:
        amount = float(match.group(1))
        return amount * 60 if match.group(2).casefold().startswith("m") else amount
    return None


def _camera_map_refresh_rate_seconds(metadata: dict, default_seconds: float) -> float | int | str | None:
    value = _camera_refresh_rate_seconds(metadata)
    if value is None:
        return default_seconds
    return int(value) if float(value).is_integer() else value


def _untrusted_reason(candidate: CameraCandidate, target: TargetContext | None) -> str:
    reasons: list[str] = []
    if candidate.trust_level == "rejected":
        reasons.append("candidate trust_level is rejected")
    if candidate.scope_status == "out_of_scope":
        reasons.append("candidate scope_status is out_of_scope")
    if candidate.validation_status:
        reasons.append(f"validation_status={candidate.validation_status}")
    if candidate.llm_semantic_decision and candidate.llm_semantic_decision != "in_scope":
        reasons.append(f"llm_semantic_decision={candidate.llm_semantic_decision}")
    if target and not target.bbox_verified:
        reasons.append("target bbox is not verified for trusted output")
    reasons.extend(candidate.reasons)
    if not reasons:
        reasons.append("not selected for trusted GeoJSON")
    return "; ".join(dict.fromkeys(str(reason) for reason in reasons if reason))


def _looks_like_static_snapshot_asset(url: str) -> bool:
    lower = url.casefold()
    static_markers = (
        "/services/thumb/", "/services/thumbs/", "/thumb/", "/thumbs/", "/thumbnail/", "/thumbnails/",
        "favicon", "apple-touch-icon", "logo", "sprite", "placeholder", "avatar", "/icons/", "/icon/",
        "/assets/", "/static/", "/template", "/banner", "seal_", "/seal", "retail",
    )
    return any(marker in lower for marker in static_markers)


def _cache_busted_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_camera_discovery_refresh", str(time.time_ns())))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment))


def _snapshot_http_status(response: httpx.Response) -> str | None:
    if response.status_code in {401, 403}:
        return "restricted_http"
    if response.status_code >= 400:
        return "offline_http"
    content_type = response.headers.get("content-type", "").casefold()
    body = response.content or b""
    if not (content_type.startswith("image/") or _bytes_look_like_image(body)):
        return "image_snapshot_not_image"
    return None


def _bytes_look_like_image(body: bytes) -> bool:
    if len(body) < 8:
        return False
    return (
        body.startswith(b"\xff\xd8\xff")
        or body.startswith(b"\x89PNG\r\n\x1a\n")
        or (body.startswith(b"RIFF") and body[8:12] == b"WEBP")
        or body.startswith(b"GIF87a")
        or body.startswith(b"GIF89a")
    )


def _headers_indicate_static_asset(headers: httpx.Headers) -> bool:
    cache_control = headers.get("cache-control", "").casefold()
    if "immutable" in cache_control:
        return True
    match = __import__("re").search(r"max-age=(\d+)", cache_control)
    if match and int(match.group(1)) >= 86400:
        return True
    return False


def _snapshot_responses_differ(first: httpx.Response, second: httpx.Response) -> bool:
    first_etag = first.headers.get("etag")
    second_etag = second.headers.get("etag")
    if first_etag and second_etag and first_etag != second_etag:
        return True
    first_modified = first.headers.get("last-modified")
    second_modified = second.headers.get("last-modified")
    if first_modified and second_modified and first_modified != second_modified:
        return True
    return first.content != second.content
