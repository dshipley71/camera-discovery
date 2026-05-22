import json

from typer.testing import CliRunner

from camera_discovery.cli import app
from camera_discovery.core.models import CandidateSet, OutputSummary, TargetContext, TargetIntent, TrustPolicy, ValidationSummary
from camera_discovery.services import discovery_engine, review_validation_pipeline, target_resolver

runner = CliRunner()


def test_run_help_documents_harvest_input():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--harvest-input" in result.stdout


def test_run_harvest_input_merges_candidates_into_normal_pipeline(tmp_path, monkeypatch):
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

    def fake_discover(self, target):
        return CandidateSet()

    captured = {}

    def fake_review_run(self, targets, candidates):
        captured["targets"] = targets
        captured["candidates"] = candidates
        return ValidationSummary(validation_enabled=False), OutputSummary()

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", fake_resolve)
    monkeypatch.setattr(discovery_engine.CandidateDiscoveryEngine, "discover", fake_discover)
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
