import pytest

from camera_discovery.core.models import RunConfig
from camera_discovery.llm.factory import LLMConfigurationError, build_llm_client, build_target_intent_client


def test_unsupported_llm_provider_is_rejected(tmp_path):
    cfg = RunConfig(query="public live cameras in Virginia", output_dir=tmp_path, llm_provider="unsupported", llm_model="model-id")
    with pytest.raises(LLMConfigurationError):
        build_target_intent_client(cfg)


def test_missing_llm_provider_is_rejected():
    with pytest.raises(LLMConfigurationError):
        build_llm_client("", "model-id")


def test_missing_llm_model_is_rejected():
    with pytest.raises(LLMConfigurationError):
        build_llm_client("ollama", None)


def test_target_intent_uses_configured_model(tmp_path):
    cfg = RunConfig(
        query="public live cameras in Virginia",
        output_dir=tmp_path,
        llm_provider="ollama",
        llm_model="gemma4:31b-cloud",
        target_intent_model="qwen3.5:4b",
    )
    client = build_target_intent_client(cfg)
    assert client.model == "qwen3.5:4b"


def test_ollama_cloud_provider_defaults_to_cloud_endpoint(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    client = build_llm_client("ollama-cloud", "qwen3.5:4b")
    assert getattr(client, "base_url") == "https://ollama.com"


def test_load_run_config_uses_requested_cloud_defaults_and_derived_caps(tmp_path, monkeypatch):
    from camera_discovery.core.config import load_run_config
    for name in list(monkeypatch.context().__dict__.keys()):
        pass
    for name in [
        "CAMERA_DISCOVERY_LLM_PROVIDER",
        "CAMERA_DISCOVERY_LLM_MODEL",
        "CAMERA_DISCOVERY_TARGET_INTENT_MODEL",
        "CAMERA_DISCOVERY_TARGET_INTENT_FALLBACK_MODEL",
        "CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL",
        "CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL",
        "CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL",
        "CAMERA_DISCOVERY_TARGET_INTENT_ATTEMPTS",
        "CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES",
        "CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES",
        "CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES",
        "CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS",
        "CAMERA_DISCOVERY_MAX_LLM_LOCATION_INFERENCES",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_HLS_CANDIDATES", "7")
    monkeypatch.setenv("CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES", "3")
    cfg = load_run_config("Get cameras from California", tmp_path)
    assert cfg.llm_provider == "ollama-cloud"
    assert cfg.llm_model == "gemma4:31b-cloud"
    assert cfg.target_intent_model == "gemma3:12b-cloud"
    assert cfg.target_intent_fallback_model == "gemma3:12b-cloud"
    assert cfg.geocoder_referee_model == "gemma4:31b-cloud"
    assert cfg.location_inference_model == "gemma4:31b-cloud"
    assert cfg.candidate_review_model == "gemma3:12b-cloud"
    assert cfg.target_intent_attempts == 2
    assert cfg.max_total_candidates == 10
    assert cfg.max_candidate_geocodes == 10
    assert cfg.max_state_scale_candidate_geocodes == 10
    assert cfg.max_candidate_reviews == 10
    assert not hasattr(cfg, "max_llm_location_inferences")
    assert not hasattr(cfg, "max_streams")
