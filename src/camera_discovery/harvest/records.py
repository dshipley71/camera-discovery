from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from camera_discovery.core.models import (
    CameraCandidate,
    DiscoveredEndpointRecord,
    HarvestedCameraRecord,
    HarvestedMediaAsset,
    HarvestedUrlRecord,
)
from camera_discovery.sources import SourceEntry
from camera_discovery.harvest.json_records import coerce_bool, promoted_metadata_fields
from camera_discovery.harvest.media_filter import (
    canonical_media_url,
    classify_media_url,
    has_camera_image_evidence,
    image_record_text,
    media_extension,
)
from camera_discovery.extraction.media import _dedupe_strings
from camera_discovery.extraction.search import clean_ddg_result_url
from camera_discovery.discovery.official_source_queries import official_source_queries_for_intent
from camera_discovery.discovery.locations import localized_camera_terms_for_intent


def dedupe_records(records: list[HarvestedUrlRecord]) -> list[HarvestedUrlRecord]:
    by_key: dict[str, HarvestedUrlRecord] = {}
    order: list[str] = []
    for record in records:
        key = canonical_media_url(record.url)
        existing = by_key.get(key)
        if existing is None:
            record.url = key
            by_key[key] = record
            order.append(key)
            continue
        merge_record(existing, record)
    return [by_key[key] for key in order]

def merge_record(existing: HarvestedUrlRecord, duplicate: HarvestedUrlRecord) -> None:
    if not existing.title and duplicate.title:
        existing.title = duplicate.title
    if not existing.location_text and duplicate.location_text:
        existing.location_text = duplicate.location_text
    if not existing.camera_id and duplicate.camera_id:
        existing.camera_id = duplicate.camera_id
    if not existing.source_url and duplicate.source_url:
        existing.source_url = duplicate.source_url
    if not existing.source_name and duplicate.source_name:
        existing.source_name = duplicate.source_name
    if not existing.source_provider and duplicate.source_provider:
        existing.source_provider = duplicate.source_provider
    if existing.media_type == "unknown_media" and duplicate.media_type != "unknown_media":
        existing.media_type = duplicate.media_type
    for attr in ("camera_record_id", "asset_id", "asset_role", "asset_field", "field_path", "source_endpoint_url", "source_page_url", "json_record_path", "lat", "lon", "coordinate_source", "direction", "bearing", "heading", "orientation", "in_service", "status", "date", "time", "timestamp", "last_updated", "last_refresh", "image_description", "current_image_update_frequency", "reference_image_update_frequency"):
        if getattr(existing, attr) in (None, "") and getattr(duplicate, attr) not in (None, ""):
            setattr(existing, attr, getattr(duplicate, attr))
    for key, value in duplicate.metadata.items():
        if value in (None, "", [], {}):
            continue
        existing.metadata.setdefault(key, value)
    duplicate_sources = existing.metadata.setdefault("duplicate_sources", [])
    if duplicate.source_url and duplicate.source_url not in duplicate_sources and duplicate.source_url != existing.source_url:
        duplicate_sources.append(duplicate.source_url)

def record_from_candidate(candidate: CameraCandidate, *, include_metadata: bool = True) -> HarvestedUrlRecord:
    metadata = dict(candidate.source_metadata or {}) if include_metadata else {}
    if candidate.lat is not None:
        metadata.setdefault("lat", candidate.lat)
    if candidate.lon is not None:
        metadata.setdefault("lon", candidate.lon)
    if candidate.coordinate_source:
        metadata.setdefault("coordinate_source", candidate.coordinate_source)
    promoted = promoted_metadata_fields(metadata)
    media_type = normalize_candidate_media_type(metadata.get("media_type"), candidate.stream_url)
    return HarvestedUrlRecord(
        url=candidate.stream_url,
        media_type=media_type,
        source_url=candidate.source_url,
        discovery_method=candidate.discovery_method,
        title=candidate.title or metadata.get("camera_name"),
        location_text=candidate.location_text or metadata.get("location_display") or metadata.get("location_text"),
        camera_id=str(metadata.get("camera_id")) if metadata.get("camera_id") not in (None, "") else None,
        source_name=metadata.get("source_name"),
        source_provider=metadata.get("source_provider"),
        camera_record_id=metadata.get("camera_record_id"),
        asset_id=metadata.get("asset_id"),
        asset_role=metadata.get("asset_role"),
        asset_field=metadata.get("asset_field"),
        field_path=metadata.get("field_path"),
        source_endpoint_url=metadata.get("source_endpoint_url") or metadata.get("json_endpoint_url"),
        source_page_url=metadata.get("source_page_url"),
        json_record_path=metadata.get("json_record_path"),
        in_service=coerce_bool(metadata.get("in_service") if "in_service" in metadata else metadata.get("inService")),
        status=str(metadata.get("status")) if metadata.get("status") not in (None, "") else None,
        last_updated=str(metadata.get("last_updated") or metadata.get("lastUpdated")) if (metadata.get("last_updated") or metadata.get("lastUpdated")) not in (None, "") else None,
        last_refresh=str(metadata.get("last_refresh") or metadata.get("lastRefresh")) if (metadata.get("last_refresh") or metadata.get("lastRefresh")) not in (None, "") else None,
        image_description=str(metadata.get("imageDescription") or metadata.get("image_description")) if (metadata.get("imageDescription") or metadata.get("image_description")) not in (None, "") else None,
        current_image_update_frequency=metadata.get("currentImageUpdateFrequency") or metadata.get("current_image_update_frequency"),
        reference_image_update_frequency=metadata.get("referenceImageUpdateFrequency") or metadata.get("reference_image_update_frequency"),
        lat=promoted.get("lat"),
        lon=promoted.get("lon"),
        coordinate_source=promoted.get("coordinate_source"),
        direction=promoted.get("direction"),
        bearing=promoted.get("bearing"),
        heading=promoted.get("heading"),
        date=promoted.get("date"),
        time=promoted.get("time"),
        timestamp=promoted.get("timestamp"),
        metadata=metadata,
    )

