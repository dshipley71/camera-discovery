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


def test_geocoder_referee_failure_preserves_deterministic_scores(tmp_path):
    from camera_discovery.core.models import GeocoderCandidate, TargetIntent
    from camera_discovery.services.target_resolver import TargetResolver

    class FailingReferee:
        model = "failing-referee"

        def chat(self, messages, *, temperature=0.0):
            raise RuntimeError("429 Too Many Requests")

    cfg = RunConfig(
        query="Get me all traffic cameras from California",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
    )
    resolver = TargetResolver(cfg, geocoder_referee_client=FailingReferee())
    candidate = GeocoderCandidate(
        query="California",
        display_name="California, United States",
        result_type="administrative",
        bbox={"min_lat": 32.0, "max_lat": 42.0, "min_lon": -125.0, "max_lon": -114.0},
        score=42.0,
        deterministic_score=42.0,
    )
    target_logs = tmp_path / "logs" / "targets" / "california"
    target_logs.mkdir(parents=True)

    resolver._apply_llm_geocoder_referee(
        [candidate],
        TargetIntent(raw_query=cfg.query, canonical_target="California", place_name="California"),
        target_logs,
    )

    assert candidate.score == 42.0
    assert candidate.deterministic_score == 42.0
    assert any("deterministic geocoder score preserved" in warning for warning in candidate.warnings)
    error_path = target_logs / "geocoder_referee_llm_error.json"
    assert error_path.exists()
    error_text = error_path.read_text(encoding="utf-8")
    assert "RuntimeError" in error_text
    assert "deterministic_geocoder_scores_preserved" in error_text


def test_nominatim_bbox_order_is_normalized():
    from camera_discovery.services.target_resolver import _bbox_from_nominatim

    raw = ["32.0", "42.0", "-125.0", "-114.0"]

    assert _bbox_from_nominatim(raw) == {
        "min_lat": 32.0,
        "max_lat": 42.0,
        "min_lon": -125.0,
        "max_lon": -114.0,
    }


def test_known_nominatim_bbox_wins_over_llm_hint(monkeypatch, tmp_path):
    from camera_discovery.core.models import GeocoderCandidate, RuntimeProfile, TargetIntent, TrustPolicy

    nominatim_bbox = {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -125.0, "max_lon": -114.0}
    llm_bbox = {"min_lat": 34.0, "max_lat": 35.0, "min_lon": -119.0, "max_lon": -118.0}
    cfg = RunConfig(
        query="Get me all traffic cameras from California",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
    )
    resolver = TargetResolver(cfg)
    intent = TargetIntent(
        raw_query=cfg.query,
        canonical_target="California",
        place_name="California",
        scope_type="state",
        admin_region="California",
        country="United States",
        camera_type_intent="traffic",
        llm_bbox=llm_bbox,
    )
    candidate = GeocoderCandidate(
        query="California",
        display_name="California, United States",
        result_type="administrative",
        bbox=nominatim_bbox,
        raw={"class": "boundary", "type": "administrative"},
    )
    monkeypatch.setattr(resolver, "_geocode_all", lambda queries: [candidate])
    monkeypatch.setattr(resolver, "_apply_llm_geocoder_referee", lambda candidates, intent, target_logs: None)

    ctx = resolver._resolve_intent(intent, 0)

    assert ctx.bbox == nominatim_bbox
    assert ctx.bbox != llm_bbox
    assert ctx.nominatim_bbox == nominatim_bbox
    assert ctx.effective_bbox == nominatim_bbox
    assert ctx.bbox_verified is True
    assert ctx.geometry_source == "nominatim_bbox"
    assert ctx.geometry_status == "verified"
    assert ctx.trust_policy == TrustPolicy.TRUSTED_ALLOWED
    assert not any("LLM geometry" in warning for warning in ctx.warnings)


