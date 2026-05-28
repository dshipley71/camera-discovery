from __future__ import annotations

from camera_discovery.core.config import load_run_config
from camera_discovery.core.models import RunConfig


_PARAMETER_ENV_VARS = [
    "CAMERA_DISCOVERY_MAX_HLS_CANDIDATES",
    "CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES",
    "CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES",
    "CAMERA_DISCOVERY_MAX_LLM_LOCATION_INFERENCES",
    "CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS",
    "CAMERA_DISCOVERY_MAX_STREAMS",
    "CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES",
    "CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES",
]


def _clear_parameter_env(monkeypatch):
    for name in _PARAMETER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_candidate_budget_defaults_align_to_hls_plus_image_snapshot_caps(tmp_path, monkeypatch):
    _clear_parameter_env(monkeypatch)
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_HLS_CANDIDATES", "7")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES", "3")

    cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.max_hls_candidates == 7
    assert cfg.max_image_snapshot_candidates == 3
    assert cfg.max_total_candidates == 10
    assert cfg.max_llm_location_inferences == 10
    assert cfg.max_candidate_reviews == 10
    assert cfg.max_streams == 10
    assert cfg.max_candidate_geocodes == 10
    assert cfg.max_state_scale_candidate_geocodes == 10


def test_candidate_budget_explicit_overrides_are_still_honored(tmp_path, monkeypatch):
    _clear_parameter_env(monkeypatch)
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_HLS_CANDIDATES", "7")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES", "3")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES", "5")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_LLM_LOCATION_INFERENCES", "4")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS", "2")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES", "6")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES", "9")

    cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.max_total_candidates == 5
    assert cfg.max_llm_location_inferences == 4
    assert cfg.max_candidate_reviews == 2
    assert cfg.max_candidate_geocodes == 6
    assert cfg.max_state_scale_candidate_geocodes == 9


def test_run_config_builtin_defaults_are_aligned():
    cfg = RunConfig(query="Get cameras from Example City", output_dir="out")
    expected = cfg.max_hls_candidates + cfg.max_image_snapshot_candidates

    assert cfg.max_total_candidates == expected
    assert cfg.max_llm_location_inferences == expected
    assert cfg.max_candidate_reviews == expected
    assert cfg.max_streams == expected
    assert cfg.max_candidate_geocodes == expected
    assert cfg.max_state_scale_candidate_geocodes == expected


def test_explicit_deprecated_max_streams_env_still_works_and_warns(tmp_path, monkeypatch):
    _clear_parameter_env(monkeypatch)
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_STREAMS", "17")

    import pytest

    with pytest.warns(DeprecationWarning, match="CAMERA_DISCOVERY_MAX_STREAMS is deprecated"):
        cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.max_streams == 17


def test_default_sources_file_resolves_from_non_repo_working_directory(tmp_path, monkeypatch):
    from camera_discovery.core.config import load_harvest_config
    from camera_discovery.sources import load_source_policy

    monkeypatch.delenv("CAMERA_DISCOVERY_SOURCES_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    cfg = load_harvest_config("California traffic cameras", tmp_path / "harvest")
    assert cfg.sources_file is not None
    assert cfg.sources_file.name == "SOURCES.md"
    assert cfg.sources_file.exists()

    policy = load_source_policy(cfg.sources_file)
    assert len(policy.enabled_allowed_sources()) > 0


def test_run_config_http_timeout_cli_override_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_HTTP_TIMEOUT", "30")

    cfg = load_run_config("Get cameras from Example City", tmp_path, http_timeout=10)

    assert cfg.http_timeout == 10.0


def test_run_config_http_timeout_env_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_HTTP_TIMEOUT", "6")

    cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.http_timeout == 6.0


def test_run_config_rejects_non_positive_http_timeout(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="http-timeout"):
        load_run_config("Get cameras from Example City", tmp_path, http_timeout=0)


def test_run_config_validation_workers_env_is_clamped(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_DISCOVERY_VALIDATION_WORKERS", "999")

    cfg = load_run_config("Get cameras from Example City", tmp_path)

    assert cfg.validation_workers == 64
