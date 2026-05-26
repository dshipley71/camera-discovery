from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from camera_discovery.core.models import CameraCandidate
from camera_discovery.enrichment.location import _valid_lat_lon
from camera_discovery.extraction.media import (
    _dedupe_media_urls,
    _dedupe_strings,
    _float_or_none,
    _looks_like_hls,
    _looks_like_image,
    _looks_like_non_camera_asset,
    _looks_like_thumbnail_asset,
)


URL_KEYS = {"url", "stream", "stream_url", "streamurl", "hls", "hls_url", "hlsurl", "video", "video_url", "src"}
IMAGE_KEYS = {"image", "image_url", "imageurl", "snapshot", "snapshot_url", "snapshoturl", "thumbnail", "thumbnail_url", "thumbnailurl", "preview", "preview_url", "poster", "poster_url"}
THUMBNAIL_IMAGE_KEYS = {"thumbnail", "thumbnail_url", "thumbnailurl", "thumb", "thumb_url", "preview", "preview_url", "poster", "poster_url", "referenceimageurl", "referenceimage1url"}
LAT_KEYS = {"lat", "latitude", "camera_latitude", "cameralatitude", "y", "data_lat", "data_latitude"}
LON_KEYS = {"lon", "lng", "long", "longitude", "camera_longitude", "cameralongitude", "x", "data_lon", "data_lng", "data_longitude"}
TITLE_KEYS = {"name", "title", "label", "description", "camera", "camera_name", "cameraname", "display_name", "displayname", "id"}

JSON_FIELD_ALIASES: dict[str, set[str]] = {
    "camera_id": {"id", "camera_id", "cameraid", "cctv_id", "cctvid", "device_id", "deviceid", "station_id", "stationid", "site_id", "siteid", "identifier", "objectid", "fid"},
    "camera_name": {"name", "title", "display_name", "displayname", "camera_name", "cameraname", "label"},
    "camera_description": {"description", "desc", "camera_description", "cameradescription", "imagedescription", "image_description"},
    "camera_type": {"type", "camera_type", "cameratype", "category", "device_type", "devicetype", "kind", "class", "subtype"},
    "camera_status": {"status", "camera_status", "camerastatus", "state", "availability"},
    "route": {"route", "road", "roadway", "highway", "corridor", "route_name", "routename", "route_number", "routenumber"},
    "direction": {"direction", "dir", "bearing", "travel_direction", "traveldirection"},
    "location_text": {"location", "location_text", "locationtext", "location_description", "locationdescription", "nearest_location", "nearestlocation", "place", "intersection"},
    "cross_street": {"cross_street", "crossstreet", "cross_road", "crossroad", "crossroadname"},
    "city": {"city", "municipality", "town"},
    "county": {"county", "parish", "borough"},
    "district": {"district", "region", "area", "zone"},
    "state": {"state", "province", "admin_region", "adminregion"},
    "country": {"country", "nation"},
    "owner": {"owner", "operator", "maintainer"},
    "agency": {"agency", "organization", "organisation", "department", "provider"},
    "milepost": {"milepost", "mile_marker", "milemarker", "postmile", "post_mile"},
    "stream_url": {"stream_url", "streamurl", "streaming_url", "streamingurl", "streamingvideourl", "streaming_video_url", "video_url", "videourl", "hls_url", "hlsurl", "hls", "m3u8", "url", "src"},
    "snapshot_url": {"snapshot_url", "snapshoturl", "current_image_url", "currentimageurl", "image_url", "imageurl", "camera_image_url", "cameraimageurl", "still_image_url", "stillimageurl", "currentimage", "image"},
    "thumbnail_url": {"thumbnail_url", "thumbnailurl", "thumb_url", "thumburl", "preview_url", "previewurl", "poster_url", "posterurl", "reference_image_url", "referenceimageurl", "referenceimage1url"},
    "refresh_rate": {"camera_refresh_rate", "camerarefreshrate", "refresh_rate", "refreshrate", "refresh_seconds", "refreshseconds", "refresh_interval", "refreshinterval", "update_interval", "updateinterval", "update_frequency", "updatefrequency", "currentimageupdatefrequency", "referenceimageupdatefrequency", "image_refresh_seconds", "imagerefreshseconds"},
}

CAMERA_TYPE_DISPLAY_CATEGORIES = {
    "traffic", "weather", "transit", "beach", "airport", "port", "park", "ski",
    "security_public_safety", "tourism", "public", "camera", "other", "unknown",
}


def _looks_like_json_response(url: str, content_type: str, text: str) -> bool:
    ctype = content_type.casefold()
    if "json" in ctype:
        return True
    if url.lower().split("?", 1)[0].endswith(".json"):
        return True
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")

def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key).casefold())

def _record_alias_value(record: dict[str, Any], canonical_key: str) -> Any:
    aliases = JSON_FIELD_ALIASES.get(canonical_key, {canonical_key})
    normalized_aliases = {_normalize_key(alias) for alias in aliases}
    for actual, value in record.items():
        if _normalize_key(actual) in normalized_aliases and value not in (None, ""):
            return value
    return None

