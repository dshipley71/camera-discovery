from __future__ import annotations

import builtins
import json
import types

import pytest

from camera_discovery.core.config import load_run_config
from camera_discovery.core.models import CameraCandidate, RunConfig
from camera_discovery.services.discovery_engine import BrowserCaptureResult, CandidateDiscoveryEngine


def _engine(tmp_path, **overrides) -> CandidateDiscoveryEngine:
    return CandidateDiscoveryEngine(RunConfig(query="Get cameras from Example City", output_dir=tmp_path, **overrides))


def test_default_browser_backend_is_playwright(tmp_path, monkeypatch):
    monkeypatch.delenv("CAMERA_DISCOVERY_BROWSER_BACKEND", raising=False)

    cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.browser_backend == "playwright"


def test_cloakbrowser_backend_env_is_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_BROWSER_BACKEND", "cloakbrowser")

    cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.browser_backend == "cloakbrowser"


def test_invalid_browser_backend_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_BROWSER_BACKEND", "not-a-browser")

    with pytest.raises(ValueError, match="CAMERA_DISCOVERY_BROWSER_BACKEND"):
        load_run_config("Get cameras from Example City", tmp_path)


def test_cloakbrowser_launches_only_when_selected(tmp_path, monkeypatch):
    launched = {"count": 0, "closed": 0}

    class FakeBrowser:
        def close(self):
            launched["closed"] += 1

    def fake_launch(*, headless=True):
        launched["count"] += 1
        assert headless is True
        return FakeBrowser()

    monkeypatch.setitem(__import__("sys").modules, "cloakbrowser", types.SimpleNamespace(launch=fake_launch))
    engine = _engine(tmp_path, browser_backend="cloakbrowser")

    with engine._browser_capture_session() as browser:
        assert isinstance(browser, FakeBrowser)

    assert launched == {"count": 1, "closed": 1}


def test_playwright_backend_uses_playwright_launch_path(tmp_path, monkeypatch):
    launched = {"playwright_started": 0, "launched": 0, "closed": 0}

    class FakeBrowser:
        def close(self):
            launched["closed"] += 1

    class FakeChromium:
        def launch(self, *, headless=True):
            launched["launched"] += 1
            assert headless is True
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self):
            launched["playwright_started"] += 1
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.sync_api":
            return types.SimpleNamespace(sync_playwright=lambda: FakeSyncPlaywright())
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    engine = _engine(tmp_path, browser_backend="playwright")

    with engine._browser_capture_session() as browser:
        assert isinstance(browser, FakeBrowser)

    assert launched == {"playwright_started": 1, "launched": 1, "closed": 1}


def test_missing_cloakbrowser_dependency_reports_install_hint(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("cloakbrowser"):
            raise ImportError("cloakbrowser unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    engine = _engine(tmp_path, browser_backend="cloakbrowser")
    row = {"url": "https://public.example/cameras", "source_provider": "directory", "source_kind": "dynamic"}

    candidates, result = engine._extract_from_dynamic_page(row["url"], row, return_result=True)

    assert candidates == []
    assert result.backend == "cloakbrowser"
    assert "pip install -e .[cloakbrowser]" in result.error


def test_browser_result_log_includes_browser_backend(tmp_path):
    engine = _engine(tmp_path, browser_backend="cloakbrowser")
    row = {"url": "https://public.example/cameras", "source_provider": "directory", "source_kind": "dynamic"}
    result = BrowserCaptureResult(url=row["url"], backend="cloakbrowser", total_browser_candidates=0)

    engine._log_browser_capture_result(result, row, "primary")

    path = tmp_path / "logs" / "browser_capture_results.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["backend"] == "cloakbrowser"
    assert record["browser_backend"] == "cloakbrowser"


def test_browser_candidate_metadata_uses_selected_backend(tmp_path):
    engine = _engine(tmp_path, browser_backend="cloakbrowser")
    candidate = CameraCandidate(stream_url="https://media.example/live/cam.m3u8")

    engine._apply_browser_metadata(candidate, "https://public.example/cameras", None, "browser_network_capture")

    assert candidate.source_metadata["browser_backend"] == "cloakbrowser"
    assert candidate.source_metadata["browser_capture_url"] == "https://public.example/cameras"
