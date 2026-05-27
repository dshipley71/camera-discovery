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
