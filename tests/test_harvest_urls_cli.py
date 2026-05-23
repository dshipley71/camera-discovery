import json
from pathlib import Path

from typer.testing import CliRunner

from camera_discovery.cli import app
from camera_discovery.services import review_validation_pipeline, target_resolver

runner = CliRunner()


def test_harvest_urls_command_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "harvest-urls" in result.stdout


def test_harvest_direct_seed_writes_plain_outputs_without_inventory_pipeline(tmp_path, monkeypatch):
    def fail_target(*args, **kwargs):  # pragma: no cover - only used on failure
        raise AssertionError("TargetResolver must not be called by harvest mode")

    def fail_review(*args, **kwargs):  # pragma: no cover - only used on failure
        raise AssertionError("ReviewAndValidationPipeline must not be called by harvest mode")

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", fail_target)
    monkeypatch.setattr(review_validation_pipeline.ReviewAndValidationPipeline, "run", fail_review)

    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://media.example/cam1.m3u8",
            "--seed-url",
            "https://media.example/cam2.jpg",
            "--output-dir",
            str(out),
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "camera_urls.txt").read_text(encoding="utf-8").splitlines() == [
        "https://media.example/cam1.m3u8",
        "https://media.example/cam2.jpg",
    ]
    assert (out / "camera_urls.csv").exists()
    assert (out / "camera_urls.jsonl").exists()
    assert (out / "harvest_summary.json").exists()
    assert (out / "source_rows.jsonl").exists()
    assert not (out / "cameras.geojson").exists()
    assert not (out / "cameras.md").exists()
    assert not (out / "map.html").exists()
    summary = json.loads((out / "harvest_summary.json").read_text(encoding="utf-8"))
    assert summary["written_urls"] == 2
    assert summary["by_media_type"] == {"hls": 1, "image_snapshot": 1}


def test_harvest_max_urls_caps_after_dedupe(tmp_path):
    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://media.example/cam1.m3u8#fragment",
            "--seed-url",
            "https://media.example/cam1.m3u8",
            "--seed-url",
            "https://media.example/cam2.m3u8",
            "--output-dir",
            str(out),
            "--max-urls",
            "1",
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "camera_urls.txt").read_text(encoding="utf-8").splitlines() == ["https://media.example/cam1.m3u8"]
    summary = json.loads((out / "harvest_summary.json").read_text(encoding="utf-8"))
    assert summary["unique_urls"] == 2
    assert summary["written_urls"] == 1


def test_harvest_max_urls_zero_is_unlimited(tmp_path):
    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://media.example/cam1.m3u8",
            "--seed-url",
            "https://media.example/cam2.m3u8",
            "--output-dir",
            str(out),
            "--max-urls",
            "0",
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert len((out / "camera_urls.txt").read_text(encoding="utf-8").splitlines()) == 2
    summary = json.loads((out / "harvest_summary.json").read_text(encoding="utf-8"))
    assert summary["unlimited"] is True


def test_harvest_block_pattern_applies_to_seed_and_final_records(tmp_path):
    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://blocked.example/cam1.m3u8",
            "--seed-url",
            "https://media.example/cam2.m3u8",
            "--block-pattern",
            "blocked.example",
            "--output-dir",
            str(out),
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "camera_urls.txt").read_text(encoding="utf-8").splitlines() == ["https://media.example/cam2.m3u8"]


def test_harvest_media_filter_outputs_only_requested_media(tmp_path):
    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://media.example/cam1.m3u8",
            "--seed-url",
            "https://media.example/cam2.mp4",
            "--seed-url",
            "https://media.example/cam3.jpg",
            "--media",
            ".m3u8,mp4",
            "--output-dir",
            str(out),
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "camera_urls.txt").read_text(encoding="utf-8").splitlines() == [
        "https://media.example/cam1.m3u8",
        "https://media.example/cam2.mp4",
    ]


def test_harvest_invalid_media_cli_error(tmp_path):
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://media.example/cam1.m3u8",
            "--media",
            "badmedia",
            "--output-dir",
            str(tmp_path / "harvest"),
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code != 0
    assert "Unsupported --media" in result.stdout


def test_harvest_notebook_exists_and_is_cli_harness():
    notebook = Path("notebooks/camera_discovery_harvest_urls_test.ipynb")
    assert notebook.exists()
    text = notebook.read_text(encoding="utf-8")
    assert "harvest-urls" in text
    assert "CameraUrlHarvestEngine" not in text
    assert "TargetResolver" not in text



