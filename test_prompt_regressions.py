from __future__ import annotations

import builtins

import httpx

from camera_discovery.core.models import CameraCandidate, RunConfig
from camera_discovery.services import discovery_engine as discovery_module
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine, _get_with_retry
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline


def _cfg(tmp_path, **overrides):
    kwargs = {
        "query": "Get public cameras from Example City",
        "output_dir": tmp_path,
        "llm_provider": "ollama",
        "llm_model": "gemma4:31b-cloud",
        "max_hls_candidates": 2,
        "max_image_snapshot_candidates": 1,
        "max_total_candidates": 3,
    }
    kwargs.update(overrides)
    return RunConfig(**kwargs)


def test_hls_budget_not_blocked_by_snapshot_cap(tmp_path, monkeypatch):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    rows = [
        {"url": "https://public.example/snap-1"},
        {"url": "https://public.example/snap-2"},
        {"url": "https://public.example/hls-1"},
        {"url": "https://public.example/hls-2"},
    ]

    def fake_extract(row, client=None):
        if "hls" in row["url"]:
            return [CameraCandidate(stream_url=row["url"] + ".m3u8", source_metadata={"media_type": "hls"})]
        return [CameraCandidate(stream_url=row["url"] + ".jpg", source_metadata={"media_type": "image_snapshot"})]

    monkeypatch.setattr(engine, "_extract_from_source_row", fake_extract)
    client = engine._make_client()
    try:
        candidates = engine._collect_candidates_from_rows(rows, client)
    finally:
        client.close()

    assert sum(c.source_metadata.get("media_type") == "image_snapshot" for c in candidates) == 1
    assert sum(c.source_metadata.get("media_type") == "hls" for c in candidates) == 2


def test_hls_displaces_snapshot_in_dedupe(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    snapshot = CameraCandidate(stream_url="https://public.example/camera.m3u8", source_metadata={"media_type": "image_snapshot"})
    hls = CameraCandidate(stream_url="https://public.example/camera.m3u8", source_metadata={"media_type": "hls"})
    assert engine._dedupe([snapshot, hls]) == [hls]


def test_playwright_skipped_when_not_installed(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("playwright unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    assert engine._extract_from_dynamic_page("https://public.example/cameras", {"url": "https://public.example/cameras"}) == []


def test_dynamic_source_type_routes_to_playwright(tmp_path, monkeypatch):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    called = {"dynamic": 0, "page": 0}

    def dynamic(url, row):
        called["dynamic"] += 1
        return []

    def page(url, row, client=None):
        called["page"] += 1
        return []

    monkeypatch.setattr(engine, "_extract_from_dynamic_page", dynamic)
    monkeypatch.setattr(engine, "_extract_from_page", page)
    engine._extract_from_source_row({"url": "https://public.example/cameras", "source_kind": "dynamic"})
    assert called == {"dynamic": 1, "page": 0}


def test_get_with_retry_retries_on_500(monkeypatch):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500 if calls["count"] == 1 else 200, request=request, text="ok")

    monkeypatch.setattr(discovery_module.time, "sleep", lambda _: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        response = _get_with_retry(client, "https://public.example/feed")
    finally:
        client.close()
    assert response.status_code == 200
    assert calls["count"] == 2


def test_proximity_coord_assigned_per_candidate(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    text = (
        "camera one 38.1111, -121.2222 https://public.example/one.m3u8 "
        + (" filler" * 120)
        + " camera two 39.3333, -122.4444 https://public.example/two.m3u8"
    )
    rows = engine._extract_from_text("https://public.example/page", {"url": "https://public.example/page"}, text)
    by_url = {row.stream_url: row for row in rows}
    assert by_url["https://public.example/one.m3u8"].lat == 38.1111
    assert by_url["https://public.example/one.m3u8"].lon == -121.2222
    assert by_url["https://public.example/two.m3u8"].lat == 39.3333
    assert by_url["https://public.example/two.m3u8"].lon == -122.4444
    assert {row.coordinate_source for row in rows} == {"proximity_text"}


def test_cameras_md_is_table(tmp_path):
    pipeline = ReviewAndValidationPipeline(_cfg(tmp_path))
    rows = [
        CameraCandidate(stream_url="https://public.example/one.m3u8", source_url="https://public.example", title="One", lat=1.0, lon=2.0),
        CameraCandidate(stream_url="https://public.example/two.m3u8", source_url="https://public.example", title="Two", lat=3.0, lon=4.0),
    ]
    pipeline._write_cameras_md(rows)
    text = (tmp_path / "cameras.md").read_text(encoding="utf-8")
    assert "| Name | Location | Latitude | Longitude | Stream URL | Source URL |" in text
