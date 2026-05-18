from __future__ import annotations

from camera_discovery.core.models import CameraCandidate, RunConfig, TargetContext, TargetIntent, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.utils.geojson_viewer import write_embedded_camera_map


def _cfg(tmp_path):
    return RunConfig(query="Get me all traffic cameras from Example State", output_dir=tmp_path, llm_provider="ollama", llm_model="gemma4:31b-cloud")


def test_traffic_intent_generates_transportation_blind_queries(tmp_path):
    target = TargetContext(
        user_query="Get me all traffic cameras from Example State",
        intent=TargetIntent(raw_query="Get me all traffic cameras from Example State", canonical_target="Example State", camera_type_intent="traffic"),
        canonical_target="Example State",
    )
    queries = CandidateDiscoveryEngine(_cfg(tmp_path))._search_queries(target)
    joined = "\n".join(queries).casefold()
    assert "department of transportation" in joined or "transportation cameras" in joined
    assert "road conditions" in joined
    assert "traffic camera map" in joined


def test_repeated_asset_hosts_promote_parent_discovery_rows(tmp_path):
    target = TargetContext(
        user_query="Get me all traffic cameras from Example State",
        intent=TargetIntent(raw_query="Get me all traffic cameras from Example State", canonical_target="Example State", camera_type_intent="traffic"),
        target_id="example_state",
        canonical_target="Example State",
    )
    candidates = [
        CameraCandidate(stream_url=f"https://assets.example.org/data/cctv/image/cam{i}.jpg", source_metadata={"media_type": "image_snapshot"})
        for i in range(4)
    ]
    rows = CandidateDiscoveryEngine(_cfg(tmp_path))._promote_repeated_asset_hosts(candidates, target)
    assert rows
    assert any(row["source_provider"] == "promoted_asset_host" for row in rows)
    assert any(row["url"].startswith("https://assets.example.org/") for row in rows)


def test_map_uses_refreshing_image_for_snapshot_candidates(tmp_path):
    geojson = tmp_path / "untrusted_camera_candidates.geojson"
    geojson.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-100,40]},"properties":{"stream_url":"https://public.example/camera.jpg","media_type":"image_snapshot","camera_type":"traffic","camera_id":"cam-1"}}]}',
        encoding="utf-8",
    )
    html = write_embedded_camera_map(tmp_path, geojson, output_name="map.html").read_text(encoding="utf-8")
    assert "View refreshing image" in html
    assert "openSnapshot" in html
    assert "Camera ID" in html
    assert "Camera type" in html


def test_effective_candidate_geocode_limit_expands_for_state_scale(tmp_path):
    target = TargetContext(
        user_query="Get me all traffic cameras from Example State",
        intent=TargetIntent(raw_query="Get me all traffic cameras from Example State", canonical_target="Example State", camera_type_intent="traffic"),
        canonical_target="Example State",
        scope_type="state",
        trust_policy=TrustPolicy.REVIEW_ONLY,
    )
    candidates = [CameraCandidate(stream_url=f"https://public.example/{i}.jpg", title=f"I-5 at Example Road {i}") for i in range(80)]
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    assert engine._effective_candidate_geocode_limit(target, candidates) >= 80
