from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from camera_discovery.core.models import CameraCandidate, HarvestedUrlRecord
from camera_discovery.harvest.media_filter import canonical_media_url


@dataclass
class ExtractedEvidence:
    """Neutral raw media evidence shared by harvest and discovery.

    Evidence is source-provided and extraction-only. It is not validated,
    trusted, scoped, or semantically reviewed until discovery converts it into a
    ``CameraCandidate`` and runs the normal target-aware pipeline.
    """

    media_url: str
    source_url: str | None = None
    media_type: str | None = None
    title: str | None = None
    lat: float | None = None
    lon: float | None = None
    source_provider: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    extraction_method: str = "unknown"


def harvested_url_record_to_evidence(record: HarvestedUrlRecord | dict[str, Any]) -> ExtractedEvidence:
    """Convert a harvested URL row into neutral evidence without trust state."""
    if isinstance(record, HarvestedUrlRecord):
        metadata = dict(record.metadata or {})
        metadata.update(
            {
                k: v
                for k, v in {
                    "camera_id": record.camera_id,
                    "camera_record_id": record.camera_record_id,
                    "asset_id": record.asset_id,
                    "asset_role": record.asset_role,
                    "asset_field": record.asset_field,
                    "field_path": record.field_path,
                    "source_endpoint_url": record.source_endpoint_url,
                    "source_page_url": record.source_page_url,
                    "json_record_path": record.json_record_path,
                    "coordinate_source": record.coordinate_source,
                    "source_policy_checked": True,
                }.items()
                if v not in (None, "", [], {})
            }
        )
        return ExtractedEvidence(
            media_url=record.url,
            source_url=record.source_url,
            media_type=record.media_type,
            title=record.title,
            lat=record.lat,
            lon=record.lon,
            source_provider=record.source_provider,
            source_metadata=metadata,
            extraction_method=record.discovery_method,
        )
    metadata = dict(record.get("metadata") or {})
    metadata.update({k: v for k, v in record.items() if v not in (None, "", [], {}) and k != "metadata"})
    return ExtractedEvidence(
        media_url=str(record.get("url") or record.get("media_url") or ""),
        source_url=record.get("source_url") or record.get("source_endpoint_url") or record.get("source_page_url"),
        media_type=record.get("media_type"),
        title=record.get("title"),
        lat=_coerce_float(record.get("lat")),
        lon=_coerce_float(record.get("lon")),
        source_provider=record.get("source_provider"),
        source_metadata=metadata,
        extraction_method=str(record.get("discovery_method") or record.get("extraction_method") or "unknown"),
    )


def evidence_to_camera_candidate(
    evidence: ExtractedEvidence,
    *,
    target_id: str | None = None,
    target_index: int | None = None,
    target_label: str | None = None,
) -> CameraCandidate:
    """Prepare discovery-side candidate evidence while leaving gates untouched."""
    metadata = dict(evidence.source_metadata or {})
    metadata.setdefault("source_provided_only", True)
    metadata.setdefault("validated", False)
    metadata.setdefault("trusted", False)
    metadata.setdefault("scope_filtered", False)
    metadata.setdefault("llm_reviewed", False)
    metadata.setdefault("harvest_input", True)
    metadata.setdefault("media_type", evidence.media_type)
    metadata.setdefault("source_policy_checked", True)
    return CameraCandidate(
        stream_url=canonical_media_url(evidence.media_url),
        source_url=evidence.source_url,
        discovery_method="harvest_handoff",
        title=evidence.title,
        lat=evidence.lat if _plausible_lat_lon(evidence.lat, evidence.lon) else None,
        lon=evidence.lon if _plausible_lat_lon(evidence.lat, evidence.lon) else None,
        location_text=metadata.get("location_text"),
        source_metadata=metadata,
        target_id=target_id,
        target_index=target_index,
        target_label=target_label,
        coordinate_source=metadata.get("coordinate_source"),
        reasons=["seeded from harvest input; still unvalidated/untrusted until normal run processing"],
    )


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _plausible_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
