from __future__ import annotations

import json
import time

from camera_discovery.core.config import load_run_config
from camera_discovery.core.models import CameraCandidate, DiscoveryMode, RunConfig, TargetContext, TargetIntent
from camera_discovery.services.discovery_engine import BrowserCaptureDecision, CandidateDiscoveryEngine, PageDiscoverySignals


def _target() -> TargetContext:
    return TargetContext(
        user_query="Get cameras from Example City",
        intent=TargetIntent(raw_query="Get cameras from Example City", canonical_target="Example City", camera_type_intent="public"),
        target_id="example_city",
        canonical_target="Example City",
    )


def _engine(tmp_path, **kwargs) -> CandidateDiscoveryEngine:
    cfg = RunConfig(query="Get cameras from Example City", output_dir=tmp_path, **kwargs)
    return CandidateDiscoveryEngine(cfg)


def _signals(url: str = "https://public.example/cameras") -> PageDiscoverySignals:
    return PageDiscoverySignals(
        url=url,
        source_provider="blind",
        source_kind="page",
        dynamic_signals=["multiple_script_tags", "map_library"],
        json_endpoint_hints=["https://public.example/api/cameras.json"],
        camera_text_score=3,
        static_candidate_count=0,
    )


def test_browser_capture_config_env_fields_are_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE", "false")
    monkeypatch.setenv("CAMERA_DISCOVERY_BROWSER_CAPTURE_TIMEOUT_MS", "9000")
    monkeypatch.setenv("CAMERA_DISCOVERY_BROWSER_CAPTURE_MIN_SCORE", "4")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES", "11")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_BLIND", "2")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_DIRECTORY", "5")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_PER_HOST", "1")
    monkeypatch.setenv("CAMERA_DISCOVERY_BROWSER_CAPTURE_SETTLE_MS", "250")
    monkeypatch.setenv("CAMERA_DISCOVERY_BROWSER_CAPTURE_SCROLL", "true")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE", "3")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE", "7")

    cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.enable_browser_capture is False
    assert cfg.browser_capture_timeout_ms == 9000
    assert cfg.browser_capture_min_score == 4
    assert cfg.max_browser_capture_pages == 11
    assert cfg.max_browser_capture_pages_blind == 2
    assert cfg.max_browser_capture_pages_directory == 5
    assert cfg.max_browser_capture_pages_per_host == 1
    assert cfg.browser_capture_settle_ms == 250
    assert cfg.browser_capture_scroll is True
    assert cfg.max_browser_json_endpoints_per_page == 3
    assert cfg.max_browser_network_events_logged_per_page == 7


def test_browser_capture_skipped_when_disabled(tmp_path):
    engine = _engine(tmp_path, enable_browser_capture=False)
    row = {"url": "https://public.example/cameras", "source_provider": "blind", "source_kind": "page"}

    decision = engine._browser_capture_decision(row, [], _signals(), "primary")

    assert decision.selected is False
    assert decision.skip_reason == "browser_capture_disabled"


