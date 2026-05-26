from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Any
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from camera_discovery.core.models import HarvestedCameraRecord, HarvestedMediaAsset

_MEDIA_EXT_RE = re.compile(r"\.(m3u8|mjpg|mjpeg|jpg|jpeg|png|webp|mp4|webm|mov|m4v)(?:$|[?#])", re.I)
_URL_RE = re.compile(r"^https?://", re.I)

MEDIA_FIELD_ROLES = {
    "streamingvideourl": "streaming_video",
    "streamingurl": "streaming_video",
    "streamurl": "streaming_video",
    "streamurlhls": "hls_stream",
    "videourl": "video_file",
    "hlsurl": "hls_stream",
    "m3u8url": "hls_stream",
    "mjpegurl": "mjpeg_stream",
    "currentimageurl": "current_image_snapshot",
    "referenceimageurl": "reference_image_snapshot",
    "imageurl": "image_snapshot",
    "snapshoturl": "image_snapshot",
    "thumbnailurl": "thumbnail",
    "mediaurl": "media_url",
    "url": "media_url",
}
MEDIA_KEY_TERMS = {"stream", "video", "hls", "m3u8", "mjpeg", "image", "snapshot", "thumbnail", "media"}
IDENTITY_KEYS = {"id", "cameraid", "camera_id", "camera", "deviceid", "device_id", "name", "title", "label"}
TEXT_KEYS = {
    "description",
    "imagedescription",
    "location",
    "locationname",
    "locationdescription",
    "intersection",
    "route",
    "road",
    "milepost",
}
STATUS_KEYS = {"inservice", "in_service", "isactive", "active", "enabled", "online", "status", "camerastatus", "operationalstatus"}
TIME_KEYS = {
    "timestamp",
    "date",
    "time",
    "datetime",
    "recorddate",
    "recordtime",
    "recordepoch",
    "recorddatetime",
    "lastupdated",
    "lastupdate",
    "lastrefresh",
    "lastrefreshed",
    "updatedat",
    "createdat",
    "capturetime",
    "imagetimestamp",
    "snapshottimestamp",
}
LAT_KEYS = {"lat", "latitude", "cameralat", "cameralatitude"}
LON_KEYS = {"lon", "lng", "long", "longitude", "cameralon", "cameralng", "cameralongitude"}
ORIENTATION_KEYS = {"direction", "cameradirection", "facing", "facingdirection", "viewdirection", "orientation", "bearing", "heading", "azimuth", "angle"}
REFRESH_KEYS = {"currentimageupdatefrequency", "referenceimageupdatefrequency", "refreshrate", "refreshinterval", "refreshseconds", "updateinterval", "imagerefreshrate", "snapshotrefreshinterval"}
CAMERA_TERMS = {"camera", "cam", "webcam", "trafficcam", "cctv"}


def extract_structured_camera_records(
    data: Any,
    *,
    endpoint_url: str,
    source_page_url: str | None,
    source_provider: str | None,
    source_name: str | None,
    include_raw_record: bool = True,
) -> list[HarvestedCameraRecord]:
    """Extract source-provided camera objects and grouped media assets.

    This is deterministic and source-agnostic. It preserves public source data
    but does not validate, geocode, trust, scope, or infer missing fields.
    """
    records: list[HarvestedCameraRecord] = []
    accepted_paths: list[str] = []
    for path, obj in _walk_objects(data):
        if not isinstance(obj, dict):
            continue
        if any(path.startswith(f"{accepted}.") or path.startswith(f"{accepted}[") for accepted in accepted_paths):
            continue
        # Feature wrappers merge sibling geometry with attributes/properties.
        # Skip the nested attributes/properties object itself so one camera does
        # not produce duplicate records with a different path.
        if path.endswith(".attributes") or path.endswith(".properties"):
            continue
        flattened = _record_payload(obj)
        if not _looks_like_camera_record(flattened):
            continue
        record = _camera_record_from_payload(
            flattened,
            path=path,
            endpoint_url=endpoint_url,
            source_page_url=source_page_url,
            source_provider=source_provider,
            source_name=source_name,
            raw_record=obj if include_raw_record else {},
        )
        if record.media_assets or record.lat is not None or record.lon is not None or record.camera_id or record.title:
            records.append(record)
            accepted_paths.append(path)
    return _dedupe_camera_records(records)


