from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.parse import unquote, urlparse

from camera_discovery.core.models import CameraCandidate, TargetContext
from camera_discovery.extraction.media import _candidate_media_type, _dedupe_strings, _float_or_none
from camera_discovery.extraction.media import COORD_RE
from camera_discovery.geo.location_profiles import country_aliases_for_location


def _specific_candidate_location_text(value: str, target: TargetContext) -> bool:
    text = value.strip()
    if not text or len(text) < 4:
        return False
    lowered = text.casefold()
    if lowered in {"camera", "cameras", "traffic", "webcam", "snapshot", "image"}:
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:/?=&%-]+", text) and "/" in text:
        return False
    target_bits = [bit.casefold() for bit in (target.canonical_target, target.target_label, target.admin_region, target.country) if isinstance(bit, str)]
    generic_camera_page = any(bit and bit in lowered for bit in target_bits) and any(phrase in lowered for phrase in ("live traffic cameras", "traffic cameras", "road conditions", "camera map", "webcams"))
    has_specific_clue = any(
        re.search(pattern, text, re.I)
        for pattern in (
            r"\b(?:I-|I\s*|SR\s*|US\s*)\d+\b",
            r"\b(?:at|near|and|@)\b",
            r"\b(?:NB|SB|EB|WB|northbound|southbound|eastbound|westbound)\b",
            r"\b\d+(?:st|nd|rd|th)\b",
            r"\b(?:St|Street|Rd|Road|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Hwy|Highway)\b",
        )
    )
    if generic_camera_page and "road conditions" in lowered and not re.search(r"\b(?:at|near|@|I-|SR\s*|US\s*)\d*", text, re.I):
        return False
    if generic_camera_page and not has_specific_clue:
        return False
    return any(ch.isalpha() for ch in text) and (has_specific_clue or not generic_camera_page)

def _limited_scalar_metadata(metadata: dict[str, Any], *, max_items: int = 40, max_value_len: int = 500) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        if len(out) >= max_items:
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = value if not isinstance(value, str) else value[:max_value_len]
            out[str(key)] = text
        elif isinstance(value, list):
            scalar_items = [item for item in value if isinstance(item, (str, int, float, bool))]
            if scalar_items:
                out[str(key)] = scalar_items[:10]
        elif isinstance(value, dict):
            nested = _limited_scalar_metadata(value, max_items=10, max_value_len=120)
            if nested:
                out[str(key)] = nested
    return out

def _candidate_location_inference_evidence_text(candidate: CameraCandidate) -> str:
    values: list[str] = [candidate.stream_url, candidate.source_url or "", candidate.title or "", candidate.location_text or ""]
    for key, value in _limited_scalar_metadata(candidate.source_metadata).items():
        if isinstance(value, str):
            values.extend([str(key), value])
        elif isinstance(value, (int, float, bool)):
            values.extend([str(key), str(value)])
        elif isinstance(value, list):
            values.extend([str(key), " ".join(str(item) for item in value)])
        elif isinstance(value, dict):
            values.extend([str(key), json.dumps(value, ensure_ascii=False)])
    return " ".join(values)

def _candidate_has_location_inference_evidence(candidate: CameraCandidate) -> bool:
    text = _candidate_location_inference_evidence_text(candidate)
    parsed = urlparse(candidate.stream_url)
    path_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", unquote(parsed.path))
    metadata_text = " ".join([candidate.title or "", candidate.location_text or "", str(candidate.source_metadata.get("source_name") or "")])
    return bool(path_tokens or re.search(r"[A-Za-z][A-Za-z0-9_-]{2,}", metadata_text) or re.search(r"[A-Za-z][A-Za-z0-9_-]{2,}", text))

def _normalize_location_inference_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        query = row.get("query")
        if not isinstance(query, str) or not _is_safe_geocode_query(query):
            continue
        variants_value = row.get("variants")
        variants = [v.strip() for v in variants_value if isinstance(v, str) and _is_safe_geocode_query(v)] if isinstance(variants_value, list) else []
        evidence_value = row.get("evidence")
        evidence = [str(v).strip()[:120] for v in evidence_value if isinstance(v, (str, int, float)) and str(v).strip()] if isinstance(evidence_value, list) else []
        confidence = max(0.0, min(1.0, _float_or_none(row.get("confidence")) or 0.0))
        reason = str(row.get("reason") or "")[:500]
        precision = str(row.get("precision") or "unknown")[:80]
        normalized.append(
            {
                "query": query.strip()[:300],
                "variants": _dedupe_strings(variants)[:5],
                "confidence": confidence,
                "evidence": _dedupe_strings(evidence)[:12],
                "reason": reason,
                "precision": precision,
            }
        )
    normalized.sort(key=lambda item: item.get("confidence", 0.0), reverse=True)
    return normalized[:5]

def _is_safe_geocode_query(value: str) -> bool:
    text = value.strip()
    if not text or len(text) < 3 or len(text) > 300:
        return False
    if COORD_RE.search(text):
        return False
    lowered = text.casefold()
    if any(marker in lowered for marker in ("latitude", "longitude", " lat ", " lon ")):
        return False
    if re.fullmatch(r"https?://\S+", text):
        return False
    return any(ch.isalpha() for ch in text)

