from __future__ import annotations

import csv

from camera_discovery.core.models import CameraCandidate, CandidateSet, RunConfig, TargetContext, TargetIntent, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline


def _cfg(tmp_path):
    return RunConfig(query="Get me all traffic cameras from California", output_dir=tmp_path, llm_provider="ollama", llm_model="gemma4:31b-cloud")


def test_arcgis_feature_attributes_and_geometry_extract_camera_coordinates(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    data = {
        "features": [
            {
                "attributes": {
                    "name": "I-80 at Example Road",
                    "snapshot_url": "https://public.example/cameras/i80.jpg",
                    "county": "Example County",
                },
                "geometry": {"x": -121.1234, "y": 38.5678},
            }
        ]
    }
    rows = engine._extract_from_json_data(data, "https://public.example/map/layer?f=json", {"url": "https://public.example/map/layer?f=json"}, "json_endpoint")
    assert len(rows) == 1
    assert rows[0].stream_url == "https://public.example/cameras/i80.jpg"
    assert rows[0].lat == 38.5678
    assert rows[0].lon == -121.1234
    assert rows[0].coordinate_source == "source_record"


def test_candidate_coordinate_enrichment_uses_url_query_coordinates(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    target = TargetContext(
        user_query="Get me all traffic cameras from California",
        intent=TargetIntent(raw_query="Get me all traffic cameras from California", canonical_target="California"),
        canonical_target="California",
        bbox_verified=False,
        trust_policy=TrustPolicy.REVIEW_ONLY,
    )
    candidate = CameraCandidate(stream_url="https://public.example/camera.jpg?lat=37.1234&lon=-121.5678")
    engine._enrich_candidate_coordinates([candidate], target)
    assert candidate.lat == 37.1234
    assert candidate.lon == -121.5678
    assert candidate.coordinate_source == "candidate_metadata"


def test_candidate_geocode_query_uses_specific_location_and_target_context(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    target = TargetContext(
        user_query="Get me all traffic cameras from California",
        intent=TargetIntent(raw_query="Get me all traffic cameras from California", canonical_target="California"),
        canonical_target="California",
        admin_region="California",
        country="United States",
        trust_policy=TrustPolicy.REVIEW_ONLY,
    )
    candidate = CameraCandidate(stream_url="https://public.example/camera.jpg", title="I-5 at Example Road")
    query = engine._candidate_geocode_query(candidate, target)
    assert query == "I-5 at Example Road, California, United States"


def test_review_pipeline_writes_table_for_candidates_without_coordinates(tmp_path):
    cfg = _cfg(tmp_path)
    target = TargetContext(
        user_query=cfg.query,
        intent=TargetIntent(raw_query=cfg.query, canonical_target="California"),
        target_id="california",
        canonical_target="California",
        trust_policy=TrustPolicy.REVIEW_ONLY,
    )
    candidate = CameraCandidate(
        stream_url="https://public.example/camera.jpg",
        title="Camera without coordinates",
        target_id="california",
        target_label="California",
        scope_status="unknown",
    )
    validation, outputs = ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[candidate], review=[candidate]))
    table = tmp_path / "camera_candidates_table.csv"
    assert table.exists()
    rows = list(csv.DictReader(table.open(newline="", encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["stream_url"] == "https://public.example/camera.jpg"
    assert outputs.camera_candidates_table_rows == 1
    assert not outputs.untrusted_geojson_created



def test_html_img_extraction_preserves_alt_coordinates_and_filters_assets(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    html = """
    <html><body>
      <img src="/static/og-default.png" alt="site preview">
      <div data-lat="38.1111" data-lon="-121.2222">
        <img src="/cameras/i5-main-st.jpg" alt="I-5 at Main St">
      </div>
    </body></html>
    """
    rows = engine._extract_from_response(
        "https://public.example/cameras.html",
        {"url": "https://public.example/cameras.html", "title": "camera page"},
        html,
        "text/html",
    )
    assert len(rows) == 1
    assert rows[0].stream_url == "https://public.example/cameras/i5-main-st.jpg"
    assert rows[0].title == "I-5 at Main St"
    assert rows[0].lat == 38.1111
    assert rows[0].lon == -121.2222
    assert rows[0].coordinate_source == "html_media_tag_attribute"


def test_image_url_slug_can_provide_specific_geocodable_location_text(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    rows = engine._extract_from_text(
        "https://public.example/page.html",
        {"url": "https://public.example/page.html", "title": "California Live Traffic Cameras"},
        "https://cwwp2.dot.ca.gov/data/d10/cctv/image/100sbsr995thst/100sbsr995thst.jpg",
    )
    assert len(rows) == 1
    assert rows[0].location_text
    assert "SR 99" in rows[0].location_text
    assert "camera_id" in rows[0].source_metadata


def test_generic_page_title_is_not_used_for_candidate_geocoding(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    target = TargetContext(
        user_query="Get me all traffic cameras from California",
        intent=TargetIntent(raw_query="Get me all traffic cameras from California", canonical_target="California"),
        canonical_target="California",
        target_label="California",
        admin_region="California",
        country="United States",
        trust_policy=TrustPolicy.REVIEW_ONLY,
    )
    candidate = CameraCandidate(
        stream_url="https://public.example/og-default.png",
        title="California Live Traffic Cameras — Road Conditions in California",
    )
    assert engine._candidate_geocode_query(candidate, target) is None