def endpoint_type_for_url(url: str, content_type: str = "") -> str:
    lowered = url.casefold()
    ctype = content_type.casefold()
    if "geojson" in ctype or lowered.endswith(".geojson") or "f=geojson" in lowered:
        return "geojson"
    if "featureserver" in lowered:
        return "arcgis_featureserver"
    if "mapserver" in lowered:
        return "arcgis_mapserver"
    if "rss" in ctype or lowered.endswith(".rss"):
        return "rss"
    if "xml" in ctype or lowered.endswith(".xml"):
        return "xml"
    if "json" in ctype or lowered.endswith(".json") or "f=json" in lowered:
        return "json"
    if any(token in lowered for token in ("/api/", "/query", "/feed", "/feeds")):
        return "unknown_api"
    return "unknown_api"


def camera_record_to_inventory(record: HarvestedCameraRecord) -> dict[str, Any]:
    data = asdict(record)
    data["source_provided_only"] = True
    data["validated"] = False
    data["geocoded"] = False
    data["scope_filtered"] = False
    data["trusted"] = False
    data["llm_reviewed"] = False
    return data


def url_record_to_inventory(url_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "camera_record_id": url_record.get("camera_record_id") or f"url:{_stable_hash(url_record.get('url') or '')}",
        "camera_id": url_record.get("camera_id"),
        "title": url_record.get("title"),
        "description": url_record.get("description"),
        "location_text": url_record.get("location_text"),
        "lat": url_record.get("lat"),
        "lon": url_record.get("lon"),
        "coordinate_source": url_record.get("coordinate_source"),
        "direction": url_record.get("direction"),
        "bearing": url_record.get("bearing"),
        "heading": url_record.get("heading"),
        "orientation": url_record.get("orientation"),
        "in_service": url_record.get("in_service"),
        "status": url_record.get("status"),
        "date": url_record.get("date"),
        "time": url_record.get("time"),
        "timestamp": url_record.get("timestamp"),
        "last_updated": url_record.get("last_updated"),
        "last_refresh": url_record.get("last_refresh"),
        "image_description": url_record.get("image_description"),
        "current_image_update_frequency": url_record.get("current_image_update_frequency"),
        "reference_image_update_frequency": url_record.get("reference_image_update_frequency"),
        "media_assets": [
            {
                "asset_id": url_record.get("asset_id") or f"asset:{_stable_hash(url_record.get('url') or '')}",
                "camera_record_id": url_record.get("camera_record_id"),
                "url": url_record.get("url"),
                "media_type": url_record.get("media_type"),
                "asset_role": url_record.get("asset_role"),
                "asset_field": url_record.get("asset_field"),
                "source_url": url_record.get("source_url"),
                "source_endpoint_url": url_record.get("source_endpoint_url"),
                "source_page_url": url_record.get("source_page_url"),
                "source_provider": url_record.get("source_provider"),
                "source_name": url_record.get("source_name"),
                "discovery_method": url_record.get("discovery_method"),
                "json_record_path": url_record.get("json_record_path"),
                "field_path": url_record.get("field_path"),
                "metadata": url_record.get("metadata") or {},
            }
        ] if url_record.get("url") else [],
        "source_endpoint_url": url_record.get("source_endpoint_url"),
        "source_page_url": url_record.get("source_page_url"),
        "source_provider": url_record.get("source_provider"),
        "source_name": url_record.get("source_name"),
        "json_record_path": url_record.get("json_record_path"),
        "normalized_fields": {},
        "field_map": {},
        "metadata": url_record.get("metadata") or {},
        "raw_record": {},
        "source_provided_only": True,
        "validated": False,
        "geocoded": False,
        "scope_filtered": False,
        "trusted": False,
        "llm_reviewed": False,
    }


