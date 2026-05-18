from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .models import DiscoveryMode, RunConfig, RuntimeProfile


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _stage_model(stage_var: str, llm_model: str | None, default: str = "gemma3:4b-cloud") -> str | None:
    return os.getenv(stage_var) or llm_model or default


def load_run_config(
    query: str,
    output_dir: str | Path,
    *,
    profile: str | None = None,
    seed_urls: list[str] | None = None,
    sources_file: str | Path | None = None,
    discovery_mode: str | None = None,
    block_patterns: list[str] | None = None,
) -> RunConfig:
    load_dotenv(override=False)
    selected_profile = RuntimeProfile(profile or os.getenv("CAMERA_DISCOVERY_PROFILE", "fast").strip().lower())
    provider = os.getenv("CAMERA_DISCOVERY_LLM_PROVIDER", "ollama").strip().lower()
    llm_model = (
        os.getenv("CAMERA_DISCOVERY_LLM_MODEL")
        or os.getenv("OLLAMA_MODEL")
        or os.getenv("OPENAI_COMPATIBLE_MODEL")
        or os.getenv("BEDROCK_MODEL_ID")
        or "gemma3:4b-cloud"
    )
    selected_discovery_mode = DiscoveryMode((discovery_mode or os.getenv("CAMERA_DISCOVERY_DISCOVERY_MODE", "both")).strip().lower())
    configured_sources_file = sources_file or os.getenv("CAMERA_DISCOVERY_SOURCES_FILE") or "SOURCES.md"
    return RunConfig(
        query=query,
        output_dir=Path(output_dir),
        profile=selected_profile,
        llm_provider=provider,
        llm_model=llm_model,
        target_intent_model=_stage_model("CAMERA_DISCOVERY_TARGET_INTENT_MODEL", llm_model),
        geocoder_referee_model=_stage_model("CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL", llm_model),
        candidate_review_model=_stage_model("CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL", llm_model),
        target_intent_timeout=_float_env("CAMERA_DISCOVERY_TARGET_INTENT_TIMEOUT", 45.0),
        geocoder_referee_timeout=_float_env("CAMERA_DISCOVERY_GEOCODER_REFEREE_TIMEOUT", 45.0),
        candidate_review_timeout=_float_env("CAMERA_DISCOVERY_CANDIDATE_REVIEW_TIMEOUT", 45.0),
        candidate_review_batch_size=max(1, _int_env("CAMERA_DISCOVERY_CANDIDATE_REVIEW_BATCH_SIZE", 8)),
        max_candidate_reviews=max(0, _int_env("CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS", 50)),
        max_search_queries=_int_env("CAMERA_DISCOVERY_MAX_SEARCH_QUERIES", 4),
        max_search_results_per_query=_int_env("CAMERA_DISCOVERY_MAX_SEARCH_RESULTS_PER_QUERY", 5),
        max_pages=_int_env("CAMERA_DISCOVERY_MAX_PAGES", 25),
        max_streams=_int_env("CAMERA_DISCOVERY_MAX_STREAMS", 100),
        http_timeout=_float_env("CAMERA_DISCOVERY_HTTP_TIMEOUT", 20.0),
        seed_urls=seed_urls or [],
        sources_file=Path(configured_sources_file).expanduser() if configured_sources_file else None,
        discovery_mode=selected_discovery_mode,
        block_patterns=block_patterns or _split_csv_env("CAMERA_DISCOVERY_BLOCK_PATTERNS"),
        enable_candidate_geocoding=_bool_env("CAMERA_DISCOVERY_ENABLE_CANDIDATE_GEOCODING", True),
        max_candidate_geocodes=_int_env("CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES", 25),
    )


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _split_csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [part.strip() for part in value.split(",") if part.strip()]
