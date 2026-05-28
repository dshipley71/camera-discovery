from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from camera_discovery.core.progress_events import PROGRESS_EVENT_PREFIX, emit_progress_event


def test_progress_event_prefix_is_machine_readable() -> None:
    assert PROGRESS_EVENT_PREFIX.startswith("__CAMERA_DISCOVERY_PROGRESS__")
    assert PROGRESS_EVENT_PREFIX.endswith(" ")


def test_emit_progress_event_writes_json_line(capsys) -> None:
    emit_progress_event("validation_hls_progress", {"completed": 3, "total": 10, "live": 2})
    out = capsys.readouterr().out
    assert out.startswith(PROGRESS_EVENT_PREFIX)
    message = json.loads(out[len(PROGRESS_EVENT_PREFIX):])
    assert message["event"] == "validation_hls_progress"
    assert message["payload"]["completed"] == 3
    assert message["payload"]["total"] == 10


def test_notebook_contains_inline_helpers_and_no_support_import() -> None:
    notebook_path = Path(__file__).resolve().parents[1] / "notebooks" / "camera_discovery_live_test.ipynb"
    text = notebook_path.read_text(encoding="utf-8")
    assert "camera_discovery_notebook" not in text
    assert "Notebook-only run/progress helpers" in text
    assert "--progress-style" in text
    assert "events" in text


def test_no_notebook_support_package_in_repository() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert not (repo_root / "src" / "camera_discovery" / "notebook").exists()
    assert not (repo_root / "notebooks" / "support" / "camera_discovery_notebook").exists()


def test_cli_help_advertises_events_progress_style() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "camera_discovery.cli", "run", "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert "--progress-style" in result.stdout
    assert "events" in result.stdout


def test_validation_progress_event_shape_is_machine_readable(capsys) -> None:
    emit_progress_event("validation_candidate_processed", {"completed": 5, "total": 10, "live": 3, "dead": 1, "unknown": 1, "validation_workers": 4})
    out = capsys.readouterr().out
    assert out.startswith(PROGRESS_EVENT_PREFIX)
    message = json.loads(out[len(PROGRESS_EVENT_PREFIX):])
    assert message["event"] == "validation_candidate_processed"
    assert message["payload"]["completed"] == 5
    assert message["payload"]["validation_workers"] == 4


def test_handoff_validation_notebooks_use_visible_cli_and_http_timeout() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    notebook_names = [
        "camera_discovery_harvest_hls_handoff_full_validation_test.ipynb",
        "camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb",
    ]
    for name in notebook_names:
        text = (repo_root / "notebooks" / name).read_text(encoding="utf-8")
        assert "!camera-discovery run" in text
        assert "--http-timeout" in text
        assert "--harvest-input-mode" in text
        assert "run_cli([" not in text
        assert "max-validation-candidates" not in text
        assert "MAX_VALIDATION_CANDIDATES" not in text
