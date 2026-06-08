import json

from typer.testing import CliRunner

from camera_discovery.cli import app
from camera_discovery.core.models import CandidateSet, OutputSummary, TargetContext, TargetIntent, TrustPolicy, ValidationSummary
from camera_discovery.evidence import ExtractedEvidence, evidence_to_camera_candidate, harvested_url_record_to_evidence
from camera_discovery.harvest.outputs import record_to_dict
from camera_discovery.harvest.records import record_from_url
from camera_discovery.services import review_validation_pipeline, target_resolver

runner = CliRunner()


def test_run_help_documents_harvest_first_options():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--harvest-first" in result.stdout
    assert "--harvest-media" in result.stdout
    assert "--harvest-max-source-rows" in result.stdout
    assert "--harvest-input-mode" in result.stdout


def test_harvest_first_runs_harvest_then_existing_handoff_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE", "false")

    def fake_resolve(self):
        return [
            TargetContext(
                user_query="test cameras",
                intent=TargetIntent(raw_query="test cameras"),
                target_id="target_1",
                target_index=0,
                target_label="Test Target",
                canonical_target="Test Target",
                bbox_verified=True,
                bbox={"min_lat": 1.0, "max_lat": 2.0, "min_lon": 3.0, "max_lon": 4.0},
                trust_policy=TrustPolicy.REVIEW_ONLY,
            )
        ]

    captured = {}

    def fake_review_run(self, targets, candidates):
        captured["targets"] = targets
        captured["candidates"] = candidates
        return ValidationSummary(validation_enabled=False), OutputSummary()

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", fake_resolve)
    monkeypatch.setattr(review_validation_pipeline.ReviewAndValidationPipeline, "run", fake_review_run)

    out = tmp_path / "combined"
    result = runner.invoke(
        app,
        [
            "run",
            "test cameras",
            "--harvest-first",
            "--harvest-media",
            ".m3u8",
            "--harvest-max-source-rows",
            "10",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://media.example/live.m3u8",
            "--output-dir",
            str(out),
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "harvest" / "harvest_handoff.json").exists()
    assert (out / "harvest" / "camera_urls.jsonl").exists()
    assert (out / "run" / "logs" / "candidate_discovery_summary.json").exists()
    assert not (out / "harvest" / "cameras.geojson").exists()
    assert not (out / "harvest" / "review_artifacts.zip").exists()

    handoff = json.loads((out / "harvest" / "harvest_handoff.json").read_text(encoding="utf-8"))
    assert handoff["schema_version"] == "harvest-handoff/v2"
    assert handoff["evidence_schema_version"] == "extracted-evidence/v1"
    assert handoff["validated"] is False
    assert handoff["trusted"] is False
    assert handoff["scope_filtered"] is False

    rows = [json.loads(line) for line in (out / "harvest" / "camera_urls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["source_policy_checked"] is True
    candidate = captured["candidates"].unique[0]
    assert candidate.discovery_method == "harvest_handoff"
    assert candidate.trust_level == "untrusted"
    assert candidate.source_metadata["trusted"] is False
    assert candidate.source_metadata["validated"] is False
    assert candidate.source_metadata["scope_filtered"] is False


def test_neutral_evidence_converts_to_candidate_without_trust():
    record = record_from_url(
        "https://media.example/live.m3u8",
        "hls",
        source_url="https://source.example/page",
        row={"url": "https://source.example/page", "query": "test cameras", "source_provider": "direct"},
        method="source_payload",
        metadata={"lat": "10.5", "lon": "20.5", "coordinate_source": "source_metadata"},
    )
    data = record_to_dict(record)
    assert data["source_policy_checked"] is True
    evidence = harvested_url_record_to_evidence(record)
    assert isinstance(evidence, ExtractedEvidence)
    candidate = evidence_to_camera_candidate(evidence, target_id="target_1", target_index=0, target_label="Target")
    assert candidate.stream_url == "https://media.example/live.m3u8"
    assert candidate.lat == 10.5
    assert candidate.lon == 20.5
    assert candidate.trust_level == "untrusted"
    assert candidate.validation_status is None
    assert candidate.scope_status == "unknown"
    assert candidate.source_metadata["source_provided_only"] is True
    assert candidate.source_metadata["trusted"] is False
    assert candidate.source_metadata["validated"] is False


def test_harvest_first_direct_seed_respects_block_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE", "false")
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

    def fake_resolve(self):
        return [TargetContext(user_query="test cameras", intent=TargetIntent(raw_query="test cameras"), trust_policy=TrustPolicy.REVIEW_ONLY)]

    def fake_review_run(self, targets, candidates: CandidateSet):
        assert not candidates.unique
        return ValidationSummary(validation_enabled=False), OutputSummary()

    monkeypatch.setattr(target_resolver.TargetResolver, "resolve_all", fake_resolve)
    monkeypatch.setattr(review_validation_pipeline.ReviewAndValidationPipeline, "run", fake_review_run)

    out = tmp_path / "combined-blocked"
    result = runner.invoke(
        app,
        [
            "run",
            "test cameras",
            "--harvest-first",
            "--discovery-mode",
            "direct",
            "--seed-url",
            "https://blocked.example/live.m3u8",
            "--sources-file",
            str(sources),
            "--output-dir",
            str(out),
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "harvest" / "camera_urls.jsonl").read_text(encoding="utf-8") == ""
