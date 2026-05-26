from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urljoin

from camera_discovery.harvest.media_filter import (
    DATE_KEYS,
    DIRECTION_KEYS,
    BEARING_KEYS,
    HEADING_KEYS,
    JSON_MEDIA_KEYS,
    JSON_METADATA_KEYS,
    LATITUDE_KEYS,
    LONGITUDE_KEYS,
    TIME_KEYS,
    TIMESTAMP_KEYS,
    X_LONGITUDE_KEYS,
    Y_LATITUDE_KEYS,
)


def text_value_variants(value: str) -> list[str]:
    variants = []
    for candidate in (value, html.unescape(value), value.replace(r"\/", "/"), value.replace(r"\u002F", "/").replace(r"\u002f", "/")):
        if candidate not in variants:
            variants.append(candidate)
    decoded = value
    for _ in range(2):
        next_value = unquote(decoded)
        if next_value == decoded or len(next_value) > max(200000, len(value) * 20):
            break
        if next_value not in variants:
            variants.append(next_value)
        decoded = next_value
    return variants

def text_variants(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, value in (
        ("raw", text),
        ("html_unescaped", html.unescape(text)),
        ("json_slash_unescaped", text.replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/")),
    ):
        if value and all(value != existing for _, existing in out):
            out.append((name, value))
    decoded = text
    for idx in range(2):
        next_value = unquote(decoded)
        if next_value == decoded or len(next_value) > max(2_000_000, len(text) * 20):
            break
        if all(next_value != existing for _, existing in out):
            out.append(("url_decoded" if idx == 0 else "double_url_decoded", next_value))
        decoded = next_value
    return out

def is_json_payload(source_url: str, content_type: str, text: str) -> bool:
    lowered = content_type.casefold()
    stripped = (text or "").lstrip()
    return "json" in lowered or source_url.casefold().split("?", 1)[0].endswith(".json") or stripped.startswith(("{", "["))

def parse_json_payload(text: str) -> Any | None:
    for variant in text_value_variants(text):
        try:
            return json.loads(variant)
        except Exception:
            continue
    return None

def extract_json_blobs(text: str) -> list[Any]:
    blobs: list[Any] = []
    decoder = json.JSONDecoder()
    for _variant_name, variant in text_variants(text):
        for match in re.finditer(r"[\[{]", variant):
            start = match.start()
            window = variant[max(0, start - 100): start].casefold()
            if window and not any(hint in window for hint in ("camera", "cameras", "features", "layers", "markers", "data", "feed", "stream", "video")):
                continue
            try:
                obj, end = decoder.raw_decode(variant[start:])
            except json.JSONDecodeError:
                continue
            if end > 10:
                blobs.append(obj)
            if len(blobs) >= 25:
                return blobs
    return blobs

def normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key).casefold())

def merge_metadata(*parts: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        if not part:
            continue
        for key, value in part.items():
            if value in (None, "", [], {}):
                continue
            merged.setdefault(key, value)
    return merged

def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().strip("°")
        if not cleaned:
            return None
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None

def coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "active", "enabled", "online", "inservice", "in service"}:
        return True
    if text in {"0", "false", "no", "n", "inactive", "disabled", "offline", "outofservice", "out of service"}:
        return False
    return None

def count_json_records(value: Any) -> int:
    if isinstance(value, list):
        return len(value) + sum(count_json_records(item) for item in value if isinstance(item, (dict, list)))
    if isinstance(value, dict):
        return 1 + sum(count_json_records(item) for item in value.values() if isinstance(item, (dict, list)))
    return 0

def plausible_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180

def value_by_normalized_key(metadata: dict[str, Any], keys: set[str]) -> tuple[str | None, Any]:
    for key, value in metadata.items():
        if normalize_key(key) in keys and value not in (None, "", [], {}):
            return str(key), value
    return None, None