def classify_media_url(url: str, *, key_hint: str = "", content_type: str = "") -> str | None:
    if not isinstance(url, str) or not _URL_RE.search(url):
        return None
    lowered = url.casefold()
    path = urlparse(url).path.casefold()
    ctype = content_type.casefold()
    key = normalize_key(key_hint)
    if path.endswith(".m3u8") or ".m3u8" in lowered or "mpegurl" in ctype:
        return "hls"
    if path.endswith((".mjpg", ".mjpeg")) or "multipart/x-mixed-replace" in ctype:
        return "mjpeg"
    if path.endswith((".mp4", ".webm", ".mov", ".m4v")):
        return "video_file"
    if path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "image_snapshot"
    if any(token in key for token in ("stream", "video", "media", "mjpeg")):
        return "stream"
    if any(token in lowered for token in ("/stream", "stream=", "/video", "video=", "/media", "media=")) and not _MEDIA_EXT_RE.search(url):
        return "stream"
    return None


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def canonical_media_url(url: str) -> str:
    split = urlsplit(str(url).strip())
    return urlunsplit((split.scheme.casefold(), split.netloc.casefold(), split.path, split.query, ""))


def _walk_objects(data: Any, path: str = "$"):
    if isinstance(data, dict):
        yield path, data
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                yield from _walk_objects(value, f"{path}.{key}")
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            if isinstance(value, (dict, list)):
                yield from _walk_objects(value, f"{path}[{idx}]")


def _record_payload(obj: dict[str, Any]) -> dict[str, Any]:
    # ArcGIS-style features: attributes carry camera fields, geometry is sibling.
    if isinstance(obj.get("attributes"), dict):
        merged = dict(obj["attributes"])
        if isinstance(obj.get("geometry"), dict):
            merged.setdefault("geometry", obj["geometry"])
        return merged
    # GeoJSON-style features: properties carry camera fields, geometry is sibling.
    if isinstance(obj.get("properties"), dict):
        merged = dict(obj["properties"])
        if isinstance(obj.get("geometry"), dict):
            merged.setdefault("geometry", obj["geometry"])
        return merged
    return obj


def _looks_like_camera_record(record: dict[str, Any]) -> bool:
    flat = _flatten_record(record)
    keys = set(flat)
    has_media = any(_media_urls_from_value(value, key) for key, (_raw, value, _path) in flat.items())
    has_identity = bool(keys & IDENTITY_KEYS) or any(term in str(value).casefold() for _raw, value, _path in flat.values() if isinstance(value, str) for term in CAMERA_TERMS)
    has_location = bool(keys & TEXT_KEYS) or _coordinates_from_flat(flat)[0] is not None
    has_status = bool(keys & STATUS_KEYS)
    has_refresh = bool(keys & REFRESH_KEYS)
    has_image_meta = "imagedescription" in keys
    has_camera_terms = any("camera" in key or key in {"camid", "cam"} for key in keys)
    if has_media and (has_identity or has_location or has_camera_terms or has_status or has_refresh or has_image_meta):
        return True
    if has_identity and has_location and (has_status or has_refresh or has_image_meta):
        return True
    if has_camera_terms and has_location and (has_status or has_refresh or has_image_meta):
        return True
    return False


