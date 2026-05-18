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
