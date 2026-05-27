from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from camera_discovery.core.models import CameraCandidate
from camera_discovery.harvest.media_filter import canonical_media_url
from camera_discovery.sources import SourcePolicy


@dataclass
class HarvestHandoffLoad:
    """Resolved harvest input records plus manifest metadata."""

    records: list[dict[str, Any]]
    source_path: Path
    source_file: Path | None = None
    schema_version: str | None = None
    media_filter: list[str] = field(default_factory=list)
    handoff_default_scope: str | None = None
    loaded_artifact: str | None = None
    files: dict[str, Any] = field(default_factory=dict)

    @property
    def filtered_by_handoff_media_filter(self) -> bool:
        return bool(self.media_filter) and self.loaded_artifact in {"camera_urls_jsonl", "filtered_media_records"}


def load_harvest_handoff(path: Path) -> list[dict[str, Any]]:
    """Load harvest_handoff.json or harvest_camera_inventory.jsonl records."""
    return load_harvest_handoff_bundle(path).records


def load_harvest_handoff_bundle(path: Path) -> HarvestHandoffLoad:
    """Load harvest input and preserve handoff media-filter metadata."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Harvest input does not exist: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema_version", "").startswith("harvest-handoff/"):
            files = data.get("files") or {}
            if not isinstance(files, dict):
                raise ValueError(f"Harvest handoff manifest has invalid files section: {path}")
            media_filter = _string_list(data.get("media_filter"))
            default_scope = str(data.get("handoff_default_scope") or "").strip() or None
            artifact_key = _default_handoff_artifact(files, media_filter, default_scope)
            file_name = files.get(artifact_key)
            if not file_name:
                raise ValueError(f"Harvest handoff manifest missing files.{artifact_key}: {path}")
            records_path = (path.parent / str(file_name)).resolve()
            return HarvestHandoffLoad(
                records=_read_jsonl(records_path),
                source_path=path,
                source_file=records_path,
                schema_version=str(data.get("schema_version") or ""),
                media_filter=media_filter,
                handoff_default_scope=default_scope,
                loaded_artifact=artifact_key,
                files=files,
            )
        if isinstance(data, list):
            return HarvestHandoffLoad(records=[item for item in data if isinstance(item, dict)], source_path=path, source_file=path)
        raise ValueError(f"Unsupported harvest JSON input: {path}")
    if path.suffix.lower() == ".jsonl":
        return HarvestHandoffLoad(records=_read_jsonl(path), source_path=path, source_file=path, loaded_artifact=path.name)
    raise ValueError(f"Unsupported harvest input extension for {path}; use harvest_handoff.json or harvest_camera_inventory.jsonl")


def describe_harvest_handoff(path: Path) -> dict[str, Any]:
    """Return lightweight handoff metadata for CLI reporting."""
    path = Path(path)
    if not path.exists() or path.suffix.lower() != ".json":
        return {"path": str(path), "exists": path.exists()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"path": str(path), "exists": True, "error": repr(exc)}
    if not isinstance(data, dict):
        return {"path": str(path), "exists": True, "schema_version": None}
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    media_filter = _string_list(data.get("media_filter"))
    default_scope = str(data.get("handoff_default_scope") or "").strip() or None
    return {
        "path": str(path),
        "exists": True,
        "schema_version": data.get("schema_version"),
        "media_filter": media_filter,
        "handoff_default_scope": default_scope,
        "default_artifact": _default_handoff_artifact(files, media_filter, default_scope) if files else None,
        "counts": data.get("counts") if isinstance(data.get("counts"), dict) else {},
    }


def _default_handoff_artifact(files: dict[str, Any], media_filter: list[str], default_scope: str | None) -> str:
    if default_scope in {"filtered_media_records", "final_media_records"} and files.get("camera_urls_jsonl"):
        return "camera_urls_jsonl"
    if default_scope == "structured_inventory_records" and files.get("harvest_camera_inventory"):
        return "harvest_camera_inventory"
    normalized_media = {str(item).strip().casefold() for item in media_filter}
    if media_filter and normalized_media not in ({"all"}, {"*"}) and files.get("camera_urls_jsonl"):
        return "camera_urls_jsonl"
    if files.get("harvest_camera_inventory"):
        return "harvest_camera_inventory"
    if files.get("camera_urls_jsonl"):
        return "camera_urls_jsonl"
    raise ValueError("Harvest handoff manifest does not reference a supported input artifact")


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def harvest_records_to_candidates(
    records: Iterable[dict[str, Any]],
    *,
    target_id: str | None = None,
    target_index: int | None = None,
    target_label: str | None = None,
    source_policy: SourcePolicy | None = None,
) -> list[CameraCandidate]:
    candidates: list[CameraCandidate] = []
    for record in records:
        metadata_base = _metadata_from_record(record)
        assets = record.get("media_assets") or []
        if not isinstance(assets, list):
            assets = []
        # Accept URL rows saved as inventory pseudo-records too.
        if not assets and record.get("url"):
            assets = [record]
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            url = asset.get("url") or asset.get("media_url")
            if not isinstance(url, str) or not url.strip():
                continue
            canonical_url = canonical_media_url(url)
            if source_policy and source_policy.is_blocked(canonical_url):
                continue
            metadata = dict(metadata_base)
            metadata.update({k: v for k, v in asset.items() if v not in (None, "", [], {})})
            metadata.setdefault("source_provided_only", True)
            metadata.setdefault("validated", False)
            metadata.setdefault("trusted", False)
            metadata.setdefault("llm_reviewed", False)
            metadata.setdefault("harvest_input", True)
            metadata.setdefault("media_type", asset.get("media_type"))
            metadata.setdefault("camera_record_id", record.get("camera_record_id"))
            metadata.setdefault("asset_id", asset.get("asset_id"))
            lat = _coerce_float(record.get("lat"))
            lon = _coerce_float(record.get("lon"))
            if not _plausible_lat_lon(lat, lon):
                lat = _coerce_float(asset.get("lat"))
                lon = _coerce_float(asset.get("lon"))
            candidate = CameraCandidate(
                stream_url=canonical_url,
                source_url=asset.get("source_url") or record.get("source_endpoint_url") or record.get("source_page_url"),
                discovery_method="harvest_handoff",
                title=record.get("title") or asset.get("title"),
                lat=lat if _plausible_lat_lon(lat, lon) else None,
                lon=lon if _plausible_lat_lon(lat, lon) else None,
                location_text=record.get("location_text") or asset.get("location_text"),
                source_metadata=metadata,
                target_id=target_id,
                target_index=target_index,
                target_label=target_label,
                coordinate_source=record.get("coordinate_source") or asset.get("coordinate_source"),
                reasons=["seeded from harvest input; still unvalidated/untrusted until normal run processing"],
            )
            candidates.append(candidate)
    return candidates


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"Harvest inventory file does not exist: {path}")
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL in {path} at line {lineno}: {exc}") from exc
        if isinstance(item, dict):
            records.append(item)
    return records


def _metadata_from_record(record: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    for key in (
        "camera_record_id",
        "camera_id",
        "source_endpoint_url",
        "source_page_url",
        "source_provider",
        "source_name",
        "json_record_path",
        "media_type",
        "lat",
        "lon",
        "coordinate_source",
        "direction",
        "bearing",
        "heading",
        "orientation",
        "in_service",
        "status",
        "timestamp",
        "last_updated",
        "last_refresh",
        "image_description",
        "current_image_update_frequency",
        "reference_image_update_frequency",
    ):
        if record.get(key) not in (None, "", [], {}):
            metadata.setdefault(key, record.get(key))
    return metadata


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _plausible_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
