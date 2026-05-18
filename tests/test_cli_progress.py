from camera_discovery.cli import _make_discovery_progress_callback
from rich.console import Console
from rich.progress import Progress
import threading


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


def test_cli_run_help_exposes_progress_toggle():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, '-m', 'camera_discovery.cli', 'run', '--help'],
        text=True,
        capture_output=True,
        check=True,
    )
    assert '--progress' in result.stdout
    assert '--no-progress' in result.stdout
