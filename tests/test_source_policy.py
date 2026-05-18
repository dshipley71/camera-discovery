from camera_discovery.core.models import DiscoveryMode, RunConfig, TargetContext, TargetIntent
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine, DirectorySourceProvider, DirectUrlSourceProvider
from camera_discovery.sources.registry import parse_sources_markdown


def test_sources_markdown_parses_allowed_and_blocked_sections():
    policy = parse_sources_markdown(
        """
# SOURCES.md

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Public page | https://public.example/cameras | page | city | true | public camera page |
| Disabled page | https://disabled.example/cameras | page | city | false | disabled |

## Blocked Sources

| pattern | reason |
|---|---|
| blocked.example | policy |
"""
    )
    assert len(policy.allowed_sources) == 2
    assert len(policy.enabled_allowed_sources()) == 1
    assert policy.is_blocked("https://blocked.example/cameras")
    assert not policy.is_blocked("https://public.example/cameras")


def test_directory_provider_uses_enabled_allowed_sources_and_skips_blocked():
    policy = parse_sources_markdown(
        """
## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Public page | https://public.example/cameras | page | city | true | public camera page |
| Blocked page | https://blocked.example/cameras | page | city | true | blocked by policy |

## Blocked Sources

| pattern | reason |
|---|---|
| blocked.example | policy |
"""
    )
    target = TargetContext(user_query="Get cameras from Greenville, Texas", intent=TargetIntent(raw_query="Get cameras from Greenville, Texas"), target_id="greenville_texas")
    rows = DirectorySourceProvider(policy).rows_for_target(target)
    assert [row["url"] for row in rows] == ["https://public.example/cameras"]
    assert rows[0]["source_provider"] == "directory"


def test_direct_provider_respects_global_block_policy():
    policy = parse_sources_markdown(
        """
## Blocked Sources

| pattern | reason |
|---|---|
| blocked.example | policy |
"""
    )
    target = TargetContext(user_query="Review direct URLs", intent=TargetIntent(raw_query="Review direct URLs"), target_id="direct")
    rows = DirectUrlSourceProvider(["https://blocked.example/live/cam.m3u8", "https://public.example/live/cam.m3u8"], policy).rows_for_target(target)
    assert [row["url"] for row in rows] == ["https://public.example/live/cam.m3u8"]


def test_blind_mode_select_rows_applies_block_rules(tmp_path):
    sources = tmp_path / "SOURCES.md"
    sources.write_text(
        """
## Blocked Sources

| pattern | reason |
|---|---|
| blocked.example | policy |
""",
        encoding="utf-8",
    )
    cfg = RunConfig(
        query="Get cameras from Greenville, Texas",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="qwen3.5:4b",
        sources_file=sources,
        discovery_mode=DiscoveryMode.BLIND,
    )
    engine = CandidateDiscoveryEngine(cfg)
    selected = engine._select_rows(
        [
            {"url": "https://blocked.example/cameras", "title": "blocked"},
            {"url": "https://public.example/cameras", "title": "public"},
        ]
    )
    assert [row["url"] for row in selected] == ["https://public.example/cameras"]
