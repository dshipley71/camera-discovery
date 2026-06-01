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


def test_resolve_all_preserves_independent_known_bboxes(monkeypatch, tmp_path):
    from camera_discovery.core.models import GeocoderCandidate, RuntimeProfile, TargetIntent

    cfg = RunConfig(
        query="Get traffic cameras from California and New York State",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
    )
    resolver = TargetResolver(cfg)
    california_intent = TargetIntent(
        raw_query=cfg.query,
        canonical_target="California",
        place_name="California",
        scope_type="state",
        admin_region="California",
        country="United States",
        camera_type_intent="traffic",
    )
    new_york_intent = TargetIntent(
        raw_query=cfg.query,
        canonical_target="New York State",
        place_name="New York State",
        scope_type="state",
        admin_region="New York",
        country="United States",
        camera_type_intent="traffic",
    )
    california_bbox = {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -125.0, "max_lon": -114.0}
    new_york_bbox = {"min_lat": 40.0, "max_lat": 45.0, "min_lon": -80.0, "max_lon": -71.0}

    def fake_geocode_all(queries):
        if any("New York" in query for query in queries):
            return [
                GeocoderCandidate(
                    query="New York State",
                    display_name="New York, United States",
                    result_type="administrative",
                    bbox=new_york_bbox,
                    raw={"class": "boundary", "type": "administrative"},
                )
            ]
        return [
            GeocoderCandidate(
                query="California",
                display_name="California, United States",
                result_type="administrative",
                bbox=california_bbox,
                raw={"class": "boundary", "type": "administrative"},
            )
        ]

    monkeypatch.setattr(resolver, "_build_target_intents", lambda: [california_intent, new_york_intent])
    monkeypatch.setattr(resolver, "_geocode_all", fake_geocode_all)
    monkeypatch.setattr(resolver, "_apply_llm_geocoder_referee", lambda candidates, intent, target_logs: None)

    targets = resolver.resolve_all()

    assert [target.target_index for target in targets] == [0, 1]
    assert [target.target_id for target in targets] == ["california", "new_york_state"]
    assert targets[0].bbox == california_bbox
    assert targets[1].bbox == new_york_bbox
    assert targets[0].nominatim_bbox == california_bbox
    assert targets[1].nominatim_bbox == new_york_bbox
    assert targets[0].bbox is not targets[1].bbox