def normalize_candidate_media_type(value: Any, url: str) -> str:
    text = str(value or "").strip().casefold()
    if text in {"hls", "rtsp", "rtsps", "mjpeg", "image_snapshot", "video_file", "stream", "unknown_media"}:
        return "rtsp" if text == "rtsps" else text
    if text == "other":
        return "stream"
    return classify_media_url(url) or "unknown_media"

def record_from_media_asset(asset: HarvestedMediaAsset, camera_record: HarvestedCameraRecord, *, row: dict[str, str]) -> HarvestedUrlRecord:
    metadata = dict(camera_record.metadata or {})
    metadata.update(asset.metadata or {})
    metadata.setdefault("source_provided_only", True)
    metadata.setdefault("validated", False)
    metadata.setdefault("trusted", False)
    metadata.setdefault("llm_reviewed", False)
    metadata.setdefault("camera_record_id", camera_record.camera_record_id)
    metadata.setdefault("asset_id", asset.asset_id)
    metadata.setdefault("asset_role", asset.asset_role)
    metadata.setdefault("asset_field", asset.asset_field)
    metadata.setdefault("field_path", asset.field_path)
    metadata.setdefault("source_endpoint_url", asset.source_endpoint_url)
    metadata.setdefault("json_record_path", asset.json_record_path)
    return HarvestedUrlRecord(
        url=asset.url,
        media_type=asset.media_type,
        source_url=asset.source_url or asset.source_endpoint_url or asset.source_page_url,
        discovery_method=asset.discovery_method,
        title=camera_record.title,
        description=camera_record.description,
        location_text=camera_record.location_text,
        camera_id=camera_record.camera_id,
        source_name=asset.source_name or camera_record.source_name or row.get("source_name") or row.get("title"),
        source_provider=asset.source_provider or camera_record.source_provider or row.get("source_provider"),
        camera_record_id=camera_record.camera_record_id,
        asset_id=asset.asset_id,
        asset_role=asset.asset_role,
        asset_field=asset.asset_field,
        field_path=asset.field_path,
        source_endpoint_url=asset.source_endpoint_url,
        source_page_url=asset.source_page_url,
        json_record_path=asset.json_record_path,
        lat=camera_record.lat,
        lon=camera_record.lon,
        coordinate_source=camera_record.coordinate_source,
        direction=camera_record.direction,
        bearing=camera_record.bearing,
        heading=camera_record.heading,
        orientation=camera_record.orientation,
        in_service=camera_record.in_service,
        status=camera_record.status,
        date=camera_record.date,
        time=camera_record.time,
        timestamp=camera_record.timestamp,
        last_updated=camera_record.last_updated,
        last_refresh=camera_record.last_refresh,
        image_description=camera_record.image_description,
        current_image_update_frequency=camera_record.current_image_update_frequency,
        reference_image_update_frequency=camera_record.reference_image_update_frequency,
        metadata={k: v for k, v in metadata.items() if v not in (None, "", [], {})},
    )

