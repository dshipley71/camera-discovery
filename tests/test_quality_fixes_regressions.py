from __future__ import annotations

import json
import warnings
from zipfile import ZipFile

from bs4 import XMLParsedAsHTMLWarning

from camera_discovery.core.models import CameraCandidate, CandidateSet, RunConfig, TargetContext, TargetIntent, TrustPolicy
from camera_discovery.llm.ollama import OllamaClient
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine, _html_soup
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline


class RoutingLocationClient:
    model = "fake-location-routing"

    def __init__(self):
        self.prompts: list[str] = []

    def chat(self, messages, *, temperature: float = 0.0) -> str:
        prompt = messages[-1].content
        self.prompts.append(prompt)
        if "Brawley" in prompt:
            query = "Brawley, California"
            evidence = ["Brawley"]
        else:
            query = "Example Road, California"
            evidence = ["Example"]
        return json.dumps(
            {
                "has_location_hint": True,
                "location_candidates": [
                    {
                        "query": query,
                        "variants": [],
                        "confidence": 0.9,
                        "evidence": evidence,
                        "reason": "evidence token present in URL",
                        "precision": "place",
                    }
                ],
            }
        )


def _cfg(tmp_path, **overrides):
    kwargs = {
        "query": "Get me all traffic cameras from California",
        "output_dir": tmp_path,
        "llm_provider": "ollama",
        "llm_model": "gemma4:31b-cloud",
        "enable_candidate_geocoding": True,
        "enable_llm_location_inference": True,
        "max_llm_location_inferences": 5,
        "llm_location_inference_min_confidence": 0.7,
        "max_candidate_geocodes": 5,
    }
    kwargs.update(overrides)
    return RunConfig(**kwargs)


def _target() -> TargetContext:
    return TargetContext(
        user_query="Get me all traffic cameras from California",
        intent=TargetIntent(raw_query="Get me all traffic cameras from California", canonical_target="California"),
        target_id="california",
        canonical_target="California",
        target_label="California",
        admin_region="California",
        country="United States",
        scope_type="state",
        bbox={"min_lat": 32.0, "max_lat": 42.1, "min_lon": -125.0, "max_lon": -114.0},
        bbox_verified=True,
        trust_policy=TrustPolicy.REVIEW_ONLY,
    )


