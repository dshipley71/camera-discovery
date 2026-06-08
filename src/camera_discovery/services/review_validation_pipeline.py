from __future__ import annotations

import concurrent.futures
import csv
import json
import shutil
import subprocess
from dataclasses import asdict
import threading
import time
from typing import Any, Callable
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
from camera_discovery.discovery.candidate_priority import (
    candidate_priority_label,
    prioritize_candidates,
    priority_bucket_counts,
)
from camera_discovery.utils.geojson_viewer import write_embedded_camera_map
from camera_discovery.utils.io import write_json, write_jsonl
from camera_discovery.sources import load_source_policy
from camera_discovery.utils.playlists import (
    build_media_validation_dashboard,
    export_candidate_playlists,
    media_type_for_row,
    status_bucket,
)
from camera_discovery.utils.url_safety import is_private_or_local_media_url, redact_url_userinfo
from camera_discovery.passive_intelligence import (
    add_passive_intelligence_to_dashboard,
    candidate_evidence_record,
    enrich_candidate_with_passive_intelligence,
    http_metadata_from_response,
    passive_intelligence_summary,
)


class ReviewAndValidationPipeline:
    """Validate candidates and write final trusted/untrusted artifacts.

    LLM semantic review may have labeled candidates earlier, but this final stage
    uses deterministic/tool evidence only for stream validation and trusted output
    authorization. Multi-target runs are supported by carrying target_id metadata
    on each candidate and checking each candidate against its target's trust policy.
    """

    def __init__(self, config: RunConfig, progress_callback: Callable[[str, dict[str, Any]], None] | None = None):
        self.config = config
        self.progress_callback = progress_callback
        self.logs_dir = config.output_dir / "logs"
        self.candidates_dir = config.output_dir / "candidates"
        self._thread_local = threading.local()
        self._validation_clients: list[httpx.Client] = []
        self._validation_clients_lock = threading.Lock()
        self._validation_result_cache: dict[str, dict[str, Any]] = {}
        self._validation_result_cache_lock = threading.Lock()
        self.source_policy = load_source_policy(config.sources_file, config.block_patterns)

    def run(self, target: TargetContext | list[TargetContext], candidates: CandidateSet, progress_callback: Callable[[str, dict[str, Any]], None] | None = None):
        targets = target if isinstance(target, list) else [target]
        target_map = {t.target_id: t for t in targets}
        if progress_callback is not None:
            self.progress_callback = progress_callback
        v = ValidationSummary(
            validation_enabled=self.config.validation_enabled,
            ffprobe_enabled=self.config.ffprobe_enabled,
            validation_workers=self.config.validation_workers if self.config.validation_enabled else 0,
            http_timeout=self.config.http_timeout,
            parallel_validation=bool(self.config.validation_enabled and self.config.validation_workers > 1),
        )
        if self.config.validation_enabled and any(t.trust_policy == TrustPolicy.TRUSTED_ALLOWED for t in targets):
            self._validate(candidates, v)
        else:
            v.skipped = len(candidates.unique)
            for c in candidates.review:
                if not c.validation_status:
                    c.validation_status = "not_validated"
                if c.trust_level != "trusted":
                    c.trust_level = c.trust_level or "untrusted"
        return v, self._write_outputs(targets, target_map, candidates, v)

    def _validate(self, candidates: CandidateSet, v: ValidationSummary) -> None:
        for candidate in candidates.unique:
            enrich_candidate_with_passive_intelligence(candidate, self.source_policy)
        rows = prioritize_candidates(candidates.in_scope or candidates.review)
        worker_count = min(max(1, self.config.validation_workers), max(1, len(rows)))
        v.validation_workers = worker_count if rows else 0
        v.http_timeout = self.config.http_timeout
        v.parallel_validation = bool(rows and worker_count > 1)
        write_json(
            self.logs_dir / "validation_priority_summary.json",
            {
                "selected_candidates": len(rows),
                "selected_by_priority_bucket": priority_bucket_counts(rows),
                "selected_by_evidence_band": _candidate_evidence_band_counts(rows),
                "validation_prioritized_by_evidence": True,
                "validation_workers": v.validation_workers,
                "http_timeout": v.http_timeout,
                "parallel_validation": v.parallel_validation,
            },
        )
        self._emit_validation_progress(
            "validation_candidates_selected",
            {
                "total": len(rows),
                "selected_candidates": len(rows),
                "validation_workers": v.validation_workers,
                "http_timeout": v.http_timeout,
                "ffprobe_enabled": self.config.ffprobe_enabled,
                "parallel_validation": v.parallel_validation,
            },
        )
        if not rows:
            self._emit_validation_progress("validation_complete", self._validation_progress_payload(v, total=0, completed=0))
            return

        statuses: list[str | None] = [None] * len(rows)
        progress_counts = {"attempted": 0, "live": 0, "dead": 0, "unknown": 0}
        completed = 0
        try:
            if worker_count == 1:
                self._get_thread_validation_client(create=True)
                try:
                    for index, candidate in enumerate(rows):
                        status = self._safe_validate_candidate(candidate)
                        statuses[index] = status
                        completed = self._record_validation_progress(progress_counts, status, completed, len(rows), v.validation_workers)
                finally:
                    self._close_validation_clients()
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="camera-validation") as executor:
                    future_map = {executor.submit(self._validate_indexed_candidate, index, candidate): index for index, candidate in enumerate(rows)}
                    try:
                        for future in concurrent.futures.as_completed(future_map):
                            index, status = future.result()
                            statuses[index] = status
                            completed = self._record_validation_progress(progress_counts, status, completed, len(rows), v.validation_workers)
                    except BaseException:
                        for pending in future_map:
                            pending.cancel()
                        raise
                self._close_validation_clients()
        finally:
            self._close_validation_clients()

        for candidate, status in zip(rows, statuses, strict=False):
            final_status = status or "dead_link"
            v.attempted += 1
            self._apply_validation_status(candidate, final_status, v)
            enrich_candidate_with_passive_intelligence(candidate, self.source_policy)
        self._emit_validation_progress("validation_complete", self._validation_progress_payload(v, total=len(rows), completed=len(rows)))

    def _validate_indexed_candidate(self, index: int, candidate: CameraCandidate) -> tuple[int, str]:
        self._get_thread_validation_client(create=True)
        return index, self._safe_validate_candidate(candidate)

    def _safe_validate_candidate(self, candidate: CameraCandidate) -> str:
        key = _normalized_validation_url(candidate.stream_url)
        with self._validation_result_cache_lock:
            cached = self._validation_result_cache.get(key)
        if cached is not None:
            candidate.source_metadata.update(cached)
            candidate.source_metadata["validation_result_reused"] = True
            return str(cached.get("validation_status") or "unknown_media_unclassified")
        try:
            status = self._validate_candidate(candidate)
        except Exception as exc:
            status = "dead"
            candidate.source_metadata.setdefault("validation_error", repr(exc)[:300])
        result_metadata = {
            key: value
            for key, value in (candidate.source_metadata or {}).items()
            if key in {"media_type", "normalized_media_type", "validator_name", "validation_status", "validation_reason", "validation_error", "validation_elapsed_ms", "validation_full_mode"}
        }
        result_metadata.setdefault("validation_status", status)
        with self._validation_result_cache_lock:
            self._validation_result_cache.setdefault(key, result_metadata)
        return status

    def _record_validation_progress(
        self,
        progress_counts: dict[str, int],
        status: str,
        completed: int,
        total: int,
        worker_count: int,
    ) -> int:
        completed += 1
        progress_counts["attempted"] += 1
        category = _validation_status_category(status)
        progress_counts[category] += 1
        payload = {
            "completed": completed,
            "total": total,
            "attempted": progress_counts["attempted"],
            "live": progress_counts["live"],
            "dead": progress_counts["dead"],
            "unknown": progress_counts["unknown"],
            "validation_workers": worker_count,
            "http_timeout": self.config.http_timeout,
            "ffprobe_enabled": self.config.ffprobe_enabled,
            "status": status,
        }
        self._emit_validation_progress("validation_candidate_processed", payload)
        return completed

    def _validation_progress_payload(self, v: ValidationSummary, *, total: int, completed: int) -> dict[str, object]:
        return {
            "completed": completed,
            "total": total,
            "attempted": v.attempted,
            "live": v.live,
            "dead": v.dead,
            "unknown": v.unknown,
            "skipped": v.skipped,
            "validation_workers": v.validation_workers,
            "http_timeout": v.http_timeout,
            "ffprobe_enabled": v.ffprobe_enabled,
            "parallel_validation": v.parallel_validation,
        }

    def _emit_validation_progress(self, event: str, payload: dict[str, object]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event, payload)

    def _apply_validation_status(self, candidate: CameraCandidate, status: str, v: ValidationSummary) -> None:
        candidate.validation_status = status
        category = _validation_status_category(status)
        if category == "live":
            v.live += 1
            candidate.trust_level = "trusted" if candidate.scope_status == "in_scope" else "untrusted"
        elif category == "dead":
            v.dead += 1
            candidate.trust_level = "rejected"
        else:
            v.unknown += 1
            candidate.trust_level = "untrusted"

    def _validate_candidate(self, candidate: CameraCandidate) -> str:
        return self._validate_candidate_with_dispatcher(candidate)

    def _validate_candidate_with_dispatcher(self, candidate: CameraCandidate, *, allow_unknown_delegate: bool = True) -> str:
        started_at = time.monotonic()
        metadata = candidate.source_metadata or {}
        candidate.source_metadata = metadata
        original_media_type = str(metadata.get("media_type") or "")
        normalized_media_type = _normalized_media_type_for_candidate(candidate)
        metadata["media_type"] = original_media_type or normalized_media_type
        metadata["normalized_media_type"] = normalized_media_type
        metadata["validation_full_mode"] = bool(self.config.full_segment_validation_enabled)
        validator_name = _validator_name_for_media_type(normalized_media_type)
        metadata["validator_name"] = validator_name
        try:
            if normalized_media_type == "hls":
                status = self._validate_hls(candidate.stream_url, candidate=candidate)
            elif normalized_media_type == "image_snapshot":
                status = self._validate_image_snapshot(candidate.stream_url, metadata, candidate=candidate)
            elif normalized_media_type == "rtsp":
                status = self._validate_rtsp(candidate.stream_url)
            elif normalized_media_type == "mjpeg":
                status = self._validate_mjpeg(candidate.stream_url, candidate=candidate)
            elif normalized_media_type == "video_file":
                status = self._validate_video_file(candidate.stream_url, candidate=candidate)
            elif normalized_media_type == "unknown_media":
                status = self._validate_unknown_media(candidate, allow_delegate=allow_unknown_delegate)
            else:
                status = "unsupported_media_type"
                metadata["validation_reason"] = f"unsupported normalized media type: {normalized_media_type}"
        except Exception as exc:
            status = "dead"
            metadata["validation_error"] = repr(exc)[:300]
        metadata["validation_status"] = status
        metadata["validation_elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        metadata.setdefault("validation_reason", _default_validation_reason(status, normalized_media_type))
        return status


    def _validate_rtsp(self, url: str) -> str:
        if is_private_or_local_media_url(url):
            return "restricted_rtsp"
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return "rtsp_validation_unavailable"
        timeout = max(1.0, min(float(self.config.http_timeout or 5.0), 10.0))
        cmd = [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return "offline_rtsp"
        except Exception:
            return "dead_rtsp"
        stdout = (result.stdout or "")[:4096]
        stderr = redact_url_userinfo((result.stderr or "")[:4096])
        if result.returncode == 0:
            try:
                payload = json.loads(stdout or "{}")
            except json.JSONDecodeError:
                payload = {}
            if payload.get("streams") or "codec_type" in stdout:
                return "active_rtsp_verified"
        lowered = f"{stdout} {stderr}".casefold()
        if any(token in lowered for token in ("401", "403", "unauthorized", "forbidden", "auth", "credential", "permission")):
            return "auth_required_rtsp"
        if any(token in lowered for token in ("timed out", "timeout", "connection refused", "not found", "unreachable")):
            return "offline_rtsp"
        return "dead_rtsp"

    def _get_thread_validation_client(self, *, create: bool) -> httpx.Client | None:
        client = getattr(self._thread_local, "validation_client", None)
        if client is None and create:
            client = httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True)
            self._thread_local.validation_client = client
            with self._validation_clients_lock:
                self._validation_clients.append(client)
        return client

    def _close_validation_clients(self) -> None:
        with self._validation_clients_lock:
            clients = list(self._validation_clients)
            self._validation_clients.clear()
        current_client = getattr(self._thread_local, "validation_client", None)
        if current_client in clients:
            self._thread_local.validation_client = None
        for client in clients:
            try:
                client.close()
            except Exception:
                pass

    def _validate_hls(self, url: str, *, candidate: CameraCandidate | None = None) -> str:
        try:
            client = self._get_thread_validation_client(create=False)
            if client is not None:
                return self._validate_hls_with_client(url, client, candidate=candidate)
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as fallback_client:
                return self._validate_hls_with_client(url, fallback_client, candidate=candidate)
        except Exception:
            return "dead_link"

    def _validate_hls_with_client(self, url: str, client: httpx.Client, *, candidate: CameraCandidate | None = None) -> str:
        try:
            started_at = time.monotonic()
            r = client.get(url)
            # Metadata comes from a request already made for validation; it is not an extra probe.
            self._attach_validation_http_metadata(url, r, text=r.text[:4096], started_at=started_at, candidate=candidate)
            if r.status_code in {401, 403}:
                return "restricted"
            if r.status_code >= 400:
                return "dead"
            if "#EXTM3U" not in r.text[:4096]:
                return "invalid_hls"
            if not self.config.full_segment_validation_enabled:
                return "active_live_unknown"
            segment_url = self._first_playlist_segment_url(url, r.text, client=client)
            if not segment_url:
                return "active_live_unknown"
            try:
                segment = client.head(segment_url)
                if segment.status_code in {401, 403}:
                    return "restricted"
                if 200 <= segment.status_code < 300:
                    return "active_live_verified"
                segment = client.get(segment_url, headers={"Range": "bytes=0-1"})
                if segment.status_code in {401, 403}:
                    return "restricted"
                if 200 <= segment.status_code < 300 or segment.status_code == 206:
                    return "active_live_verified"
                return "active_playlist_dead_segments"
            except Exception:
                return "active_playlist_dead_segments"
        except Exception:
            return "dead"

    def _first_playlist_segment_url(self, playlist_url: str, playlist_body: str, *, client: httpx.Client | None = None, depth: int = 0) -> str | None:
        if depth > 2:
            return None
        variant_urls: list[str] = []
        for line in playlist_body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            clean = stripped.split("?", 1)[0].casefold()
            absolute = urljoin(playlist_url, stripped)
            if clean.endswith(".m3u8"):
                variant_urls.append(absolute)
                continue
            if clean.endswith((".ts", ".m4s", ".mp4", ".aac", ".mp3", ".cmfv", ".cmfa")) or "#EXTINF" in playlist_body:
                return absolute
        if client is not None:
            for variant_url in variant_urls[:3]:
                try:
                    variant = client.get(variant_url)
                except Exception:
                    continue
                if variant.status_code < 400 and "#EXTM3U" in variant.text[:4096]:
                    nested = self._first_playlist_segment_url(variant_url, variant.text, client=client, depth=depth + 1)
                    if nested:
                        return nested
        return variant_urls[0] if variant_urls else None

    def _validate_image_snapshot(self, url: str, metadata: dict | None = None, *, candidate: CameraCandidate | None = None) -> str:
        """Validate that an image snapshot endpoint is a real image and appears refreshable.

        This performs live HTTP checks. Static web assets are rejected; image
        endpoints that return a valid image but do not change during the sampling
        window remain untrusted/unknown rather than being promoted to live.
        """
        if _looks_like_static_snapshot_asset(url):
            return "static_image_asset"
        try:
            client = self._get_thread_validation_client(create=False)
            if client is not None:
                return self._validate_image_snapshot_with_client(url, metadata or {}, client, candidate=candidate)
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as fallback_client:
                return self._validate_image_snapshot_with_client(url, metadata or {}, fallback_client, candidate=candidate)
        except Exception:
            return "dead_link"

    def _validate_image_snapshot_with_client(self, url: str, metadata: dict, client: httpx.Client, *, candidate: CameraCandidate | None = None) -> str:
        try:
            started_at = time.monotonic()
            first = client.get(_cache_busted_url(url), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            self._attach_validation_http_metadata(url, first, text=None, started_at=started_at, candidate=candidate)
            first_status = _snapshot_http_status(first)
            if first_status:
                return first_status
            if _headers_indicate_static_asset(first.headers):
                return "static_image_asset"
            delay_value = _camera_refresh_rate_seconds(metadata or {})
            delay = max(0.0, float(delay_value if delay_value is not None else getattr(self.config, "image_snapshot_refresh_delay_seconds", 2.0)))
            if delay:
                time.sleep(delay)
            second_started_at = time.monotonic()
            second = client.get(_cache_busted_url(url), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            self._attach_validation_http_metadata(url, second, text=None, started_at=second_started_at, candidate=candidate)
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


    def _validate_mjpeg(self, url: str, *, candidate: CameraCandidate | None = None) -> str:
        try:
            client = self._get_thread_validation_client(create=False)
            if client is not None:
                return self._validate_mjpeg_with_client(url, client, candidate=candidate)
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as fallback_client:
                return self._validate_mjpeg_with_client(url, fallback_client, candidate=candidate)
        except Exception:
            return "dead"

    def _validate_mjpeg_with_client(self, url: str, client: httpx.Client, *, candidate: CameraCandidate | None = None) -> str:
        started_at = time.monotonic()
        try:
            response, sample = _bounded_get_bytes(client, url, max_bytes=32768)
            text_sample = sample[:4096].decode("latin-1", errors="ignore") if sample else None
            self._attach_validation_http_metadata(url, response, text=text_sample, started_at=started_at, candidate=candidate)
            if response.status_code in {401, 403}:
                return "restricted"
            if response.status_code >= 400:
                return "dead"
            content_type = response.headers.get("content-type", "").casefold()
            if "multipart/x-mixed-replace" in content_type or "mjpeg" in content_type or _bytes_look_like_mjpeg(sample):
                return "active_mjpeg_verified"
            if content_type.startswith(("text/html", "application/json", "text/plain")):
                return "invalid_mjpeg"
            return "active_mjpeg_unknown" if not self.config.full_segment_validation_enabled else "invalid_mjpeg"
        except Exception:
            return "dead"

    def _validate_video_file(self, url: str, *, candidate: CameraCandidate | None = None) -> str:
        try:
            client = self._get_thread_validation_client(create=False)
            if client is not None:
                return self._validate_video_file_with_client(url, client, candidate=candidate)
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as fallback_client:
                return self._validate_video_file_with_client(url, fallback_client, candidate=candidate)
        except Exception:
            return "dead"

    def _validate_video_file_with_client(self, url: str, client: httpx.Client, *, candidate: CameraCandidate | None = None) -> str:
        try:
            started_at = time.monotonic()
            head = client.head(url)
            self._attach_validation_http_metadata(url, head, text=None, started_at=started_at, candidate=candidate)
            if head.status_code in {401, 403}:
                return "restricted"
            if 200 <= head.status_code < 300 and _headers_or_url_indicate_video_file(url, head.headers):
                return "video_file_reachable_unknown_live"
            response, sample = _bounded_get_bytes(client, url, max_bytes=4096)
            self._attach_validation_http_metadata(url, response, text=None, started_at=None, candidate=candidate)
            if response.status_code in {401, 403}:
                return "restricted"
            if response.status_code >= 400:
                return "dead"
            if _headers_indicate_video_file(response.headers) or _bytes_look_like_video_file(sample):
                return "video_file_reachable_unknown_live"
            return "invalid_video_file"
        except Exception:
            return "dead"

    def _validate_unknown_media(self, candidate: CameraCandidate, *, allow_delegate: bool = True) -> str:
        if not allow_delegate:
            candidate.source_metadata["validation_reason"] = "unknown media delegate recursion prevented"
            return "unknown_media_unclassified"
        try:
            client = self._get_thread_validation_client(create=False)
            owns_client = client is None
            if client is None:
                client = httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True)
            try:
                response, sample = _bounded_get_bytes(client, candidate.stream_url, max_bytes=8192)
                self._attach_validation_http_metadata(candidate.stream_url, response, text=sample[:4096].decode("latin-1", errors="ignore"), started_at=None, candidate=candidate)
            finally:
                if owns_client:
                    client.close()
            if response.status_code in {401, 403}:
                return "restricted"
            if response.status_code >= 400:
                return "dead"
            classified = _classify_unknown_media_response(candidate.stream_url, response.headers, sample)
            if not classified:
                candidate.source_metadata["validation_reason"] = "unknown media could not be classified from URL, headers, or bounded content sample"
                return "unknown_media_unclassified"
            candidate.source_metadata["unknown_media_classified_as"] = classified
            candidate.source_metadata["normalized_media_type"] = classified
            candidate.source_metadata["validator_name"] = _validator_name_for_media_type(classified)
            return self._validate_candidate_with_dispatcher(candidate, allow_unknown_delegate=False)
        except Exception as exc:
            candidate.source_metadata["validation_error"] = repr(exc)[:300]
            return "unknown_media_unclassified"


    def _attach_validation_http_metadata(self, url: str, response: httpx.Response, *, text: str | None = None, started_at: float | None = None, candidate: CameraCandidate | None = None) -> None:
        """Cache passive HTTP metadata from validation requests already in progress."""
        try:
            metadata = http_metadata_from_response(response, text=text, started_at=started_at)
        except Exception:
            return
        if candidate is not None:
            candidate.source_metadata.setdefault("http_metadata", metadata)
            candidate.source_metadata.setdefault("validation_http_metadata", metadata)
        cache = getattr(self._thread_local, "validation_http_metadata", None)
        if cache is None:
            cache = {}
            self._thread_local.validation_http_metadata = cache
        cache[url.split("#", 1)[0]] = metadata

    def _apply_cached_validation_http_metadata(self, rows: list[CameraCandidate]) -> None:
        merged: dict[str, Any] = {}
        for client_cache in [getattr(self._thread_local, "validation_http_metadata", None)]:
            if isinstance(client_cache, dict):
                merged.update(client_cache)
        for candidate in rows:
            key = candidate.stream_url.split("#", 1)[0]
            if key in merged:
                candidate.source_metadata.setdefault("http_metadata", merged[key])
                candidate.source_metadata.setdefault("validation_http_metadata", merged[key])

    def _write_outputs(self, targets: list[TargetContext], target_map: dict[str, TargetContext], candidates: CandidateSet, v: ValidationSummary) -> OutputSummary:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self._apply_cached_validation_http_metadata(candidates.unique)
        target_intents = {t.target_id: (t.intent.camera_type_intent if t.intent else None) for t in targets}
        for candidate in candidates.unique:
            _normalize_candidate_display_metadata(candidate, target_intents.get(candidate.target_id or ""))
            enrich_candidate_with_passive_intelligence(candidate, self.source_policy)
        trusted_allowed = {t.target_id for t in targets if t.trust_policy == TrustPolicy.TRUSTED_ALLOWED and t.bbox_verified}
        prioritized_unique = prioritize_candidates(candidates.unique)
        trusted = prioritize_candidates(
            c for c in prioritized_unique
            if c.trust_level == "trusted" and c.scope_status == "in_scope" and c.has_coordinates and c.target_id in trusted_allowed
        )
        trusted_keys = {(c.stream_url, c.target_id) for c in trusted}
        coordinate_bearing = prioritize_candidates(c for c in prioritized_unique if c.has_coordinates)
        review = prioritize_candidates(c for c in coordinate_bearing if (c.stream_url, c.target_id) not in trusted_keys)
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
        table_path = self._write_candidate_table(prioritized_unique)
        out.camera_candidates_table_csv = str(table_path)
        out.camera_candidates_table_rows = len(prioritized_unique)
        write_jsonl(self.logs_dir / "validation_results.jsonl", [asdict(c) for c in prioritized_unique])
        evidence_records = [candidate_evidence_record(c) for c in prioritized_unique]
        write_jsonl(self.logs_dir / "candidate_evidence_summary.jsonl", evidence_records)
        write_jsonl(self.logs_dir / "candidate_priority_explanation.jsonl", evidence_records)
        passive_summary = passive_intelligence_summary(prioritized_unique)
        write_json(self.logs_dir / "passive_intelligence_summary.json", passive_summary)
        write_json(
            self.logs_dir / "candidate_priority_summary.json",
            _candidate_priority_summary(prioritized_unique),
        )
        write_json(self.logs_dir / "validation_summary.json", {**asdict(v), "media_validation_mode": "full" if self.config.full_segment_validation_enabled else "lightweight", "full_segment_validation_enabled": self.config.full_segment_validation_enabled, "http_segment_fallback_enabled": True, "enabled_validators": _enabled_validator_names(), "validation_result_cache_entries": len(self._validation_result_cache)})
        playlist_summary = export_candidate_playlists(
            self.config.output_dir,
            prioritized_unique,
            trusted_candidates=trusted,
            review_candidates=review,
            source_policy=self.source_policy,
        )
        write_json(self.logs_dir / "playlist_export_summary.json", playlist_summary)
        out.playlist_export_summary = str(self.logs_dir / "playlist_export_summary.json")
        dashboard = build_media_validation_dashboard(
            prioritized_unique,
            trusted_candidates=trusted,
            review_candidates=review,
            validation_attempted=v.attempted,
        )
        add_passive_intelligence_to_dashboard(dashboard, prioritized_unique)
        dashboard["outputs"] = {
            "trusted_geojson_features": len(trusted),
            "untrusted_geojson_features": len(review),
            "candidate_table_rows": len(prioritized_unique),
        }
        write_json(self.config.output_dir / "media_validation_dashboard.json", dashboard)
        write_json(self.logs_dir / "media_validation_dashboard.json", dashboard)
        out.media_validation_dashboard = str(self.config.output_dir / "media_validation_dashboard.json")
        target_geometry_path, target_geometry_features = self._write_target_geometry_geojson(targets)
        if target_geometry_path is not None:
            out.target_geometry_geojson = str(target_geometry_path)
        out.target_geometry_features_written = target_geometry_features
        out.map_html = str(self._write_map())
        out.review_artifacts_zip = str(self.config.output_dir / "review_artifacts.zip")
        self._write_run_explanation(targets, candidates, v, out, playlist_summary=playlist_summary, media_dashboard=dashboard)
        out.review_artifacts_zip = str(self._package_review_artifacts())
        write_json(self.logs_dir / "output_summary.json", asdict(out))
        return out

    def _write_run_explanation(self, targets: list[TargetContext], candidates: CandidateSet, v: ValidationSummary, out: OutputSummary, *, playlist_summary: dict[str, Any] | None = None, media_dashboard: dict[str, Any] | None = None) -> None:
        media_counts: dict[str, int] = {}
        provider_counts: dict[str, int] = {}
        missing_coordinates = 0
        harvest_input_candidates = 0
        native_candidates = 0
        for candidate in candidates.unique:
            metadata = candidate.source_metadata or {}
            media = str(metadata.get("media_type") or "unknown")
            provider = str(metadata.get("source_provider") or candidate.discovery_method or "unknown")
            media_counts[media] = media_counts.get(media, 0) + 1
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            if candidate.discovery_method == "harvest_handoff" or metadata.get("harvest_input"):
                harvest_input_candidates += 1
            else:
                native_candidates += 1
            if not candidate.has_coordinates:
                missing_coordinates += 1
        google_dorking_summary = _read_optional_json(self.logs_dir / "google_dorking_summary.json") or _google_dorking_default_summary(self.config)
        harvest_search_service_summary_path = self.config.output_dir.parent / "harvest" / "logs" / "search_service_summary.json"
        search_service_summary = _read_optional_json(harvest_search_service_summary_path)
        passive_summary = _read_optional_json(self.logs_dir / "passive_intelligence_summary.json") or passive_intelligence_summary(candidates.unique)
        write_json(self.logs_dir / "google_dorking_summary.json", google_dorking_summary)
        write_json(self.logs_dir / "passive_intelligence_summary.json", passive_summary)
        explanation = {
            "plain_language_summary": [
                f"Resolved {len(targets)} target(s): " + ", ".join(t.canonical_target or t.target_label or t.target_id for t in targets),
                f"Found {len(candidates.unique)} unique candidate camera record(s): {native_candidates} native discovery candidate(s) and {harvest_input_candidates} harvest-input candidate(s).",
                f"{out.coordinate_bearing_candidates} candidate(s) had real coordinates; {missing_coordinates} remain table-only because no verified coordinate was extracted or geocoded.",
                f"Trusted camera.geojson created: {out.trusted_geojson_created} ({out.trusted_geojson_features_written} feature(s)).",
                f"Untrusted review GeoJSON created: {out.untrusted_geojson_created} ({out.untrusted_geojson_features_written} feature(s)).",
                f"Coordinate-bearing GeoJSON coverage: {out.coordinate_bearing_geojson_features_written}/{out.coordinate_bearing_candidates} feature(s) written; {out.coordinate_bearing_without_geojson} coordinate-bearing candidate(s) were not written to a GeoJSON artifact.",
                f"Media validation dashboard: {media_dashboard or {}}",
                f"Passive intelligence scored {passive_summary.get('candidates_scored', 0)} candidate(s); evidence bands: {passive_summary.get('candidate_evidence_bands', {})}.",
                f"Playlist exports written: {bool(playlist_summary and playlist_summary.get('created'))}.",
                "Fast profile is review-only; use balanced/full validation when you want stream validation and trusted output authorization.",
            ],
            "candidate_source_counts": {"native_discovery": native_candidates, "harvest_input": harvest_input_candidates, "combined": len(candidates.unique)},
            "candidate_priority_counts": priority_bucket_counts(candidates.unique),
            "media_type_counts": media_counts,
            "source_provider_counts": provider_counts,
            "geojson_metrics": {
                "coordinate_bearing_candidates": out.coordinate_bearing_candidates,
                "trusted_geojson_features": out.trusted_geojson_features_written,
                "untrusted_geojson_features": out.untrusted_geojson_features_written,
                "coordinate_bearing_geojson_features_written": out.coordinate_bearing_geojson_features_written,
                "coordinate_bearing_without_geojson": out.coordinate_bearing_without_geojson,
            },
            "validation": {**asdict(v), "media_validation_mode": "full" if self.config.full_segment_validation_enabled else "lightweight", "full_segment_validation_enabled": self.config.full_segment_validation_enabled, "http_segment_fallback_enabled": True, "enabled_validators": _enabled_validator_names()},
            "media_validation_dashboard": media_dashboard or {},
            "passive_intelligence": passive_summary,
            "playlist_exports": playlist_summary or {},
            "google_dorking": google_dorking_summary,
            "search_service_summary": search_service_summary,
            "search_service_summary_path": str(harvest_search_service_summary_path) if harvest_search_service_summary_path.exists() else None,
            "outputs": asdict(out),
            "interpretation": {
                "camera_geojson": "Trusted, validated, in-scope coordinate-bearing camera inventory. Not written when validation is disabled or no trusted records exist.",
                "untrusted_camera_candidates_geojson": "Every coordinate-bearing candidate not written to trusted camera.geojson. These are not trusted inventory and may include rejected, out-of-scope, unknown, or review-only records for audit/map analysis.",
                "camera_candidates_table_csv": "All unique candidates considered by the run, including trusted, untrusted review, dead/restricted, out-of-scope, unknown-location, and not-validated rows. Deduplication key: stream_url without fragment plus target_id.",
                "map_html": "Interactive map for coordinate-bearing trusted/untrusted GeoJSON only. RTSP URLs are external-player links, not browser/hls.js playback.",
                "playlist_exports": "Convenience M3U/TXT views over existing candidates and validation state; playlists do not promote trust.",
                "media_validation_dashboard": "Top-level summary of candidate validation, trust, review, dead, restricted, not-validated counts, and passive intelligence evidence bands.",
                "passive_intelligence": "Deterministic source/candidate evidence scoring, safe passive signatures, HTTP metadata, and protocol labels. It affects prioritization and explanation only, not trust.",
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
        lines.append("## Media validation dashboard")
        for key, value in (media_dashboard or {}).items():
            if not isinstance(value, dict):
                lines.append(f"- `{key}`: {value}")
        lines.append("")
        passive = explanation.get("passive_intelligence") or {}
        lines.append("## Passive intelligence")
        lines.append(f"- sources_scored: {passive.get('sources_scored', 0)}")
        lines.append(f"- candidates_scored: {passive.get('candidates_scored', 0)}")
        lines.append(f"- candidate_evidence_bands: {passive.get('candidate_evidence_bands', {})}")
        lines.append(f"- protocol_label_counts: {passive.get('protocol_label_counts', {})}")
        lines.append(f"- signature_family_counts: {passive.get('signature_family_counts', {})}")
        lines.append("")
        lines.append("## Playlist exports")
        for key, value in (playlist_summary or {}).get("counts", {}).items():
            lines.append(f"- `{key}`: {value}")
        lines.append("")
        search_services = explanation.get("search_service_summary") or {}
        if search_services:
            lines.append("## Search service summary")
            for key in ("ddg", "bing", "searxng", "google_dork"):
                item = search_services.get(key) or {}
                lines.append(f"- `{key}`: status={item.get('status')} parsed={item.get('parsed_rows', 0)} selected={item.get('selected_rows', 0)} errors={item.get('error_count', 0)} skip={item.get('skip_reason', '')}")
            lines.append("")
        dorking = explanation.get("google_dorking") or {}
        if dorking:
            lines.append("## Google dorking")
            lines.append(f"- enabled: {dorking.get('enabled', False)}")
            lines.append(f"- queries_generated: {dorking.get('queries_generated', 0)}")
            lines.append(f"- results_after_block_policy: {dorking.get('results_after_block_policy', 0)}")
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
            "candidate_disposition",
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
            "source_provider",
            "source_engine",
            "latitude",
            "longitude",
            "coordinate_source",
            "geocoded_query",
            "geocoded_display_name",
            "thumbnail_url",
            "snapshot_url",
            "camera_refresh_rate",
            "map_refresh_rate_seconds",
            "media_type",
            "normalized_media_type",
            "validator_name",
            "validation_reason",
            "validation_error",
            "validation_elapsed_ms",
            "validation_full_mode",
            "source_metadata_json",
            "protocol_label",
            "media_family",
            "protocol_confidence",
            "camera_evidence_score",
            "camera_evidence_band",
            "why_candidate_mattered",
            "candidate_priority_bucket",
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
        visible = list(rows)
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
                        "candidate_disposition": _candidate_disposition(row),
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
                        "source_provider": metadata.get("source_provider") or row.discovery_method,
                        "source_engine": metadata.get("source_engine") or metadata.get("search_engine"),
                        "latitude": row.lat,
                        "longitude": row.lon,
                        "coordinate_source": row.coordinate_source,
                        "geocoded_query": row.geocoded_query,
                        "geocoded_display_name": row.geocoded_display_name,
                        "thumbnail_url": metadata.get("thumbnail_url") or metadata.get("snapshot_url"),
                        "snapshot_url": metadata.get("snapshot_url") or metadata.get("thumbnail_url"),
                        "camera_refresh_rate": _camera_refresh_rate(metadata),
                        "map_refresh_rate_seconds": _camera_map_refresh_rate_seconds(metadata, self.config.image_snapshot_refresh_delay_seconds) if media_type == "image_snapshot" else None,
                        "media_type": media_type,
                        "normalized_media_type": metadata.get("normalized_media_type") or media_type_for_row(row),
                        "validator_name": metadata.get("validator_name"),
                        "validation_reason": metadata.get("validation_reason"),
                        "validation_error": metadata.get("validation_error"),
                        "validation_elapsed_ms": metadata.get("validation_elapsed_ms"),
                        "validation_full_mode": metadata.get("validation_full_mode"),
                        "source_metadata_json": json.dumps(metadata, sort_keys=True, default=str),
                        "protocol_label": metadata.get("protocol_label"),
                        "media_family": metadata.get("media_family"),
                        "protocol_confidence": metadata.get("protocol_confidence"),
                        "camera_evidence_score": metadata.get("camera_evidence_score"),
                        "camera_evidence_band": metadata.get("camera_evidence_band"),
                        "why_candidate_mattered": metadata.get("why_candidate_mattered"),
                        "candidate_priority_bucket": candidate_priority_label(row),
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
            {"path": str(path), "rows": len(visible), "includes_rows_without_coordinates": True, "includes_rejected_candidates": True, "dedupe_key": "stream_url_without_fragment + target_id"},
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
                    "normalized_media_type": metadata.get("normalized_media_type") or media_type_for_row(c),
                    "validator_name": metadata.get("validator_name"),
                    "validation_reason": metadata.get("validation_reason"),
                    "validation_error": metadata.get("validation_error"),
                    "validation_elapsed_ms": metadata.get("validation_elapsed_ms"),
                    "validation_full_mode": metadata.get("validation_full_mode"),
                    "protocol_label": metadata.get("protocol_label"),
                    "media_family": metadata.get("media_family"),
                    "protocol_confidence": metadata.get("protocol_confidence"),
                    "protocol_reasons": metadata.get("protocol_reasons"),
                    "camera_evidence_score": metadata.get("camera_evidence_score"),
                    "camera_evidence_band": metadata.get("camera_evidence_band"),
                    "camera_evidence_reasons": metadata.get("camera_evidence_reasons"),
                    "signature_matches": metadata.get("signature_matches"),
                    "http_status": (metadata.get("http_metadata") or {}).get("http_status") if isinstance(metadata.get("http_metadata"), dict) else None,
                    "content_type": (metadata.get("http_metadata") or {}).get("content_type") if isinstance(metadata.get("http_metadata"), dict) else None,
                    "final_url": (metadata.get("http_metadata") or {}).get("final_url") if isinstance(metadata.get("http_metadata"), dict) else None,
                    "source_evidence_score": metadata.get("source_camera_evidence_score") or metadata.get("source_evidence_score"),
                    "source_evidence_band": metadata.get("source_camera_evidence_band") or metadata.get("source_evidence_band"),
                    "why_candidate_mattered": metadata.get("why_candidate_mattered"),
                    "candidate_priority_bucket": candidate_priority_label(c),
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


    def _write_target_geometry_geojson(self, targets: list[TargetContext]) -> tuple[Any | None, int]:
        """Write portable target geometry from explicit resolver geometry roles only.

        Target geometry artifacts are intentionally strict. A feature may be
        emitted only when the resolver populated one of the explicit geometry
        hierarchy fields:

        1. ``primary_geometry_geojson`` for a verified boundary polygon/multipolygon.
        2. ``fallback_geometry_bbox`` for the verified rectangular fallback bbox.
        3. ``last_fallback_geometry_bbox`` for the configured last fallback bbox.

        Do not synthesize target geometry from legacy/convenience fields such as
        ``bbox``, ``effective_bbox``, ``nominatim_bbox``, ``polygon``, or a
        geocoder point. Those fields can be useful diagnostics elsewhere, but
        they are not confirmed target-geometry artifact sources.
        """
        features: list[dict[str, Any]] = []
        skipped_without_explicit_geometry = 0
        for target in targets:
            geometry_role = None
            geometry_source = None
            geometry = _normalized_geojson_geometry(target.primary_geometry_geojson)
            if geometry is not None:
                geometry_role = "primary"
                geometry_source = target.primary_geometry_source or "primary_geometry_geojson"
            elif target.fallback_geometry_bbox:
                geometry = _bbox_polygon_geometry(target.fallback_geometry_bbox)
                geometry_role = "fallback"
                geometry_source = target.fallback_geometry_source or "fallback_geometry_bbox"
            elif target.last_fallback_geometry_bbox:
                geometry = _bbox_polygon_geometry(target.last_fallback_geometry_bbox)
                geometry_role = "last_fallback"
                geometry_source = target.last_fallback_geometry_source or "last_fallback_geometry_bbox"

            if geometry is None or geometry_role not in {"primary", "fallback", "last_fallback"}:
                skipped_without_explicit_geometry += 1
                continue
            properties = {
                "target_id": target.target_id,
                "target_index": target.target_index,
                "target_label": target.target_label,
                "canonical_target": target.canonical_target,
                "scope_type": target.scope_type,
                "geometry_role": geometry_role,
                "geometry_source": geometry_source,
                "primary_geometry_source": target.primary_geometry_source,
                "fallback_geometry_source": target.fallback_geometry_source,
                "last_fallback_geometry_source": target.last_fallback_geometry_source,
                "bbox_verified": target.bbox_verified,
                "geometry_status": target.geometry_status,
            }
            if target.chosen_candidate:
                properties["geocoder_display_name"] = target.chosen_candidate.display_name
                properties["geocoder_result_type"] = target.chosen_candidate.result_type
            features.append({"type": "Feature", "geometry": geometry, "properties": properties})

        path = self.config.output_dir / "target_geometry.geojson"
        if features:
            write_json(path, {"type": "FeatureCollection", "features": features})
        elif path.exists():
            path.unlink()
        write_json(
            self.logs_dir / "target_geometry_geojson_status.json",
            {
                "created": bool(features),
                "features": len(features),
                "path": str(path) if features else None,
                "primary_features": sum(1 for f in features if f.get("properties", {}).get("geometry_role") == "primary"),
                "fallback_features": sum(1 for f in features if f.get("properties", {}).get("geometry_role") == "fallback"),
                "last_fallback_features": sum(1 for f in features if f.get("properties", {}).get("geometry_role") == "last_fallback"),
                "skipped_without_explicit_geometry": skipped_without_explicit_geometry,
                "allowed_geometry_roles": ["primary", "fallback", "last_fallback"],
                "strict_artifact_geometry_only": True,
            },
        )
        return (path if features else None), len(features)

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
            for rel in ["camera.geojson", "untrusted_camera_candidates.geojson", "target_geometry.geojson", "camera_inventory.jsonl", "cameras.md", "map.html", "camera_candidates_table.csv", "media_validation_dashboard.json", "RUN_EXPLANATION.md"]:
                p = self.config.output_dir / rel
                if p.exists():
                    z.write(p, rel)
            for sub in ["logs", "candidates", "playlists"]:
                folder = self.config.output_dir / sub
                if folder.exists():
                    for p in folder.rglob("*"):
                        if p.is_file():
                            z.write(p, str(p.relative_to(self.config.output_dir)))
        return zpath



def _normalized_geojson_geometry(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    geometry_type = value.get("type")
    coordinates = value.get("coordinates")
    if geometry_type not in {"Polygon", "MultiPolygon"} or not coordinates:
        return None
    return {"type": geometry_type, "coordinates": coordinates}


def _bbox_polygon_geometry(bbox: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(bbox, dict):
        return None
    try:
        min_lat = float(bbox["min_lat"])
        max_lat = float(bbox["max_lat"])
        min_lon = float(bbox["min_lon"])
        max_lon = float(bbox["max_lon"])
    except Exception:
        return None
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat
    if min_lon > max_lon:
        min_lon, max_lon = max_lon, min_lon
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lon, min_lat],
            [max_lon, min_lat],
            [max_lon, max_lat],
            [min_lon, max_lat],
            [min_lon, min_lat],
        ]],
    }

def _validation_status_category(status: str) -> str:
    if status in {"active_live_unknown", "active_live_verified", "active_image_snapshot_refreshing", "active_rtsp_verified", "active_mjpeg_verified"}:
        return "live"
    if status in {
        "dead_link",
        "offline_http",
        "active_playlist_dead_segments",
        "static_image_asset",
        "image_snapshot_not_image",
        "dead_rtsp",
        "offline_rtsp",
        "dead",
        "invalid_hls",
        "invalid_mjpeg",
        "invalid_video_file",
    }:
        return "dead"
    if status in {"restricted", "restricted_http", "restricted_rtsp", "auth_required_rtsp"}:
        return "unknown"
    return "unknown"



def _google_dorking_default_summary(config: RunConfig) -> dict[str, Any]:
    return {
        "enabled": bool(config.enable_google_dorking),
        "queries_generated": 0,
        "results_seen": 0,
        "results_after_block_policy": 0,
        "promoted_source_leads": 0,
        "candidates_extracted": 0,
    }

def _read_optional_json(path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _candidate_priority_summary(candidates: list[CameraCandidate]) -> dict[str, object]:
    located = [candidate for candidate in candidates if candidate.has_coordinates]
    unlocated = [candidate for candidate in candidates if not candidate.has_coordinates]
    located_in_scope = [candidate for candidate in located if candidate.scope_status == "in_scope"]
    located_out_of_scope = [candidate for candidate in located if candidate.scope_status == "out_of_scope"]
    return {
        "total_candidates": len(candidates),
        "located_candidates": len(located),
        "located_in_scope_candidates": len(located_in_scope),
        "located_out_of_scope_candidates": len(located_out_of_scope),
        "unlocated_candidates": len(unlocated),
        "by_priority_bucket": priority_bucket_counts(candidates),
        "by_evidence_band": _candidate_evidence_band_counts(candidates),
        "validation_prioritized_by_evidence": True,
    }


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


def _normalized_validation_url(url: str) -> str:
    return str(url or "").split("#", 1)[0]


def _normalized_media_type_for_candidate(candidate: CameraCandidate) -> str:
    metadata = candidate.source_metadata or {}
    explicit = str(metadata.get("normalized_media_type") or metadata.get("media_type") or "").strip().casefold()
    url = str(candidate.stream_url or "")
    url_classified = _classify_media_url_for_validation(url, content_type=str(metadata.get("content_type") or metadata.get("http_content_type") or ""))
    if explicit in {"hls", "hls_stream"}:
        return "hls"
    if explicit in {"rtsp", "rtsps", "rtsp_stream"}:
        return "rtsp"
    if explicit in {"mjpeg", "mjpg"}:
        return "mjpeg"
    if explicit in {"mp4", "video", "video_file", "mov", "webm", "m4v"}:
        return "video_file"
    if explicit in {"image", "snapshot", "image_snapshot"}:
        return "image_snapshot"
    if explicit in {"unknown", "unknown_media", "stream", "unknown_media"}:
        return url_classified or "unknown_media"
    if explicit:
        return url_classified or explicit
    return url_classified or media_type_for_row(candidate) or "unknown_media"


def _classify_media_url_for_validation(url: str, *, content_type: str = "") -> str | None:
    lowered = str(url or "").casefold()
    ctype = str(content_type or "").casefold()
    path = urlparse(lowered).path
    if lowered.startswith(("rtsp://", "rtsps://")):
        return "rtsp"
    if path.endswith(".m3u8") or ".m3u8" in lowered or "mpegurl" in ctype:
        return "hls"
    if path.endswith((".mjpg", ".mjpeg")) or "multipart/x-mixed-replace" in ctype or "mjpeg" in ctype:
        return "mjpeg"
    if path.endswith((".mp4", ".webm", ".mov", ".m4v")) or ctype.startswith("video/"):
        return "video_file"
    if path.endswith((".jpg", ".jpeg", ".png", ".webp")) or ctype.startswith("image/"):
        return "image_snapshot"
    return None


def _validator_name_for_media_type(media_type: str) -> str:
    return {
        "hls": "hls",
        "image_snapshot": "image_snapshot",
        "rtsp": "rtsp",
        "mjpeg": "mjpeg",
        "video_file": "video_file",
        "unknown_media": "unknown_media",
    }.get(media_type, "unsupported_media")


def _enabled_validator_names() -> list[str]:
    return ["hls", "image_snapshot", "rtsp", "mjpeg", "video_file", "unknown_media"]


def _default_validation_reason(status: str, media_type: str) -> str:
    return f"{_validator_name_for_media_type(media_type)} validator returned {status}"


def _candidate_disposition(candidate: CameraCandidate) -> str:
    status = (candidate.validation_status or "").casefold()
    if candidate.trust_level == "trusted":
        return "trusted"
    if candidate.scope_status == "out_of_scope":
        return "out_of_scope"
    if status in {"restricted", "restricted_http"} or "restricted" in status or "forbidden" in status or "auth" in status:
        return "restricted"
    if status in {"dead", "offline_http", "dead_link", "decode_failed", "active_playlist_dead_segments"} or status.startswith(("dead", "offline")):
        return "dead"
    if status == "not_validated" or not candidate.validation_status:
        return "not_validated"
    if candidate.scope_status == "unknown" or not candidate.has_coordinates:
        return "unknown_location"
    return "untrusted_review"


def _normalize_candidate_display_metadata(candidate: CameraCandidate, target_camera_type: str | None) -> None:
    metadata = candidate.source_metadata or {}
    candidate.source_metadata = metadata
    if not metadata.get("camera_type"):
        structured_type = metadata.get("category") or metadata.get("type") or metadata.get("device_type")
        if isinstance(structured_type, str) and structured_type.strip():
            metadata["camera_type"] = structured_type.strip().casefold().replace(" ", "_")
        elif target_camera_type and target_camera_type != "public_live":
            metadata["camera_type"] = target_camera_type
    snapshot = _promoted_image_url(metadata, prefer=("snapshot_url", "currentImageURL", "currentimageurl", "current_image_url", "image_url", "camera_image_url", "preview_image_url"))
    thumbnail = _promoted_image_url(metadata, prefer=("thumbnail_url", "thumb_url", "preview_image_url", "poster_url", "image_url"))
    if snapshot and not metadata.get("snapshot_url"):
        metadata["snapshot_url"] = snapshot
    if thumbnail and not metadata.get("thumbnail_url"):
        metadata["thumbnail_url"] = thumbnail
    elif snapshot and not metadata.get("thumbnail_url"):
        metadata["thumbnail_url"] = snapshot


def _promoted_image_url(metadata: dict[str, Any], *, prefer: tuple[str, ...]) -> str | None:
    for key in prefer:
        value = metadata.get(key)
        if isinstance(value, str) and _looks_like_direct_image_url(value):
            return value
    for key, value in metadata.items():
        if isinstance(key, str) and "image" in key.casefold() and isinstance(value, str) and _looks_like_direct_image_url(value):
            return value
    return None


def _looks_like_direct_image_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme == "data":
        return value.startswith("data:image/")
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.path.casefold().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))


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


def _bounded_get_bytes(client: httpx.Client, url: str, *, max_bytes: int) -> tuple[httpx.Response, bytes]:
    chunks: list[bytes] = []
    total = 0
    with client.stream("GET", url, headers={"Range": f"bytes=0-{max(0, max_bytes - 1)}"}) as response:
        for chunk in response.iter_bytes():
            if not chunk:
                continue
            remaining = max_bytes - total
            if remaining <= 0:
                break
            chunks.append(chunk[:remaining])
            total += min(len(chunk), remaining)
            if total >= max_bytes:
                break
        return response, b"".join(chunks)


def _bytes_look_like_mjpeg(sample: bytes) -> bool:
    lowered = sample[:4096].lower()
    if b"multipart/x-mixed-replace" in lowered:
        return True
    return b"--" in sample[:2048] and b"\xff\xd8" in sample and b"\xff\xd9" in sample


def _headers_or_url_indicate_video_file(url: str, headers: httpx.Headers) -> bool:
    content_type = headers.get("content-type", "").casefold()
    path = urlparse(url).path.casefold()
    return content_type.startswith("video/") or path.endswith((".mp4", ".webm", ".mov", ".m4v"))


def _headers_indicate_video_file(headers: httpx.Headers) -> bool:
    return headers.get("content-type", "").casefold().startswith("video/")


def _bytes_look_like_video_file(sample: bytes) -> bool:
    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        return True
    return sample.startswith(b"\x1a\x45\xdf\xa3")


def _classify_unknown_media_response(url: str, headers: httpx.Headers, sample: bytes) -> str | None:
    by_url = _classify_media_url_for_validation(url, content_type=headers.get("content-type", ""))
    if by_url:
        return by_url
    prefix = sample[:4096]
    if b"#EXTM3U" in prefix:
        return "hls"
    if _bytes_look_like_mjpeg(prefix):
        return "mjpeg"
    if _bytes_look_like_image(sample):
        return "image_snapshot"
    if _bytes_look_like_video_file(sample):
        return "video_file"
    return None


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


def _candidate_evidence_band_counts(candidates: list[CameraCandidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        band = str((candidate.source_metadata or {}).get("camera_evidence_band") or "none")
        counts[band] = counts.get(band, 0) + 1
    return {key: counts.get(key, 0) for key in ("very_strong", "strong", "moderate", "weak", "none") if counts.get(key, 0)}
