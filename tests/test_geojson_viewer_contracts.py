from camera_discovery.utils.geojson_viewer import select_camera_geojson, write_embedded_camera_map


def test_camera_map_html_supports_popup_thumbnail_and_video_button(tmp_path):
    map_path = write_embedded_camera_map(tmp_path, output_name="map.html")
    html = map_path.read_text(encoding="utf-8")
    assert "playCamera" in html
    assert "hls.js" in html or "Hls.isSupported" in html
    assert "thumbnail_url" in html
    assert "Camera color legend" in html
    assert "HLS video" in html
    assert "Image snapshot" in html
    assert "No camera GeoJSON features found" in html
    status = (tmp_path / "logs" / "camera_map_status.json").read_text(encoding="utf-8")
    assert '"target_bbox_overlays": 0' in status
    assert '"has_target_bbox_overlays": false' in status


def test_select_camera_geojson_prefers_trusted_over_untrusted(tmp_path):
    untrusted = tmp_path / "untrusted_camera_candidates.geojson"
    trusted = tmp_path / "camera.geojson"
    untrusted.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    assert select_camera_geojson(tmp_path) == untrusted
    trusted.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    assert select_camera_geojson(tmp_path) == trusted


def test_camera_map_merges_trusted_and_untrusted_geojson_and_colors_by_media_type(tmp_path):
    (tmp_path / "camera.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-100,40]},"properties":{"stream_url":"https://public.example/live.m3u8","media_type":"hls","location_display":"I-5 at Main","trust_level":"trusted"}}]}',
        encoding="utf-8",
    )
    (tmp_path / "untrusted_camera_candidates.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-101,41]},"properties":{"stream_url":"https://public.example/cam.jpg","media_type":"image_snapshot","map_refresh_rate_seconds":2.0,"trust_level":"rejected"}}]}',
        encoding="utf-8",
    )
    html = write_embedded_camera_map(tmp_path, output_name="map.html").read_text(encoding="utf-8")
    assert "live.m3u8" in html
    assert "cam.jpg" in html
    assert "markerColor" in html
    assert "green" in html
    assert "gold" in html
    assert "Camera Refresh Rate" in html
    assert "Map Refresh Rate" in html


def test_camera_map_overlays_target_bbox_and_geocoder_point(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "target_resolution_all.json").write_text(
        '{"targets":[{"target_id":"example","target_label":"Example Target","scope_type":"place","bbox":{"min_lat":38.0,"max_lat":38.01,"min_lon":-77.01,"max_lon":-77.0},"nominatim_bbox":{"min_lat":38.0001,"max_lat":38.0002,"min_lon":-77.0002,"max_lon":-77.0001},"bbox_verified":true,"geometry_source":"geocoder_padded","geometry_status":"verified","bbox_padding_applied":true,"bbox_padding_reason":"known_geocoder_bbox_below_minimum_precise_target_extent","bbox_min_side_miles":1.0,"chosen_candidate":{"lat":38.00015,"lon":-77.00015,"display_name":"Example Target","result_type":"monument"}}]}',
        encoding="utf-8",
    )
    (tmp_path / "untrusted_camera_candidates.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-77.005,38.005]},"properties":{"stream_url":"https://public.example/live.m3u8","media_type":"hls","trust_level":"untrusted"}}]}',
        encoding="utf-8",
    )

    html = write_embedded_camera_map(tmp_path, output_name="map.html").read_text(encoding="utf-8")
    status = (logs / "camera_map_status.json").read_text(encoding="utf-8")

    assert "TARGET_GEOMETRIES" in html
    assert "L.rectangle" in html
    assert "fill: false" in html
    assert "Example Target" in html
    assert "geocoder_padded" in html
    assert "Geocoder point" in html
    assert '"target_bbox_overlays": 1' in status
    assert '"target_point_overlays": 1' in status
    assert '"has_target_bbox_overlays": true' in status
    assert '"map_embeds_target_overlay_code": true' in status


def test_camera_map_prefers_target_polygon_over_rectangle_when_available(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    polygon = '{"type":"Polygon","coordinates":[[[-124,32],[-114,32],[-114,42],[-124,42],[-124,32]]]}'
    (logs / "target_resolution_all.json").write_text(
        '{"targets":[{"target_id":"ca","target_label":"California","scope_type":"state","target_geometry_geojson":'
        + polygon
        + ',"primary_geometry_source":"nominatim_polygon","fallback_geometry_bbox":{"min_lat":32,"max_lat":42,"min_lon":-124,"max_lon":-114},"bbox":{"min_lat":32,"max_lat":42,"min_lon":-124,"max_lon":-114},"bbox_verified":true,"geometry_source":"nominatim_polygon","geometry_status":"verified","chosen_candidate":{"lat":37,"lon":-119,"display_name":"California","result_type":"administrative"}}]}',
        encoding="utf-8",
    )
    html = write_embedded_camera_map(tmp_path, output_name="map.html").read_text(encoding="utf-8")
    status = (logs / "camera_map_status.json").read_text(encoding="utf-8")

    assert "L.geoJSON(primaryGeometry" in html
    assert "nominatim_polygon" in html
    assert '"target_primary_geometry_overlays": 1' in status
    assert '"target_fallback_bbox_overlays": 1' in status