def test_ollama_cloud_preflight_rejects_missing_api_key_without_network(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    client = OllamaClient("qwen3.5:4b", base_url="https://ollama.com", api_key="")
    result = client.preflight()
    assert result["ok"] is False
    assert result["error_type"] == "missing_api_key"


def test_ollama_api_url_does_not_double_append_api():
    client = OllamaClient("model", base_url="https://ollama.com/api", api_key="token")
    assert client._api_url("/chat") == "https://ollama.com/api/chat"


def test_llm_location_inference_prioritizes_hls_slug_over_image_candidate(tmp_path, monkeypatch):
    client = RoutingLocationClient()
    engine = CandidateDiscoveryEngine(_cfg(tmp_path, max_llm_location_inferences=1), location_inference_client=client)
    image = CameraCandidate(
        stream_url="https://public.example/cameras/example-road.jpg",
        source_metadata={"media_type": "image_snapshot", "source_name": "Example camera page"},
    )
    hls = CameraCandidate(
        stream_url="https://wzmedia.dot.ca.gov/D6/180_Brawley.stream/playlist.m3u8",
        source_metadata={"media_type": "hls", "source_name": "Caltrans"},
    )
    monkeypatch.setattr(engine, "_geocode_candidate_location", lambda query: (32.9787, -115.5303, "Brawley, Imperial County, California, United States"))

    engine._enrich_candidate_coordinates([image, hls], _target())

    assert hls.coordinate_source == "llm_url_location_nominatim"
    assert image.coordinate_source is None
    assert len(client.prompts) == 1
    assert "Brawley" in client.prompts[0]


def test_llm_location_inference_rejects_broad_target_level_geocode(tmp_path, monkeypatch):
    client = RoutingLocationClient()
    engine = CandidateDiscoveryEngine(_cfg(tmp_path), location_inference_client=client)
    candidate = CameraCandidate(
        stream_url="https://wzmedia.dot.ca.gov/D6/California.stream/playlist.m3u8",
        source_metadata={"media_type": "hls"},
    )

    def fake_chat(messages, *, temperature=0.0):
        return json.dumps(
            {
                "has_location_hint": True,
                "location_candidates": [
                    {"query": "California", "variants": ["California, United States"], "confidence": 0.95, "evidence": ["California"], "reason": "target token only", "precision": "state"}
                ],
            }
        )

    client.chat = fake_chat  # type: ignore[method-assign]
    monkeypatch.setattr(engine, "_geocode_candidate_location", lambda query: (36.7783, -119.4179, "California, United States"))

    engine._enrich_candidate_coordinates([candidate], _target())

    assert not candidate.has_coordinates
    log = json.loads((tmp_path / "logs" / "candidate_coordinate_enrichment.json").read_text(encoding="utf-8"))
    assert any(d.get("status") == "rejected_broad_or_target_level_inference" for d in log["diagnostics"])


def test_coordinate_conflict_detected_between_proximity_and_llm_geocode(tmp_path, monkeypatch):
    client = RoutingLocationClient()
    engine = CandidateDiscoveryEngine(_cfg(tmp_path), location_inference_client=client)
    candidate = CameraCandidate(
        stream_url="https://wzmedia.dot.ca.gov/D6/180_Brawley.stream/playlist.m3u8",
        lat=36.735694,
        lon=-119.862069,
        coordinate_source="proximity_text",
        source_metadata={"media_type": "hls"},
    )
    monkeypatch.setattr(engine, "_geocode_candidate_location", lambda query: (32.9787, -115.5303, "Brawley, Imperial County, California, United States"))

    engine._enrich_candidate_coordinates([candidate], _target())

    assert candidate.lat == 36.735694
    assert candidate.lon == -119.862069
    assert candidate.coordinate_source == "proximity_text"
    assert "coordinate_conflict" in candidate.source_metadata
    assert "coordinate_conflict_between_proximity_text_and_llm_geocode" in candidate.reasons


def test_generic_image_assets_are_filtered_from_json_records(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    rows = engine._extract_from_json_data(
        {"features": [{"attributes": {"image": "https://public.example/static/apple-touch-icon.png", "name": "Site icon"}}]},
        "https://public.example/feed.json",
        {"url": "https://public.example/feed.json"},
        "json_endpoint",
    )
    assert rows == []


def test_review_artifact_zip_includes_run_explanation_files(tmp_path):
    cfg = _cfg(tmp_path, enable_llm_location_inference=False)
    target = _target()
    candidate = CameraCandidate(
        stream_url="https://public.example/cameras/i5.m3u8",
        lat=37.0,
        lon=-121.0,
        coordinate_source="source_record",
        target_id="california",
        target_label="California",
        scope_status="review",
        source_metadata={"media_type": "hls"},
    )
    _validation, outputs = ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[candidate], review=[candidate], coordinate_bearing=[candidate]))
    assert outputs.review_artifacts_zip
    with ZipFile(outputs.review_artifacts_zip) as zf:
        names = set(zf.namelist())
    assert "RUN_EXPLANATION.md" in names
    assert "logs/run_explanation.json" in names


def test_xml_parsed_as_html_warning_is_suppressed():
    xmlish = "<?xml version='1.0'?><root><camera href='https://example.com/cam.m3u8'/></root>"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        soup = _html_soup(xmlish)
    assert soup is not None
    assert not any(isinstance(item.message, XMLParsedAsHTMLWarning) for item in caught)


def test_review_artifact_zip_includes_portable_primary_target_geometry(tmp_path):
    target = _target()
    california_polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-124.48, 32.52], [-114.13, 32.52], [-114.13, 42.01], [-124.48, 42.01], [-124.48, 32.52]
        ]],
    }
    nominatim_bbox = {"min_lat": 32.5295236, "max_lat": 42.009499, "min_lon": -124.482003, "max_lon": -114.1307816}
    target.target_geometry_geojson = california_polygon
    target.primary_geometry_geojson = california_polygon
    target.primary_geometry_source = "nominatim_polygon"
    target.geometry_source = "nominatim_polygon"
    target.geometry_status = "verified"
    target.nominatim_bbox = nominatim_bbox
    target.fallback_geometry_bbox = nominatim_bbox
    target.fallback_geometry_source = "nominatim_bbox"
    target.effective_bbox = nominatim_bbox

    cfg = _cfg(tmp_path, enable_llm_location_inference=False)
    candidate = CameraCandidate(
        stream_url="https://public.example/cameras/i5.m3u8",
        lat=37.0,
        lon=-121.0,
        coordinate_source="source_record",
        target_id="california",
        target_label="California",
        scope_status="review",
        source_metadata={"media_type": "hls"},
    )
    _validation, outputs = ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[candidate], review=[candidate], coordinate_bearing=[candidate]))

    target_geometry_path = tmp_path / "target_geometry.geojson"
    assert target_geometry_path.exists()
    target_geometry = json.loads(target_geometry_path.read_text(encoding="utf-8"))
    feature = target_geometry["features"][0]
    assert feature["geometry"] == california_polygon
    assert feature["properties"]["geometry_role"] == "primary"
    assert feature["properties"]["geometry_source"] == "nominatim_polygon"
    assert "nominatim_bbox" not in feature["properties"]
    assert "effective_bbox" not in feature["properties"]
    assert outputs.target_geometry_geojson == str(target_geometry_path)
    assert outputs.target_geometry_features_written == 1
    with ZipFile(outputs.review_artifacts_zip) as zf:
        names = set(zf.namelist())
        assert "target_geometry.geojson" in names
        zipped = json.loads(zf.read("target_geometry.geojson").decode("utf-8"))
    assert zipped["features"][0]["geometry"] == california_polygon


