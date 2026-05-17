from camera_discovery.utils.geojson_viewer import select_camera_geojson, write_embedded_camera_map


def test_camera_map_html_supports_popup_thumbnail_and_video_button(tmp_path):
    map_path = write_embedded_camera_map(tmp_path, output_name="map.html")
    html = map_path.read_text(encoding="utf-8")
    assert "playCamera" in html
    assert "hls.js" in html or "Hls.isSupported" in html
    assert "thumbnail_url" in html
    assert "No camera GeoJSON features found" in html


def test_select_camera_geojson_prefers_trusted_over_untrusted(tmp_path):
    untrusted = tmp_path / "untrusted_camera_candidates.geojson"
    trusted = tmp_path / "camera.geojson"
    untrusted.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    assert select_camera_geojson(tmp_path) == untrusted
    trusted.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    assert select_camera_geojson(tmp_path) == trusted