def coordinates_from_sequence(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None, None
    first = value[0]
    # GeoJSON polygons/lines may be nested. Follow the first coordinate pair.
    while isinstance(first, (list, tuple)) and first:
        value = first
        first = value[0]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None, None
    a = coerce_float(value[0])
    b = coerce_float(value[1])
    # GeoJSON order is lon, lat. Fall back to lat, lon only when that is the
    # only plausible interpretation.
    if plausible_lat_lon(b, a):
        return b, a
    if plausible_lat_lon(a, b):
        return a, b
    return None, None

def coordinates_from_geometry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    x_key, x_value = value_by_normalized_key(value, X_LONGITUDE_KEYS | LONGITUDE_KEYS)
    y_key, y_value = value_by_normalized_key(value, Y_LATITUDE_KEYS | LATITUDE_KEYS)
    lat = coerce_float(y_value)
    lon = coerce_float(x_value)
    if plausible_lat_lon(lat, lon):
        out["lat"] = lat
        out["lon"] = lon
        out["coordinate_source"] = f"geometry:{y_key},{x_key}"
    coords_key, coords_value = value_by_normalized_key(value, {"coordinates", "coordinate", "coords"})
    if "lat" not in out and coords_key:
        seq_lat, seq_lon = coordinates_from_sequence(coords_value)
        if plausible_lat_lon(seq_lat, seq_lon):
            out["lat"] = seq_lat
            out["lon"] = seq_lon
            out["coordinate_source"] = f"geometry:{coords_key}"
    return out

def json_context_metadata(record: dict[str, Any], source_url: str, path: str) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if isinstance(record.get("geometry"), dict):
        geometry = record["geometry"]
        context["geometry"] = geometry
        context["geometry_json_endpoint_url"] = source_url
        context["geometry_json_record_path"] = f"{path}.geometry"
        context.update(coordinates_from_geometry(geometry))
    elif isinstance(record.get("coordinates"), (list, tuple)):
        context["coordinates"] = record["coordinates"]
        lat, lon = coordinates_from_sequence(record["coordinates"])
        if plausible_lat_lon(lat, lon):
            context["lat"] = lat
            context["lon"] = lon
            context["coordinate_source"] = f"json:{path}.coordinates"
    x_key, x_value = value_by_normalized_key(record, X_LONGITUDE_KEYS | LONGITUDE_KEYS)
    y_key, y_value = value_by_normalized_key(record, Y_LATITUDE_KEYS | LATITUDE_KEYS)
    lat = coerce_float(y_value)
    lon = coerce_float(x_value)
    if plausible_lat_lon(lat, lon):
        context.setdefault("lat", lat)
        context.setdefault("lon", lon)
        context.setdefault("coordinate_source", f"json:{path}:{y_key},{x_key}")
    return context

def promoted_metadata_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lat_key, lat_value = value_by_normalized_key(metadata, LATITUDE_KEYS)
    lon_key, lon_value = value_by_normalized_key(metadata, LONGITUDE_KEYS)
    lat = coerce_float(lat_value)
    lon = coerce_float(lon_value)
    if not plausible_lat_lon(lat, lon):
        x_key, x_value = value_by_normalized_key(metadata, X_LONGITUDE_KEYS)
        y_key, y_value = value_by_normalized_key(metadata, Y_LATITUDE_KEYS)
        lat = coerce_float(y_value)
        lon = coerce_float(x_value)
        lat_key = y_key
        lon_key = x_key
    if not plausible_lat_lon(lat, lon) and isinstance(metadata.get("geometry"), dict):
        geo = coordinates_from_geometry(metadata["geometry"])
        lat = geo.get("lat")
        lon = geo.get("lon")
        if geo.get("coordinate_source"):
            out["coordinate_source"] = geo["coordinate_source"]
    if not plausible_lat_lon(lat, lon) and isinstance(metadata.get("coordinates"), (list, tuple)):
        lat, lon = coordinates_from_sequence(metadata["coordinates"])
        if plausible_lat_lon(lat, lon):
            out["coordinate_source"] = "metadata:coordinates"
    if plausible_lat_lon(lat, lon):
        out["lat"] = lat
        out["lon"] = lon
        out.setdefault("coordinate_source", str(metadata.get("coordinate_source") or f"metadata:{lat_key},{lon_key}"))

    direction_key, direction_value = value_by_normalized_key(metadata, DIRECTION_KEYS)
    if direction_value not in (None, "", [], {}):
        out["direction"] = str(direction_value)
    bearing_key, bearing_value = value_by_normalized_key(metadata, BEARING_KEYS)
    bearing = coerce_float(bearing_value)
    if bearing is not None:
        out["bearing"] = bearing
    heading_key, heading_value = value_by_normalized_key(metadata, HEADING_KEYS)
    heading = coerce_float(heading_value)
    if heading is not None:
        out["heading"] = heading
    # Some feeds use numeric direction/orientation as an angle. Keep the raw
    # direction string above and also expose it as bearing when useful.
    if "bearing" not in out and direction_key:
        maybe_bearing = coerce_float(direction_value)
        if maybe_bearing is not None:
            out["bearing"] = maybe_bearing

    timestamp_key, timestamp_value = value_by_normalized_key(metadata, TIMESTAMP_KEYS)
    if timestamp_value not in (None, "", [], {}):
        if timestamp_key and normalize_key(timestamp_key) in {"recordepoch", "epoch", "timestampms", "timestampepoch"}:
            out["timestamp"] = epoch_to_utc_iso(timestamp_value) or str(timestamp_value)
        else:
            out["timestamp"] = str(timestamp_value)
    date_key, date_value = value_by_normalized_key(metadata, DATE_KEYS)
    if date_value not in (None, "", [], {}):
        out["date"] = str(date_value)
    time_key, time_value = value_by_normalized_key(metadata, TIME_KEYS)
    if time_value not in (None, "", [], {}):
        out["time"] = str(time_value)
    return out

def epoch_to_utc_iso(value: Any) -> str | None:
    try:
        if value in (None, ""):
            return None
        raw = float(value)
        seconds = raw / 1000.0 if raw > 100_000_000_000 else raw
        if seconds <= 0 or seconds > 4_102_444_800:
            return None
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None

def simple_metadata(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        key_norm = normalize_key(key)
        if isinstance(value, list):
            # Preserve coordinate arrays as structured metadata; other lists are
            # collapsed for compact CSV/JSONL readability.
            if key_norm in {"coordinates", "coordinate", "coords"}:
                out[str(key)] = value
            else:
                out[str(key)] = " ".join(str(part) for part in value)
            continue
        if isinstance(value, dict):
            if key_norm == "geometry":
                out[str(key)] = value
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value
    return out

def json_record_metadata(
    record: dict[str, Any],
    source_url: str,
    path: str,
    media_key: str,
    *,
    context_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = merge_metadata(context_metadata, simple_metadata(record))
    if isinstance(record.get("recordTimestamp"), dict):
        for key, value in record["recordTimestamp"].items():
            metadata.setdefault(str(key), value)
    metadata["json_endpoint_url"] = source_url
    metadata["json_record_path"] = path
    metadata["json_media_key"] = media_key
    for key, value in list(record.items()):
        key_norm = normalize_key(key)
        if isinstance(value, (dict, list)) and key_norm not in {"geometry", "coordinates", "coordinate", "coords"}:
            continue
        if key_norm in JSON_METADATA_KEYS or key_norm in JSON_MEDIA_KEYS:
            metadata.setdefault(str(key), value)
    metadata = merge_metadata(metadata, json_context_metadata(record, source_url, path))
    promoted = promoted_metadata_fields(metadata)
    for key, value in promoted.items():
        metadata.setdefault(key, value)
    # Friendly aliases used by output records.
    for candidate_key in ("camera_id", "cameraid", "id", "device_id", "deviceid"):
        if candidate_key in metadata:
            metadata.setdefault("camera_id", str(metadata[candidate_key]))
            break
    for candidate_key in ("location_text", "location", "intersection", "description"):
        if candidate_key in metadata:
            metadata.setdefault("location_text", str(metadata[candidate_key]))
            break
    return {k: v for k, v in metadata.items() if v not in (None, "", [], {})}
