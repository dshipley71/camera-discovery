import json

from typer.testing import CliRunner

from camera_discovery.cli import app
from camera_discovery.core.config import load_run_config
from camera_discovery.core.models import HarvestInputMode
from camera_discovery.core.models import CameraCandidate, CandidateSet, OutputSummary, TargetContext, TargetIntent, TrustPolicy, ValidationSummary
from camera_discovery.services import discovery_engine, review_validation_pipeline, target_resolver

runner = CliRunner()


def test_run_help_documents_harvest_input():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--harvest-input" in result.stdout
    assert "--harvest-input-mode" in result.stdout
    assert "--browser-backend" in result.stdout


def test_load_run_config_stores_harvest_input_mode(tmp_path):
    cfg = load_run_config("test cameras", tmp_path, harvest_input_mode="seed")
    assert cfg.harvest_input_mode == HarvestInputMode.SEED


def test_run_harvest_input_handoff_only_skips_native_discovery(tmp_path, monkeypatch):
    inventory = tmp_path / "harvest_camera_inventory.jsonl"
    inventory.write_text(
        json.dumps(
            {
                "camera_record_id": "cam:1",
                "camera_id": "cam-1",
                "title": "Harvested Camera",
                "lat": 38.0,
                "lon": -77.0,
                "coordinate_source": "source_fields:lat,lon",
                "media_assets": [
                    {
                        "asset_id": "asset:1",
                        "url": "https://media.example/cam1.m3u8",
                        "media_type": "hls",
                        "asset_role": "streaming_video",
                    }
                ],
                "source_provided_only": True,
                "validated": False,
                "trusted": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "harvest_handoff.json"
    manifest.write_text(
        json.dumps({"schema_version": "harvest-handoff/v1", "files": {"harvest_camera_inventory": "harvest_camera_inventory.jsonl"}}),
        encoding="utf-8",
    )

    def fake_resolve(self):
        return [
            TargetContext(
                user_query="test cameras",
                intent=TargetIntent(raw_query="test cameras"),
                target_id="target_1",
                target_index=0,
                canonical_target="Test",
                trust_policy=TrustPolicy.REVIEW_ONLY,
            )
        ]

    def fail_discover(self, target):
        raise AssertionError("native discovery must not run in handoff-only mode")

    captured = {}

    def fake_review_run(self, targets, candidates):
        captured["targets"] = targets
        captured["candidates"] = candidates
        return ValidationSummary(validation_enabled=False), OutputSummary()

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", fake_resolve)
    monkeypatch.setattr(discovery_engine.CandidateDiscoveryEngine, "discover", fail_discover)
    monkeypatch.setattr(review_validation_pipeline.ReviewAndValidationPipeline, "run", fake_review_run)

    result = runner.invoke(
        app,
        [
            "run",
            "test cameras",
            "--output-dir",
            str(tmp_path / "run"),
            "--harvest-input",
            str(manifest),
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert len(captured["candidates"].unique) == 1
    candidate = captured["candidates"].unique[0]
    assert candidate.stream_url == "https://media.example/cam1.m3u8"
    assert candidate.discovery_method == "harvest_handoff"
    assert candidate.lat == 38.0
    assert candidate.source_metadata["trusted"] is False
    assert candidate.source_metadata["validated"] is False
    summary = json.loads((tmp_path / "run" / "logs" / "candidate_discovery_summary.json").read_text(encoding="utf-8"))
    assert summary["native_discovery"]["enabled"] is False
    assert summary["native_discovery"]["unique_candidates"] == 0
    assert summary["harvest_input"]["mode"] == "handoff-only"
    assert summary["harvest_input"]["normal_discovery_enabled"] is False


def test_run_harvest_input_seed_merges_candidates_into_normal_pipeline(tmp_path, monkeypatch):
    inventory = tmp_path / "harvest_camera_inventory.jsonl"
    inventory.write_text(
        json.dumps(
            {
                "camera_record_id": "cam:1",
                "camera_id": "cam-1",
                "title": "Harvested Camera",
                "lat": 38.0,
                "lon": -77.0,
                "coordinate_source": "source_fields:lat,lon",
                "media_assets": [
                    {
                        "asset_id": "asset:1",
                        "url": "https://media.example/cam1.m3u8",
                        "media_type": "hls",
                        "asset_role": "streaming_video",
                    }
                ],
                "source_provided_only": True,
                "validated": False,
                "trusted": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "harvest_handoff.json"
    manifest.write_text(
        json.dumps({"schema_version": "harvest-handoff/v1", "files": {"harvest_camera_inventory": "harvest_camera_inventory.jsonl"}}),
        encoding="utf-8",
    )

    def fake_resolve(self):
        return [
            TargetContext(
                user_query="test cameras",
                intent=TargetIntent(raw_query="test cameras"),
                target_id="target_1",
                target_index=0,
                canonical_target="Test",
                trust_policy=TrustPolicy.REVIEW_ONLY,
            )
        ]

    calls = {"discover": 0}

    def fake_discover(self, target):
        calls["discover"] += 1
        return CandidateSet(unique=[CameraCandidate(stream_url="https://native.example/live.m3u8", target_id=target.target_id)])

    captured = {}

    def fake_review_run(self, targets, candidates):
        captured["candidates"] = candidates
        return ValidationSummary(validation_enabled=False), OutputSummary()

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", fake_resolve)
    monkeypatch.setattr(discovery_engine.CandidateDiscoveryEngine, "discover", fake_discover)
    monkeypatch.setattr(review_validation_pipeline.ReviewAndValidationPipeline, "run", fake_review_run)

    out_dir = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "run",
            "test cameras",
            "--output-dir",
            str(out_dir),
            "--harvest-input",
            str(manifest),
            "--harvest-input-mode",
            "seed",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert calls["discover"] == 1
    assert {candidate.stream_url for candidate in captured["candidates"].unique} == {
        "https://native.example/live.m3u8",
        "https://media.example/cam1.m3u8",
    }
    summary = json.loads((out_dir / "logs" / "candidate_discovery_summary.json").read_text(encoding="utf-8"))
    assert summary["native_discovery"]["enabled"] is True
    assert summary["native_discovery"]["unique_candidates"] == 1
    assert summary["harvest_input"]["mode"] == "seed"
    assert summary["harvest_input"]["normal_discovery_enabled"] is True


def test_run_target_resolution_auth_error_is_concise(tmp_path, monkeypatch):
    import httpx

    def raise_auth_error(self):
        request = httpx.Request("POST", "https://ollama.com/api/chat")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", raise_auth_error)
    result = runner.invoke(
        app,
        [
            "run",
            "test cameras",
            "--output-dir",
            str(tmp_path / "run"),
            "--no-progress",
        ],
    )
    assert result.exit_code == 2
    assert "LLM provider authentication/configuration failed" in result.stdout
    assert "Set/verify" in result.stdout


def test_run_harvest_input_applies_deterministic_scope_and_summary(tmp_path, monkeypatch):
    media_records = tmp_path / "camera_urls.jsonl"
    rows = [
        {"url": "https://media.example/inside.m3u8", "media_type": "hls", "lat": 34.0, "lon": -118.0},
        {"url": "https://media.example/outside.m3u8", "media_type": "hls", "lat": 44.0, "lon": -118.0},
        {"url": "https://media.example/missing.m3u8", "media_type": "hls"},
    ]
    media_records.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = tmp_path / "harvest_handoff.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "harvest-handoff/v2",
                "media_filter": [".m3u8"],
                "handoff_default_scope": "filtered_media_records",
                "files": {"camera_urls_jsonl": "camera_urls.jsonl"},
            }
        ),
        encoding="utf-8",
    )

    def fake_resolve(self):
        return [
            TargetContext(
                user_query="test cameras",
                intent=TargetIntent(raw_query="test cameras"),
                target_id="target_1",
                target_index=0,
                canonical_target="Test",
                bbox_verified=True,
                bbox={"min_lat": 30.0, "max_lat": 40.0, "min_lon": -125.0, "max_lon": -110.0},
                trust_policy=TrustPolicy.REVIEW_ONLY,
            )
        ]

    def fake_discover(self, target):
        return CandidateSet(unique=[CameraCandidate(stream_url="https://native.example/live.m3u8", target_id=target.target_id)])

    captured = {}

    def fake_review_run(self, targets, candidates):
        captured["candidates"] = candidates
        return ValidationSummary(validation_enabled=False), OutputSummary()

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", fake_resolve)
    monkeypatch.setattr(discovery_engine.CandidateDiscoveryEngine, "discover", fake_discover)
    monkeypatch.setattr(review_validation_pipeline.ReviewAndValidationPipeline, "run", fake_review_run)

    out_dir = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "run",
            "test cameras",
            "--output-dir",
            str(out_dir),
            "--harvest-input",
            str(manifest),
            "--no-progress",
        ],
    )

    assert result.exit_code == 0, result.stdout
    by_url = {candidate.stream_url: candidate for candidate in captured["candidates"].unique}
    assert by_url["https://media.example/inside.m3u8"].scope_status == "in_scope"
    assert by_url["https://media.example/outside.m3u8"].scope_status == "out_of_scope"
    assert by_url["https://media.example/missing.m3u8"].scope_status == "unknown"

    summary = json.loads((out_dir / "logs" / "candidate_discovery_summary.json").read_text(encoding="utf-8"))
    assert summary["native_discovery"]["enabled"] is False
    assert summary["native_discovery"]["unique_candidates"] == 0
    assert summary["harvest_input"]["candidate_count"] == 3
    assert summary["harvest_input"]["record_count"] == 3
    assert summary["harvest_input"]["mode"] == "handoff-only"
    assert summary["harvest_input"]["filtered_by_handoff_media_filter"] is True
    assert summary["combined"]["unique_candidates"] == 3


def test_run_browser_backend_cli_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_BROWSER_BACKEND", "playwright")
    cfg = __import__("camera_discovery.core.config", fromlist=["load_run_config"]).load_run_config(
        "test cameras",
        tmp_path,
        browser_backend="cloakbrowser",
    )
    assert cfg.browser_backend == "cloakbrowser"