def record_from_url(
    url: str,
    media_type: str,
    *,
    source_url: str | None,
    row: dict[str, str],
    method: str,
    title: str | None = None,
    location_text: str | None = None,
    camera_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> HarvestedUrlRecord:
    metadata = dict(metadata or {})
    metadata.setdefault("source_row_url", row.get("url"))
    metadata.setdefault("original_query", row.get("original_query") or row.get("query"))
    metadata.setdefault("source_kind", row.get("source_kind"))
    metadata.setdefault("media_extension", media_extension(url))
    cleaned_metadata = {k: v for k, v in metadata.items() if v not in (None, "", [], {})}
    promoted = promoted_metadata_fields(cleaned_metadata)
    return HarvestedUrlRecord(
        url=url,
        media_type=media_type,
        source_url=source_url,
        discovery_method=method,
        title=title or row.get("title") or row.get("source_name"),
        location_text=location_text,
        camera_id=camera_id,
        source_name=row.get("source_name") or row.get("title"),
        source_provider=row.get("source_provider"),
        camera_record_id=cleaned_metadata.get("camera_record_id"),
        asset_id=cleaned_metadata.get("asset_id"),
        asset_role=cleaned_metadata.get("asset_role"),
        asset_field=cleaned_metadata.get("asset_field") or cleaned_metadata.get("json_media_key"),
        field_path=cleaned_metadata.get("field_path"),
        source_endpoint_url=cleaned_metadata.get("source_endpoint_url") or cleaned_metadata.get("json_endpoint_url"),
        source_page_url=cleaned_metadata.get("source_page_url"),
        json_record_path=cleaned_metadata.get("json_record_path"),
        in_service=coerce_bool(cleaned_metadata.get("in_service") if "in_service" in cleaned_metadata else cleaned_metadata.get("inService")),
        status=str(cleaned_metadata.get("status")) if cleaned_metadata.get("status") not in (None, "") else None,
        orientation=str(cleaned_metadata.get("orientation")) if cleaned_metadata.get("orientation") not in (None, "") else None,
        last_updated=str(cleaned_metadata.get("last_updated") or cleaned_metadata.get("lastUpdated")) if (cleaned_metadata.get("last_updated") or cleaned_metadata.get("lastUpdated")) not in (None, "") else None,
        last_refresh=str(cleaned_metadata.get("last_refresh") or cleaned_metadata.get("lastRefresh")) if (cleaned_metadata.get("last_refresh") or cleaned_metadata.get("lastRefresh")) not in (None, "") else None,
        image_description=str(cleaned_metadata.get("imageDescription") or cleaned_metadata.get("image_description")) if (cleaned_metadata.get("imageDescription") or cleaned_metadata.get("image_description")) not in (None, "") else None,
        current_image_update_frequency=cleaned_metadata.get("currentImageUpdateFrequency") or cleaned_metadata.get("current_image_update_frequency"),
        reference_image_update_frequency=cleaned_metadata.get("referenceImageUpdateFrequency") or cleaned_metadata.get("reference_image_update_frequency"),
        lat=promoted.get("lat"),
        lon=promoted.get("lon"),
        coordinate_source=promoted.get("coordinate_source"),
        direction=promoted.get("direction"),
        bearing=promoted.get("bearing"),
        heading=promoted.get("heading"),
        date=promoted.get("date"),
        time=promoted.get("time"),
        timestamp=promoted.get("timestamp"),
        metadata=cleaned_metadata,
    )

def row_from_source_entry(entry: SourceEntry, query: str, *, provider: str) -> dict[str, str]:
    return {
        "query": query,
        "title": entry.name,
        "url": entry.url,
        "snippet": entry.notes or "",
        "source_provider": provider,
        "source_kind": entry.source_type,
        "source_name": entry.name,
        "source_scope_hint": entry.scope_hint or "",
        "source_notes": entry.notes or "",
    }

def harvest_search_queries(query: str, max_queries: int) -> list[str]:
    if max_queries <= 0:
        return []
    intent = _infer_harvest_camera_intent(query)
    general = [
        query,
        f"{query} public cameras",
        f"{query} live cameras",
        f"{query} webcams",
        f"{query} camera map",
        f"{query} camera feed json",
        f"{query} public camera API json",
        f"{query} camera MapServer FeatureServer",
        f"{query} camera FeatureServer query",
        f"{query} camera GeoJSON",
        f"{query} m3u8",
        f"{query} snapshot camera",
    ]
    localized_terms = localized_camera_terms_for_intent(intent, query, include_generic=False)
    localized = [f"{query} {term}" for term in localized_terms]
    official_budget = min(10, max(2, max_queries // 3))
    official = official_source_queries_for_intent(
        intent,
        query,
        max_queries=official_budget,
        safe_exclusions=True,
    )
    general_pool = _dedupe_strings([*localized, *general])
    general_limit = max(0, max_queries - len(official))
    selected_general = general_pool[:general_limit]
    return _dedupe_strings(selected_general + [q for q in official if q not in set(selected_general)])[:max_queries]


def _infer_harvest_camera_intent(query: str) -> str:
    lowered = str(query or "").replace("_", " ").casefold()
    for intent, terms in {
        "traffic": ("traffic", "road", "roads", "highway", "freeway", "transportation", "511"),
        "weather": ("weather", "meteorological", "airport weather"),
        "airport": ("airport", "airfield", "aviation", "runway"),
        "beach": ("beach", "surf", "coastal", "shore", "pier"),
        "harbor": ("harbor", "port", "marina", "waterfront", "ferry"),
        "park": ("park", "wildlife", "trail", "visitor center"),
        "mountain": ("mountain", "ski", "snow", "pass"),
        "campus": ("campus", "university", "college"),
        "construction": ("construction", "project", "bridge", "infrastructure"),
        "city": ("city", "downtown", "municipal"),
    }.items():
        if any(term in lowered for term in terms):
            return intent
    return "default"

def clean_ddg_url(href: str) -> str:
    return clean_ddg_result_url(href)

def clean_extracted_url(value: str) -> str:
    raw = str(value or "").strip()
    decoded = raw.replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/")
    if decoded.startswith(("http://", "https://", "rtsp://", "rtsps://", "//")):
        return canonical_media_url(decoded)
    return decoded.strip("\'\"),;}]")
