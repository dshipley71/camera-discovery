from __future__ import annotations

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

from .models import DiscoveryMode, HarvestConfig, HarvestInputMode, RunConfig, RuntimeProfile

_ALLOWED_BROWSER_BACKENDS = {"playwright", "cloakbrowser"}


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


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _split_csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [part.strip() for part in value.split(",") if part.strip()]


def _deprecated_max_streams_env(default: int) -> int:
    if "CAMERA_DISCOVERY_MAX_STREAMS" in os.environ:
        warnings.warn(
            "CAMERA_DISCOVERY_MAX_STREAMS is deprecated; use "
            "CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES plus "
            "CAMERA_DISCOVERY_MAX_HLS_CANDIDATES and "
            "CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    return _int_env("CAMERA_DISCOVERY_MAX_STREAMS", default)



def _repo_root_sources_file() -> Path | None:
    """Return the repository-root SOURCES.md when running from an editable checkout."""

    # src/camera_discovery/core/config.py -> src/camera_discovery/core ->
    # src/camera_discovery -> src -> repository root
    candidate = Path(__file__).resolve().parents[3] / "SOURCES.md"
    return candidate if candidate.exists() else None


def _resolve_sources_file(value: str | Path | None, *, explicit: bool) -> Path | None:
    """Resolve SOURCES.md robustly for CLI runs launched outside the repo root.

    Explicit paths keep their historical current-working-directory behavior unless
    they are exactly the default SOURCES.md name and are missing from cwd. The
    implicit default also falls back to the editable repository root so notebook
    and console-script runs still use the checked-in source registry.
    """

    if value is None:
        return None
    path = Path(value).expanduser()
    if path.is_absolute() or path.exists():
        return path
    if path.name == "SOURCES.md" and path.parent == Path("."):
        root_sources = _repo_root_sources_file()
        if root_sources is not None and (not explicit or not path.exists()):
            return root_sources
    return path


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



def _browser_backend_env() -> str:
    backend = os.getenv("CAMERA_DISCOVERY_BROWSER_BACKEND", "playwright").strip().lower()
    if backend not in _ALLOWED_BROWSER_BACKENDS:
        allowed = ", ".join(sorted(_ALLOWED_BROWSER_BACKENDS))
        raise ValueError(f"Invalid CAMERA_DISCOVERY_BROWSER_BACKEND={backend!r}; expected one of: {allowed}")
    return backend


def load_run_config(
    query: str,
    output_dir: str | Path,
    *,
    profile: str | None = None,
    seed_urls: list[str] | None = None,
    sources_file: str | Path | None = None,
    discovery_mode: str | None = None,
    block_patterns: list[str] | None = None,
    harvest_input: str | Path | None = None,
    harvest_input_mode: str | HarvestInputMode | None = None,
    browser_backend: str | None = None,
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
    discovery_mode_value = discovery_mode or os.getenv("CAMERA_DISCOVERY_DISCOVERY_MODE") or "both"
    selected_discovery_mode = DiscoveryMode(discovery_mode_value.strip().lower())
    harvest_mode_value = harvest_input_mode or os.getenv("CAMERA_DISCOVERY_HARVEST_INPUT_MODE") or "handoff-only"
    selected_harvest_input_mode = HarvestInputMode(str(harvest_mode_value).strip().lower())
    configured_browser_backend = (browser_backend or _browser_backend_env()).strip().lower()
    if configured_browser_backend not in _ALLOWED_BROWSER_BACKENDS:
        allowed = ", ".join(sorted(_ALLOWED_BROWSER_BACKENDS))
        raise ValueError(f"Invalid browser backend {configured_browser_backend!r}; expected one of: {allowed}")
    configured_sources_value = sources_file or os.getenv("CAMERA_DISCOVERY_SOURCES_FILE") or "SOURCES.md"
    sources_file_explicit = sources_file is not None or bool(os.getenv("CAMERA_DISCOVERY_SOURCES_FILE"))
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
        max_streams=_deprecated_max_streams_env(max_total_candidates),
        max_directory_pages=max(1, _int_env("CAMERA_DISCOVERY_MAX_DIRECTORY_PAGES", 8)),
        max_structured_endpoints_per_page=max(1, _int_env("CAMERA_DISCOVERY_MAX_STRUCTURED_ENDPOINTS_PER_PAGE", 20)),
        enable_browser_capture=_bool_env("CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE", True),
        browser_backend=configured_browser_backend,
        browser_capture_timeout_ms=max(1000, _int_env("CAMERA_DISCOVERY_BROWSER_CAPTURE_TIMEOUT_MS", 15000)),
        browser_capture_min_score=max(0, _int_env("CAMERA_DISCOVERY_BROWSER_CAPTURE_MIN_SCORE", 3)),
        max_browser_capture_pages=max(0, _int_env("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES", 20)),
        max_browser_capture_pages_blind=max(0, _int_env("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_BLIND", 6)),
        max_browser_capture_pages_directory=max(0, _int_env("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_DIRECTORY", 12)),
        max_browser_capture_pages_per_host=max(0, _int_env("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_PER_HOST", 3)),
        browser_capture_settle_ms=max(0, _int_env("CAMERA_DISCOVERY_BROWSER_CAPTURE_SETTLE_MS", 1000)),
        browser_capture_scroll=_bool_env("CAMERA_DISCOVERY_BROWSER_CAPTURE_SCROLL", False),
        max_browser_json_endpoints_per_page=max(0, _int_env("CAMERA_DISCOVERY_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE", 10)),
        max_browser_network_events_logged_per_page=max(0, _int_env("CAMERA_DISCOVERY_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE", 50)),
        asset_host_promotion_threshold=max(2, _int_env("CAMERA_DISCOVERY_ASSET_HOST_PROMOTION_THRESHOLD", 3)),
        max_state_scale_candidate_geocodes=max(0, _int_env("CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES", max_total_candidates)),
        http_timeout=_float_env("CAMERA_DISCOVERY_HTTP_TIMEOUT", 20.0),
        seed_urls=seed_urls or [],
        sources_file=_resolve_sources_file(configured_sources_value, explicit=sources_file_explicit),
        discovery_mode=selected_discovery_mode,
        block_patterns=block_patterns or _split_csv_env("CAMERA_DISCOVERY_BLOCK_PATTERNS"),
        enable_candidate_geocoding=_bool_env("CAMERA_DISCOVERY_ENABLE_CANDIDATE_GEOCODING", True),
        max_candidate_geocodes=max(0, _int_env("CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES", max_total_candidates)),
        image_snapshot_refresh_delay_seconds=max(0.0, _float_env("CAMERA_DISCOVERY_IMAGE_SNAPSHOT_REFRESH_DELAY_SECONDS", 2.0)),
        harvest_input=Path(harvest_input).expanduser() if harvest_input else None,
        harvest_input_mode=selected_harvest_input_mode,
    )


def load_harvest_config(
    query: str,
    output_dir: str | Path,
    *,
    seed_urls: list[str] | None = None,
    seed_file: str | Path | None = None,
    sources_file: str | Path | None = None,
    discovery_mode: str | None = None,
    block_patterns: list[str] | None = None,
    max_urls: int | None = None,
    media: list[str] | None = None,
    max_search_queries: int | None = None,
    max_search_results_per_query: int | None = None,
    max_source_rows: int | None = None,
    max_pages_per_source: int | None = None,
    max_structured_endpoints_per_page: int | None = None,
    enable_browser_capture: bool | None = None,
    browser_backend: str | None = None,
    max_browser_pages: int | None = None,
    max_browser_pages_per_host: int | None = None,
    include_source_metadata: bool = True,
    write_intermediate_records: bool | None = None,
    image_asset_filter: str | None = None,
) -> HarvestConfig:
    """Load extraction-only harvest configuration.

    Harvest mode intentionally has no LLM, target-resolution, geocoding, trust,
    validation, GeoJSON, or review-package settings. It reuses only public source
    policy, HTTP, search, browser, and crawl-budget settings.
    """
    load_dotenv(override=False)
    configured_sources_value = sources_file or os.getenv("CAMERA_DISCOVERY_SOURCES_FILE") or "SOURCES.md"
    sources_file_explicit = sources_file is not None or bool(os.getenv("CAMERA_DISCOVERY_SOURCES_FILE"))
    discovery_mode_value = discovery_mode or os.getenv("CAMERA_DISCOVERY_DISCOVERY_MODE") or "both"
    selected_discovery_mode = DiscoveryMode(discovery_mode_value.strip().lower())
    configured_browser_backend = (browser_backend or _browser_backend_env()).strip().lower()
    configured_image_asset_filter = (image_asset_filter or os.getenv("CAMERA_DISCOVERY_HARVEST_IMAGE_ASSET_FILTER") or "raw").strip().lower()
    if configured_image_asset_filter not in {"raw", "exclude-page-assets", "camera-evidence"}:
        raise ValueError("Invalid image asset filter {!r}; expected one of: raw, exclude-page-assets, camera-evidence".format(configured_image_asset_filter))
    if configured_browser_backend not in _ALLOWED_BROWSER_BACKENDS:
        allowed = ", ".join(sorted(_ALLOWED_BROWSER_BACKENDS))
        raise ValueError(f"Invalid browser backend {configured_browser_backend!r}; expected one of: {allowed}")
    return HarvestConfig(
        query=query,
        output_dir=Path(output_dir),
        discovery_mode=selected_discovery_mode,
        seed_urls=seed_urls or [],
        seed_file=Path(seed_file).expanduser() if seed_file else None,
        sources_file=_resolve_sources_file(configured_sources_value, explicit=sources_file_explicit),
        block_patterns=block_patterns or _split_csv_env("CAMERA_DISCOVERY_BLOCK_PATTERNS"),
        max_urls=max(0, int(max_urls if max_urls is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_URLS", 10000))),
        media=media or [],
        max_search_queries=max(0, int(max_search_queries if max_search_queries is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_SEARCH_QUERIES", _int_env("CAMERA_DISCOVERY_MAX_SEARCH_QUERIES", 40)))),
        max_search_results_per_query=max(0, int(max_search_results_per_query if max_search_results_per_query is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_SEARCH_RESULTS_PER_QUERY", _int_env("CAMERA_DISCOVERY_MAX_SEARCH_RESULTS_PER_QUERY", 50)))),
        max_source_rows=max(0, int(max_source_rows if max_source_rows is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_SOURCE_ROWS", 5000))),
        max_pages_per_source=max(1, int(max_pages_per_source if max_pages_per_source is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_PAGES_PER_SOURCE", _int_env("CAMERA_DISCOVERY_MAX_DIRECTORY_PAGES", 25)))),
        max_structured_endpoints_per_page=max(0, int(max_structured_endpoints_per_page if max_structured_endpoints_per_page is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_STRUCTURED_ENDPOINTS_PER_PAGE", _int_env("CAMERA_DISCOVERY_MAX_STRUCTURED_ENDPOINTS_PER_PAGE", 500)))),
        enable_browser_capture=_bool_env("CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE", True) if enable_browser_capture is None else bool(enable_browser_capture),
        browser_backend=configured_browser_backend,
        browser_capture_timeout_ms=max(1000, _int_env("CAMERA_DISCOVERY_BROWSER_CAPTURE_TIMEOUT_MS", 15000)),
        browser_capture_settle_ms=max(0, _int_env("CAMERA_DISCOVERY_BROWSER_CAPTURE_SETTLE_MS", 1000)),
        browser_capture_scroll=_bool_env("CAMERA_DISCOVERY_BROWSER_CAPTURE_SCROLL", False),
        max_browser_pages=max(0, int(max_browser_pages if max_browser_pages is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_PAGES", _int_env("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES", 1000)))),
        max_browser_pages_per_host=max(0, int(max_browser_pages_per_host if max_browser_pages_per_host is not None else _int_env("CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_PAGES_PER_HOST", _int_env("CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_PER_HOST", 100)))),
        max_browser_json_endpoints_per_page=max(0, _int_env("CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE", _int_env("CAMERA_DISCOVERY_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE", 100))),
        max_browser_network_events_logged_per_page=max(0, _int_env("CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE", _int_env("CAMERA_DISCOVERY_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE", 100))),
        include_source_metadata=include_source_metadata,
        write_intermediate_records=_bool_env("CAMERA_DISCOVERY_HARVEST_WRITE_INTERMEDIATE_RECORDS", False) if write_intermediate_records is None else bool(write_intermediate_records),
        image_asset_filter=configured_image_asset_filter,
        http_timeout=_float_env("CAMERA_DISCOVERY_HTTP_TIMEOUT", 20.0),
        user_agent=os.getenv("CAMERA_DISCOVERY_USER_AGENT", "camera-discovery/0.1 (+public-camera-research)"),
    )
