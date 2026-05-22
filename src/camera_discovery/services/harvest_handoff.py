from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from camera_discovery.core.models import CameraCandidate
from camera_discovery.sources import SourcePolicy


def load_harvest_handoff(path: Path) -> list[dict[str, Any]]:
    """Load harvest_handoff.json or harvest_camera_inventory.jsonl records."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Harvest input does not exist: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema_version", "").startswith("harvest-handoff/"):
            files = data.get("files") or {}
            inventory_name = files.get("harvest_camera_inventory")
            if not inventory_name:
                raise ValueError(f"Harvest handoff manifest missing files.harvest_camera_inventory: {path}")
            inventory_path = (path.parent / inventory_name).resolve()
            return _read_jsonl(inventory_path)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        raise ValueError(f"Unsupported harvest JSON input: {path}")
    if path.suffix.lower() == ".jsonl":
        return _read_jsonl(path)
    raise ValueError(f"Unsupported harvest input extension for {path}; use harvest_handoff.json or harvest_camera_inventory.jsonl")


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
            if source_policy and source_policy.is_blocked(url):
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
                stream_url=url.strip(),
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