def _first_record_alias_text(record: dict[str, Any], canonical_key: str, *, max_len: int = 300) -> str | None:
    value = _record_alias_value(record, canonical_key)
    if isinstance(value, str) and value.strip():
        return value.strip()[:max_len]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)[:max_len]
    return None

def _parse_refresh_seconds(value: Any) -> float | int | str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return None
    numeric = _float_or_none(text)
    if numeric is not None:
        return int(numeric) if numeric.is_integer() else numeric
    match = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b", text, re.I)
    if match:
        amount = float(match.group(1))
        unit = match.group(2).casefold()
        seconds = amount * 60 if unit.startswith("m") else amount
        return int(seconds) if seconds.is_integer() else seconds
    return text[:80]

def _normalize_camera_type(value: Any) -> tuple[str, str | None]:
    raw = str(value).strip() if value not in (None, "") else ""
    if not raw:
        return "camera", None
    lowered = raw.casefold()
    if any(token in lowered for token in ("traffic", "road", "highway", "cctv", "transportation")):
        return "traffic", raw
    if any(token in lowered for token in ("weather", "wx", "meteo")):
        return "weather", raw
    if any(token in lowered for token in ("transit", "rail", "bus", "train")):
        return "transit", raw
    if any(token in lowered for token in ("beach", "surf", "coast")):
        return "beach", raw
    if "airport" in lowered:
        return "airport", raw
    if any(token in lowered for token in ("port", "harbor", "harbour", "marina")):
        return "port", raw
    if any(token in lowered for token in ("park", "trail")):
        return "park", raw
    if any(token in lowered for token in ("ski", "snow", "mountain")):
        return "ski", raw
    if any(token in lowered for token in ("security", "public safety", "police", "fire")):
        return "security_public_safety", raw
    if any(token in lowered for token in ("tourism", "tourist", "public", "webcam")):
        return "tourism" if "tour" in lowered else "public", raw
    if any(token in lowered for token in ("camera", "cam", "video", "image")):
        return "camera", raw
    return "other", raw

def _bounded_json_record(record: dict[str, Any], *, max_items: int = 60, max_value_len: int = 300) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if len(out) >= max_items:
            break
        key_text = str(key)[:120]
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key_text] = value if not isinstance(value, str) else value[:max_value_len]
        elif isinstance(value, list):
            scalar_items = [item if not isinstance(item, str) else item[:max_value_len] for item in value if isinstance(item, (str, int, float, bool)) or item is None]
            if scalar_items:
                out[key_text] = scalar_items[:10]
        elif isinstance(value, dict):
            nested = _bounded_json_record(value, max_items=12, max_value_len=120)
            if nested:
                out[key_text] = nested
    return out

def _source_record_schema_hint(record: dict[str, Any]) -> str:
    if str(record.get("type") or "").casefold() == "feature" and isinstance(record.get("geometry"), dict):
        return "geojson_feature"
    if isinstance(record.get("attributes"), dict) and isinstance(record.get("geometry"), dict):
        return "arcgis_feature"
    if any(_normalize_key(key) in {_normalize_key(alias) for alias in JSON_FIELD_ALIASES["stream_url"] | JSON_FIELD_ALIASES["snapshot_url"]} for key in record):
        return "flat_record"
    return "generic_record"

def _media_type_from_url_and_key(url: str, key_norm: str) -> str | None:
    lower = url.casefold()
    if _looks_like_hls(url) or ".m3u8" in lower:
        return "hls"
    if re.search(r"\.(?:mjpg|mjpeg)(?:\?|$)", lower) or "mjpeg" in key_norm:
        return "mjpeg"
    if re.search(r"\.(?:mp4|webm|mov)(?:\?|$)", lower):
        return "video_file"
    if _looks_like_image(url) or key_norm in {_normalize_key(alias) for alias in JSON_FIELD_ALIASES["snapshot_url"]}:
        return "image_snapshot"
    if lower.startswith(("http://", "https://")) and any(token in key_norm for token in ("stream", "video", "media")):
        return "other"
    return None

