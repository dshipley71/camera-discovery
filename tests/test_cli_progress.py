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
        callback('discovery_complete', {'target_label': 'California', 'raw': 3, 'unique': 3, 'coordinate_bearing': 1})
    assert state['total'] == 3
    assert state['completed'] == 3


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
