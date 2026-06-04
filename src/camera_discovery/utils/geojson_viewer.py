from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any

from camera_discovery.utils.io import write_json

CAMERA_GEOJSON_FILENAMES = (
    "camera.geojson",
    "untrusted_camera_candidates.geojson",
    "untrusted_camera.geojson",
)

TABLE_COLUMNS = [
    "name",
    "target_label",
    "location_text",
    "camera_type",
    "camera_id",
    "media_type",
    "latitude",
    "longitude",
    "stream_url",
    "source_url",
    "thumbnail_url",
    "camera_refresh_rate",
    "map_refresh_rate_seconds",
    "trust_level",
    "validation_status",
    "scope_status",
    "discovery_method",
    "review_required",
]

THUMBNAIL_KEYS = (
    "thumbnail_url",
    "snapshot_url",
    "image_url",
    "camera_image_url",
    "preview_image_url",
    "poster_url",
)


def select_camera_geojson(output_dir: Path) -> Path | None:
    """Return the preferred trusted or untrusted camera GeoJSON file for a run."""
    for filename in CAMERA_GEOJSON_FILENAMES:
        path = output_dir / filename
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def load_geojson(path: Path) -> dict[str, Any]:
    """Load a GeoJSON file and return a FeatureCollection-like dictionary."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"GeoJSON file did not contain an object: {path}")
    features = data.get("features")
    if features is None:
        data["features"] = []
    elif not isinstance(features, list):
        raise ValueError(f"GeoJSON features must be a list: {path}")
    return data


def load_camera_rows(path: Path) -> list[dict[str, Any]]:
    """Flatten camera GeoJSON features into rows suitable for tabular display."""
    return geojson_features_to_rows(load_geojson(path))


def load_camera_map_geojson(output_dir: Path, geojson_path: Path | None = None) -> tuple[dict[str, Any], str | None, list[Path]]:
    """Load one explicit camera GeoJSON or merge trusted and untrusted map files."""
    if geojson_path is not None:
        data = load_geojson(geojson_path)
        return data, geojson_path.name, [geojson_path]

    selected_paths = [output_dir / filename for filename in CAMERA_GEOJSON_FILENAMES if (output_dir / filename).exists() and (output_dir / filename).stat().st_size > 0]
    if not selected_paths:
        return {"type": "FeatureCollection", "features": []}, None, []
    if len(selected_paths) == 1:
        data = load_geojson(selected_paths[0])
        return data, selected_paths[0].name, selected_paths

    features: list[dict[str, Any]] = []
    for path in selected_paths:
        data = load_geojson(path)
        for feature in data.get("features") or []:
            if not isinstance(feature, dict):
                continue
            props = feature.setdefault("properties", {})
            if isinstance(props, dict):
                props.setdefault("source_geojson", path.name)
            features.append(feature)
    return {"type": "FeatureCollection", "features": features}, " + ".join(path.name for path in selected_paths), selected_paths


def load_target_geometry_overlays(output_dir: Path) -> list[dict[str, Any]]:
    """Load explicit target geometry overlays from resolver diagnostics.

    Camera GeoJSON remains the source of camera point markers. This helper is
    intentionally strict: it emits overlays only from explicit
    ``primary_geometry_geojson``, ``fallback_geometry_bbox``, or
    ``last_fallback_geometry_bbox`` fields. It does not synthesize overlays from
    legacy ``bbox``/``effective_bbox``/``nominatim_bbox`` fields or from a
    geocoder point.
    """
    candidates = [
        output_dir / "logs" / "target_resolution_all.json",
        output_dir / "logs" / "target_resolution.json",
    ]
    for path in candidates:
        if not path.exists() or path.stat().st_size <= 0:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        raw_targets = data.get("targets") if isinstance(data, dict) and isinstance(data.get("targets"), list) else None
        if raw_targets is None and isinstance(data, dict):
            raw_targets = [data]
        overlays: list[dict[str, Any]] = []
        for item in raw_targets or []:
            if not isinstance(item, dict):
                continue
            fallback_bbox = _normalized_bbox_for_overlay(item.get("fallback_geometry_bbox"))
            last_fallback_bbox = _normalized_bbox_for_overlay(item.get("last_fallback_geometry_bbox"))
            primary_geometry = _normalized_geojson_geometry_for_overlay(item.get("primary_geometry_geojson"))
            chosen = item.get("chosen_candidate") if isinstance(item.get("chosen_candidate"), dict) else {}
            overlay = {
                "target_id": item.get("target_id"),
                "target_index": item.get("target_index"),
                "target_label": item.get("target_label") or item.get("canonical_target") or item.get("target_id"),
                "canonical_target": item.get("canonical_target"),
                "scope_type": item.get("scope_type"),
                "primary_geometry_geojson": primary_geometry,
                "primary_geometry_source": item.get("primary_geometry_source"),
                "fallback_geometry_bbox": fallback_bbox,
                "fallback_geometry_source": item.get("fallback_geometry_source"),
                "last_fallback_geometry_bbox": last_fallback_bbox,
                "last_fallback_geometry_source": item.get("last_fallback_geometry_source"),
                "bbox_verified": item.get("bbox_verified"),
                "geometry_source": item.get("geometry_source"),
                "geometry_status": item.get("geometry_status"),
                "bbox_padding_applied": item.get("bbox_padding_applied"),
                "bbox_padding_reason": item.get("bbox_padding_reason"),
                "bbox_min_side_miles": item.get("bbox_min_side_miles"),
                "display_name": chosen.get("display_name"),
                "result_type": chosen.get("result_type"),
            }
            if overlay["primary_geometry_geojson"] or overlay["fallback_geometry_bbox"] or overlay["last_fallback_geometry_bbox"]:
                overlays.append(overlay)
        return overlays
    return []


def _normalized_bbox_for_overlay(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {
            "min_lat": float(value["min_lat"]),
            "max_lat": float(value["max_lat"]),
            "min_lon": float(value["min_lon"]),
            "max_lon": float(value["max_lon"]),
        }
    except Exception:
        return None
    if bbox["max_lat"] <= bbox["min_lat"] or bbox["max_lon"] <= bbox["min_lon"]:
        return None
    if not (-90 <= bbox["min_lat"] <= 90 and -90 <= bbox["max_lat"] <= 90):
        return None
    if not (-180 <= bbox["min_lon"] <= 180 and -180 <= bbox["max_lon"] <= 180):
        return None
    return bbox



def _normalized_geojson_geometry_for_overlay(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    geom_type = value.get("type")
    coords = value.get("coordinates")
    if geom_type not in {"Polygon", "MultiPolygon"} or not isinstance(coords, list) or not coords:
        return None
    return value if _geometry_has_coordinate_pair(coords) else None


def _geometry_has_coordinate_pair(value: Any) -> bool:
    if isinstance(value, list):
        if len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
            lat = float(value[1])
            lon = float(value[0])
            return -90 <= lat <= 90 and -180 <= lon <= 180
        return any(_geometry_has_coordinate_pair(item) for item in value)
    return False


def geojson_features_to_rows(geojson: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten GeoJSON features into stable table rows without changing trust state."""
    rows: list[dict[str, Any]] = []
    for index, feature in enumerate(geojson.get("features") or []):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        lon = coordinates[0] if isinstance(coordinates, list) and len(coordinates) >= 2 else None
        lat = coordinates[1] if isinstance(coordinates, list) and len(coordinates) >= 2 else None
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        row = {
            "feature_index": index,
            "name": _first_text(props, "name", "title", "camera_name", "source_name") or f"Camera {index + 1}",
            "target_label": props.get("target_label") or props.get("target_id"),
            "location_text": _first_text(props, "location_display", "location_text", "geocoded_display_name", "source_scope_hint"),
            "camera_type": _first_text(props, "camera_type", "type", "category"),
            "camera_id": _first_text(props, "camera_id", "id"),
            "media_type": _first_text(props, "media_type"),
            "latitude": props.get("lat", lat),
            "longitude": props.get("lon", lon),
            "stream_url": props.get("stream_url"),
            "source_url": props.get("source_url"),
            "thumbnail_url": find_thumbnail_url(props),
            "camera_refresh_rate": props.get("camera_refresh_rate"),
            "map_refresh_rate_seconds": props.get("map_refresh_rate_seconds"),
            "trust_level": props.get("trust_level"),
            "validation_status": props.get("validation_status"),
            "scope_status": props.get("scope_status"),
            "discovery_method": props.get("discovery_method"),
            "review_required": props.get("review_required"),
            "target_id": props.get("target_id"),
            "output_policy": props.get("output_policy"),
            "llm_semantic_decision": props.get("llm_semantic_decision"),
            "llm_semantic_reason": props.get("llm_semantic_reason"),
        }
        rows.append(row)
    return rows


