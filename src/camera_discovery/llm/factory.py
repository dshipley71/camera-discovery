from __future__ import annotations

import os

from camera_discovery.core.models import RunConfig

from .base import LLMClient
from .bedrock import BedrockConverseClient
from .ollama import OllamaClient
from .openai_compatible import OpenAICompatibleClient

SUPPORTED_PROVIDERS = {"ollama", "ollama-cloud", "openai", "openai-compatible", "openai_compatible", "bedrock"}


class LLMConfigurationError(ValueError):
    """Raised when a required LLM provider or model is missing or unsupported."""


def build_llm_client(provider: str | None, model: str | None, *, timeout: float = 45.0) -> LLMClient:
    resolved_provider = (provider or "").strip().lower()
    if not resolved_provider:
        raise LLMConfigurationError(
            "No LLM provider configured. Set CAMERA_DISCOVERY_LLM_PROVIDER to one of: "
            "ollama, ollama-cloud, openai-compatible, bedrock."
        )
    if resolved_provider not in SUPPORTED_PROVIDERS:
        raise LLMConfigurationError(
            f"Unsupported LLM provider {resolved_provider!r}. Expected one of: "
            "ollama, ollama-cloud, openai-compatible, bedrock."
        )
    if not model or not str(model).strip():
        raise LLMConfigurationError(f"No LLM model configured for provider {resolved_provider!r}.")
    resolved_model = str(model).strip()
    if resolved_provider == "ollama-cloud":
        return OllamaClient(
            model=resolved_model,
            base_url=os.getenv("OLLAMA_BASE_URL") or "https://ollama.com",
            timeout=timeout,
        )
    if resolved_provider == "ollama":
        return OllamaClient(model=resolved_model, timeout=timeout)
    if resolved_provider in {"openai", "openai-compatible", "openai_compatible"}:
        return OpenAICompatibleClient(model=resolved_model, timeout=timeout)
    if resolved_provider == "bedrock":
        return BedrockConverseClient(model=resolved_model, timeout=timeout)
    raise LLMConfigurationError(f"Unsupported LLM provider {resolved_provider!r}.")


def _provider(stage_var: str, config: RunConfig) -> str:
    return (os.getenv(stage_var) or config.llm_provider).strip().lower()


def _model(stage_var: str, configured: str | None, config: RunConfig) -> str | None:
    return os.getenv(stage_var) or configured or config.llm_model


def build_target_intent_client(config: RunConfig) -> LLMClient:
    return build_llm_client(
        _provider("CAMERA_DISCOVERY_TARGET_INTENT_PROVIDER", config),
        _model("CAMERA_DISCOVERY_TARGET_INTENT_MODEL", config.target_intent_model, config),
        timeout=config.target_intent_timeout,
    )


def build_geocoder_referee_client(config: RunConfig) -> LLMClient:
    return build_llm_client(
        _provider("CAMERA_DISCOVERY_GEOCODER_REFEREE_PROVIDER", config),
        _model("CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL", config.geocoder_referee_model, config),
        timeout=config.geocoder_referee_timeout,
    )


def build_candidate_review_client(config: RunConfig) -> LLMClient:
    return build_llm_client(
        _provider("CAMERA_DISCOVERY_CANDIDATE_REVIEW_PROVIDER", config),
        _model("CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL", config.candidate_review_model, config),
        timeout=config.candidate_review_timeout,
    )
