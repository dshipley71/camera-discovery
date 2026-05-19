from __future__ import annotations

import os
from typing import Any

from camera_discovery.core.models import RunConfig

from .base import ChatMessage, LLMClient
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


def build_location_inference_client(config: RunConfig) -> LLMClient:
    return build_llm_client(
        _provider("CAMERA_DISCOVERY_LOCATION_INFERENCE_PROVIDER", config),
        _model("CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL", config.location_inference_model, config),
        timeout=config.location_inference_timeout,
    )


def build_candidate_review_client(config: RunConfig) -> LLMClient:
    return build_llm_client(
        _provider("CAMERA_DISCOVERY_CANDIDATE_REVIEW_PROVIDER", config),
        _model("CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL", config.candidate_review_model, config),
        timeout=config.candidate_review_timeout,
    )


def preflight_llm_client(client: LLMClient) -> dict[str, Any]:
    preflight = getattr(client, "preflight", None)
    if callable(preflight):
        result = preflight()
        return result if isinstance(result, dict) else {"ok": bool(result), "model": getattr(client, "model", None)}
    try:
        raw = client.chat([ChatMessage("user", "Return exactly: ok")], temperature=0.0)  # type: ignore[name-defined]
        return {"ok": bool(str(raw).strip()), "model": getattr(client, "model", None), "provider": type(client).__name__}
    except Exception as exc:
        return {"ok": False, "model": getattr(client, "model", None), "provider": type(client).__name__, "error_type": type(exc).__name__, "error": str(exc)[:1000]}


def preflight_llm_services(config: RunConfig) -> dict[str, Any]:
    stages = {
        "target_intent": ("CAMERA_DISCOVERY_TARGET_INTENT_PROVIDER", "CAMERA_DISCOVERY_TARGET_INTENT_MODEL", config.target_intent_model, config.target_intent_timeout),
        "geocoder_referee": ("CAMERA_DISCOVERY_GEOCODER_REFEREE_PROVIDER", "CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL", config.geocoder_referee_model, config.geocoder_referee_timeout),
        "location_inference": ("CAMERA_DISCOVERY_LOCATION_INFERENCE_PROVIDER", "CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL", config.location_inference_model, config.location_inference_timeout),
        "candidate_review": ("CAMERA_DISCOVERY_CANDIDATE_REVIEW_PROVIDER", "CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL", config.candidate_review_model, config.candidate_review_timeout),
    }
    summary: dict[str, Any] = {"enabled": bool(getattr(config, "enable_llm_preflight", True)), "stages": {}}
    if not summary["enabled"]:
        summary["status"] = "skipped"
        return summary
    cache: dict[tuple[str, str | None], dict[str, Any]] = {}
    for stage, (provider_var, model_var, configured_model, timeout) in stages.items():
        if stage == "target_intent" and not bool(getattr(config, "enable_target_intent_llm", True)):
            summary["stages"][stage] = {"ok": True, "status": "skipped", "reason": "target_intent_llm_disabled"}
            continue
        if stage == "geocoder_referee" and not bool(getattr(config, "enable_geocoder_referee_llm", True)):
            summary["stages"][stage] = {"ok": True, "status": "skipped", "reason": "geocoder_referee_llm_disabled"}
            continue
        if stage == "location_inference" and not bool(getattr(config, "enable_llm_location_inference", True)):
            summary["stages"][stage] = {"ok": True, "status": "skipped", "reason": "location_inference_disabled"}
            continue
        if stage == "candidate_review" and int(getattr(config, "max_candidate_reviews", 0)) <= 0:
            summary["stages"][stage] = {"ok": True, "status": "skipped", "reason": "candidate_review_disabled"}
            continue
        provider = _provider(provider_var, config)
        model = _model(model_var, configured_model, config)
        key = (provider, model)
        if key not in cache:
            try:
                client = build_llm_client(provider, model, timeout=timeout)
                cache[key] = preflight_llm_client(client)
            except Exception as exc:
                cache[key] = {"ok": False, "provider": provider, "model": model, "error_type": type(exc).__name__, "error": str(exc)[:1000]}
        summary["stages"][stage] = dict(cache[key], provider=provider, model=model)
    summary["ok"] = all(bool(stage.get("ok")) for stage in summary["stages"].values())
    return summary
