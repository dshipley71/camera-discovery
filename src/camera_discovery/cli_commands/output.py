from __future__ import annotations

from camera_discovery.core.models import RunConfig


def friendly_llm_error(exc: Exception, cfg: RunConfig) -> str | None:
    text = repr(exc)
    lowered = text.casefold()
    if "401" not in lowered and "unauthorized" not in lowered and "api_key" not in lowered and "authentication" not in lowered:
        return None
    provider = (cfg.llm_provider or "unknown").strip().lower()
    model = cfg.target_intent_model or cfg.geocoder_referee_model or cfg.llm_model or "unknown"
    key_hint = "OLLAMA_API_KEY" if provider in {"ollama", "ollama-cloud"} else "OPENAI_COMPATIBLE_API_KEY" if provider in {"openai", "openai-compatible", "openai_compatible"} else "AWS credentials" if provider == "bedrock" else "provider credentials"
    return (
        "LLM provider authentication/configuration failed while resolving the target query. "
        f"Provider: {provider}; model: {model}. "
        f"Set/verify {key_hint} or select a provider with valid credentials."
    )
