from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from camera_discovery.utils.url_safety import is_private_or_local_media_url, redact_url_userinfo

LIVE_STATUSES = {"active_live_unknown", "active_live_verified", "active_image_snapshot_refreshing", "active_rtsp_verified"}
RESTRICTED_STATUS_FRAGMENTS = ("restricted", "auth_required", "private_network", "not_allowed", "forbidden", "401", "403")
DEAD_STATUS_FRAGMENTS = ("dead", "offline", "invalid", "decode_failed", "static_image_asset", "not_image", "dead_segments")
NOT_VALIDATED_STATUSES = {"not_validated", "validation_disabled", "not_validated_media_type", "rtsp_validation_unavailable"}


def media_type_for_row(row: Any) -> str:
    metadata = _metadata(row)
    explicit = str(metadata.get("media_type") or _get(row, "media_type", "") or "").casefold()
    url = media_url_for_row(row).casefold()
    if explicit in {"hls", "hls_stream"}:
        return "hls"
    if explicit in {"rtsp", "rtsps", "rtsp_stream"}:
        return "rtsp"
    if explicit in {"image", "snapshot", "image_snapshot"}:
        return "image_snapshot"
    if explicit:
        return explicit
    if url.startswith(("rtsp://", "rtsps://")):
        return "rtsp"
    if ".m3u8" in url:
        return "hls"
    if url.split("?", 1)[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "image_snapshot"
    return "unknown_media"


def media_url_for_row(row: Any) -> str:
    return str(_get(row, "stream_url", None) or _get(row, "url", None) or _metadata(row).get("media_url") or "")


def validation_status_for_row(row: Any) -> str:
    return str(_get(row, "validation_status", None) or _metadata(row).get("validation_status") or "").casefold()


def status_bucket(status: str | None) -> str:
    lowered = str(status or "").casefold()
    if lowered in LIVE_STATUSES:
        return "live"
    if lowered in NOT_VALIDATED_STATUSES or not lowered:
        return "not_validated"
    if any(fragment in lowered for fragment in RESTRICTED_STATUS_FRAGMENTS):
        return "restricted"
    if any(fragment in lowered for fragment in DEAD_STATUS_FRAGMENTS):
        return "dead"
    return "unknown"


def export_candidate_playlists(
    output_dir: Path,
    all_candidates: Iterable[Any],
    *,
    trusted_candidates: Iterable[Any],
    review_candidates: Iterable[Any],
    source_policy: Any | None = None,
) -> dict[str, Any]:
    playlists_dir = output_dir / "playlists"
    playlists_dir.mkdir(parents=True, exist_ok=True)
    all_rows = list(all_candidates)
    trusted = list(trusted_candidates)
    review = list(review_candidates)
    buckets = {
        "trusted_media": [row for row in trusted if _playable(row, source_policy)],
        "untrusted_review_media": [row for row in review if _playable(row, source_policy)],
        "hls_candidates": [row for row in all_rows if media_type_for_row(row) == "hls" and _playable(row, source_policy)],
        "rtsp_candidates": [row for row in all_rows if media_type_for_row(row) == "rtsp" and _playable(row, source_policy)],
        "live_or_reachable_media": [row for row in all_rows if status_bucket(validation_status_for_row(row)) == "live" and _playable(row, source_policy)],
        "dead_or_restricted_media": [row for row in all_rows if status_bucket(validation_status_for_row(row)) in {"dead", "restricted"} and _eligible_url(row, source_policy)],
        "image_snapshots": [row for row in all_rows if media_type_for_row(row) == "image_snapshot" and _eligible_url(row, source_policy)],
    }
    files: dict[str, str] = {}
    counts: dict[str, int] = {}
    for name, rows in buckets.items():
        deduped = _dedupe_rows(rows)
        counts[name] = len(deduped)
        if name not in {"dead_or_restricted_media", "image_snapshots"}:
            rel = Path("playlists") / f"{name}.m3u"
            _write_m3u(output_dir / rel, deduped, group=name)
            files[f"{name}_m3u"] = str(rel)
        rel_txt = Path("playlists") / f"{name}.txt"
        _write_txt(output_dir / rel_txt, deduped)
        files[f"{name}_txt"] = str(rel_txt)
    return {"created": True, "output_dir": "playlists", "files": files, "counts": counts}


def export_harvest_playlists(output_dir: Path, records: Iterable[Any], *, source_policy: Any | None = None) -> dict[str, Any]:
    playlists_dir = output_dir / "playlists"
    playlists_dir.mkdir(parents=True, exist_ok=True)
    rows = list(records)
    buckets = {
        "harvested_media": [row for row in rows if _playable(row, source_policy)],
        "harvested_hls": [row for row in rows if media_type_for_row(row) == "hls" and _playable(row, source_policy)],
        "harvested_rtsp": [row for row in rows if media_type_for_row(row) == "rtsp" and _playable(row, source_policy)],
        "harvested_image_snapshots": [row for row in rows if media_type_for_row(row) == "image_snapshot" and _eligible_url(row, source_policy)],
    }
    files: dict[str, str] = {}
    counts: dict[str, int] = {}
    for name, bucket_rows in buckets.items():
        deduped = _dedupe_rows(bucket_rows)
        counts[name] = len(deduped)
        if name != "harvested_image_snapshots":
            rel = Path("playlists") / f"{name}.m3u"
            _write_m3u(output_dir / rel, deduped, group="harvest")
            files[f"{name}_m3u"] = str(rel)
        rel_txt = Path("playlists") / f"{name}.txt"
        _write_txt(output_dir / rel_txt, deduped)
        files[f"{name}_txt"] = str(rel_txt)
    return {"created": True, "output_dir": "playlists", "files": files, "counts": counts}


def build_media_validation_dashboard(
    candidates: Iterable[Any],
    *,
    trusted_candidates: Iterable[Any] = (),
    review_candidates: Iterable[Any] = (),
    validation_attempted: int | None = None,
) -> dict[str, Any]:
    rows = list(candidates)
    trusted_keys = {_row_key(row) for row in trusted_candidates}
    review_keys = {_row_key(row) for row in review_candidates}
    by_media_type = Counter(media_type_for_row(row) for row in rows)
    by_status = Counter(validation_status_for_row(row) or "not_validated" for row in rows)
    buckets = Counter(status_bucket(validation_status_for_row(row)) for row in rows)
    attempted = validation_attempted
    if attempted is None:
        attempted = sum(1 for row in rows if status_bucket(validation_status_for_row(row)) != "not_validated")
    return {
        "total_candidates": len(rows),
        "validated": int(attempted or 0),
        "trusted": len(trusted_keys),
        "untrusted_review": len(review_keys - trusted_keys),
        "dead": buckets.get("dead", 0),
        "restricted": buckets.get("restricted", 0),
        "not_validated": buckets.get("not_validated", 0),
        "by_media_type": dict(sorted(by_media_type.items())),
        "by_validation_status": dict(sorted(by_status.items())),
    }


def _playable(row: Any, source_policy: Any | None) -> bool:
    media_type = media_type_for_row(row)
    return media_type in {"hls", "rtsp", "mjpeg", "stream", "video_file"} and _eligible_url(row, source_policy)


def _eligible_url(row: Any, source_policy: Any | None) -> bool:
    url = media_url_for_row(row)
    if not url:
        return False
    if is_private_or_local_media_url(url):
        return False
    if source_policy is not None:
        try:
            if source_policy.is_blocked(url):
                return False
        except Exception:
            pass
    return True


def _dedupe_rows(rows: Iterable[Any]) -> list[Any]:
    seen: set[tuple[str, str | None]] = set()
    out: list[Any] = []
    for row in rows:
        url = media_url_for_row(row).split("#", 1)[0]
        if not url:
            continue
        key = (url, _target_id(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _write_m3u(path: Path, rows: list[Any], *, group: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U"]
    for row in rows:
        url = media_url_for_row(row)
        title = _m3u_text(_title_for_row(row) or redact_url_userinfo(url) or "Camera")
        lines.append(f'#EXTINF:-1 tvg-name="{title}" group-title="{_m3u_text(group)}",{title}')
        lines.append(url)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_txt(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(media_url_for_row(row) + "\n" for row in rows), encoding="utf-8")


def _title_for_row(row: Any) -> str | None:
    metadata = _metadata(row)
    for value in (
        _get(row, "title", None),
        metadata.get("camera_name"),
        metadata.get("name"),
        _get(row, "location_text", None),
        metadata.get("location_display"),
        metadata.get("camera_id"),
        _get(row, "camera_id", None),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _m3u_text(value: str) -> str:
    return " ".join(str(value).replace("\n", " ").replace("\r", " ").replace('"', "'").split())[:300]


def _metadata(row: Any) -> dict[str, Any]:
    value = _get(row, "source_metadata", None) or _get(row, "metadata", None) or {}
    return value if isinstance(value, dict) else {}


def _get(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    if is_dataclass(row):
        return getattr(row, name, default)
    return getattr(row, name, default)


def _target_id(row: Any) -> str | None:
    value = _get(row, "target_id", None) or _metadata(row).get("target_id")
    return str(value) if value not in (None, "") else None


def _row_key(row: Any) -> tuple[str, str | None]:
    return (media_url_for_row(row).split("#", 1)[0], _target_id(row))


def row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    if is_dataclass(row):
        return asdict(row)
    return dict(getattr(row, "__dict__", {}))