def test_harvest_write_intermediate_records_opt_in(tmp_path):
    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://MEDIA.EXAMPLE/cam1.m3u8",
            "--seed-url",
            "https://media.example/cam1.m3u8",
            "--seed-url",
            "https://media.example/cam2.jpg",
            "--media",
            ".m3u8",
            "--output-dir",
            str(out),
            "--write-intermediate-records",
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    raw_path = out / "raw_media_records.jsonl"
    unique_path = out / "unique_media_records.jsonl"
    filtered_path = out / "media_filtered_records.jsonl"
    assert raw_path.exists()
    assert unique_path.exists()
    assert filtered_path.exists()
    raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    unique_rows = [json.loads(line) for line in unique_path.read_text(encoding="utf-8").splitlines()]
    filtered_rows = [json.loads(line) for line in filtered_path.read_text(encoding="utf-8").splitlines()]
    assert len(raw_rows) == 3
    assert len(unique_rows) == 2
    assert [row["url"] for row in filtered_rows] == ["https://media.example/cam1.m3u8"]
    assert (out / "camera_urls.txt").read_text(encoding="utf-8").splitlines() == ["https://media.example/cam1.m3u8"]
    summary = json.loads((out / "harvest_summary.json").read_text(encoding="utf-8"))
    assert summary["intermediate_records_written"] is True
    assert summary["intermediate_record_counts"] == {
        "raw_media_records": 3,
        "unique_media_records": 2,
        "media_filtered_records": 1,
        "image_filtered_records": 1,
    }
    assert set(summary["intermediate_record_files"]) == {
        "raw_media_records_jsonl",
        "unique_media_records_jsonl",
        "media_filtered_records_jsonl",
        "image_filtered_records_jsonl",
    }
    assert (out / "logs" / "intermediate_records_summary.json").exists()
    assert "raw_media_records.jsonl" in result.stdout


def test_harvest_intermediate_records_default_not_written(tmp_path):
    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://media.example/cam1.m3u8",
            "--output-dir",
            str(out),
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert not (out / "raw_media_records.jsonl").exists()
    assert not (out / "unique_media_records.jsonl").exists()
    assert not (out / "media_filtered_records.jsonl").exists()
    summary = json.loads((out / "harvest_summary.json").read_text(encoding="utf-8"))
    assert summary["intermediate_records_written"] is False
    assert summary["intermediate_record_files"] == {}

def test_harvest_reports_sources_md_directory_usage(tmp_path, monkeypatch):
    from camera_discovery.services import harvest_engine

    def fail_fetch(*args, **kwargs):  # avoid network; direct media rows are emitted before fetch attempt
        raise RuntimeError("network disabled in test")

    monkeypatch.setattr(harvest_engine, "_get_with_retry", fail_fetch)
    sources = tmp_path / "SOURCES.md"
    sources.write_text(
        """
# Allowed Sources

| name | url | type | scope_hint | enabled | notes |
| --- | --- | --- | --- | --- | --- |
| Fixture HLS | https://media.example/directory-cam.m3u8 | direct_hls | public | true | test source |

# Blocked Sources

| pattern | reason |
| --- | --- |
| blocked.example | test block |
""".strip(),
        encoding="utf-8",
    )
    out = tmp_path / "harvest"
    result = runner.invoke(
        app,
        [
            "harvest-urls",
            "test cameras",
            "--discovery-mode",
            "both",
            "--max-search-queries",
            "0",
            "--sources-file",
            str(sources),
            "--output-dir",
            str(out),
            "--disable-browser-capture",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    summary = json.loads((out / "harvest_summary.json").read_text(encoding="utf-8"))
    source_rows = summary["source_rows"]
    assert source_rows["sources_file"] == str(sources)
    assert source_rows["sources_file_exists"] is True
    assert source_rows["sources_file_loaded"] is True
    assert source_rows["sources_file_used"] is True
    assert source_rows["directory_sources_configured"] == 1
    assert source_rows["directory_sources_enabled"] == 1
    assert source_rows["selected_by_provider"] == {"directory": 1}
    assert summary["source_rows_by_provider"] == {"directory": 1}
    assert summary["directory_source_rows_selected"] == 1
    assert "SOURCES.md used" in result.stdout
    assert "directory" in result.stdout
    assert (out / "logs" / "source_rows_summary.json").exists()
    handoff = json.loads((out / "harvest_handoff.json").read_text(encoding="utf-8"))
    assert handoff["source_rows"]["sources_file_used"] is True