def test_direct_hls_urls_do_not_route_to_browser_capture(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://public.example/live/cam.m3u8", "source_provider": "direct", "source_kind": "direct_hls"}

    decision = engine._browser_capture_decision(row, [], _signals(row["url"]), "primary")

    assert decision.selected is False
    assert decision.skip_reason == "direct_media_url"


def test_explicit_dynamic_row_routes_to_browser_when_budget_allows(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://public.example/cameras", "source_provider": "directory", "source_kind": "dynamic", "source_name": "Public Cameras"}

    decision = engine._browser_capture_decision(row, [], _signals(), "primary")

    assert decision.selected is True
    assert "explicit_dynamic_source_kind" in decision.reasons
    assert "directory_source" in decision.reasons


def test_blind_rows_receive_browser_consideration_from_generic_dynamic_signals(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://public.example/cameras", "source_provider": "blind", "source_kind": "page", "title": "Live public cameras"}

    decision = engine._browser_capture_decision(row, [], _signals(), "primary")

    assert decision.selected is True
    assert "blind_source" in decision.reasons
    assert "camera_text_signals" in decision.reasons


def test_browser_capture_host_budget_prevents_unbounded_capture(tmp_path):
    engine = _engine(tmp_path, max_browser_capture_pages_per_host=1)
    row1 = {"url": "https://public.example/cameras", "source_provider": "blind", "source_kind": "page", "title": "Live cameras"}
    row2 = {"url": "https://public.example/webcams", "source_provider": "blind", "source_kind": "page", "title": "Live webcams"}

    first = engine._browser_capture_decision(row1, [], _signals(row1["url"]), "primary")
    second = engine._browser_capture_decision(row2, [], _signals(row2["url"]), "primary")

    assert first.selected is True
    assert second.selected is False
    assert second.skip_reason == "host_browser_budget_exhausted"


def test_browser_capture_decisions_are_logged(tmp_path):
    engine = _engine(tmp_path)
    decision = BrowserCaptureDecision(
        url="https://public.example/cameras",
        source_provider="blind",
        source_kind="page",
        selected=True,
        score=8,
        reasons=["camera_text_signals"],
        host="public.example",
    )

    engine._log_browser_capture_decision(decision)

    log_path = tmp_path / "logs" / "browser_capture_decisions.jsonl"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["selected"] is True
    assert records[0]["source_provider"] == "blind"


def test_browser_capture_candidate_metadata_is_preserved(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://public.example/cameras", "source_provider": "directory", "source_kind": "dynamic", "source_name": "Public Cameras"}
    candidate = engine._candidate_from_stream("https://media.example/live/cam.m3u8", row["url"], row, "browser_network_capture")
    decision = BrowserCaptureDecision(url=row["url"], source_provider="directory", source_kind="dynamic", selected=True, score=9, reasons=["explicit_dynamic_source_kind"])

    engine._apply_browser_metadata(candidate, row["url"], decision, "browser_network_capture")

    assert candidate.source_metadata["source_provider"] == "directory"
    assert candidate.source_metadata["source_kind"] == "dynamic"
    assert candidate.source_metadata["browser_backend"] == "playwright"
    assert candidate.source_metadata["browser_capture_url"] == row["url"]
    assert candidate.source_metadata["media_type"] == "hls"


def test_both_mode_directory_and_blind_row_discovery_are_parallel(tmp_path, monkeypatch):
    engine = _engine(tmp_path, discovery_mode=DiscoveryMode.BOTH)
    target = _target()

    def slow_directory_rows(target):
        time.sleep(0.2)
        return [{"url": "https://directory.example/cameras", "source_provider": "directory"}]

    def slow_blind_search(queries, client=None):
        time.sleep(0.2)
        return [{"url": "https://blind.example/cameras", "source_provider": "blind"}]

    monkeypatch.setattr(engine.directory_provider, "rows_for_target", slow_directory_rows)
    monkeypatch.setattr(engine, "_blind_search", slow_blind_search)

    started = time.monotonic()
    rows = engine._source_rows(target, ["Example City cameras"])
    elapsed = time.monotonic() - started

    assert {row["source_provider"] for row in rows} == {"directory", "blind"}
    assert elapsed < 0.35


def test_browser_preflight_disables_capture_once(tmp_path, monkeypatch):
    from camera_discovery.extraction.browser import BrowserPreflightResult

    engine = _engine(tmp_path)
    calls = {"count": 0}

    def fake_preflight(backend):
        calls["count"] += 1
        return BrowserPreflightResult(backend=backend, ok=False, disabled_reason="playwright_chromium_missing", install_hint="install chromium")

    monkeypatch.setattr("camera_discovery.services.discovery_engine.browser_backend_preflight", fake_preflight)

    engine._run_browser_preflight()
    engine._run_browser_preflight()

    assert calls["count"] == 1
    assert engine.config.enable_browser_capture is False
    assert engine._browser_capture_summary["preflight_ok"] is False
    assert engine._browser_capture_summary["disabled_reason"] == "playwright_chromium_missing"