def _json_camera_record_metadata(record: dict[str, Any], source_url: str, *, record_path: str = "", schema_hint: str | None = None) -> dict[str, Any]:
    flattened = _flatten_camera_record(record)
    metadata: dict[str, Any] = {}
    metadata.update(_simple_metadata(flattened))
    metadata["json_metadata_extracted"] = True
    metadata["json_endpoint_url"] = source_url
    metadata["json_record_path"] = record_path
    metadata["json_record_schema_hint"] = schema_hint or _source_record_schema_hint(record)
    metadata["json_record_fields"] = [str(key) for key in list(flattened.keys())[:80]]
    metadata["json_record_raw"] = _bounded_json_record(record)

    for canonical in (
        "camera_id", "camera_name", "camera_description", "camera_type", "camera_status", "route", "direction",
        "location_text", "cross_street", "city", "county", "district", "state", "country", "owner", "agency", "milepost",
        "thumbnail_url",
    ):
        value = _record_alias_value(flattened, canonical)
        if value not in (None, ""):
            if canonical == "camera_type":
                normalized_type, raw_type = _normalize_camera_type(value)
                metadata["camera_type"] = normalized_type
                if raw_type:
                    metadata["raw_camera_type"] = raw_type
            else:
                metadata[canonical] = str(value)[:500] if isinstance(value, str) else value

    name = _first_record_alias_text(flattened, "camera_name")
    if name:
        metadata.setdefault("camera_name", name)
    description = _first_record_alias_text(flattened, "camera_description")
    if description:
        metadata.setdefault("camera_description", description)
    location_parts = [metadata.get(key) for key in ("location_text", "route", "direction", "cross_street", "city", "county", "district")]
    location_parts = [str(part).strip() for part in location_parts if isinstance(part, (str, int, float)) and str(part).strip()]
    if location_parts:
        metadata.setdefault("location_display", ", ".join(_dedupe_strings(location_parts))[:500])

    refresh = _parse_refresh_seconds(_record_alias_value(flattened, "refresh_rate"))
    if refresh not in (None, ""):
        metadata["camera_refresh_rate"] = refresh
        metadata["refresh_rate_seconds"] = refresh
        metadata["image_snapshot_refresh_delay_seconds"] = refresh
        metadata["map_refresh_rate_seconds"] = refresh

    lat_lon = _record_lat_lon(flattened)
    if lat_lon:
        metadata["latitude"] = lat_lon[0]
        metadata["longitude"] = lat_lon[1]
        metadata["json_coordinate_source"] = "json_arcgis_geometry" if isinstance(record.get("geometry"), dict) and {"x", "y"}.issubset(record["geometry"].keys()) else "json_record"
        metadata["coordinate_source"] = "source_record"
    return metadata

def _stable_camera_id(metadata: dict[str, Any], media_url: str) -> str | None:
    for key in ("camera_id", "id", "device_id", "station_id", "site_id", "camera_name"):
        value = metadata.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text:
                return text[:160]
    parsed = urlparse(media_url)
    segments = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
    if segments:
        stem = segments[-1].split(".", 1)[0]
        if stem.casefold() == "playlist" and len(segments) >= 2:
            return segments[-2].split(".", 1)[0][:160]
        return stem[:160]
    return None

def _record_looks_like_camera_record(record: dict[str, Any]) -> bool:
    keys = {_normalize_key(key) for key in record.keys()}
    camera_aliases = set()
    for canonical in ("camera_id", "camera_name", "camera_type", "stream_url", "snapshot_url", "location_text", "route"):
        camera_aliases |= {_normalize_key(alias) for alias in JSON_FIELD_ALIASES.get(canonical, set())}
    return bool(keys & camera_aliases)

def _update_json_stats(stats: dict[str, Any], candidates: list[CameraCandidate], record: dict[str, Any]) -> None:
    if not candidates:
        return
    stats["records_considered"] += 1
    stats["records_with_media"] += 1
    if any(c.has_coordinates for c in candidates):
        stats["records_with_authoritative_coordinates"] += 1
    metadata = candidates[0].source_metadata if candidates else {}
    if any(metadata.get(key) not in (None, "") for key in ("camera_refresh_rate", "refresh_rate_seconds", "image_snapshot_refresh_delay_seconds")):
        stats["records_with_refresh_metadata"] += 1
    if metadata.get("camera_type"):
        stats["records_with_camera_type"] += 1
    for candidate in candidates:
        media_type = _candidate_media_type(candidate)
        if media_type == "hls":
            stats["hls_candidates"] += 1
        elif media_type == "image_snapshot":
            stats["image_snapshot_candidates"] += 1
        else:
            stats["other_media_candidates"] += 1

def _record_media_urls(record: dict[str, Any], base_url: str) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    thumbnail_aliases = {_normalize_key(alias) for alias in JSON_FIELD_ALIASES["thumbnail_url"]} | {_normalize_key(key) for key in THUMBNAIL_IMAGE_KEYS}
    stream_aliases = {_normalize_key(alias) for alias in JSON_FIELD_ALIASES["stream_url"]}
    snapshot_aliases = {_normalize_key(alias) for alias in JSON_FIELD_ALIASES["snapshot_url"]}
    for key, value in record.items():
        key_norm = _normalize_key(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str) or not item.strip():
                continue
            raw = item.strip()
            absolute = urljoin(base_url, raw)
            lower = absolute.casefold()
            has_media_extension = bool(re.search(r"\.(?:m3u8|mjpg|mjpeg|mp4|webm|mov|jpg|jpeg|png|webp)(?:\?|$)", lower))
            is_media_key = key_norm in stream_aliases or key_norm in snapshot_aliases
            if not has_media_extension and not is_media_key:
                continue
            media_type = _media_type_from_url_and_key(absolute, key_norm)
            if not media_type:
                continue
            if media_type == "image_snapshot":
                # Preview/thumbnail fields are useful metadata when another real
                # stream URL exists, but they are not themselves refreshing camera
                # feeds. Do not promote thumbnail CDN/object-store assets to
                # stream_url candidates.
                if _looks_like_non_camera_asset(absolute) or _looks_like_thumbnail_asset(absolute) or key_norm in thumbnail_aliases:
                    continue
            urls.append((absolute, media_type))
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
