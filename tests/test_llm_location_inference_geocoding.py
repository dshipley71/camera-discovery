from __future__ import annotations

import json

from camera_discovery.core.models import CameraCandidate, RunConfig, TargetContext, TargetIntent, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine


class FakeLocationInferenceClient:
    model = "fake-location-inference"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def chat(self, messages, *, temperature: float = 0.0) -> str:
        self.calls.append(messages)
        return json.dumps(self.payload)


def _cfg(tmp_path, **overrides):
    kwargs = {
        "query": "Get me all traffic cameras from California",
        "output_dir": tmp_path,
        "llm_provider": "ollama",
        "llm_model": "gemma4:31b-cloud",
        "enable_candidate_geocoding": True,
        "enable_llm_location_inference": True,
        "llm_location_inference_min_confidence": 0.7,
        "max_candidate_geocodes": 5,
    }
    kwargs.update(overrides)
    return RunConfig(**kwargs)


def _target() -> TargetContext:
    return TargetContext(
        user_query="Get me all traffic cameras from California",
        intent=TargetIntent(raw_query="Get me all traffic cameras from California", canonical_target="California"),
        canonical_target="California",
        target_label="California",
        admin_region="California",
        country="United States",
        scope_type="state",
        bbox={"min_lat": 32.0, "max_lat": 42.1, "min_lon": -125.0, "max_lon": -114.0},
        bbox_verified=True,
        trust_policy=TrustPolicy.REVIEW_ONLY,
    )


def test_llm_url_location_inference_geocodes_brawley_url_inside_scope(tmp_path, monkeypatch):
    client = FakeLocationInferenceClient(
        {
            "has_location_hint": True,
            "location_candidates": [
                {
                    "query": "Brawley, California",
                    "variants": ["Brawley, Imperial County, California", "Brawley CA"],
                    "confidence": 0.86,
                    "evidence": ["Brawley", "dot.ca.gov"],
                    "reason": "Stream URL contains Brawley and host is California DOT media infrastructure.",
                    "precision": "place",
                }
            ],
        }
    )
    engine = CandidateDiscoveryEngine(_cfg(tmp_path), location_inference_client=client)
    candidate = CameraCandidate(
        stream_url="https://wzmedia.dot.ca.gov/D6/180_Brawley.stream/playlist.m3u8",
        source_url="https://public.example/page",
        source_metadata={"source_name": "Caltrans"},
    )

    monkeypatch.setattr(
        engine,
        "_geocode_candidate_location",
        lambda query: (32.9787, -115.5303, "Brawley, Imperial County, California, United States"),
    )

    engine._enrich_candidate_coordinates([candidate], _target())

    assert candidate.lat == 32.9787
    assert candidate.lon == -115.5303
    assert candidate.coordinate_source == "llm_url_location_nominatim"
    assert candidate.geocoded_query == "Brawley, California, United States"
    assert candidate.source_metadata["llm_location_inference"]["query"] == "Brawley, California"
    assert "coordinates_geocoded_from_llm_inferred_location_name" in candidate.reasons


def test_llm_location_inference_rejects_geocode_outside_verified_bbox(tmp_path, monkeypatch):
    client = FakeLocationInferenceClient(
        {
            "has_location_hint": True,
            "location_candidates": [
                {
                    "query": "Brawley, California",
                    "variants": [],
                    "confidence": 0.9,
                    "evidence": ["Brawley"],
                    "reason": "URL token.",
                    "precision": "place",
                }
            ],
        }
    )
    engine = CandidateDiscoveryEngine(_cfg(tmp_path), location_inference_client=client)
    candidate = CameraCandidate(stream_url="https://wzmedia.dot.ca.gov/D6/180_Brawley.stream/playlist.m3u8")
    monkeypatch.setattr(engine, "_geocode_candidate_location", lambda query: (45.0, -90.0, "Brawley, Somewhere Else"))

    engine._enrich_candidate_coordinates([candidate], _target())

    assert not candidate.has_coordinates
    assert candidate.coordinate_source is None


def test_llm_location_inference_does_not_overwrite_existing_coordinates(tmp_path):
    client = FakeLocationInferenceClient(
        {
            "has_location_hint": True,
            "location_candidates": [
                {"query": "Brawley, California", "variants": [], "confidence": 0.9, "evidence": ["Brawley"], "reason": "URL token.", "precision": "place"}
            ],
        }
    )
    engine = CandidateDiscoveryEngine(_cfg(tmp_path), location_inference_client=client)
    candidate = CameraCandidate(
        stream_url="https://wzmedia.dot.ca.gov/D6/180_Brawley.stream/playlist.m3u8",
        lat=33.0,
        lon=-116.0,
        coordinate_source="source_record",
    )

    engine._enrich_candidate_coordinates([candidate], _target())

    assert candidate.lat == 33.0
    assert candidate.lon == -116.0
    assert candidate.coordinate_source == "source_record"
    assert client.calls == []
