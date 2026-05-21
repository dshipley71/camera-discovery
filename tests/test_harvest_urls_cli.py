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
