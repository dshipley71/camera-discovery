from pathlib import Path

from camera_discovery.core.models import RunConfig, TargetContext, TargetIntent
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine


def test_directory_site_source_generates_target_aware_rows(tmp_path: Path) -> None:
    sources = tmp_path / "SOURCES.md"
    sources.write_text(
        """# SOURCES.md

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Example Cameras | https://example.org/ | site | global | true | public directory |

## Blocked Sources

| pattern | reason |
|---|---|
""",
        encoding="utf-8",
    )
    cfg = RunConfig(
        query="Get me all traffic cameras from Example State",
        output_dir=tmp_path / "run",
        sources_file=sources,
        discovery_mode="both",  # type: ignore[arg-type]
    )
    engine = CandidateDiscoveryEngine(cfg)
    target = TargetContext(
        user_query=cfg.query,
        intent=TargetIntent(
            raw_query=cfg.query,
            canonical_target="Example State, Example Country",
            admin_region="Example State",
            country="Example Country",
            camera_type_intent="traffic",
        ),
        target_id="example_state",
        target_label="Example State",
        canonical_target="Example State, Example Country",
        admin_region="Example State",
        country="Example Country",
    )

    rows = engine.directory_provider.rows_for_target(target)
    urls = {row["url"] for row in rows}

    assert "https://example.org/" in urls
    assert "https://example.org/cameras/example-country/example-state" in urls
    assert "https://example.org/livetraffic/example-country/example-state" in urls
    assert "https://example.org/cameras/example-country/example-state/category/traffic" in urls
    assert any(url.endswith("category/traffic?page=2") for url in urls)
    assert all(row["source_provider"] == "directory" for row in rows)


def test_directory_rows_precede_blind_rows(tmp_path: Path) -> None:
    sources = tmp_path / "SOURCES.md"
    sources.write_text(
        """# SOURCES.md

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Example Cameras | https://example.org/ | site | global | true | public directory |
""",
        encoding="utf-8",
    )
    cfg = RunConfig(query="Example cameras", output_dir=tmp_path / "run", sources_file=sources)
    engine = CandidateDiscoveryEngine(cfg)
    target = TargetContext(
        user_query=cfg.query,
        intent=TargetIntent(raw_query=cfg.query, canonical_target="Example State", country="Example Country"),
        target_label="Example State",
        canonical_target="Example State",
        country="Example Country",
    )

    rows = engine._source_rows(target, queries=["ignored query"])

    assert rows
    assert rows[0]["source_provider"] == "directory"
