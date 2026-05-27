from __future__ import annotations

import csv

from camera_discovery.core.models import (
    CameraCandidate,
    CandidateSet,
    RunConfig,
    RuntimeProfile,
    TargetContext,
    TargetIntent,
    TrustPolicy,
)
from camera_discovery.discovery.candidate_priority import (
    candidate_priority_label,
    prioritize_candidate_set,
    prioritize_candidates,
    priority_bucket_counts,
)
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline


def _target() -> TargetContext:
    return TargetContext(
        user_query="California traffic cameras",
        intent=TargetIntent(raw_query="California traffic cameras", canonical_target="California"),
        target_id="california",
        target_label="California",
        bbox_verified=True,
        bbox={"min_lat": 32.0, "max_lat": 42.5, "min_lon": -125.0, "max_lon": -114.0},
        trust_policy=TrustPolicy.TRUSTED_ALLOWED,
    )


def _hls(url: str, *, scope: str = "unknown", lat: float | None = None, lon: float | None = None) -> CameraCandidate:
    return CameraCandidate(
        stream_url=url,
        source_url="https://public.example/source",
        discovery_method="harvest_handoff",
        lat=lat,
        lon=lon,
        scope_status=scope,  # type: ignore[arg-type]
        target_id="california",
        target_label="California",
        source_metadata={"media_type": "hls", "harvest_input": True},
    )


def test_priority_ordering_ranks_located_in_scope_above_unlocated() -> None:
    unlocated = _hls("https://public.example/unlocated.m3u8")
    located = _hls("https://public.example/located.m3u8", scope="in_scope", lat=38.0, lon=-121.0)

    ordered = prioritize_candidates([unlocated, located])

    assert ordered == [located, unlocated]
    assert candidate_priority_label(located) == "located_in_scope_direct_media"
    assert candidate_priority_label(unlocated) == "unlocated_direct_media"


def test_out_of_scope_coordinates_do_not_outrank_in_scope_candidates() -> None:
    out_of_scope = _hls("https://public.example/out.m3u8", scope="out_of_scope", lat=45.0, lon=-100.0)
    in_scope = _hls("https://public.example/in.m3u8", scope="in_scope", lat=38.0, lon=-121.0)

    ordered = prioritize_candidates([out_of_scope, in_scope])

    assert ordered == [in_scope, out_of_scope]
    assert candidate_priority_label(out_of_scope) == "located_out_of_scope"


def test_candidate_set_priority_preserves_candidates_but_orders_review_lists() -> None:
    unlocated = _hls("https://public.example/unlocated.m3u8")
    located = _hls("https://public.example/located.m3u8", scope="in_scope", lat=38.0, lon=-121.0)
    candidate_set = CandidateSet(unique=[unlocated, located], review=[unlocated, located], in_scope=[located])

    prioritized = prioritize_candidate_set(candidate_set)

    assert prioritized.unique == [located, unlocated]
    assert prioritized.review == [located, unlocated]
    assert priority_bucket_counts(prioritized.unique) == {
        "located_in_scope_direct_media": 1,
        "unlocated_direct_media": 1,
    }


def test_validation_selects_located_in_scope_candidates_first(tmp_path, monkeypatch) -> None:
    cfg = RunConfig(query="California traffic cameras", output_dir=tmp_path, profile=RuntimeProfile.BALANCED)
    target = _target()
    unlocated = _hls("https://public.example/unlocated.m3u8")
    located = _hls("https://public.example/located.m3u8", scope="in_scope", lat=38.0, lon=-121.0)
    order: list[str] = []

    def fake_validate(self, candidate):  # noqa: ANN001
        order.append(candidate.stream_url)
        return "active_live_unknown"

    monkeypatch.setattr(ReviewAndValidationPipeline, "_validate_candidate", fake_validate)

    ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[unlocated, located], review=[unlocated, located], in_scope=[located]))

    assert order[0] == located.stream_url
    assert located.trust_level == "trusted"
    assert unlocated.trust_level == "untrusted"


def test_review_table_orders_located_in_scope_before_unlocated(tmp_path) -> None:
    cfg = RunConfig(query="California traffic cameras", output_dir=tmp_path, profile=RuntimeProfile.FAST)
    target = _target()
    unlocated = _hls("https://public.example/unlocated.m3u8")
    located = _hls("https://public.example/located.m3u8", scope="in_scope", lat=38.0, lon=-121.0)

    ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[unlocated, located], review=[unlocated, located], in_scope=[located]))

    rows = list(csv.DictReader((tmp_path / "camera_candidates_table.csv").open(encoding="utf-8", newline="")))
    assert [row["stream_url"] for row in rows] == [located.stream_url, unlocated.stream_url]
    assert rows[0]["candidate_priority_bucket"] == "located_in_scope_direct_media"


def test_coordinates_alone_do_not_make_candidate_trusted_when_validation_disabled(tmp_path) -> None:
    cfg = RunConfig(query="California traffic cameras", output_dir=tmp_path, profile=RuntimeProfile.FAST)
    target = _target()
    located = _hls("https://public.example/located.m3u8", scope="in_scope", lat=38.0, lon=-121.0)

    ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[located], review=[located], in_scope=[located]))

    assert located.validation_status == "not_validated"
    assert located.trust_level == "untrusted"
    assert not (tmp_path / "camera.geojson").exists()
