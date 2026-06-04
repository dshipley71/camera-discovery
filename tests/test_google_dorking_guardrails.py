from __future__ import annotations

import json

import httpx

from camera_discovery.core.models import DiscoveryMode, RunConfig, TargetContext, TargetIntent
from camera_discovery.discovery.search_dispatch import _is_safe_google_dork
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine


def _sources(path):
    path.write_text(
        """# SOURCES.md

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Public Cameras | https://public.example/cameras | site | global | true | test |

## Blocked Sources

| pattern | reason |
|---|---|
| blocked.example | blocked |
| shodan.io | blocked |
""",
        encoding="utf-8",
    )
    return path


def _target() -> TargetContext:
    query = "Get public cameras from Example City"
    return TargetContext(
        user_query=query,
        intent=TargetIntent(raw_query=query, canonical_target="Example City", camera_type_intent="traffic"),
        target_id="example_city",
        target_label="Example City",
        canonical_target="Example City",
    )


def test_google_dorking_enabled_by_default(tmp_path):
    cfg = RunConfig(query="Get public cameras from Example City", output_dir=tmp_path, sources_file=_sources(tmp_path / "SOURCES.md"))
    engine = CandidateDiscoveryEngine(cfg)
    queries = engine._search_queries(_target())
    assert queries
    dorks = [query for query in queries if "site:" in query.casefold()]
    assert dorks
    summary = json.loads((tmp_path / "logs" / "google_dorking_summary.json").read_text(encoding="utf-8"))
    assert summary["enabled"] is True
    assert summary["queries_generated"] == len(dorks)


def test_google_dorking_can_be_explicitly_disabled(tmp_path):
    cfg = RunConfig(
        query="Get public cameras from Example City",
        output_dir=tmp_path,
        sources_file=_sources(tmp_path / "SOURCES.md"),
        enable_google_dorking=False,
    )
    engine = CandidateDiscoveryEngine(cfg)
    queries = engine._search_queries(_target())
    assert queries
    assert not any("site:" in query.casefold() for query in queries)


def test_google_dorking_generates_bounded_safe_site_queries(tmp_path):
    cfg = RunConfig(
        query="Get public cameras from Example City",
        output_dir=tmp_path,
        sources_file=_sources(tmp_path / "SOURCES.md"),
        enable_google_dorking=True,
        max_dork_queries=3,
        max_search_queries=2,
    )
    engine = CandidateDiscoveryEngine(cfg)
    queries = engine._search_queries(_target())
    dorks = [query for query in queries if "site:" in query.casefold()]
    assert 0 < len(dorks) <= 3
    for query in dorks:
        lowered = query.casefold()
        assert "site:public.example" in lowered
        assert "example city" in lowered
        assert "camera" in lowered
        assert "rtsp://" not in lowered
        assert "login" not in lowered.replace("-login", "")
        assert _is_safe_google_dork(query)
    assert not _is_safe_google_dork('site:public.example "Example City" rtsp:// camera')
    summary = json.loads((tmp_path / "logs" / "google_dorking_summary.json").read_text(encoding="utf-8"))
    assert summary["enabled"] is True
    assert summary["queries_generated"] == len(dorks)


def test_dorked_results_are_tagged_and_blocked_after_search(tmp_path, monkeypatch):
    cfg = RunConfig(
        query="Get public cameras from Example City",
        output_dir=tmp_path,
        sources_file=_sources(tmp_path / "SOURCES.md"),
        discovery_mode=DiscoveryMode.BLIND,
        enable_google_dorking=True,
        max_dork_queries=1,
        max_search_queries=0,
    )
    engine = CandidateDiscoveryEngine(cfg)
    queries = engine._search_queries(_target())
    monkeypatch.setattr(
        "camera_discovery.discovery.search_dispatch._get_with_retry",
        lambda client, url: httpx.Response(200, request=httpx.Request("GET", url), text="fixture"),
    )
    monkeypatch.setattr(
        engine,
        "_parse_ddg",
        lambda query, html: [
            {"query": query, "url": "https://public.example/cameras/list", "title": "public"},
            {"query": query, "url": "https://blocked.example/cameras/list", "title": "blocked"},
        ],
    )
    rows = engine._blind_search(queries, engine._make_client())
    assert all(row.get("discovery_query_kind") == "google_dork" for row in rows)
    selected = engine._select_rows(rows)
    assert [row["url"] for row in selected] == ["https://public.example/cameras/list"]
    summary = json.loads((tmp_path / "logs" / "google_dorking_summary.json").read_text(encoding="utf-8"))
    assert summary["results_seen"] == 2
    assert summary["results_after_block_policy"] == 1


def test_docs_and_notebooks_mention_new_media_outputs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "codex_prompt_media_playlists_rtsp_validation_dashboard.md").exists()
    docs = (root / "docs" / "output_artifacts.md").read_text(encoding="utf-8") + (root / "docs" / "runtime_configuration.md").read_text(encoding="utf-8")
    assert "media_validation_dashboard.json" in docs
    assert "playlists/" in docs
    assert "RTSP" in docs
    assert "Google dorking" in docs
    notebook_text = (root / "notebooks" / "camera_discovery_live_test.ipynb").read_text(encoding="utf-8")
    assert "media_validation_dashboard.json" in notebook_text
    assert "playlists/" in notebook_text
    assert "google_dorking_summary.json" in notebook_text
