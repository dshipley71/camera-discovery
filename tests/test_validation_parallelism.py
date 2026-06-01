from __future__ import annotations

import json
import threading
import time

from camera_discovery.core.models import (
    CameraCandidate,
    CandidateSet,
    RunConfig,
    RuntimeProfile,
    TargetContext,
    TargetIntent,
    TrustPolicy,
)
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline


def _target() -> TargetContext:
    return TargetContext(
        user_query="Example cameras",
        intent=TargetIntent(raw_query="Example cameras", canonical_target="Example"),
        target_id="example",
        target_label="Example",
        bbox_verified=True,
        bbox={"min_lat": 0.0, "max_lat": 2.0, "min_lon": 0.0, "max_lon": 2.0},
        trust_policy=TrustPolicy.TRUSTED_ALLOWED,
    )


def _candidate(index: int) -> CameraCandidate:
    return CameraCandidate(
        stream_url=f"https://media.example/{index}.m3u8",
        source_url="https://source.example/cameras",
        discovery_method="harvest_handoff",
        lat=1.0,
        lon=1.0,
        scope_status="in_scope",  # type: ignore[arg-type]
        target_id="example",
        target_label="Example",
        source_metadata={"media_type": "hls", "harvest_input": True},
    )


def test_validation_parallelism_attempts_every_candidate_and_keeps_output_order(tmp_path, monkeypatch) -> None:
    cfg = RunConfig(
        query="Example cameras",
        output_dir=tmp_path,
        profile=RuntimeProfile.BALANCED,
        validation_workers=4,
        http_timeout=7.0,
    )
    target = _target()
    rows = [_candidate(i) for i in range(8)]
    active = 0
    max_active = 0
    lock = threading.Lock()
    seen: list[str] = []

    def fake_validate(self, candidate):  # noqa: ANN001
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        with lock:
            seen.append(candidate.stream_url)
            active -= 1
        return "active_live_unknown"

    monkeypatch.setattr(ReviewAndValidationPipeline, "_validate_candidate", fake_validate)

    validation, outputs = ReviewAndValidationPipeline(cfg).run(
        [target],
        CandidateSet(unique=rows, review=rows, in_scope=rows, coordinate_bearing=rows),
    )

    assert validation.attempted == len(rows)
    assert validation.live == len(rows)
    assert validation.dead == 0
    assert validation.validation_workers == 4
    assert validation.http_timeout == 7.0
    assert validation.parallel_validation is True
    assert max_active > 1
    assert sorted(seen) == sorted(row.stream_url for row in rows)
    assert outputs.camera_candidates_table_rows == len(rows)

    result_rows = [json.loads(line) for line in (tmp_path / "logs" / "validation_results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["stream_url"] for row in result_rows] == [row.stream_url for row in rows]


def test_validation_progress_events_are_emitted(tmp_path, monkeypatch) -> None:
    cfg = RunConfig(query="Example cameras", output_dir=tmp_path, profile=RuntimeProfile.BALANCED, validation_workers=2)
    target = _target()
    rows = [_candidate(i) for i in range(3)]
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(ReviewAndValidationPipeline, "_validate_candidate", lambda self, candidate: "active_live_unknown")

    ReviewAndValidationPipeline(cfg, progress_callback=lambda event, payload: events.append((event, payload))).run(
        [target],
        CandidateSet(unique=rows, review=rows, in_scope=rows, coordinate_bearing=rows),
    )

    names = [event for event, _payload in events]
    assert names[0] == "validation_candidates_selected"
    assert names.count("validation_candidate_processed") == len(rows)
    assert names[-1] == "validation_complete"
    selected = events[0][1]
    assert selected["total"] == len(rows)
    assert selected["validation_workers"] == 2
    assert selected["http_timeout"] == cfg.http_timeout


def test_validation_reuses_thread_local_http_clients_and_closes_them(tmp_path, monkeypatch) -> None:
    cfg = RunConfig(query="Example cameras", output_dir=tmp_path, profile=RuntimeProfile.BALANCED, validation_workers=3)
    target = _target()
    rows = [_candidate(i) for i in range(6)]
    created = []

    class FakeResponse:
        status_code = 200
        text = "#EXTM3U\n#EXTINF:1,\nsegment.ts\n"
        headers = {"content-type": "application/vnd.apple.mpegurl"}
        content = b"#EXTM3U"

    class FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.closed = False
            created.append(self)

        def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return FakeResponse()

        def head(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return FakeResponse()

        def close(self):
            self.closed = True

    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.httpx.Client", FakeClient)

    validation, _outputs = ReviewAndValidationPipeline(cfg).run(
        [target],
        CandidateSet(unique=rows, review=rows, in_scope=rows, coordinate_bearing=rows),
    )

    assert validation.attempted == len(rows)
    assert validation.live == len(rows)
    assert len(created) <= cfg.validation_workers
    assert len(created) < len(rows)
    assert all(client.closed for client in created)