def write_camera_table_csv(output_dir: Path, rows: list[dict[str, Any]], filename: str = "camera_candidates_table.csv") -> Path:
    """Write flattened camera rows to CSV for Colab download/review."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    fieldnames = list(TABLE_COLUMNS)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_embedded_camera_map(
    output_dir: Path,
    geojson_path: Path | None = None,
    *,
    output_name: str = "map.html",
) -> Path:
    """Write a self-contained camera map that embeds the selected GeoJSON data.

    The map displays a popup for each camera with GeoJSON properties, an optional
    thumbnail URL when present in the feature properties, and a button that tries
    to play the stream URL with hls.js or native browser video support.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    geojson, source_name, selected_paths = load_camera_map_geojson(output_dir, geojson_path)
    target_overlays = load_target_geometry_overlays(output_dir)
    target_primary_geometry_overlay_count = sum(1 for target in target_overlays if target.get("primary_geometry_geojson"))
    target_fallback_bbox_overlay_count = sum(1 for target in target_overlays if target.get("fallback_geometry_bbox"))
    target_last_fallback_bbox_overlay_count = sum(1 for target in target_overlays if target.get("last_fallback_geometry_bbox"))
    target_bbox_overlay_count = target_fallback_bbox_overlay_count + target_last_fallback_bbox_overlay_count
    target_point_overlay_count = 0
    html = _camera_map_html(geojson, source_name, target_overlays)
    path = output_dir / output_name
    path.write_text(html, encoding="utf-8")
    write_json(
        output_dir / "logs" / "camera_map_status.json",
        {
            "map_html": str(path),
            "source_geojson": str(selected_paths[0]) if len(selected_paths) == 1 else None,
            "source_geojson_files": [str(path) for path in selected_paths],
            "features": len(geojson.get("features") or []),
            "target_geometry_overlays": len(target_overlays),
            "target_primary_geometry_overlays": target_primary_geometry_overlay_count,
            "target_fallback_bbox_overlays": target_fallback_bbox_overlay_count,
            "target_last_fallback_bbox_overlays": target_last_fallback_bbox_overlay_count,
            "target_bbox_overlays": target_bbox_overlay_count,
            "target_point_overlays": target_point_overlay_count,
            "has_target_primary_geometry_overlays": target_primary_geometry_overlay_count > 0,
            "has_target_bbox_overlays": target_bbox_overlay_count > 0,
            "has_target_point_overlays": False,
            "strict_artifact_geometry_only": True,
            "allowed_target_geometry_roles": ["primary", "fallback", "last_fallback"],
            "map_embeds_target_overlay_code": True,
            "has_video_playback_button": True,
            "has_refreshing_snapshot_viewer": True,
            "has_camera_type_legend": True,
            "has_trust_shape_legend": True,
            "marker_shapes": {"trusted": "star", "untrusted_review": "circle"},
            "marker_colors": {"traffic": "green", "weather": "deepskyblue", "transit": "purple", "public": "royalblue", "image_snapshot": "gold", "hls": "green", "other": "royalblue", "unknown": "gray"},
            "thumbnail_fields_supported": list(THUMBNAIL_KEYS),
        },
    )
    return path


