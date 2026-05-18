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
    """Flatten camera GeoJSON features into rows suitable for notebook display."""
    return geojson_features_to_rows(load_geojson(path))


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
            "location_text": props.get("location_text") or props.get("source_metadata", {}).get("source_scope_hint") if isinstance(props.get("source_metadata"), dict) else props.get("location_text"),
            "camera_type": _first_text(props, "camera_type", "type", "category"),
            "camera_id": _first_text(props, "camera_id", "id"),
            "media_type": _first_text(props, "media_type"),
            "latitude": props.get("lat", lat),
            "longitude": props.get("lon", lon),
            "stream_url": props.get("stream_url"),
            "source_url": props.get("source_url"),
            "thumbnail_url": find_thumbnail_url(props),
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
    selected = geojson_path or select_camera_geojson(output_dir)
    geojson = load_geojson(selected) if selected else {"type": "FeatureCollection", "features": []}
    source_name = selected.name if selected else None
    html = _camera_map_html(geojson, source_name)
    path = output_dir / output_name
    path.write_text(html, encoding="utf-8")
    write_json(
        output_dir / "logs" / "camera_map_status.json",
        {
            "map_html": str(path),
            "source_geojson": str(selected) if selected else None,
            "features": len(geojson.get("features") or []),
            "has_video_playback_button": True,
            "has_refreshing_snapshot_viewer": True,
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


def _camera_map_html(geojson: dict[str, Any], source_name: str | None) -> str:
    data = json.dumps(geojson, ensure_ascii=False)
    title = escape(source_name or "No GeoJSON selected")
    return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Camera Discovery Map</title>
  <link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
  <script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
  <script src='https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js'></script>
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .status {{ position: absolute; z-index: 999; left: 10px; top: 10px; background: white; padding: 8px 10px; border-radius: 8px; box-shadow: 0 1px 8px rgba(0,0,0,.25); font-family: sans-serif; max-width: 420px; }}
    .popup {{ width: 300px; font-family: sans-serif; }}
    .popup h3 {{ margin: 0 0 6px 0; font-size: 15px; }}
    .popup table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .popup td {{ vertical-align: top; border-top: 1px solid #eee; padding: 3px 2px; }}
    .popup td:first-child {{ font-weight: 600; color: #444; width: 88px; }}
    .thumb {{ width: 100%; max-height: 170px; object-fit: cover; border-radius: 8px; border: 1px solid #ddd; margin: 6px 0; }}
    .no-thumb {{ padding: 12px; border: 1px dashed #bbb; color: #666; border-radius: 8px; text-align: center; margin: 6px 0; }}
    .play {{ width: 100%; padding: 8px; border: 0; border-radius: 8px; background: #1565c0; color: white; cursor: pointer; font-weight: 700; }}
    .play:hover {{ background: #0d47a1; }}
    .video-modal {{ display: none; position: fixed; z-index: 2000; inset: 0; background: rgba(0,0,0,.82); align-items: center; justify-content: center; }}
    .video-card {{ width: min(94vw, 920px); background: #111; color: white; border-radius: 12px; padding: 12px; box-shadow: 0 4px 24px rgba(0,0,0,.5); }}
    .video-card header {{ display: flex; justify-content: space-between; gap: 10px; align-items: center; font-family: sans-serif; }}
    .close {{ background: #444; color: white; border: 0; padding: 6px 10px; border-radius: 6px; cursor: pointer; }}
    video {{ width: 100%; max-height: 72vh; margin-top: 10px; background: black; }}
    .snapshot-live {{ width: 100%; max-height: 72vh; object-fit: contain; margin-top: 10px; background: #000; }}
    .stream-link {{ color: #90caf9; word-break: break-all; font-size: 12px; }}
  </style>
</head>
<body>
  <div class='status' id='status'>Loading {title}...</div>
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
    const CAMERA_GEOJSON = {data};
    let activeHls = null;
    const map = L.map('map').setView([39, -98], 4);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }}).addTo(map);

    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    }}
    function getMetadata(props) {{ return props && typeof props.source_metadata === 'object' && props.source_metadata !== null ? props.source_metadata : {{}}; }}
    function firstValue(props, keys) {{
      const meta = getMetadata(props);
      for (const k of keys) {{ if (props && props[k]) return props[k]; }}
      for (const k of keys) {{ if (meta && meta[k]) return meta[k]; }}
      return '';
    }}
    function cacheBust(url) {{
      if (!url || url.startsWith('data:')) return url;
      const sep = url.includes('?') ? '&' : '?';
      return url + sep + '_camera_discovery_ts=' + Date.now();
    }}
    let snapshotTimer = null;
    function popupHtml(feature) {{
      const p = feature.properties || {{}};
      const coords = feature.geometry && Array.isArray(feature.geometry.coordinates) ? feature.geometry.coordinates : [];
      const lon = p.lon ?? coords[0] ?? '';
      const lat = p.lat ?? coords[1] ?? '';
      const name = firstValue(p, ['name', 'title', 'camera_name', 'source_name']) || 'Camera candidate';
      const thumb = firstValue(p, {json.dumps(list(THUMBNAIL_KEYS))});
      const stream = p.stream_url || '';
      const source = p.source_url || '';
      const mediaType = firstValue(p, ['media_type']) || (String(stream).toLowerCase().includes('.m3u8') ? 'hls' : (thumb || /\\.(jpg|jpeg|png|webp)(\\?|$)/i.test(stream) ? 'image_snapshot' : 'unknown'));
      const cameraType = firstValue(p, ['camera_type', 'type', 'category']) || '';
      const cameraId = firstValue(p, ['camera_id', 'id']) || '';
      const thumbHtml = thumb ? `<img class="thumb" src="${{esc(cacheBust(thumb))}}" alt="Camera thumbnail" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'),{{className:'no-thumb',innerText:'Thumbnail unavailable'}}))">` : `<div class="no-thumb">No thumbnail URL in GeoJSON</div>`;
      const buttonLabel = mediaType === 'image_snapshot' ? '↻ Open refreshing snapshot' : '▶ Play video';
      const playHtml = stream ? `<button class="play" onclick='playCamera(${{JSON.stringify(stream)}}, ${{JSON.stringify(name)}}, ${{JSON.stringify(mediaType)}})'>${{buttonLabel}}</button>` : '';
      const sourceHtml = source ? `<a href="${{esc(source)}}" target="_blank" rel="noopener">source</a>` : '';
      const streamHtml = stream ? `<a href="${{esc(stream)}}" target="_blank" rel="noopener">media</a>` : '';
      return `<div class="popup"><h3>${{esc(name)}}</h3>${{thumbHtml}}${{playHtml}}<table>
        <tr><td>Target</td><td>${{esc(p.target_label || p.target_id || '')}}</td></tr>
        <tr><td>Location</td><td>${{esc(p.location_text || '')}}</td></tr>
        <tr><td>Camera type</td><td>${{esc(cameraType)}}</td></tr>
        <tr><td>Camera ID</td><td>${{esc(cameraId)}}</td></tr>
        <tr><td>Media type</td><td>${{esc(mediaType)}}</td></tr>
        <tr><td>Lat/Lon</td><td>${{esc(lat)}}, ${{esc(lon)}}</td></tr>
        <tr><td>Trust</td><td>${{esc(p.trust_level || '')}}</td></tr>
        <tr><td>Validation</td><td>${{esc(p.validation_status || '')}}</td></tr>
        <tr><td>Scope</td><td>${{esc(p.scope_status || '')}}</td></tr>
        <tr><td>Discovery</td><td>${{esc(p.discovery_method || '')}}</td></tr>
        <tr><td>Links</td><td>${{sourceHtml}} ${{streamHtml}}</td></tr>
      </table></div>`;
    }}
    function playCamera(url, title, mediaType) {{
      const modal = document.getElementById('videoModal');
      const video = document.getElementById('cameraVideo');
      const snapshot = document.getElementById('snapshotViewer');
      document.getElementById('videoTitle').innerText = title || 'Camera media';
      document.getElementById('streamLink').innerHTML = `<a href="${{esc(url)}}" target="_blank" rel="noopener">${{esc(url)}}</a>`;
      if (activeHls) {{ activeHls.destroy(); activeHls = null; }}
      if (snapshotTimer) {{ clearInterval(snapshotTimer); snapshotTimer = null; }}
      video.pause(); video.removeAttribute('src'); video.load();
      video.style.display = 'none';
      snapshot.style.display = 'none';
      snapshot.removeAttribute('src');
      if (mediaType === 'image_snapshot' || /\\.(jpg|jpeg|png|webp)(\\?|$)/i.test(url)) {{
        snapshot.src = cacheBust(url);
        snapshot.style.display = 'block';
        snapshotTimer = setInterval(() => {{ snapshot.src = cacheBust(url); }}, 15000);
      }} else {{
        video.style.display = 'block';
        if (url.toLowerCase().includes('.m3u8') && window.Hls && Hls.isSupported()) {{
          activeHls = new Hls({{ lowLatencyMode: true }});
          activeHls.loadSource(url);
          activeHls.attachMedia(video);
        }} else {{
          video.src = url;
        }}
        video.play().catch(() => {{}});
      }}
      modal.style.display = 'flex';
    }}
    function closeVideo() {{
      const modal = document.getElementById('videoModal');
      const video = document.getElementById('cameraVideo');
      const snapshot = document.getElementById('snapshotViewer');
      if (activeHls) {{ activeHls.destroy(); activeHls = null; }}
      if (snapshotTimer) {{ clearInterval(snapshotTimer); snapshotTimer = null; }}
      video.pause(); video.removeAttribute('src'); video.load();
      snapshot.removeAttribute('src');
      modal.style.display = 'none';
    }}
    document.getElementById('videoModal').addEventListener('click', e => {{ if (e.target.id === 'videoModal') closeVideo(); }});

    const layer = L.geoJSON(CAMERA_GEOJSON, {{
      onEachFeature: (feature, layer) => layer.bindPopup(popupHtml(feature), {{ maxWidth: 340 }}),
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, {{ radius: 7, weight: 2, fillOpacity: .75 }})
    }}).addTo(map);
    const count = (CAMERA_GEOJSON.features || []).length;
    if (count && layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {{ padding: [24, 24] }});
    document.getElementById('status').innerText = count ? `Loaded {title}: ${{count}} camera feature(s)` : 'No camera GeoJSON features found';
  </script>
</body>
</html>
"""
