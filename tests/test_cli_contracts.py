import subprocess
import sys


def test_cli_exposes_run_subcommand():
    result = subprocess.run(
        [sys.executable, "-m", "camera_discovery.cli", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "run" in result.stdout


def test_cli_run_help_exposes_http_timeout():
    result = subprocess.run(
        [sys.executable, "-m", "camera_discovery.cli", "run", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--http-timeout" in result.stdout
