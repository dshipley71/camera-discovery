from __future__ import annotations

import httpx

from camera_discovery.core.models import CameraCandidate, CandidateSet, RunConfig, RuntimeProfile, TargetContext, TargetIntent, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline


class _FakeImageClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, headers=None):
        self.requests.append((url, headers or {}))
        if not self.responses:
            raise httpx.ConnectError("no fake response remaining")
        return self.responses.pop(0)


def _png_response(content: bytes, *, headers: dict[str, str] | None = None) -> httpx.Response:
    merged = {"content-type": "image/png"}
    if headers:
        merged.update(headers)
    return httpx.Response(200, headers=merged, content=content)


def test_services_thumb_webp_is_not_regex_image_snapshot_candidate(tmp_path):
    cfg = RunConfig(query="Get cameras from California", output_dir=tmp_path)
    engine = CandidateDiscoveryEngine(cfg)
    text = "https://pub-bc6ed29fe6da455fac3e4a96cbedb174.r2.dev/services/thumb/amLbwgFQcd1722329427.webp"

    rows = engine._extract_from_text("https://example.org/page", {"url": "https://example.org/page"}, text)

    assert rows == []


def test_thumbnail_json_field_is_metadata_not_stream_candidate(tmp_path):
    cfg = RunConfig(query="Get cameras from California", output_dir=tmp_path)
    engine = CandidateDiscoveryEngine(cfg)
    data = {
        "cameras": [
            {
                "name": "Retail card, not a camera feed",
                "thumbnail_url": "https://cdn.example/services/thumb/store.webp",
            }
        ]
    }

    rows = engine._extract_from_json_data(data, "https://example.org/cameras.json", {"url": "https://example.org/cameras.json"}, "json_endpoint")

    assert rows == []


def test_hls_record_keeps_thumbnail_metadata_without_using_it_as_stream(tmp_path):
    cfg = RunConfig(query="Get cameras from California", output_dir=tmp_path)
    engine = CandidateDiscoveryEngine(cfg)
    data = {
        "cameras": [
            {
                "name": "I-5 at Example Road",
                "hls_url": "https://media.example/live/i5_example.stream/playlist.m3u8",
                "thumbnail_url": "https://cdn.example/services/thumb/i5_example.webp",
            }
        ]
    }

    rows = engine._extract_from_json_data(data, "https://example.org/cameras.json", {"url": "https://example.org/cameras.json"}, "json_endpoint")

    assert len(rows) == 1
    assert rows[0].stream_url.endswith("playlist.m3u8")
    assert rows[0].source_metadata["thumbnail_url"].endswith("i5_example.webp")
    assert rows[0].source_metadata["media_type"] == "hls"


def test_image_snapshot_validation_detects_refreshing_image(tmp_path, monkeypatch):
    cfg = RunConfig(
        query="Get cameras from Example",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
        image_snapshot_refresh_delay_seconds=0.0,
    )
    pipeline = ReviewAndValidationPipeline(cfg)
    fake_client = _FakeImageClient([
        _png_response(b"\x89PNG\r\n\x1a\nfirst-frame"),
        _png_response(b"\x89PNG\r\n\x1a\nsecond-frame"),
    ])
    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.httpx.Client", lambda *args, **kwargs: fake_client)

    status = pipeline._validate_image_snapshot("https://public.example/camera/snapshot.jpg")

    assert status == "active_image_snapshot_refreshing"
    assert len(fake_client.requests) == 2
    assert all("_camera_discovery_refresh=" in request[0] for request in fake_client.requests)


def test_image_snapshot_validation_rejects_static_thumbnail_without_fetch(tmp_path, monkeypatch):
    cfg = RunConfig(query="Get cameras from Example", output_dir=tmp_path, profile=RuntimeProfile.BALANCED)
    pipeline = ReviewAndValidationPipeline(cfg)

    def fail_client(*args, **kwargs):
        raise AssertionError("thumbnail assets should be rejected before network validation")

    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.httpx.Client", fail_client)

    status = pipeline._validate_image_snapshot("https://pub.example/services/thumb/not-a-camera.webp")

    assert status == "static_image_asset"


def test_validation_pipeline_rejects_non_refreshing_static_image_candidate(tmp_path, monkeypatch):
    cfg = RunConfig(
        query="Get cameras from Example",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
        image_snapshot_refresh_delay_seconds=0.0,
    )
    target = TargetContext(
        user_query=cfg.query,
        intent=TargetIntent(raw_query=cfg.query, canonical_target="Example"),
        target_id="example",
        target_label="Example",
        bbox_verified=True,
        trust_policy=TrustPolicy.TRUSTED_ALLOWED,
    )
    candidate = CameraCandidate(
        stream_url="https://public.example/camera/snapshot.jpg",
        lat=38.0,
        lon=-121.0,
        scope_status="in_scope",
        source_metadata={"media_type": "image_snapshot"},
        target_id=target.target_id,
    )
    fake_client = _FakeImageClient([
        _png_response(b"\x89PNG\r\n\x1a\nstatic-frame", headers={"cache-control": "public, max-age=31536000, immutable"}),
    ])
    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.httpx.Client", lambda *args, **kwargs: fake_client)

    ReviewAndValidationPipeline(cfg).run([target], CandidateSet(unique=[candidate], in_scope=[candidate], review=[candidate]))

    assert candidate.validation_status == "static_image_asset"
    assert candidate.trust_level == "rejected"