def test_state_scope_bbox_is_not_replaced_or_padded(monkeypatch, tmp_path):
    from camera_discovery.core.models import GeocoderCandidate, RuntimeProfile, TargetIntent

    state_bbox = {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -125.0, "max_lon": -114.0}
    cfg = RunConfig(
        query="Get me all traffic cameras from California",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
    )
    resolver = TargetResolver(cfg)
    intent = TargetIntent(
        raw_query=cfg.query,
        canonical_target="California",
        place_name="California",
        scope_type="state",
        admin_region="California",
        country="United States",
        camera_type_intent="traffic",
    )
    candidate = GeocoderCandidate(
        query="California",
        display_name="California, United States",
        result_type="administrative",
        bbox=state_bbox,
        raw={"class": "boundary", "type": "administrative"},
    )
    monkeypatch.setattr(resolver, "_geocode_all", lambda queries: [candidate])
    monkeypatch.setattr(resolver, "_apply_llm_geocoder_referee", lambda candidates, intent, target_logs: None)

    ctx = resolver._resolve_intent(intent, 0)

    assert ctx.bbox == state_bbox
    assert ctx.effective_bbox == state_bbox
    assert ctx.bbox_padding_applied is False
    assert ctx.geometry_source == "nominatim_bbox"


def test_llm_bbox_without_known_geocoder_bbox_is_unverified(monkeypatch, tmp_path):
    from camera_discovery.core.models import RuntimeProfile, TargetIntent, TrustPolicy

    llm_bbox = {"min_lat": 34.0, "max_lat": 35.0, "min_lon": -119.0, "max_lon": -118.0}
    cfg = RunConfig(
        query="Get me all cameras from Example Place",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
    )
    resolver = TargetResolver(cfg)
    intent = TargetIntent(
        raw_query=cfg.query,
        canonical_target="Example Place",
        place_name="Example Place",
        scope_type="place",
        llm_bbox=llm_bbox,
    )
    monkeypatch.setattr(resolver, "_geocode_all", lambda queries: [])
    monkeypatch.setattr(resolver, "_apply_llm_geocoder_referee", lambda candidates, intent, target_logs: None)

    ctx = resolver._resolve_intent(intent, 0)

    assert ctx.bbox == llm_bbox
    assert ctx.nominatim_bbox is None
    assert ctx.bbox_verified is False
    assert ctx.geometry_source == "llm_hint"
    assert ctx.geometry_status == "unverified_review_only"
    assert ctx.trust_policy == TrustPolicy.STOP


def test_small_precise_nominatim_bbox_is_padded_and_diagnosed(monkeypatch, tmp_path):
    from camera_discovery.core.models import GeocoderCandidate, RuntimeProfile, TargetIntent
    from camera_discovery.services.target_resolver import _bbox_center, _bbox_dimensions_miles

    tiny_bbox = {"min_lat": 38.0000, "max_lat": 38.0001, "min_lon": -77.0000, "max_lon": -76.9999}
    cfg = RunConfig(
        query="Get public cameras near Example Monument",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
    )
    resolver = TargetResolver(cfg)
    intent = TargetIntent(
        raw_query=cfg.query,
        canonical_target="Example Monument",
        place_name="Example Monument",
        scope_type="place",
        camera_type_intent="public_live",
    )
    candidate = GeocoderCandidate(
        query="Example Monument",
        display_name="Example Monument, Example City, United States",
        result_type="monument",
        bbox=tiny_bbox,
        raw={"class": "historic", "type": "monument"},
    )
    monkeypatch.setattr(resolver, "_geocode_all", lambda queries: [candidate])
    monkeypatch.setattr(resolver, "_apply_llm_geocoder_referee", lambda candidates, intent, target_logs: None)

    ctx = resolver._resolve_intent(intent, 0)
    width_miles, height_miles = _bbox_dimensions_miles(ctx.bbox)
    original_center = _bbox_center(tiny_bbox)
    padded_center = _bbox_center(ctx.bbox)

    assert ctx.nominatim_bbox == tiny_bbox
    assert ctx.bbox != tiny_bbox
    assert ctx.effective_bbox == ctx.bbox
    assert width_miles >= 0.99
    assert height_miles >= 0.99
    assert abs(original_center[0] - padded_center[0]) < 0.000001
    assert abs(original_center[1] - padded_center[1]) < 0.000001
    assert ctx.bbox_padding_applied is True
    assert ctx.bbox_padding_reason == "known_geocoder_bbox_below_minimum_precise_target_extent"
    assert ctx.bbox_min_side_miles == 1.0
    assert ctx.geometry_source == "geocoder_padded"
    assert ctx.bbox_verified is True

    target_resolution = tmp_path / "logs" / "target_resolution.json"
    assert target_resolution.exists()
    text = target_resolution.read_text(encoding="utf-8")
    assert "nominatim_bbox" in text
    assert "effective_bbox" in text
    assert "geocoder_padded" in text


