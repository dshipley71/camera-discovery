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


def _stage_model(stage_var: str, llm_model: str | None, default: str = "gemma3:4b") -> str | None:
    return os.getenv(stage_var) or llm_model or default


def _default_target_intent_model(provider: str, llm_model: str | None) -> str | None:
    explicit = os.getenv("CAMERA_DISCOVERY_TARGET_INTENT_MODEL")
    if explicit:
        return explicit
    if provider in {"ollama", "ollama-cloud"}:
        # Target intent is a lightweight extraction task. Keep it fast by
        # default while allowing users to override it independently.
        return "qwen3.5:4b"
    return llm_model


def _default_target_intent_fallback_model(provider: str) -> str | None:
    explicit = os.getenv("CAMERA_DISCOVERY_TARGET_INTENT_FALLBACK_MODEL")
    if explicit:
        return explicit
    if provider in {"ollama", "ollama-cloud"}:
        return "qwen3.5:4b"
    return None


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
    provider = os.getenv("CAMERA_DISCOVERY_LLM_PROVIDER", "ollama-cloud").strip().lower()
    default_llm_model = "gemma4:31b-cloud" if provider == "ollama-cloud" else "gemma3:4b"
    llm_model = (
        os.getenv("CAMERA_DISCOVERY_LLM_MODEL")
        or os.getenv("OLLAMA_MODEL")
        or os.getenv("OPENAI_COMPATIBLE_MODEL")
        or os.getenv("BEDROCK_MODEL_ID")
        or default_llm_model
    )
    selected_discovery_mode = DiscoveryMode((discovery_mode or os.getenv("CAMERA_DISCOVERY_DISCOVERY_MODE", "both")).strip().lower())
    configured_sources_file = sources_file or os.getenv("CAMERA_DISCOVERY_SOURCES_FILE") or "SOURCES.md"
    max_hls_candidates = max(0, _int_env("CAMERA_DISCOVERY_MAX_HLS_CANDIDATES", 100))
    max_image_snapshot_candidates = max(0, _int_env("CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES", 50))
    default_candidate_budget = max_hls_candidates + max_image_snapshot_candidates
    max_total_candidates = max(0, _int_env("CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES", default_candidate_budget))
    return RunConfig(
        query=query,
        output_dir=Path(output_dir),
        profile=selected_profile,
        llm_provider=provider,
        llm_model=llm_model,
        target_intent_model=_default_target_intent_model(provider, llm_model),
        target_intent_attempts=max(1, _int_env("CAMERA_DISCOVERY_TARGET_INTENT_ATTEMPTS", 1)),
        target_intent_fallback_model=_default_target_intent_fallback_model(provider),
        geocoder_referee_model=_stage_model("CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL", llm_model),
        location_inference_model=_stage_model("CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL", llm_model),
        candidate_review_model=_stage_model("CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL", llm_model),
        target_intent_timeout=_float_env("CAMERA_DISCOVERY_TARGET_INTENT_TIMEOUT", 45.0),
        geocoder_referee_timeout=_float_env("CAMERA_DISCOVERY_GEOCODER_REFEREE_TIMEOUT", 45.0),
        location_inference_timeout=_float_env("CAMERA_DISCOVERY_LOCATION_INFERENCE_TIMEOUT", 45.0),
        candidate_review_timeout=_float_env("CAMERA_DISCOVERY_CANDIDATE_REVIEW_TIMEOUT", 45.0),
        enable_llm_location_inference=_bool_env("CAMERA_DISCOVERY_ENABLE_LLM_LOCATION_INFERENCE", True),
        max_llm_location_inferences=max(0, _int_env("CAMERA_DISCOVERY_MAX_LLM_LOCATION_INFERENCES", max_total_candidates)),
        llm_location_inference_min_confidence=max(0.0, min(1.0, _float_env("CAMERA_DISCOVERY_LOCATION_INFERENCE_MIN_CONFIDENCE", 0.70))),
        candidate_review_batch_size=max(1, _int_env("CAMERA_DISCOVERY_CANDIDATE_REVIEW_BATCH_SIZE", 8)),
        max_candidate_reviews=max(0, _int_env("CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS", max_total_candidates)),
        max_search_queries=_int_env("CAMERA_DISCOVERY_MAX_SEARCH_QUERIES", 4),
        max_search_results_per_query=_int_env("CAMERA_DISCOVERY_MAX_SEARCH_RESULTS_PER_QUERY", 5),
        max_pages=_int_env("CAMERA_DISCOVERY_MAX_PAGES", 25),
        max_hls_candidates=max_hls_candidates,
        max_image_snapshot_candidates=max_image_snapshot_candidates,
        max_total_candidates=max_total_candidates,
        max_streams=_int_env("CAMERA_DISCOVERY_MAX_STREAMS", max_total_candidates),
        max_directory_pages=max(1, _int_env("CAMERA_DISCOVERY_MAX_DIRECTORY_PAGES", 8)),
        max_structured_endpoints_per_page=max(1, _int_env("CAMERA_DISCOVERY_MAX_STRUCTURED_ENDPOINTS_PER_PAGE", 20)),
        asset_host_promotion_threshold=max(2, _int_env("CAMERA_DISCOVERY_ASSET_HOST_PROMOTION_THRESHOLD", 3)),
        max_state_scale_candidate_geocodes=max(0, _int_env("CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES", 250)),
        http_timeout=_float_env("CAMERA_DISCOVERY_HTTP_TIMEOUT", 20.0),
        seed_urls=seed_urls or [],
        sources_file=Path(configured_sources_file).expanduser() if configured_sources_file else None,
        discovery_mode=selected_discovery_mode,
        block_patterns=block_patterns or _split_csv_env("CAMERA_DISCOVERY_BLOCK_PATTERNS"),
        enable_candidate_geocoding=_bool_env("CAMERA_DISCOVERY_ENABLE_CANDIDATE_GEOCODING", True),
        max_candidate_geocodes=_int_env("CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES", 25),
        image_snapshot_refresh_delay_seconds=max(0.0, _float_env("CAMERA_DISCOVERY_IMAGE_SNAPSHOT_REFRESH_DELAY_SECONDS", 2.0)),
    )


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _split_csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [part.strip() for part in value.split(",") if part.strip()]