def _camera_record_from_payload(
    payload: dict[str, Any],
    *,
    path: str,
    endpoint_url: str,
    source_page_url: str | None,
    source_provider: str | None,
    source_name: str | None,
    raw_record: dict[str, Any],
) -> HarvestedCameraRecord:
    flat = _flatten_record(payload)
    field_map = {norm: p for norm, (_raw, _value, p) in flat.items()}
    normalized = _normalized_fields(flat)
    camera_id = _first_str(flat, ["cameraid", "camera_id", "id", "deviceid", "device_id"])
    title = _first_str(flat, ["title", "name", "label"])
    description = _first_str(flat, ["description"])
    image_description = _first_str(flat, ["imagedescription"])
    location_text = _first_str(flat, ["location", "locationname", "locationdescription", "intersection", "route", "road"])
    lat, lon, coord_source, coords = _coordinates_from_flat(flat)
    direction = _first_str(flat, ["direction", "cameradirection", "facing", "facingdirection", "viewdirection"])
    orientation = _first_str(flat, ["orientation"])
    bearing = _first_float(flat, ["bearing", "azimuth", "angle"])
    heading = _first_float(flat, ["heading"])
    in_service, status_source = _source_service_status(flat)
    status = _first_str(flat, ["status", "camerastatus", "operationalstatus"])
    date = _first_str(flat, ["date", "recorddate", "capturedate", "imagedate", "snapshotdate"])
    time = _first_str(flat, ["time", "recordtime", "capturetime", "imagetime", "snapshottime"])
    timestamp = _timestamp_from_flat(flat)
    last_updated = _first_str(flat, ["lastupdated", "lastupdate", "updatedat"])
    last_refresh = _first_str(flat, ["lastrefresh", "lastrefreshed"])
    current_freq = _first_value(flat, ["currentimageupdatefrequency", "refreshrate", "refreshinterval", "refreshseconds", "updateinterval", "imagerefreshrate", "snapshotrefreshinterval"])
    reference_freq = _first_value(flat, ["referenceimageupdatefrequency"])
    camera_record_id = "cam:" + _stable_hash("|".join([endpoint_url, path, camera_id or title or location_text or ""]))
    record = HarvestedCameraRecord(
        camera_record_id=camera_record_id,
        camera_id=camera_id,
        source_endpoint_url=endpoint_url,
        source_page_url=source_page_url,
        source_provider=source_provider,
        source_name=source_name,
        json_record_path=path,
        title=title,
        description=description,
        location_text=location_text,
        lat=lat,
        lon=lon,
        coordinate_source=coord_source,
        coordinates=coords,
        direction=direction,
        bearing=bearing,
        heading=heading,
        orientation=orientation,
        in_service=in_service,
        status=status,
        status_source=status_source,
        date=date,
        time=time,
        timestamp=timestamp or last_updated or last_refresh,
        last_updated=last_updated,
        last_refresh=last_refresh,
        image_description=image_description,
        current_image_update_frequency=current_freq,
        reference_image_update_frequency=reference_freq,
        normalized_fields=normalized,
        field_map=field_map,
        metadata={k: v for k, (_raw, v, _p) in flat.items() if _is_scalar_or_small(v)},
        raw_record=raw_record,
    )
    record.media_assets = _media_assets_from_flat(record, flat)
    return record


def _timestamp_from_flat(flat: dict[str, tuple[str, Any, str]]) -> str | None:
    epoch = _first_value(flat, ["recordepoch", "epoch", "timestampms", "timestampepoch"])
    converted = _epoch_to_utc_iso(epoch)
    if converted:
        return converted
    return _first_str(flat, [
        "timestamp", "datetime", "recorddatetime", "recordedat", "imagetimestamp",
        "snapshottimestamp", "capturetimestamp", "createdat", "updatedat",
    ])


