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


def test_load_run_config_uses_updated_ollama_cloud_default_models(monkeypatch, tmp_path):
    from camera_discovery.core.config import load_run_config

    for key in [
        "CAMERA_DISCOVERY_LLM_PROVIDER",
        "CAMERA_DISCOVERY_LLM_MODEL",
        "CAMERA_DISCOVERY_TARGET_INTENT_MODEL",
        "CAMERA_DISCOVERY_TARGET_INTENT_FALLBACK_MODEL",
        "CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL",
        "CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL",
        "CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL",
        "OLLAMA_MODEL",
        "OPENAI_COMPATIBLE_MODEL",
        "BEDROCK_MODEL_ID",
    ]:
        monkeypatch.delenv(key, raising=False)

    cfg = load_run_config("public cameras in California", tmp_path)

    assert cfg.llm_provider == "ollama-cloud"
    assert cfg.llm_model == "gemma3:27b-cloud"
    assert cfg.target_intent_model == "gemma3:12b-cloud"
    assert cfg.target_intent_fallback_model == "gemma3:12b-cloud"
    assert cfg.geocoder_referee_model == "gemma3:27b-cloud"
    assert cfg.location_inference_model == "gemma3:27b-cloud"