def test_review_artifact_target_geometry_uses_nominatim_bbox_only_when_polygon_missing(tmp_path):
    target = _target()
    nominatim_bbox = {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -124.0, "max_lon": -114.0}
    target.target_geometry_geojson = None
    target.primary_geometry_geojson = None
    target.primary_geometry_source = None
    target.geometry_source = "nominatim_bbox"
    target.geometry_status = "verified"
    target.nominatim_bbox = nominatim_bbox
    target.fallback_geometry_bbox = nominatim_bbox
    target.fallback_geometry_source = "nominatim_bbox"
    target.effective_bbox = nominatim_bbox
    target.bbox = nominatim_bbox

    cfg = _cfg(tmp_path, enable_llm_location_inference=False)
    ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[], review=[], coordinate_bearing=[]))

    target_geometry = json.loads((tmp_path / "target_geometry.geojson").read_text(encoding="utf-8"))
    feature = target_geometry["features"][0]
    assert feature["properties"]["geometry_role"] == "fallback"
    assert feature["properties"]["geometry_source"] == "nominatim_bbox"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["geometry"]["coordinates"][0][0] == [-124.0, 32.0]




def test_target_geometry_artifact_does_not_assume_nominatim_bbox_is_fallback(tmp_path):
    target = _target()
    nominatim_bbox = {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -124.0, "max_lon": -114.0}
    target.primary_geometry_geojson = None
    target.fallback_geometry_bbox = None
    target.fallback_geometry_source = None
    target.last_fallback_geometry_bbox = None
    target.last_fallback_geometry_source = None
    target.geometry_source = "nominatim_bbox"
    target.geometry_status = "verified"
    target.nominatim_bbox = nominatim_bbox
    target.effective_bbox = nominatim_bbox
    target.bbox = nominatim_bbox

    cfg = _cfg(tmp_path, enable_llm_location_inference=False)
    _validation, outputs = ReviewAndValidationPipeline(cfg).run(
        [target], CandidateSet(unique=[], review=[], coordinate_bearing=[])
    )

    assert outputs.target_geometry_geojson is None
    assert outputs.target_geometry_features_written == 0
    assert not (tmp_path / "target_geometry.geojson").exists()
    status = json.loads((tmp_path / "logs" / "target_geometry_geojson_status.json").read_text(encoding="utf-8"))
    assert status["created"] is False
    assert status["skipped_without_explicit_geometry"] == 1
    assert status["strict_artifact_geometry_only"] is True


def test_target_geometry_artifact_requires_explicit_geometry_role(tmp_path):
    target = _target()
    legacy_bbox = {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -124.0, "max_lon": -114.0}
    target.target_geometry_geojson = None
    target.primary_geometry_geojson = None
    target.primary_geometry_source = None
    target.fallback_geometry_bbox = None
    target.fallback_geometry_source = None
    target.last_fallback_geometry_bbox = None
    target.last_fallback_geometry_source = None
    target.geometry_source = "legacy_bbox"
    target.geometry_status = "verified"
    target.nominatim_bbox = None
    target.effective_bbox = legacy_bbox
    target.bbox = legacy_bbox

    cfg = _cfg(tmp_path, enable_llm_location_inference=False)
    _validation, outputs = ReviewAndValidationPipeline(cfg).run(
        [target], CandidateSet(unique=[], review=[], coordinate_bearing=[])
    )

    assert outputs.target_geometry_geojson is None
    assert outputs.target_geometry_features_written == 0
    assert not (tmp_path / "target_geometry.geojson").exists()
    status = json.loads((tmp_path / "logs" / "target_geometry_geojson_status.json").read_text(encoding="utf-8"))
    assert status["created"] is False
    assert status["features"] == 0
    with ZipFile(outputs.review_artifacts_zip) as zf:
        assert "target_geometry.geojson" not in set(zf.namelist())