def _epoch_to_utc_iso(value: Any) -> str | None:
    try:
        if value in (None, ""):
            return None
        raw = float(value)
        # Values above 10^11 are almost certainly milliseconds.
        seconds = raw / 1000.0 if raw > 100_000_000_000 else raw
        if seconds <= 0 or seconds > 4_102_444_800:  # 2100-01-01 UTC
            return None
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _media_assets_from_flat(record: HarvestedCameraRecord, flat: dict[str, tuple[str, Any, str]]) -> list[HarvestedMediaAsset]:
    assets: list[HarvestedMediaAsset] = []
    seen: set[tuple[str, str]] = set()
    for key, (raw_key, value, path) in flat.items():
        for url, media_type in _media_urls_from_value(value, key):
            canonical = canonical_media_url(url)
            pair = (path, canonical)
            if pair in seen:
                continue
            seen.add(pair)
            role = _role_for_field_key(key, media_type)
            asset_id = "asset:" + _stable_hash("|".join([record.camera_record_id, path, canonical]))
            assets.append(
                HarvestedMediaAsset(
                    asset_id=asset_id,
                    camera_record_id=record.camera_record_id,
                    url=canonical,
                    media_type=media_type,
                    asset_role=role,
                    asset_field=raw_key,
                    source_url=record.source_endpoint_url,
                    source_endpoint_url=record.source_endpoint_url,
                    source_page_url=record.source_page_url,
                    source_provider=record.source_provider,
                    source_name=record.source_name,
                    discovery_method="structured_camera_record",
                    json_record_path=record.json_record_path,
                    field_path=path,
                    metadata={
                        "camera_record_id": record.camera_record_id,
                        "json_record_path": record.json_record_path,
                        "asset_field": raw_key,
                        "field_path": path,
                        "source_provided_only": True,
                    },
                    date=record.date,
                    time=record.time,
                    timestamp=record.timestamp,
                    last_updated=record.last_updated,
                    last_refresh=record.last_refresh,
                    image_description=record.image_description,
                    current_image_update_frequency=record.current_image_update_frequency,
                    reference_image_update_frequency=record.reference_image_update_frequency,
                )
            )
    return assets


def _role_for_field_key(key: str, media_type: str) -> str:
    """Return the canonical asset role for a normalised field key.

    Exact-match MEDIA_FIELD_ROLES first, then apply pattern-based recognition
    for multi-variant reference-image field names.  Public traffic camera APIs
    such as Caltrans expose reference images under numbered field names
    (referenceimage1updateagourl … referenceimage12updatesagourl) that do not
    appear in the verbatim MEDIA_FIELD_ROLES dictionary.  Classifying them by
    prefix/suffix keeps the role mapping deterministic without enumerating every
    possible variant.
    """
    exact = MEDIA_FIELD_ROLES.get(key)
    if exact:
        return exact
    if key.startswith("referenceimage") and key.endswith("url"):
        return "reference_image_snapshot"
    return _asset_role_for_media_type(media_type)


def _media_urls_from_value(value: Any, key_hint: str) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    if isinstance(value, str):
        for candidate in _urls_in_string(value):
            media_type = classify_media_url(candidate, key_hint=key_hint)
            if media_type:
                urls.append((candidate, media_type))
        if not urls and _URL_RE.search(value):
            media_type = classify_media_url(value.strip(), key_hint=key_hint)
            if media_type:
                urls.append((value.strip(), media_type))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_media_urls_from_value(item, key_hint))
    return urls


def _urls_in_string(value: str) -> list[str]:
    text = value.strip().replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/")
    if _URL_RE.match(text):
        return [text]
    return re.findall(r"https?://[^\s'\"<>\\)\]}]+", text, re.I)


def _flatten_record(value: Any, prefix: str = "", path: str = "$") -> dict[str, tuple[str, Any, str]]:
    out: dict[str, tuple[str, Any, str]] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            norm = normalize_key(key)
            child_path = f"{path}.{key}"
            if isinstance(child, dict):
                if norm in {"geometry", "position", "locationpoint"}:
                    out[norm] = (str(key), child, child_path)
                for child_key, child_value in _flatten_record(child, f"{prefix}{norm}", child_path).items():
                    out.setdefault(child_key, child_value)
            elif isinstance(child, list):
                out[norm] = (str(key), child, child_path)
                # Do not recursively flatten large arrays as metadata fields.
            else:
                out[norm] = (str(key), child, child_path)
    return out