def _llm_location_evidence_supported(candidate: CameraCandidate, row: dict[str, Any]) -> bool:
    evidence = row.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    haystack = _candidate_location_inference_evidence_text(candidate).casefold()
    supported = 0
    for token in evidence:
        text = str(token).strip().casefold()
        if len(text) < 2:
            continue
        compact = re.sub(r"[^a-z0-9]+", "", text)
        haystack_compact = re.sub(r"[^a-z0-9]+", "", haystack)
        if text in haystack or (compact and compact in haystack_compact):
            supported += 1
    return supported > 0

def _append_target_context_to_query(query: str, target: TargetContext) -> str:
    parts = [query.strip()]
    for value in (target.canonical_target, target.admin_region, target.country):
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if value.casefold() not in ", ".join(parts).casefold():
            parts.append(value)
    return ", ".join(_dedupe_strings(parts))[:300]

def _candidate_location_enrichment_sort_key(candidate: CameraCandidate) -> tuple[int, str]:
    """Prioritize expensive location inference toward likely camera HLS URLs."""
    media_type = _candidate_media_type(candidate)
    has_slug = _url_has_location_like_slug(candidate.stream_url)
    if media_type == "hls" and has_slug:
        return (0, candidate.stream_url)
    if media_type == "hls":
        return (1, candidate.stream_url)
    if media_type == "image_snapshot" and _candidate_has_location_inference_evidence(candidate):
        return (2, candidate.stream_url)
    return (3, candidate.stream_url)

def _url_has_location_like_slug(url: str) -> bool:
    parsed = urlparse(url or "")
    path = unquote(parsed.path or "")
    tokens = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", path) if t]
    generic = {"stream", "playlist", "m3u8", "camera", "cameras", "video", "live", "image", "snapshot", "jpg", "jpeg", "png", "webp"}
    return any(token.casefold() not in generic for token in tokens)

def _is_broad_or_target_level_inference(row: dict[str, Any], query: str, display_name: str, target: TargetContext) -> bool:
    precision = str(row.get("precision") or "").casefold()
    if precision in {"state", "country", "region", "county", "province", "administrative", "admin"}:
        return True
    target_values: list[str] = []
    for value in (target.canonical_target, target.target_label, target.admin_region, target.country):
        if isinstance(value, str) and value.strip():
            target_values.append(value.strip())
            target_values.extend(country_aliases_for_location(value))
    target_values = _dedupe_strings(target_values)
    normalized_targets = {_normalize_place_token(value) for value in target_values if value}
    normalized_query = _normalize_place_token(query)
    normalized_display = _normalize_place_token(display_name)
    if normalized_query in normalized_targets or normalized_display in normalized_targets:
        return True
    residual = normalized_query
    for value in sorted(normalized_targets, key=len, reverse=True):
        residual = residual.replace(value, " ")
    residual_tokens = [tok for tok in residual.split() if len(tok) >= 3]
    return not residual_tokens

def _normalize_place_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()

def _haversine_km(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if None in {lat1, lon1, lat2, lon2}:
        return None
    if not (_valid_lat_lon(lat1, lon1) and _valid_lat_lon(lat2, lon2)):
        return None
    radius_km = 6371.0088
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _valid_lat_lon(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180

def _point_in_bbox(lat: float, lon: float, bbox: dict[str, float]) -> bool:
    return bbox["min_lat"] <= lat <= bbox["max_lat"] and bbox["min_lon"] <= lon <= bbox["max_lon"]


def _point_in_geojson_geometry(lat: float, lon: float, geometry: dict[str, object] | None) -> bool:
    """Return True when a WGS84 point is inside a GeoJSON Polygon/MultiPolygon.

    Coordinates are GeoJSON order [lon, lat]. This intentionally avoids heavy GIS
    dependencies so Colab/notebook runs keep working with the base package.
    """
    if not isinstance(geometry, dict):
        return False
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geom_type == "Polygon" and isinstance(coords, list):
        return _point_in_polygon_rings(lat, lon, coords)
    if geom_type == "MultiPolygon" and isinstance(coords, list):
        return any(_point_in_polygon_rings(lat, lon, poly) for poly in coords if isinstance(poly, list))
    return False


def _point_in_polygon_rings(lat: float, lon: float, rings: list[object]) -> bool:
    if not rings or not isinstance(rings[0], list):
        return False
    exterior = rings[0]
    if not _point_in_ring(lat, lon, exterior):
        return False
    for hole in rings[1:]:
        if isinstance(hole, list) and _point_in_ring(lat, lon, hole):
            return False
    return True


def _point_in_ring(lat: float, lon: float, ring: list[object]) -> bool:
    points: list[tuple[float, float]] = []
    for item in ring:
        if isinstance(item, list) and len(item) >= 2:
            try:
                x = float(item[0])
                y = float(item[1])
            except Exception:
                continue
            points.append((x, y))
    if len(points) < 3:
        return False
    inside = False
    x = lon
    y = lat
    j = len(points) - 1
    for i, (xi, yi) in enumerate(points):
        xj, yj = points[j]
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside
