from camera_discovery.core.models import (
    CameraCandidate,
    CandidateSet,
    RunConfig,
    RuntimeProfile,
    TargetContext,
    TargetIntent,
    TrustPolicy,
)
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline


def test_untrusted_geojson_includes_coordinate_bearing_non_trusted_candidates(tmp_path):
    cfg = RunConfig(
        query="Get cameras from Greenville, Texas",
        output_dir=tmp_path,
        profile=RuntimeProfile.FAST,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
    )
    target = TargetContext(
        user_query=cfg.query,
        intent=TargetIntent(raw_query=cfg.query, canonical_target="Greenville, Texas"),
        target_id="greenville_texas",
        target_label="Greenville, Texas",
        trust_policy=TrustPolicy.REVIEW_ONLY,
        bbox_verified=False,
    )
    review_candidate = CameraCandidate(
        stream_url="https://public.example/live/review.m3u8",
        lat=33.1,
        lon=-96.1,
        scope_status="review",
        trust_level="untrusted",
        target_id=target.target_id,
        target_label=target.target_label,
    )
    rejected_candidate = CameraCandidate(
        stream_url="https://public.example/live/rejected.m3u8",
        lat=34.1,
        lon=-97.1,
        scope_status="out_of_scope",
        trust_level="rejected",
        target_id=target.target_id,
        target_label=target.target_label,
    )
    candidates = CandidateSet(unique=[review_candidate, rejected_candidate], review=[review_candidate], rejected=[rejected_candidate])
    _, outputs = ReviewAndValidationPipeline(cfg).run([target], candidates)
    assert outputs.untrusted_geojson_created is True
    assert outputs.coordinate_bearing_candidates == 2
    assert outputs.untrusted_geojson_features_written == 2
    assert outputs.coordinate_bearing_without_geojson == 0
    geojson = (tmp_path / "untrusted_camera_candidates.geojson").read_text(encoding="utf-8")
    assert "review.m3u8" in geojson
    assert "rejected.m3u8" in geojson
    assert "untrusted_reason" in geojson
