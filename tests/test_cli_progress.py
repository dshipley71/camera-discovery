from pathlib import Path
import subprocess
import sys
import threading

from camera_discovery.cli import (
    _make_discovery_progress_callback,
    _make_plain_discovery_progress_callback,
    _resolve_progress_mode,
)
from rich.console import Console
from rich.progress import Progress


def test_cli_progress_callback_tracks_source_rows():
    console = Console(file=open('/tmp/camera_discovery_progress_test.out', 'w'), force_terminal=False)
    progress = Progress(console=console, transient=True, disable=True)
    with progress:
        task_id = progress.add_task('Discovering target', total=None)
        state = {'total': 0, 'completed': 0}
        callback = _make_discovery_progress_callback(progress, task_id, state, threading.Lock())
        callback('source_rows_selected', {'target_label': 'California', 'selected_rows': 3, 'primary_rows': 3})
        callback('source_row_processed', {'target_label': 'California', 'accepted_total': 2, 'hls_count': 1, 'image_snapshot_count': 1})
        callback('source_row_processed', {'target_label': 'California', 'accepted_total': 3, 'hls_count': 2, 'image_snapshot_count': 1})
        callback('coordinate_enrichment_started', {'target_label': 'California', 'unique': 3, 'already_coordinate_bearing': 1})
        callback('coordinate_candidate_processed', {'target_label': 'California', 'processed': 1, 'total': 3, 'coordinate_bearing': 1, 'metadata_enriched': 0, 'geocode_enriched': 0, 'llm_location_enriched': 0})
        callback('coordinate_candidate_processed', {'target_label': 'California', 'processed': 2, 'total': 3, 'coordinate_bearing': 2, 'metadata_enriched': 1, 'geocode_enriched': 0, 'llm_location_enriched': 0})
        callback('coordinate_enrichment_complete', {'target_label': 'California', 'total': 3, 'coordinate_bearing': 2, 'metadata_enriched': 1, 'geocode_enriched': 0, 'llm_location_enriched': 0})
        callback('discovery_complete', {'target_label': 'California', 'raw': 3, 'unique': 3, 'coordinate_bearing': 2})
    assert state['total'] == 3
    assert state['completed'] == 3
    assert state['coord_total'] == 3
    assert state['coord_completed'] == 2


def test_cli_plain_progress_callback_is_low_noise(tmp_path):
    output = tmp_path / 'plain_progress.out'
    with output.open('w', encoding='utf-8') as fh:
        console = Console(file=fh, force_terminal=False, width=120)
        state = {'total': 0, 'completed': 0}
        callback = _make_plain_discovery_progress_callback(console, state, threading.Lock())
        callback('source_rows_loading', {'target_label': 'California'})
        callback('source_rows_selected', {'target_label': 'California', 'selected_rows': 100, 'discovered_rows': 150, 'primary_rows': 100})
        for i in range(1, 101):
            callback(
                'source_row_processed',
                {
                    'target_label': 'California',
                    'processed_rows': i,
                    'rows': 100,
                    'accepted_total': i,
                    'hls_count': i // 2,
                    'image_snapshot_count': i // 2,
                },
            )
        callback('coordinate_enrichment_started', {'target_label': 'California', 'unique': 80})
        callback('scope_review_started', {'target_label': 'California'})
        callback('discovery_complete', {'target_label': 'California', 'raw': 100, 'unique': 80, 'coordinate_bearing': 25})
    text = output.read_text(encoding='utf-8')
    assert 'Progress: California — scanning 100 source rows' in text
    assert 'Progress: California — discovery complete: raw 100, unique 80, mapped 25.' in text
    # The plain renderer should summarize progress in coarse milestones, not emit one line per source row.
    assert text.count('scanned') <= 12
    assert text.count('Resolved targets') == 0


def test_cli_progress_mode_auto_uses_plain_for_non_terminal(tmp_path):
    output = tmp_path / 'console.out'
    with output.open('w', encoding='utf-8') as fh:
        console = Console(file=fh, force_terminal=False)
        assert _resolve_progress_mode(console, enabled=True, style='auto') == 'plain'
        assert _resolve_progress_mode(console, enabled=True, style='plain') == 'plain'
        assert _resolve_progress_mode(console, enabled=True, style='rich') == 'rich'
        assert _resolve_progress_mode(console, enabled=False, style='rich') == 'off'


def test_cli_run_help_exposes_progress_toggle():
    result = subprocess.run(
        [sys.executable, '-m', 'camera_discovery.cli', 'run', '--help'],
        text=True,
        capture_output=True,
        check=True,
    )
    assert '--progress' in result.stdout
    assert '--no-progress' in result.stdout
    assert '--progress-style' in result.stdout


def test_rich_progress_callback_tracks_coordinate_enrichment():
    console = Console(file=open('/tmp/camera_discovery_coordinate_progress_test.out', 'w'), force_terminal=False)
    progress = Progress(console=console, transient=True, disable=True)
    with progress:
        task_id = progress.add_task('Discovering target', total=None)
        state = {'total': 0, 'completed': 0}
        callback = _make_discovery_progress_callback(progress, task_id, state, threading.Lock())
        callback('coordinate_enrichment_started', {'target_label': 'California', 'unique': 500, 'already_coordinate_bearing': 117})
        assert state['total'] == 500
        assert state['completed'] == 0
        callback('coordinate_candidate_processed', {'target_label': 'California', 'processed': 250, 'total': 500, 'coordinate_bearing': 220, 'metadata_enriched': 10, 'geocode_enriched': 30, 'llm_location_enriched': 20})
        assert state['completed'] == 250
        callback('coordinate_enrichment_complete', {'target_label': 'California', 'total': 500, 'coordinate_bearing': 360, 'metadata_enriched': 25, 'geocode_enriched': 80, 'llm_location_enriched': 40})
        task = progress.tasks[task_id]
        assert task.completed == 500
        assert task.total == 500


def test_rich_validation_progress_callback_tracks_candidate_counts():
    from camera_discovery.cli import _make_rich_validation_progress_callback
    console = Console(file=open('/tmp/camera_discovery_validation_progress_test.out', 'w'), force_terminal=False)
    progress = Progress(console=console, transient=True, disable=True)
    with progress:
        callback = _make_rich_validation_progress_callback(progress, threading.Lock())
        callback('hls_validation_started', {'total': 3, 'live': 0, 'dead': 0, 'restricted': 0, 'decode_failed': 0, 'static_image_asset': 0, 'unknown': 0})
        callback('hls_validation_processed', {'processed': 1, 'total': 3, 'live': 1, 'dead': 0, 'restricted': 0, 'decode_failed': 0, 'static_image_asset': 0, 'unknown': 0})
        callback('hls_validation_processed', {'processed': 2, 'total': 3, 'live': 1, 'dead': 1, 'restricted': 0, 'decode_failed': 0, 'static_image_asset': 0, 'unknown': 0})
        hls_tasks = [task for task in progress.tasks if 'HLS' in task.description]
        assert hls_tasks
        assert hls_tasks[0].completed == 2
        assert hls_tasks[0].total == 3
