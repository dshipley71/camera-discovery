from pathlib import Path

from camera_discovery.core.models import CameraCandidate, CandidateSet, RunConfig, TargetContext, TargetIntent
from camera_discovery.services.target_resolver import TargetResolver


def test_query_clause_can_contain_multiple_locations(tmp_path):
    cfg = RunConfig(
        query="Get me all cameras from London, England and New York, New York",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
    )
    resolver = TargetResolver(cfg)
    phrases = resolver._extract_target_phrases(cfg.query)
    assert phrases == ["London, England", "New York, New York"]


def test_run_state_model_supports_multiple_targets():
    models = Path("src/camera_discovery/core/models.py").read_text(encoding="utf-8")
    assert "targets: list[TargetContext]" in models
    assert "candidate_sets_by_target" in models
    assert "target_id" in models


def test_candidate_set_merge_preserves_target_identity():
    first = CandidateSet(unique=[CameraCandidate(stream_url="https://example.invalid/a.m3u8", target_id="london")])
    second = CandidateSet(unique=[CameraCandidate(stream_url="https://example.invalid/a.m3u8", target_id="new_york")])
    merged = CandidateSet.merge([first, second])
    assert len(merged.unique) == 2
    assert {c.target_id for c in merged.unique} == {"london", "new_york"}




def test_candidate_set_merge_keeps_first_duplicate_for_same_target():
    first_candidate = CameraCandidate(
        stream_url="https://example.invalid/live.m3u8#first",
        target_id="california",
        title="first",
        lat=35.0,
        lon=-120.0,
        validation_status="active",
        source_metadata={"rank": "first"},
    )
    duplicate_candidate = CameraCandidate(
        stream_url="https://example.invalid/live.m3u8#duplicate",
        target_id="california",
        title="duplicate",
        lat=36.0,
        lon=-121.0,
        validation_status="duplicate-active",
        source_metadata={"rank": "duplicate"},
    )

    merged = CandidateSet.merge([CandidateSet(unique=[first_candidate]), CandidateSet(unique=[duplicate_candidate])])

    assert merged.unique == [first_candidate]
    assert merged.unique[0].title == "first"
    assert merged.unique[0].lat == 35.0
    assert merged.unique[0].source_metadata == {"rank": "first"}


def test_candidate_set_merge_order_is_deterministic():
    first = CameraCandidate(stream_url="https://example.invalid/a.m3u8", target_id="target", title="a")
    second = CameraCandidate(stream_url="https://example.invalid/b.m3u8", target_id="target", title="b")
    duplicate_first = CameraCandidate(stream_url="https://example.invalid/a.m3u8", target_id="target", title="duplicate")

    merged = CandidateSet.merge([CandidateSet(unique=[first, second]), CandidateSet(unique=[duplicate_first])])

    assert [candidate.title for candidate in merged.unique] == ["a", "b"]


def test_candidate_set_merge_does_not_merge_later_enrichment_fields():
    base = CameraCandidate(
        stream_url="https://example.invalid/c.m3u8",
        target_id="target",
        title="base",
        location_text="Base Location",
        reasons=["base_reason"],
        source_metadata={"source": "base"},
    )
    enriched_duplicate = CameraCandidate(
        stream_url="https://example.invalid/c.m3u8",
        target_id="target",
        title="enriched",
        lat=34.0,
        lon=-118.0,
        location_text="Enriched Location",
        reasons=["enriched_reason"],
        source_metadata={"source": "enriched"},
    )

    merged = CandidateSet.merge([CandidateSet(unique=[base]), CandidateSet(unique=[enriched_duplicate])])

    assert merged.unique == [base]
    assert merged.coordinate_bearing == []
    assert merged.unique[0].location_text == "Base Location"
    assert merged.unique[0].reasons == ["base_reason"]
    assert merged.unique[0].source_metadata == {"source": "base"}

def test_target_context_has_stable_target_identity():
    ctx = TargetContext(
        user_query="Get cameras from Greenville, Texas",
        intent=TargetIntent(raw_query="Get cameras from Greenville, Texas", canonical_target="Greenville, Texas"),
        target_id="greenville_texas",
        target_index=0,
        target_label="Greenville, Texas",
    )
    assert ctx.target_id == "greenville_texas"
    assert ctx.target_label == "Greenville, Texas"