def find_thumbnail_url(properties: dict[str, Any]) -> str | None:
    """Find a thumbnail/snapshot URL in feature properties or source metadata."""
    for key in THUMBNAIL_KEYS:
        value = properties.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://", "data:")):
            return value
    metadata = properties.get("source_metadata")
    if isinstance(metadata, dict):
        for key in THUMBNAIL_KEYS:
            value = metadata.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://", "data:")):
                return value
    return None


def _first_text(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = mapping.get("source_metadata")
    if isinstance(metadata, dict):
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _camera_map_html(geojson: dict[str, Any], source_name: str | None, target_overlays: list[dict[str, Any]] | None = None) -> str:
    data = json.dumps(geojson, ensure_ascii=False)
    targets = json.dumps(target_overlays or [], ensure_ascii=False)
    title = escape(source_name or "No GeoJSON selected")
    thumbnail_keys_json = json.dumps(list(THUMBNAIL_KEYS))
    template = """<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Camera Discovery Map</title>
  <link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
  <script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
  <script src='https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js'></script>
  <style>
    html, body, #map { height: 100%; margin: 0; }
    .status { position: absolute; z-index: 999; left: 10px; top: 10px; background: white; padding: 8px 10px; border-radius: 8px; box-shadow: 0 1px 8px rgba(0,0,0,.25); font-family: sans-serif; max-width: 420px; }
    .map-legend { position: absolute; z-index: 999; right: 10px; bottom: 22px; background: white; padding: 8px 10px; border-radius: 8px; box-shadow: 0 1px 8px rgba(0,0,0,.25); font-family: sans-serif; font-size: 12px; }
    .legend-title { font-weight: 700; margin-bottom: 5px; }
    .legend-row { display: flex; align-items: center; gap: 6px; margin: 3px 0; }
    .swatch { display: inline-block; width: 12px; height: 12px; border-radius: 999px; border: 1px solid rgba(0,0,0,.35); }
    .shape-swatch { display:inline-flex; align-items:center; justify-content:center; width:14px; height:14px; font-size:14px; line-height:14px; color:#222; }
    .target-point-swatch { display:inline-block; width:10px; height:10px; border-radius:999px; border:2px solid #1d4ed8; background:white; }
    .target-popup { width: 300px; font-family: sans-serif; }
    .target-popup h3 { margin: 0 0 6px 0; font-size: 15px; }
    .target-popup table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .target-popup td { vertical-align: top; border-top: 1px solid #eee; padding: 3px 2px; }
    .target-popup td:first-child { font-weight: 600; color: #444; width: 110px; }
    .star-marker { width:16px; height:16px; line-height:16px; text-align:center; font-size:16px; font-weight:900; text-shadow:0 0 2px #222; transform: translate(-8px, -8px); }
    .popup { width: 320px; font-family: sans-serif; }
    .popup h3 { margin: 0 0 6px 0; font-size: 15px; }
    .popup table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .popup td { vertical-align: top; border-top: 1px solid #eee; padding: 3px 2px; }
    .popup td:first-child { font-weight: 600; color: #444; width: 100px; }
    .popup details { margin-top: 6px; font-size: 12px; }
    .thumb { width: 100%; max-height: 170px; object-fit: cover; border-radius: 8px; border: 1px solid #ddd; margin: 6px 0; background: #000; }
    .no-thumb { padding: 12px; border: 1px dashed #bbb; color: #666; border-radius: 8px; text-align: center; margin: 6px 0; }
    .play { width: 100%; padding: 8px; border: 0; border-radius: 8px; background: #1565c0; color: white; cursor: pointer; font-weight: 700; }
    .play:hover { background: #0d47a1; }
    .video-modal { display: none; position: fixed; z-index: 2000; inset: 0; background: rgba(0,0,0,.82); align-items: center; justify-content: center; }
    .video-card { width: min(94vw, 920px); background: #111; color: white; border-radius: 12px; padding: 12px; box-shadow: 0 4px 24px rgba(0,0,0,.5); }
    .video-card header { display: flex; justify-content: space-between; gap: 10px; align-items: center; font-family: sans-serif; }
    .close { background: #444; color: white; border: 0; padding: 6px 10px; border-radius: 6px; cursor: pointer; }
    video { width: 100%; max-height: 72vh; margin-top: 10px; background: black; }
    .snapshot-live { width: 100%; max-height: 72vh; object-fit: contain; margin-top: 10px; background: #000; }
    .stream-link { color: #90caf9; word-break: break-all; font-size: 12px; }
  </style>
</head>
<body>
  <div class='status' id='status'>Loading __TITLE__...</div>
  <div class='map-legend' aria-label='Camera color legend and marker shape legend'>
    <div class='legend-title'>Marker shape</div>
    <div class='legend-row'><span class='shape-swatch'>★</span><span>Trusted</span></div>
    <div class='legend-row'><span class='shape-swatch'>●</span><span>Untrusted / review</span></div>
    <div class='legend-title' style='margin-top:6px'>Target geometry</div>
    <div class='legend-row'><span class='swatch' style='background:white;border:2px solid #1d4ed8;border-radius:0'></span><span>Primary/fallback target geometry</span></div>
    <div class='legend-title' style='margin-top:6px'>Camera color legend</div>
    <div class='legend-row'><span class='swatch' style='background:green'></span><span>Traffic / HLS video fallback</span></div>
    <div class='legend-row'><span class='swatch' style='background:deepskyblue'></span><span>Weather</span></div>
    <div class='legend-row'><span class='swatch' style='background:purple'></span><span>Transit</span></div>
    <div class='legend-row'><span class='swatch' style='background:gold'></span><span>Image snapshot fallback</span></div>
    <div class='legend-row'><span class='swatch' style='background:royalblue'></span><span>Public / other</span></div>
    <div class='legend-row'><span class='swatch' style='background:gray'></span><span>Unknown</span></div>
  </div>
  <div id='map'></div>
  <div class='video-modal' id='videoModal'>
    <div class='video-card'>
      <header><strong id='videoTitle'>Camera stream</strong><button class='close' onclick='closeVideo()'>Close</button></header>
      <video id='cameraVideo' controls autoplay muted playsinline></video>
      <img id='snapshotViewer' class='snapshot-live' style='display:none' alt='Refreshing camera snapshot'>
      <div id='streamLink' class='stream-link'></div>
    </div>
  </div>
  <script>
    const CAMERA_GEOJSON = __DATA__;
    const TARGET_GEOMETRIES = __TARGET_GEOMETRIES__;
    const THUMBNAIL_KEYS = __THUMBNAIL_KEYS__;
    let activeHls = null;
    const map = L.map('map').setView([39, -98], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);

    function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
    function getMetadata(props) { return props && typeof props.source_metadata === 'object' && props.source_metadata !== null ? props.source_metadata : {}; }
    function firstValue(props, keys) {
      const meta = getMetadata(props);
      for (const k of keys) { if (props && props[k] !== undefined && props[k] !== null && props[k] !== '') return props[k]; }
      for (const k of keys) { if (meta && meta[k] !== undefined && meta[k] !== null && meta[k] !== '') return meta[k]; }
      return '';
    }
    function cacheBust(url) { if (!url || url.startsWith('data:')) return url; const sep = url.includes('?') ? '&' : '?'; return url + sep + '_camera_discovery_ts=' + Date.now(); }
    let snapshotTimer = null;
    let popupPreviewHlsPlayers = [];
    function normalizedMediaType(props, stream, thumb) {
      const mediaType = firstValue(props, ['media_type']);
      if (mediaType) return String(mediaType).toLowerCase();
      const lower = String(stream || '').toLowerCase();
      if (lower.includes('.m3u8')) return 'hls';
      if (thumb || /\\.(jpg|jpeg|png|webp)(\\?|$)/i.test(lower)) return 'image_snapshot';
      return 'other';
    }
    function cameraColorCategory(props, mediaType) {
      const raw = String(firstValue(props, ['camera_type', 'raw_camera_type', 'type', 'category']) || '').toLowerCase();
      if (raw.includes('traffic') || raw.includes('road') || raw.includes('highway') || raw.includes('cctv')) return 'traffic';
      if (raw.includes('weather') || raw.includes('wx')) return 'weather';
      if (raw.includes('transit') || raw.includes('rail') || raw.includes('bus') || raw.includes('train')) return 'transit';
      if (raw.includes('public') || raw.includes('tour')) return 'public';
      if (raw.includes('camera') || raw.includes('webcam')) return 'public';
      if (mediaType === 'image_snapshot') return 'image_snapshot';
      if (mediaType === 'hls' || mediaType === 'hls_stream' || mediaType === 'video') return 'traffic';
      return raw ? 'other' : 'unknown';
    }
    function markerColor(category) {
      if (category === 'traffic') return 'green';
      if (category === 'weather') return 'deepskyblue';
      if (category === 'transit') return 'purple';
      if (category === 'image_snapshot') return 'gold';
      if (category === 'unknown') return 'gray';
      return 'royalblue';
    }
    function trustedStarIcon(color) { return L.divIcon({ className: '', html: `<div class="star-marker" style="color:${esc(color)}">★</div>`, iconSize: [16,16], iconAnchor: [8,8] }); }
    function markerForFeature(feature, latlng) {
      const p = feature.properties || {};
      const stream = p.stream_url || '';
      const thumb = firstValue(p, THUMBNAIL_KEYS);
      const mediaType = normalizedMediaType(p, stream, thumb);
      const color = markerColor(cameraColorCategory(p, mediaType));
      if (String(p.trust_level || '').toLowerCase() === 'trusted' || p.trusted_geojson_candidate === true) return L.marker(latlng, { icon: trustedStarIcon(color) });
      return L.circleMarker(latlng, { radius: 7, weight: 2, color: '#222', fillColor: color, fillOpacity: .82 });
    }
    function stopPopupPreviews() {
      for (const item of popupPreviewHlsPlayers) { try { if (item.hls) item.hls.destroy(); } catch (err) {} try { if (item.video) { item.video.pause(); item.video.removeAttribute('src'); item.video.load(); } } catch (err) {} }
      popupPreviewHlsPlayers = [];
    }
    function initPopupPreviews(container) {
      stopPopupPreviews();
      if (!container) return;
      for (const video of container.querySelectorAll('video.hls-thumb[data-stream]')) {
        const url = video.getAttribute('data-stream');
        if (!url) continue;
        if (url.toLowerCase().includes('.m3u8') && window.Hls && Hls.isSupported()) { const hls = new Hls({ lowLatencyMode: true }); hls.loadSource(url); hls.attachMedia(video); popupPreviewHlsPlayers.push({ video, hls }); }
        else { video.src = url; popupPreviewHlsPlayers.push({ video, hls: null }); }
        video.play().catch(() => {});
      }
    }
    function previewHtml(mediaType, stream, thumb) {
      if (mediaType === 'image_snapshot') { const imageUrl = thumb || stream; return imageUrl ? `<img class="thumb" src="${esc(cacheBust(imageUrl))}" alt="Current camera image" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'no-thumb',innerText:'Snapshot unavailable'}))">` : `<div class="no-thumb">No snapshot URL in GeoJSON</div>`; }
      if (mediaType === 'rtsp') return `<div class="no-thumb">RTSP media requires an external player</div>`;
      if (thumb) return `<img class="thumb" src="${esc(cacheBust(thumb))}" alt="Camera thumbnail" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'no-thumb',innerText:'Thumbnail unavailable'}))">`;
      if (stream && String(stream).toLowerCase().includes('.m3u8')) return `<video class="thumb hls-thumb" data-stream="${esc(stream)}" muted autoplay playsinline></video>`;
      return `<div class="no-thumb">No thumbnail URL in GeoJSON</div>`;
    }
    function linkHtml(label, url) { return url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)}</a>` : ''; }
    function detailRow(label, value) { if (value === undefined || value === null || value === '') return ''; return `<tr><td>${esc(label)}</td><td>${esc(value)}</td></tr>`; }
    function bboxToBounds(bbox) {
      if (!bbox) return null;
      const minLat = Number(bbox.min_lat), maxLat = Number(bbox.max_lat), minLon = Number(bbox.min_lon), maxLon = Number(bbox.max_lon);
      if (![minLat, maxLat, minLon, maxLon].every(Number.isFinite) || maxLat <= minLat || maxLon <= minLon) return null;
      return [[minLat, minLon], [maxLat, maxLon]];
    }
    function formatBbox(bbox) {
      if (!bbox) return '';
      return `${Number(bbox.min_lat).toFixed(6)}, ${Number(bbox.min_lon).toFixed(6)} → ${Number(bbox.max_lat).toFixed(6)}, ${Number(bbox.max_lon).toFixed(6)}`;
    }
    function targetPopupHtml(target) {
      const label = target.target_label || target.canonical_target || target.target_id || 'Target';
      return `<div class="target-popup"><h3>${esc(label)}</h3><table>
        ${detailRow('Target ID', target.target_id || '')}
        ${detailRow('Scope', target.scope_type || '')}
        ${detailRow('Geometry source', target.geometry_source || '')}
        ${detailRow('Geometry status', target.geometry_status || '')}
        ${detailRow('Primary geometry', target.primary_geometry_source || (target.primary_geometry_geojson ? 'nominatim_polygon' : ''))}
        ${detailRow('Fallback geometry', target.fallback_geometry_source || '')}
        ${detailRow('Last fallback geometry', target.last_fallback_geometry_source || '')}
        ${detailRow('Verified bbox', target.bbox_verified)}
        ${detailRow('Padding applied', target.bbox_padding_applied)}
        ${detailRow('Padding reason', target.bbox_padding_reason || '')}
        ${detailRow('Min side miles', target.bbox_min_side_miles || '')}
        ${detailRow('Display name', target.display_name || '')}
      </table></div>`;
    }
    function popupHtml(feature) {
      const p = feature.properties || {};
      const coords = feature.geometry && Array.isArray(feature.geometry.coordinates) ? feature.geometry.coordinates : [];
      const lon = p.lon ?? coords[0] ?? '';
      const lat = p.lat ?? coords[1] ?? '';
      const name = firstValue(p, ['name', 'title', 'camera_name', 'source_name']) || 'Camera candidate';
      const thumb = firstValue(p, THUMBNAIL_KEYS);
      const stream = p.stream_url || firstValue(p, ['media_url', 'stream_url']) || '';
      const source = p.source_url || firstValue(p, ['json_endpoint_url']) || '';
      const mediaType = normalizedMediaType(p, stream, thumb);
      const cameraType = firstValue(p, ['camera_type', 'type', 'category']) || '';
      const rawCameraType = firstValue(p, ['raw_camera_type']) || '';
      const cameraId = firstValue(p, ['camera_id', 'id']) || '';
      const locationText = firstValue(p, ['location_display', 'location_text', 'geocoded_display_name', 'source_scope_hint']) || '';
      const cameraRefreshRate = firstValue(p, ['camera_refresh_rate', 'refresh_rate', 'refresh_rate_seconds', 'refresh_interval', 'refresh_interval_seconds']) || '';
      const mapRefreshRate = firstValue(p, ['map_refresh_rate_seconds', 'image_snapshot_refresh_delay_seconds']) || '';
      const sourceEndpoint = firstValue(p, ['json_endpoint_url']) || source;
      const snapshot = firstValue(p, ['snapshot_url', 'current_image_url', 'currentImageURL']);
      const thumbnail = thumb || firstValue(p, ['thumbnail_url', 'reference_image_url', 'referenceImageURL', 'referenceImage1URL']);
      const thumbHtml = previewHtml(mediaType, stream, thumb);
      const buttonLabel = mediaType === 'rtsp' ? '↗ Open RTSP URL' : (mediaType === 'image_snapshot' ? '↻ Open refreshing snapshot' : '▶ Play media');
      const playHtml = stream ? `<button class="play" onclick='playCamera(${JSON.stringify(stream)}, ${JSON.stringify(name)}, ${JSON.stringify(mediaType)}, ${JSON.stringify(mapRefreshRate)})'>${buttonLabel}</button>` : '';
      const linkBits = [
        linkHtml(sourceEndpoint && String(sourceEndpoint).toLowerCase().includes('.json') ? 'source JSON' : 'source page', sourceEndpoint),
        linkHtml('media', stream),
        snapshot && snapshot !== stream ? linkHtml('snapshot', snapshot) : '',
        thumbnail && thumbnail !== stream && thumbnail !== snapshot ? linkHtml('thumbnail/reference', thumbnail) : '',
      ].filter(Boolean).join(' ');
      const details = ['route','road','direction','intersection','cross_street','city','county','district','region','camera_status','owner','agency','coordinate_source','geocoded_query','json_record_path','json_record_schema_hint']
        .map(k => detailRow(k.replaceAll('_',' '), firstValue(p, [k])))
        .join('');
      return `<div class="popup"><h3>${esc(name)}</h3>${thumbHtml}${playHtml}<table>
        ${detailRow('Target', p.target_label || p.target_id || '')}
        ${detailRow('Location', locationText)}
        ${detailRow('Camera type', cameraType)}
        ${detailRow('Raw type', rawCameraType)}
        ${detailRow('Camera ID', cameraId)}
        ${detailRow('Media type', mediaType)}
        ${detailRow('Camera Refresh Rate', cameraRefreshRate)}
        ${detailRow('Map Refresh Rate', mapRefreshRate)}
        ${detailRow('Lat/Lon', `${lat}, ${lon}`)}
        ${detailRow('Trust', p.trust_level || '')}
        ${detailRow('Validation', p.validation_status || '')}
        ${detailRow('Scope', p.scope_status || '')}
        ${detailRow('Discovery', p.discovery_method || '')}
        <tr><td>Links</td><td>${linkBits}</td></tr>
      </table>${details ? `<details><summary>Source metadata</summary><table>${details}</table></details>` : ''}</div>`;
    }
    function playCamera(url, title, mediaType, refreshSeconds) {
      const modal = document.getElementById('videoModal');
      const video = document.getElementById('cameraVideo');
      const snapshot = document.getElementById('snapshotViewer');
      document.getElementById('videoTitle').innerText = title || 'Camera media';
      document.getElementById('streamLink').innerHTML = `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`;
      if (activeHls) { activeHls.destroy(); activeHls = null; }
      if (snapshotTimer) { clearInterval(snapshotTimer); snapshotTimer = null; }
      video.pause(); video.removeAttribute('src'); video.load();
      video.style.display = 'none';
      snapshot.style.display = 'none';
      snapshot.removeAttribute('src');
      if (mediaType === 'image_snapshot' || /\\.(jpg|jpeg|png|webp)(\\?|$)/i.test(url)) {
        snapshot.src = cacheBust(url);
        snapshot.style.display = 'block';
        const refreshMs = Math.max(1000, Number(refreshSeconds || 15) * 1000);
        snapshotTimer = setInterval(() => { snapshot.src = cacheBust(url); }, refreshMs);
      } else {
        video.style.display = 'block';
        if (url.toLowerCase().includes('.m3u8') && window.Hls && Hls.isSupported()) { activeHls = new Hls({ lowLatencyMode: true }); activeHls.loadSource(url); activeHls.attachMedia(video); }
        else { video.src = url; }
        video.play().catch(() => {});
      }
      modal.style.display = 'flex';
    }
    function closeVideo() {
      const modal = document.getElementById('videoModal');
      const video = document.getElementById('cameraVideo');
      const snapshot = document.getElementById('snapshotViewer');
      if (activeHls) { activeHls.destroy(); activeHls = null; }
      if (snapshotTimer) { clearInterval(snapshotTimer); snapshotTimer = null; }
      video.pause(); video.removeAttribute('src'); video.load();
      snapshot.removeAttribute('src');
      modal.style.display = 'none';
    }
    document.getElementById('videoModal').addEventListener('click', e => { if (e.target.id === 'videoModal') closeVideo(); });
    map.on('popupopen', e => initPopupPreviews(e.popup && e.popup.getElement ? e.popup.getElement() : null));
    map.on('popupclose', () => stopPopupPreviews());

    const layer = L.geoJSON(CAMERA_GEOJSON, {
      onEachFeature: (feature, layer) => layer.bindPopup(popupHtml(feature), { maxWidth: 360 }),
      pointToLayer: (feature, latlng) => markerForFeature(feature, latlng)
    }).addTo(map);

    const targetLayer = L.featureGroup().addTo(map);
    for (const target of TARGET_GEOMETRIES || []) {
      const primaryGeometry = target.primary_geometry_geojson;
      if (primaryGeometry) {
        L.geoJSON(primaryGeometry, { style: { color: '#1d4ed8', weight: 3, fill: false, fillOpacity: 0 } })
          .bindPopup(targetPopupHtml(target), { maxWidth: 340 })
          .addTo(targetLayer);
      }
      const fallbackBounds = bboxToBounds(target.fallback_geometry_bbox);
      const lastFallbackBounds = bboxToBounds(target.last_fallback_geometry_bbox);
      if (!primaryGeometry && fallbackBounds) {
        L.rectangle(fallbackBounds, { color: '#1d4ed8', weight: 2, fill: false, fillOpacity: 0 })
          .bindPopup(targetPopupHtml(target), { maxWidth: 340 })
          .addTo(targetLayer);
      }
      if (!primaryGeometry && !fallbackBounds && lastFallbackBounds) {
        L.rectangle(lastFallbackBounds, { color: '#9333ea', weight: 2, fill: false, fillOpacity: 0, dashArray: '4 4' })
          .bindPopup(targetPopupHtml(target), { maxWidth: 340 })
          .addTo(targetLayer);
      }
    }

    const count = (CAMERA_GEOJSON.features || []).length;
    const targetCount = (TARGET_GEOMETRIES || []).length;
    const fitGroup = L.featureGroup();
    if (count) layer.eachLayer(item => fitGroup.addLayer(item));
    targetLayer.eachLayer(item => fitGroup.addLayer(item));
    if (fitGroup.getLayers().length && fitGroup.getBounds().isValid()) map.fitBounds(fitGroup.getBounds(), { padding: [24, 24] });
    const cameraText = count ? `${count} camera feature(s)` : 'No camera GeoJSON features found';
    const targetText = targetCount ? `${targetCount} target geometry overlay(s)` : 'no target geometry overlay';
    document.getElementById('status').innerText = `Loaded __TITLE__: ${cameraText}; ${targetText}`;
  </script>
</body>
</html>
"""
    return (
        template.replace("__DATA__", data)
        .replace("__TARGET_GEOMETRIES__", targets)
        .replace("__TITLE__", title)
        .replace("__THUMBNAIL_KEYS__", thumbnail_keys_json)
    )