def test_nominatim_polygon_is_primary_geometry_with_bbox_fallback(monkeypatch, tmp_path):
    from camera_discovery.core.models import GeocoderCandidate, RuntimeProfile, TargetIntent

    bbox = {"min_lat": 0.0, "max_lat": 2.0, "min_lon": 0.0, "max_lon": 2.0}
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]
        ]],
    }
    cfg = RunConfig(query="Get cameras from Example State", output_dir=tmp_path, profile=RuntimeProfile.BALANCED)
    resolver = TargetResolver(cfg)
    intent = TargetIntent(raw_query=cfg.query, canonical_target="Example State", place_name="Example State", scope_type="state")
    candidate = GeocoderCandidate(
        query="Example State",
        display_name="Example State, United States",
        result_type="administrative",
        bbox=bbox,
        polygon=polygon,
        raw={"class": "boundary", "type": "administrative"},
    )
    monkeypatch.setattr(resolver, "_geocode_all", lambda queries: [candidate])
    monkeypatch.setattr(resolver, "_apply_llm_geocoder_referee", lambda candidates, intent, target_logs: None)

    ctx = resolver._resolve_intent(intent, 0)

    assert ctx.target_geometry_geojson == polygon
    assert ctx.primary_geometry_geojson == polygon
    assert ctx.primary_geometry_source == "nominatim_polygon"
    assert ctx.geometry_source == "nominatim_polygon"
    assert ctx.fallback_geometry_bbox == bbox
    assert ctx.fallback_geometry_source == "nominatim_bbox"
    assert ctx.effective_bbox == bbox
    assert ctx.bbox_verified is True


def test_point_geocoder_without_bbox_uses_unverified_last_fallback_geometry(monkeypatch, tmp_path):
    from camera_discovery.core.models import GeocoderCandidate, RuntimeProfile, TargetIntent, TrustPolicy

    cfg = RunConfig(query="Get cameras near Example Building", output_dir=tmp_path, profile=RuntimeProfile.FAST)
    resolver = TargetResolver(cfg)
    intent = TargetIntent(raw_query=cfg.query, canonical_target="Example Building", place_name="Example Building", scope_type="place")
    candidate = GeocoderCandidate(
        query="Example Building",
        display_name="Example Building, Example City",
        result_type="building",
        lat=38.0,
        lon=-77.0,
        raw={"class": "building", "type": "yes"},
    )
    monkeypatch.setattr(resolver, "_geocode_all", lambda queries: [candidate])
    monkeypatch.setattr(resolver, "_apply_llm_geocoder_referee", lambda candidates, intent, target_logs: None)

    ctx = resolver._resolve_intent(intent, 0)

    assert ctx.last_fallback_geometry_bbox is not None
    assert ctx.last_fallback_geometry_source == "generic_point_bbox"
    assert ctx.geometry_source == "generic_point_bbox"
    assert ctx.bbox_verified is False
    assert ctx.trust_policy == TrustPolicy.REVIEW_ONLY
