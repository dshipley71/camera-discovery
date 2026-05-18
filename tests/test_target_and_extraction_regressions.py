from camera_discovery.core.models import RunConfig
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.target_resolver import TargetResolver


def test_traffic_cameras_from_state_keeps_geography_as_target(tmp_path):
    cfg = RunConfig(
        query="Get me all traffic cameras from California",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
    )
    resolver = TargetResolver(cfg)
    phrases = resolver._extract_target_phrases(cfg.query)
    assert phrases == ["California"]
    fallback = resolver._fallback_intent_from_text(phrases[0])
    intent = resolver._intent_from_dict(
        {"canonical_target": "traffic_cameras", "camera_type_intent": "traffic"},
        fallback,
    )
    assert intent.canonical_target == "California"
    assert intent.camera_type_intent == "traffic"


def test_json_endpoint_extracts_image_snapshot_camera_record(tmp_path):
    cfg = RunConfig(
        query="Get me all traffic cameras from California",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
    )
    engine = CandidateDiscoveryEngine(cfg)
    text = """
    {
      "cameras": [
        {
          "name": "I-5 Camera",
          "latitude": 38.1234,
          "longitude": -121.5678,
          "snapshot_url": "https://public.example/camera/i5.jpg",
          "route": "I-5"
        }
      ]
    }
    """
    rows = engine._extract_from_response(
        "https://public.example/cameras.json",
        {"url": "https://public.example/cameras.json", "title": "camera feed"},
        text,
        "application/json",
    )
    assert len(rows) == 1
    assert rows[0].stream_url == "https://public.example/camera/i5.jpg"
    assert rows[0].lat == 38.1234
    assert rows[0].lon == -121.5678
    assert rows[0].source_metadata["media_type"] == "image_snapshot"


def test_html_extracts_javascript_config_hls_and_coordinates(tmp_path):
    cfg = RunConfig(
        query="Get me all traffic cameras from California",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
    )
    engine = CandidateDiscoveryEngine(cfg)
    html = """
    <html><script>
    window.cameraData = {"cameras":[{"name":"Downtown","lat":37.1234,"lng":-122.1234,"hls_url":"/live/downtown.m3u8"}]};
    </script></html>
    """
    rows = engine._extract_from_response(
        "https://public.example/map.html",
        {"url": "https://public.example/map.html", "title": "camera map"},
        html,
        "text/html",
    )
    assert len(rows) == 1
    assert rows[0].stream_url == "https://public.example/live/downtown.m3u8"
    assert rows[0].lat == 37.1234
    assert rows[0].lon == -122.1234
    assert rows[0].source_metadata["media_type"] == "hls"


def test_geojson_feature_extracts_camera_snapshot(tmp_path):
    cfg = RunConfig(
        query="Get me all cameras from Example Region",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
    )
    engine = CandidateDiscoveryEngine(cfg)
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-118.25, 34.05]},
                "properties": {"name": "Harbor Camera", "image_url": "https://public.example/harbor.jpg"},
            }
        ],
    }
    rows = engine._extract_from_json_data(data, "https://public.example/layer.json", {"url": "https://public.example/layer.json"}, "json_endpoint")
    assert len(rows) == 1
    assert rows[0].title == "Harbor Camera"
    assert rows[0].lat == 34.05
    assert rows[0].lon == -118.25
    assert rows[0].stream_url == "https://public.example/harbor.jpg"