def _normalized_fields(flat: dict[str, tuple[str, Any, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, (_raw, value, _path) in flat.items():
        if _is_scalar_or_small(value):
            out[key] = value
    return out


def _first_value(flat: dict[str, tuple[str, Any, str]], keys: list[str]) -> Any | None:
    for key in keys:
        if key in flat:
            value = flat[key][1]
            if value not in (None, "", [], {}):
                return value
    return None


def _first_str(flat: dict[str, tuple[str, Any, str]], keys: list[str]) -> str | None:
    value = _first_value(flat, keys)
    if value in (None, "", [], {}):
        return None
    return str(value)


def _first_float(flat: dict[str, tuple[str, Any, str]], keys: list[str]) -> float | None:
    value = _first_value(flat, keys)
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return None


def _coordinates_from_flat(flat: dict[str, tuple[str, Any, str]]) -> tuple[float | None, float | None, str | None, Any | None]:
    lat = _first_float(flat, list(LAT_KEYS))
    lon = _first_float(flat, list(LON_KEYS))
    if _plausible_lat_lon(lat, lon):
        return lat, lon, "source_fields:lat,lon", None
    x = _first_float(flat, ["x"])
    y = _first_float(flat, ["y"])
    if _plausible_lat_lon(y, x):
        return y, x, "source_fields:y,x", None
    geometry = _first_value(flat, ["geometry", "position", "locationpoint"])
    if isinstance(geometry, dict):
        gx = _coerce_float(geometry.get("x"))
        gy = _coerce_float(geometry.get("y"))
        if _plausible_lat_lon(gy, gx):
            return gy, gx, "geometry:y,x", geometry
        coords = geometry.get("coordinates")
        lat2, lon2 = _coords_from_sequence(coords)
        if _plausible_lat_lon(lat2, lon2):
            return lat2, lon2, "geometry:coordinates", coords
    coords = _first_value(flat, ["coordinates"])
    lat3, lon3 = _coords_from_sequence(coords)
    if _plausible_lat_lon(lat3, lon3):
        return lat3, lon3, "coordinates", coords
    return None, None, None, None


def _coords_from_sequence(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None, None
    first = _coerce_float(value[0])
    second = _coerce_float(value[1])
    # GeoJSON default order is [lon, lat].
    if _plausible_lat_lon(second, first):
        return second, first
    if _plausible_lat_lon(first, second):
        return first, second
    return None, None


def _source_service_status(flat: dict[str, tuple[str, Any, str]]) -> tuple[bool | None, str | None]:
    for key in ["inservice", "in_service", "isactive", "active", "enabled", "online"]:
        if key not in flat:
            continue
        value = flat[key][1]
        if isinstance(value, bool):
            return value, flat[key][2]
        text = str(value).strip().casefold()
        if text in {"1", "true", "yes", "y", "active", "enabled", "online", "inservice", "in service"}:
            return True, flat[key][2]
        if text in {"0", "false", "no", "n", "inactive", "disabled", "offline", "outofservice", "out of service"}:
            return False, flat[key][2]
    return None, None


def _asset_role_for_media_type(media_type: str) -> str:
    return {
        "hls": "hls_stream",
        "mjpeg": "mjpeg_stream",
        "image_snapshot": "image_snapshot",
        "video_file": "video_file",
        "stream": "media_url",
    }.get(media_type, "unknown_media")


def _dedupe_camera_records(records: list[HarvestedCameraRecord]) -> list[HarvestedCameraRecord]:
    seen: dict[str, HarvestedCameraRecord] = {}
    order: list[str] = []
    for record in records:
        if record.camera_record_id not in seen:
            seen[record.camera_record_id] = record
            order.append(record.camera_record_id)
    return [seen[key] for key in order]


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _plausible_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def _is_scalar_or_small(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, list) and len(value) <= 8:
        return all(isinstance(item, (str, int, float, bool)) or item is None for item in value)
    if isinstance(value, dict) and len(value) <= 8:
        return all(isinstance(item, (str, int, float, bool)) or item is None for item in value.values())
    return False
