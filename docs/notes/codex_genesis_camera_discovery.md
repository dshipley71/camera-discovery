# Genesis Prompt — camera-discovery v2 Ground-Up Rebuild

You are building `camera-discovery` from scratch. This is a complete, clean reimplementation of the public-camera discovery application. Do not port old code line-by-line. Use the behavioral specification below as the authoritative source of truth and implement it with the modern technology stack defined here.

The existing repository at `dshipley71/camera-discovery` (dev branch) contains a working reference implementation. Its behavioral rules, output artifact contracts, trust model, and domain logic are the reference. Its technology choices (synchronous code, plain `@dataclass` models, environment variables, monolithic service files) are explicitly replaced by the decisions in this prompt.

---

## Technology Stack — Non-Negotiable

| Concern | Choice |
|---|---|
| Python version | `>=3.11` — use `tomllib`, `TaskGroup`, `ExceptionGroup`, `except*`, `asyncio.timeout()`, `Self` |
| Data models | **Pydantic v2 `BaseModel`** for all domain models and config |
| Configuration | **TOML file** loaded with `tomllib` + CLI overrides. **Zero environment variables** anywhere in the application. |
| HTTP client | **`httpx.AsyncClient`** used as an async context manager per run. No sync `httpx.Client` in the pipeline. |
| Concurrency | **`asyncio`** throughout. `asyncio.gather`, `asyncio.TaskGroup`, `asyncio.Semaphore`, `asyncio.timeout()`. No `ThreadPoolExecutor` in the pipeline. |
| Async file I/O | **`asyncio.to_thread()`** wrapping sync `pathlib.Path` operations. No `aiofiles` dependency needed. |
| CLI | **`typer`** — all pipeline commands are sync wrappers that call `asyncio.run()` on an internal async function. See Async Patterns section. |
| API server | **`fastapi`** with `uvicorn`. Shares the same async pipeline as the CLI. Tested in standalone deployment only — not in Colab. |
| Browser capture | **`async_playwright`** (Playwright async API). **CloakBrowser is the default backend**; Playwright selectable as alternative. Both use the same async interface. |
| HTML parsing | `beautifulsoup4` with `lxml` parser where available, falling back to `html.parser` |
| Terminal output | `rich` |
| Logging | Python stdlib `logging` with a single root configuration in `cli.py` and `api/server.py` |
| Linting | `ruff` |
| Type checking | `mypy` |
| Testing | `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"`) and `respx` for httpx mocking |

**Environment variables are forbidden.** All configuration lives in a TOML file and/or CLI flags. There are no `CAMERA_DISCOVERY_*`, `OLLAMA_*`, `OPENAI_*`, `AWS_*`, or any other environment variable reads anywhere in the codebase. Colab notebooks populate the TOML config file from Colab Secrets via a setup cell.

---

## Non-Negotiable Behavioral Rules

1. **No fake runtime evidence.** Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime camera inventories anywhere in source code.
2. **No source-specific hacks.** Do not hard-code real-world locations, agencies, source domains, source-specific behavior, or one-off camera types. Generic media normalization, URL canonicalization, candidate-priority scoring, and diagnostics are allowed.
3. **LLMs are advisory only.** LLMs may interpret target intent, rank geocoder candidates, infer place-name queries from candidate evidence, and review semantic relevance. They must never invent coordinates or authorize trusted output. Deterministic code is authoritative for: bbox/geometry verification, coordinate acceptance, scope classification, media validation, trusted output authorization, and final artifact writing.
4. **Trust requires deterministic evidence.** Trusted output requires all of: verified target geometry + in-scope coordinates + successful media validation + `trust_policy = TrustPolicy.TRUSTED_ALLOWED`. The `fast` profile blocks trusted output because it skips validation.
5. **No browser success fabrication.** If a browser backend is missing or fails preflight, emit diagnostics and skip browser capture. Never fabricate browser capture success.
6. **Passive intelligence is evidence-only.** It scores already-discovered evidence. It must not scan networks, probe guessed URLs, brute-force RTSP paths, try credentials, or capture packets.
7. **Source block policy is global and authoritative.** Blocked patterns apply to blind search, directory rows, direct seeds, fetched pages, extracted media URLs, harvest outputs, and final candidates. Evidence score never bypasses block policy.
8. **Notebooks are separate.** Notebook-specific helper/display code belongs in `notebooks/`. Source modules must not import from `notebooks/`.
9. **RTSP is limited.** Support only RTSP URLs explicitly supplied by the user or verbatim-extracted from allowed public source content. Do not synthesize RTSP URLs, probe paths, or enumerate ports.
10. **Google dorking is on by default and bounded.** Queries must include a target/location term and a camera/media term. Never target device UIs, admin pages, credentials, vendor fingerprints, private networks, or blocked internet-asset search engines.
11. **Do not auto-edit `SOURCES.md`.** The file is user-managed. The application reads it; it never writes it.
12. **No test weakening.** Tests must protect behavior. Do not relax assertions to make a change pass.
13. **Private network requests are forbidden.** The application must never make HTTP requests to RFC 1918 private addresses, loopback addresses, or link-local addresses. See URL Safety section.

---

## Application Overview

`camera-discovery` has three top-level commands:

### 1. `camera-discovery run` — Discovery pipeline
Target-aware pipeline: config → target resolution → concurrent source discovery (DDG + Bing simultaneously + directory rows + direct seeds) → extraction → coordinate enrichment → passive intelligence scoring → candidate priority ordering → optional validation → artifact writing → optional map.

### 2. `camera-discovery harvest-urls` — Harvest pipeline
Extraction-only. Bypasses target resolution, geocoding, validation, trust, scope, LLM review, GeoJSON/maps, `cameras.md`, and review ZIP. Produces raw camera/media URL inventory and `harvest_handoff.json`.

### 3. `camera-discovery serve` — API server
FastAPI server wrapping both pipelines for UI consumption. Accepts discovery/harvest requests, streams progress via SSE, serves artifacts. Tested in standalone deployment — not in Colab.

---

## Complete Module Structure

```
src/camera_discovery/
  __init__.py                         # exports __version__ = "2.0.0"
  py.typed                            # PEP 561 marker — package is fully typed
  cli.py                              # Typer commands: run, harvest-urls, serve, status
  api/
    __init__.py
    server.py                         # FastAPI app factory + logging setup + uvicorn entry
    job_manager.py                    # Async in-memory job registry with asyncio.Lock
    routes/
      __init__.py
      discovery.py                    # POST /api/v1/discovery, GET /api/v1/discovery/{job_id}
      harvest.py                      # POST /api/v1/harvest, GET /api/v1/harvest/{job_id}
      progress.py                     # GET /api/v1/jobs/{job_id}/progress (SSE)
      artifacts.py                    # GET /api/v1/jobs/{job_id}/artifacts/{name}
      config.py                       # GET /api/v1/config (redacts secrets)
      health.py                       # GET /api/v1/health
    schemas.py                        # API request/response Pydantic models
  core/
    __init__.py
    config.py                         # TOML loading, AppConfig, RunConfig, HarvestConfig
    models.py                         # All domain Pydantic models
    progress.py                       # ProgressEvent model, async Queue publisher, event types
    exceptions.py                     # Custom exception hierarchy
  runners/
    __init__.py
    discovery_run.py                  # execute_discovery_run(config, queue) async
    harvest_run.py                    # execute_harvest_run(config, queue) async
  services/
    __init__.py
    target_resolver.py                # TargetResolver (async)
    discovery_engine.py               # CandidateDiscoveryEngine (async)
    harvest_engine.py                 # CameraUrlHarvestEngine (async)
    validation_pipeline.py            # ReviewAndValidationPipeline (async)
    harvest_handoff.py                # Harvest handoff manifest loader (async)
    structured_camera_records.py      # Structured camera-record extraction helpers
  targeting/
    __init__.py
    intent_parser.py                  # LLM target intent extraction (async)
    geocoder.py                       # Nominatim async geocoding — rate-limited, 1 req/sec
    geocoder_referee.py               # LLM advisory geocoder ranking (async, advisory only)
    trust_policy.py                   # Deterministic TrustPolicy evaluation
    geometry.py                       # Bbox padding, min-side, fallback geometry hierarchy
  discovery/
    __init__.py
    search_dispatcher.py              # SearchDispatcher (async, explicit constructor injection)
    source_rows.py                    # SourceRow adapters, SOURCES.md directory rows
    candidate_extraction.py           # Async extraction from pages/endpoints/records
    browser_capture.py                # Async CloakBrowser/Playwright preflight and capture
    candidate_processing.py           # URL normalization, scope classification, dedup
    candidate_priority.py             # Candidate ordering — geocoordinate-bearing Tier 1
    artifact_writer.py                # Discovery-stage artifact file writing
  extraction/
    __init__.py
    http.py                           # Async httpx retry helper
    html.py                           # HTML parsing helpers (BeautifulSoup + lxml/html.parser)
    media.py                          # Media detection, URL cleaning, canonicalization, dedupe
    json_records.py                   # JSON/GeoJSON/ArcGIS/FeatureServer record helpers
    pagination.py                     # Pagination and structured endpoint expansion
    browser.py                        # Browser backend/session helpers (shared)
    search/
      __init__.py
      ddg.py                          # DuckDuckGo HTML result parser
      bing.py                         # Bing HTML result parser
      queries.py                      # Comprehensive query generation — all camera types always
      dispatcher.py                   # SearchEngineDispatcher: DDG + Bing simultaneous parallel
  harvest/
    __init__.py
    source_dispatch.py                # Async source row loading and per-row dispatch
    media_filter.py                   # Media type parsing, filtering, quality scoring
    catalog.py                        # Records catalog management, JSONL upserts, run dedup
    output_writer.py                  # Harvest artifact file writing
  validation/
    __init__.py
    url_check.py                      # Async HTTP reachability, redirect, timeout
    media_probe.py                    # Async FFprobe, HLS playlist/segment checking
    browser_snap.py                   # Async CloakBrowser/Playwright screenshot capture
    llm_review.py                     # Async LLM quality scoring and content classification
  enrichment/
    __init__.py
    location.py                       # Async coordinate enrichment, LLM location inference
  passive_intelligence/
    __init__.py
    evidence.py                       # Source/candidate evidence scoring (0-100, deterministic)
    signatures.py                     # Safe passive camera/media signature matching
    protocol_labels.py                # Deterministic protocol/media-family labels
    http_metadata.py                  # Allowlisted HTTP metadata normalization and redaction
  sources/
    __init__.py
    registry.py                       # SOURCES.md parser and SourceEntry registry
    policy.py                         # Global block policy evaluation
    models.py                         # SourceEntry Pydantic model
  llm/
    __init__.py
    base.py                           # Abstract async LLM client protocol
    factory.py                        # Provider factory: builds correct client from config
    ollama.py                         # Ollama async client (local and ollama-cloud)
    openai_compatible.py              # OpenAI-compatible async client
    bedrock.py                        # AWS Bedrock async client (aiobotocore)
  utils/
    __init__.py
    io.py                             # asyncio.to_thread() wrappers for file I/O; JSON/JSONL helpers
    json_utils.py                     # JSON extraction, safe parsing, ensure_ascii=False writes
    geojson_viewer.py                 # Thin Python writer: loads template, substitutes, writes
    geojson_viewer_template.html      # Standalone Leaflet map HTML template
    playlists.py                      # M3U and TXT playlist export helpers
    url_safety.py                     # Private-network blocking, URL scheme validation
```

---

## Async Implementation Patterns — Non-Negotiable

### 1. Typer CLI async command pattern

Typer does not support `async def` commands. Every pipeline command must follow this wrapper pattern:

```python
import asyncio
import typer
from camera_discovery.runners.discovery_run import execute_discovery_run

app = typer.Typer()

@app.command("run")
def cmd_run(
    query: str,
    output_dir: Path = typer.Option(Path("./output"), "--output-dir", "-o"),
    # ... all other CLI options ...
) -> None:
    """Discover public cameras for a target location."""
    asyncio.run(_async_run(query, output_dir, ...))

async def _async_run(query: str, output_dir: Path, ...) -> None:
    config = load_config()
    run_config = build_run_config(config, query=query, output_dir=output_dir, ...)
    queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(execute_discovery_run(run_config, queue))
        tg.create_task(_drain_progress(queue, run_config.progress_style))
```

Never use `async def` directly as a Typer command callback.

### 2. `asyncio.TaskGroup` and `ExceptionGroup` handling

Python 3.11's `asyncio.TaskGroup` raises `ExceptionGroup` when any task fails. All code that uses `TaskGroup` must handle this with `except*`:

```python
try:
    async with asyncio.TaskGroup() as tg:
        search_task = tg.create_task(search_dispatcher.search_all(queries))
        dir_task    = tg.create_task(directory_provider.rows_for_target(target))
except* SearchEngineError as eg:
    # Log all search failures but continue — partial results are acceptable
    for exc in eg.exceptions:
        logger.warning("Search engine error: %s", exc)
    rows = dir_task.result() if not dir_task.cancelled() else []
except* Exception as eg:
    # Unexpected failures — re-raise as a single CameraDiscoveryError
    raise CameraDiscoveryError("Pipeline task group failed") from eg.exceptions[0]
```

Never use bare `except Exception` to catch `ExceptionGroup` — it will catch the group object but not unwrap the individual exceptions.

### 3. `httpx.AsyncClient` lifecycle

A single `httpx.AsyncClient` is created per pipeline run and passed explicitly to all async functions. It must be used as an async context manager to ensure connection pool cleanup on all exit paths:

```python
async def execute_discovery_run(config: RunConfig, queue: asyncio.Queue) -> RunState:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.discovery.http_timeout),
        follow_redirects=True,
        headers={"User-Agent": config.discovery.user_agent},
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    ) as http_client:
        engine = CandidateDiscoveryEngine(config, http_client, queue)
        return await engine.run()
```

Never create a new `httpx.AsyncClient` per request. Never use sync `httpx.Client` anywhere in the pipeline.

### 4. `asyncio.timeout()` for all timed operations

Use Python 3.11's `asyncio.timeout()` for every operation with a configured timeout:

```python
# LLM calls
async with asyncio.timeout(config.llm.stage_overrides.target_intent_timeout):
    result = await llm_client.complete(prompt)

# HTTP requests use httpx Timeout object (set at client construction)

# Browser capture
async with asyncio.timeout(config.browser.capture_timeout_ms / 1000):
    page_result = await browser_session.capture(url)
```

When a timeout fires, catch `asyncio.TimeoutError`, emit a progress event, and treat the operation as failed — never as successful.

### 5. Async file I/O with `asyncio.to_thread()`

`utils/io.py` provides all file I/O helpers. Use `asyncio.to_thread()` to run sync `pathlib.Path` operations off the event loop:

```python
import asyncio
import json
from pathlib import Path

async def write_json(path: Path, data: dict, /) -> None:
    """Write a JSON file asynchronously using asyncio.to_thread."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    await asyncio.to_thread(path.write_text, text, encoding="utf-8")

async def read_json(path: Path, /) -> dict:
    """Read a JSON file asynchronously using asyncio.to_thread."""
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    return json.loads(text)

async def append_jsonl(path: Path, record: dict, /) -> None:
    """Append one JSON record to a JSONL file asynchronously."""
    line = json.dumps(record, ensure_ascii=False) + "\n"
    await asyncio.to_thread(_append_text, path, line)

def _append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
```

Never call `path.write_text()`, `path.read_text()`, `open()`, or any sync file I/O directly from async functions.

### 6. Logging configuration

Configure Python's standard `logging` module once at application startup. Use `logging.getLogger(__name__)` in every module.

```python
# In cli.py and api/server.py — called once at startup
import logging
from rich.logging import RichHandler

def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
```

Every source module uses:
```python
import logging
logger = logging.getLogger(__name__)
```

Never use `print()` for diagnostic output inside `src/`. Use `logger.debug/info/warning/error`. Use `rich.console.Console` only in CLI output helpers (`cli_commands/`).

---

## Custom Exception Hierarchy

Define in `core/exceptions.py`. All application exceptions inherit from `CameraDiscoveryError`:

```python
class CameraDiscoveryError(Exception):
    """Base exception for all camera-discovery errors."""

class ConfigurationError(CameraDiscoveryError):
    """Invalid or missing configuration."""

class TargetResolutionError(CameraDiscoveryError):
    """Target resolution failed (geocoding, geometry, or trust-policy stop)."""

class GeocodeError(CameraDiscoveryError):
    """Nominatim geocoding error."""

class BrowserCaptureError(CameraDiscoveryError):
    """Browser backend unavailable or preflight failed."""

class LLMProviderError(CameraDiscoveryError):
    """LLM provider call failed or timed out."""

class HarvestError(CameraDiscoveryError):
    """Harvest pipeline error."""

class ValidationConfigError(CameraDiscoveryError):
    """Validation pipeline configured incorrectly."""

class URLSafetyError(CameraDiscoveryError):
    """URL blocked by safety policy (private network, forbidden scheme)."""
```

---

## URL Safety Specification

`utils/url_safety.py` must enforce the following rules before any HTTP request is made to a user-supplied or extracted URL.

### Private network blocking

Block requests to all of:
- Loopback: `127.0.0.0/8`, `::1`
- RFC 1918 private: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- Link-local: `169.254.0.0/16`, `fe80::/10`
- Multicast: `224.0.0.0/4`, `ff00::/8`
- Reserved/unspecified: `0.0.0.0`, `::`

```python
import ipaddress
from urllib.parse import urlparse

def is_safe_url(url: str) -> bool:
    """Return True if the URL is safe to fetch (not a private/reserved address)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https", "rtsp", "rtsps"}:
            return False
        host = parsed.hostname or ""
        addr = ipaddress.ip_address(host)  # raises ValueError for hostnames
        return addr.is_global and not addr.is_private
    except ValueError:
        # Hostname (not IP) — allow; DNS resolution happens at request time
        return bool(parsed.hostname)
```

### Scheme allowlist

Only these URL schemes are permitted in the pipeline: `http`, `https`, `rtsp`, `rtsps`. All other schemes (`ftp`, `file`, `data`, `javascript`, etc.) must be rejected before fetching.

### Where to apply

Call `is_safe_url(url)` in:
- `extraction/http.py` before every `httpx.AsyncClient.get/post`
- `harvest/source_dispatch.py` before processing each source row URL
- `discovery/candidate_processing.py` before adding each candidate URL to the set
- `utils/url_safety.py` must be imported by any module that makes outbound HTTP requests

Raise `URLSafetyError` when a URL fails the check. Log the blocked URL and continue — never crash the pipeline on a single bad URL.

---

## Nominatim Usage Policy

The geocoder in `targeting/geocoder.py` must comply with Nominatim's usage policy.

### Rate limiting — non-negotiable

Nominatim enforces a hard **1 request per second** limit on the public API (`https://nominatim.openstreetmap.org`). Violating this results in IP bans.

```python
# In targeting/geocoder.py — one semaphore shared across all geocode calls for a run
_nominatim_semaphore = asyncio.Semaphore(1)
_last_nominatim_request: float = 0.0

async def geocode(query: str, http_client: httpx.AsyncClient) -> list[GeocoderCandidate]:
    """Rate-limited Nominatim geocode call — max 1 request/second."""
    global _last_nominatim_request
    async with _nominatim_semaphore:
        elapsed = asyncio.get_event_loop().time() - _last_nominatim_request
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        _last_nominatim_request = asyncio.get_event_loop().time()
        # ... perform the request ...
```

### Required User-Agent

All Nominatim requests must use a User-Agent in the format `AppName/version (contact)`:

```
camera-discovery/2.0 (public-camera-research; https://github.com/dshipley71/camera-discovery)
```

Set this as the `User-Agent` header on Nominatim requests specifically — not as the global httpx client user-agent.

### Endpoint

Use `https://nominatim.openstreetmap.org/search` with `format=jsonv2` and `addressdetails=1`. Do not use any other Nominatim endpoint without documenting the reason.

---

## ProgressEvent Model

Define in `core/progress.py`. Every stage that emits progress must use this model.

### Model definition

```python
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

class ProgressEvent(BaseModel):
    event_type: str = Field(description="Machine-readable event identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the event",
    )
    target_id: str | None = Field(
        default=None,
        description="Which target this event relates to, or None for pipeline-level events",
    )
    message: str = Field(description="Human-readable description of the event")
    level: Literal["debug", "info", "warning", "error"] = Field(
        default="info",
        description="Severity level for filtering",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific structured payload",
    )
```

### Required event types

Every pipeline stage must emit these events using the exact `event_type` strings shown:

| `event_type` | When emitted | Required `data` keys |
|---|---|---|
| `run_started` | Pipeline begins | `profile`, `discovery_mode`, `query` |
| `config_loaded` | TOML config loaded | `config_path`, `profile` |
| `target_resolved` | Per target resolved | `geometry_status`, `trust_policy`, `bbox_verified` |
| `target_resolution_failed` | Resolution failed | `reason`, `stop_reason` |
| `source_discovery_started` | Source rows begin | `mode` |
| `search_query_started` | Per search query | `query`, `engines` |
| `search_query_complete` | Per search query | `query`, `ddg_count`, `bing_count`, `merged_count` |
| `search_engine_error` | Per engine failure | `engine`, `query`, `error` |
| `source_discovery_complete` | All source rows found | `row_count`, `blocked_count` |
| `browser_capture_preflight_passed` | Browser ready | `backend` |
| `browser_capture_preflight_failed` | Browser unavailable | `backend`, `reason` |
| `browser_capture_complete` | Per page captured | `url`, `candidates_found` |
| `browser_capture_skipped` | Page skipped | `url`, `reason` |
| `candidates_extracted` | Extraction complete | `raw_count` |
| `candidates_processed` | After dedup/normalize | `unique_count`, `blocked_count` |
| `validation_started` | Validation begins | `candidate_count`, `workers`, `profile` |
| `validation_candidate_processed` | Per candidate | `status`, `method`, `url` |
| `validation_complete` | Validation done | `live`, `dead`, `unknown`, `skipped` |
| `artifacts_written` | Artifacts written | `artifact_paths` |
| `map_written` | Map HTML written | `path` |
| `map_skipped` | `--no-map` active | — |
| `run_complete` | Pipeline finished | `duration_seconds`, `trusted_count`, `review_count` |
| `harvest_started` | Harvest begins | `query`, `max_urls` |
| `harvest_extraction_progress` | During harvest | `extracted_count`, `unique_count` |
| `harvest_complete` | Harvest done | `unique_count`, `output_files` |

### Publisher helper

```python
def emit(queue: asyncio.Queue, event_type: str, message: str,
         target_id: str | None = None, level: str = "info", **data: Any) -> None:
    """Non-blocking progress event emit. Silently drops if queue is full."""
    event = ProgressEvent(event_type=event_type, message=message,
                          target_id=target_id, level=level, data=data)
    queue.put_nowait(event)
```

The `None` sentinel value closes the SSE stream. Always `put_nowait(None)` when the pipeline completes or fails.

---

## Configuration System

### Config file search order

1. `--config PATH` CLI flag
2. `./camera_discovery.toml` (current working directory)
3. `~/.config/camera-discovery/config.toml`
4. Built-in Pydantic defaults (all fields have defaults; the config file is optional)

### First-run behavior

When no config file is found at any search path, the application must:
1. Log a `WARNING` stating which paths were searched.
2. Emit a `config_loaded` progress event with `config_path: null`.
3. Proceed with all built-in defaults — never raise `FileNotFoundError`.

```python
def load_config(config_path: Path | None = None) -> AppConfig:
    """Load AppConfig from TOML file or return defaults if no file is found."""
    search_paths = _config_search_paths(config_path)
    for path in search_paths:
        if path.exists():
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            return AppConfig.model_validate(raw)
    logger.warning(
        "No camera_discovery.toml found (searched: %s). Using built-in defaults.",
        ", ".join(str(p) for p in search_paths),
    )
    return AppConfig()
```

### Committed example config file

Commit `camera_discovery.toml.example` to the repository root. It must be a fully commented example of all supported config keys. Users copy and rename it to `camera_discovery.toml`. It must not contain real API keys — use placeholder strings like `"your-api-key-here"`.

### Config schema (TOML)

```toml
# camera_discovery.toml.example — copy to camera_discovery.toml and fill in values

[discovery]
# Runtime profile: fast (no validation), balanced (playlist/snapshot), full (deep HLS check)
profile = "fast"

# Discovery mode: blind (search only) | directory (SOURCES.md only) | both | direct (seed URLs only)
discovery_mode = "both"

# HTTP request timeout in seconds for network discovery, enrichment, and validation requests
http_timeout = 20.0

# Number of concurrent validation workers. Clamped to 1–64. Not a candidate cap.
validation_workers = 24

# Maximum search queries sent to each engine (DDG and Bing each run this many)
max_search_queries = 4

# Maximum results to accept per query per engine
max_search_results_per_query = 5

# Maximum pages to fetch from a single discovered source
max_pages = 25

# Single budget cap across ALL media types (HLS, RTSP, MJPEG, image_snapshot, etc.)
# No per-media-type sub-caps. Geocoordinate-bearing candidates are prioritized within this cap.
max_total_candidates = 150

# Maximum pages to follow from a single SOURCES.md directory entry
max_directory_pages = 8

# Maximum structured endpoints to extract from a single page
max_structured_endpoints_per_page = 20

# Whether to geocode candidates lacking coordinates using Nominatim
enable_candidate_geocoding = true

# Maximum Nominatim geocode calls per run
max_candidate_geocodes = 150

# Whether to use LLM to infer place-name queries for candidates lacking coordinates
enable_llm_location_inference = true

# Maximum LLM location inference calls per run
max_llm_location_inferences = 150

# Minimum LLM confidence to accept a location inference (0.0–1.0)
location_inference_min_confidence = 0.70

# Number of candidates batched per LLM review call
candidate_review_batch_size = 8

# Maximum LLM candidate review calls per run
max_candidate_reviews = 150

# Maximum geocode calls for state/region-scale queries
max_state_scale_candidate_geocodes = 150

# Minimum number of times a media asset host must appear before being promoted for crawling
asset_host_promotion_threshold = 3

# Whether to include Google dork queries in blind search (ON by default)
enable_google_dorking = true

# Maximum dork queries to generate per run
max_dork_queries = 8

# User-Agent sent with all HTTP requests (not Nominatim — see geocoder.py)
user_agent = "camera-discovery/2.0 (+public-camera-research)"

[browser]
# Default browser backend: cloakbrowser (default) | playwright
backend = "cloakbrowser"

# Whether browser capture is enabled at all
enabled = true

# Maximum milliseconds to wait for a single browser page capture
capture_timeout_ms = 15000

# Minimum passive intelligence evidence score for a page to qualify for browser capture
min_score = 3

# Maximum total pages to capture across the run
max_pages = 20

# Maximum pages for blind-search-originated rows
max_pages_blind = 6

# Maximum pages for SOURCES.md directory rows
max_pages_directory = 12

# Maximum pages captured from any single host
max_pages_per_host = 3

# Milliseconds to wait for network activity to settle after page load
settle_ms = 1000

# Whether to scroll the page during capture (helps lazy-loading pages)
scroll = false

# Maximum JSON endpoints to extract per captured page
max_json_endpoints_per_page = 10

# Maximum network events to log per captured page
max_network_events_logged_per_page = 50

[search]
# Run DDG and Bing simultaneously for every query (recommended — both are always active)
mode = "parallel"

[harvest]
# Maximum unique URLs to write (0 = unlimited)
max_urls = 10000

# Maximum search queries per harvest run
max_search_queries = 40

# Maximum results per query per engine
max_search_results_per_query = 50

# Maximum source rows to process per run
max_source_rows = 5000

# Maximum pages per source
max_pages_per_source = 25

# Maximum structured endpoints per page
max_structured_endpoints_per_page = 500

# Maximum total browser pages per harvest run
max_browser_pages = 1000

# Maximum browser pages per host
max_browser_pages_per_host = 100

# Maximum JSON endpoints per captured page
max_browser_json_endpoints_per_page = 100

# Maximum network events logged per page
max_browser_network_events_logged_per_page = 100

# Image asset filter: raw | exclude-page-assets | camera-evidence
image_asset_filter = "raw"

[llm]
# LLM provider: ollama | ollama-cloud | openai | openai-compatible | openai_compatible | bedrock
provider = "ollama-cloud"

# Model name for the selected provider. Empty string uses the provider's default.
model = "gemma3:12b-it"

[llm.ollama]
# Base URL for local Ollama or Ollama Cloud
# Local: http://localhost:11434
# Cloud: https://ollama.com
base_url = "https://ollama.com"

# API key — required for ollama-cloud; leave empty for local Ollama
api_key = "your-ollama-api-key-here"

[llm.openai_compatible]
base_url = ""
api_key = "your-api-key-here"
model = ""

[llm.bedrock]
model_id = ""
region = ""

[llm.stage_overrides]
# Per-stage model overrides. Empty string = use llm.model.
target_intent_model = ""
target_intent_fallback_model = ""
geocoder_referee_model = ""
location_inference_model = ""
candidate_review_model = ""

# Per-stage timeouts in seconds
target_intent_timeout = 45.0
geocoder_referee_timeout = 45.0
location_inference_timeout = 45.0
candidate_review_timeout = 45.0

# Retry attempts for target intent extraction before using fallback model
target_intent_attempts = 1

[api]
host = "0.0.0.0"
port = 8000
# Allowed CORS origins — use ["*"] for development; restrict in production
cors_origins = ["*"]

# Maximum number of concurrently running jobs on the server
max_concurrent_jobs = 4
```

### Pydantic v2 config models

`AppConfig` is a `BaseModel` with `model_config = ConfigDict(extra="forbid")` to reject unknown TOML keys and catch typos. `RunConfig` and `HarvestConfig` extend `AppConfig` with per-run fields (`query`, `output_dir`, `seed_urls`, `sources_file`, `generate_map`, etc.).

---

## CLI Specification

### `camera-discovery run`

| Flag | Default | Notes |
|---|---|---|
| `--config PATH` | (search order) | TOML config path |
| `--output-dir / -o PATH` | `./output` | |
| `--profile` | `fast` | `fast \| balanced \| full` |
| `--seed-url TEXT` | | Repeatable |
| `--sources-file PATH` | `SOURCES.md` | |
| `--discovery-mode` | `both` | `blind \| directory \| both \| direct` |
| `--block-pattern TEXT` | | Repeatable |
| `--harvest-input PATH` | | |
| `--harvest-input-mode` | `handoff-only` | `handoff-only \| seed` |
| `--browser-backend` | `cloakbrowser` | `cloakbrowser \| playwright` |
| `--http-timeout SECONDS` | `20.0` | |
| `--map / --no-map` | `--map` | Generate Leaflet map; use `--no-map` when UI handles visualization |
| `--progress / --no-progress` | `--progress` | |
| `--progress-style` | `auto` | `auto \| rich \| plain \| events` |
| `--log-level` | `INFO` | `DEBUG \| INFO \| WARNING \| ERROR` |

### `camera-discovery harvest-urls`

| Flag | Default | Notes |
|---|---|---|
| `--config PATH` | (search order) | |
| `--output-dir / -o PATH` | `./output` | |
| `--max-urls INTEGER` | `10000` | `0` = unlimited |
| `--discovery-mode` | `both` | |
| `--seed-url TEXT` | | Repeatable |
| `--seed-file PATH` | | |
| `--sources-file PATH` | `SOURCES.md` | |
| `--block-pattern TEXT` | | Repeatable |
| `--enable-browser-capture / --disable-browser-capture` | enabled | |
| `--browser-backend` | `cloakbrowser` | `cloakbrowser \| playwright` |
| `--max-search-queries INTEGER` | `40` | |
| `--max-search-results-per-query INTEGER` | `50` | |
| `--max-source-rows INTEGER` | `5000` | |
| `--max-pages-per-source INTEGER` | `25` | |
| `--max-browser-pages INTEGER` | `1000` | |
| `--max-browser-pages-per-host INTEGER` | `100` | |
| `--media TEXT` | | Repeatable/comma-sep |
| `--include-source-metadata / --no-source-metadata` | included | |
| `--write-intermediate-records / --no-write-intermediate-records` | off | |
| `--image-asset-filter` | `raw` | `raw \| exclude-page-assets \| camera-evidence` |
| `--progress / --no-progress` | `--progress` | |
| `--progress-style` | `auto` | |
| `--log-level` | `INFO` | |

### `camera-discovery serve`

| Flag | Default | Notes |
|---|---|---|
| `--config PATH` | (search order) | |
| `--host TEXT` | `0.0.0.0` | |
| `--port INTEGER` | `8000` | |
| `--reload` | off | Dev auto-reload |
| `--log-level` | `INFO` | |

---

## Comprehensive Camera Type Discovery

### All camera types in every run

`extraction/search/queries.py` implements `build_search_queries(target, config)`. This function always generates queries covering **all** camera types regardless of detected intent. Intent detection may ORDER or BOOST queries but must never suppress an entire type.

The query pool always covers:
- Traffic and transportation cameras (DOT, 511, traffic feeds)
- Weather and environmental cameras (weather stations, airport, mountain)
- Generic public cameras (city, public, neighborhood, street)
- HLS/M3U8 stream endpoints
- RTSP stream endpoints
- MJPEG stream endpoints
- Image snapshot cameras (refreshing JPEG/PNG)
- JSON/API/feed endpoints (ArcGIS, MapServer, FeatureServer, GeoJSON feeds)
- Structured data discovery (`filetype:json`, `filetype:geojson` dork queries)

No per-media-type candidate caps. All types compete for the single `max_total_candidates` budget.

### Dork queries — both engines, no restrictions

When `enable_google_dorking = true` (default), dork queries (`site:`, `filetype:`, `intitle:`, `inurl:`) are sent to **both DDG and Bing simultaneously**. Bing supports all these operators. Both engines index differently and will surface different endpoints. The same safety rules apply: location term + camera/media term required.

### Geocoordinate-bearing candidates — highest priority

`discovery/candidate_priority.py` enforces strict three-tier ordering:

- **Tier 1** — Coordinate-bearing, deterministically in-scope, sorted by evidence score desc.
- **Tier 2** — No coordinates but strong evidence signals, sorted by evidence score desc.
- **Tier 3** — Out-of-scope or unknown-scope candidates.

This ordering applies to: validation budget allocation, candidate table rows, GeoJSON feature ordering, map marker z-index, and review artifact ordering. Coordinates alone never confer trust.

---

## Search Engine Dispatcher

`extraction/search/dispatcher.py` implements `SearchEngineDispatcher` with explicit constructor injection.

### Constructor

```python
class SearchEngineDispatcher:
    def __init__(
        self,
        config: RunConfig,
        source_policy: SourcePolicy,
        logs_dir: Path,
        progress_queue: asyncio.Queue,
        http_client: httpx.AsyncClient,
    ) -> None:
```

### Simultaneous parallel execution

For every query, DDG and Bing are dispatched simultaneously. Both result sets are returned and merged before downstream deduplication. If one engine raises an exception, the other's results are still used:

```python
async def _search_one_query(self, query: str) -> list[dict]:
    ddg_task  = asyncio.create_task(self._ddg_search(query))
    bing_task = asyncio.create_task(self._bing_search(query))
    results = await asyncio.gather(ddg_task, bing_task, return_exceptions=True)
    rows: list[dict] = []
    for engine, result in zip(("ddg", "bing"), results):
        if isinstance(result, list):
            rows.extend(result)
        else:
            logger.warning("Search engine %s failed for query %r: %s", engine, query, result)
            emit(self._queue, "search_engine_error", f"{engine} search failed",
                 engine=engine, query=query, error=str(result))
    return rows
```

Both engines run all queries including dork queries.

Tag each row with `search_engine: "ddg"` or `search_engine: "bing"`. When both engines return the same URL, downstream `_select_rows` keeps the first-seen row — but the passive intelligence layer records both-engine confirmation as an evidence boost before dedup runs.

---

## FastAPI Server Specification

Tested in standalone deployment only. Colab notebooks use the CLI/library interface directly.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Health check, version, uptime |
| `GET` | `/api/v1/config` | Current config with API keys redacted |
| `POST` | `/api/v1/discovery` | Submit a discovery run — body: `DiscoveryRequest` |
| `POST` | `/api/v1/harvest` | Submit a harvest run — body: `HarvestRequest` |
| `GET` | `/api/v1/jobs/{job_id}` | Job status and result summary |
| `GET` | `/api/v1/jobs/{job_id}/progress` | **SSE** stream of `ProgressEvent` NDJSON |
| `GET` | `/api/v1/jobs/{job_id}/artifacts` | List available artifact file names |
| `GET` | `/api/v1/jobs/{job_id}/artifacts/{name}` | Download named artifact file |
| `DELETE` | `/api/v1/jobs/{job_id}` | Cancel or delete a job |

### Job manager — concurrent job safety

`api/job_manager.py` uses `asyncio.Lock` for the job registry to prevent race conditions:

```python
class JobManager:
    def __init__(self, max_concurrent: int = 4) -> None:
        self._jobs: dict[str, JobStatus] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._max_concurrent = max_concurrent

    async def submit(self, job_id: str, coro) -> None:
        async with self._lock:
            running = sum(1 for j in self._jobs.values() if j.status == "running")
            if running >= self._max_concurrent:
                raise CameraDiscoveryError(
                    f"Server at capacity ({self._max_concurrent} concurrent jobs)"
                )
            self._tasks[job_id] = asyncio.create_task(coro)
```

### API schemas

`DiscoveryRequest` mirrors all CLI `run` flags. `HarvestRequest` mirrors `harvest-urls` flags. Both include `generate_map: bool = True`. `JobStatus` includes: `job_id`, `status` (`queued | running | completed | failed | cancelled`), `created_at`, `updated_at`, `progress_summary`, `error`, `artifact_paths`.

---

## Colab Notebook Requirements

### Context

Initial testing uses Google Colab (GPU T4). All notebooks must be Colab-safe. FastAPI server testing is done in standalone deployment — not from Colab.

### Colab event loop — `nest_asyncio`

Colab runs its own event loop. `asyncio.run()` raises `RuntimeError` in notebook cells. All notebooks must apply `nest_asyncio.patch()` in the first setup cell:

```python
# Cell 1 — install dependencies (always first)
import subprocess

# Install CloakBrowser (default backend) and Playwright (underlying engine)
subprocess.run([
    "pip", "install", "-q",
    "camera-discovery[cloakbrowser,playwright]",
    "nest_asyncio",
    "tomli-w",
    "pandas",
], check=True)

# Install Chromium browser binary used by Playwright/CloakBrowser
subprocess.run(["playwright", "install", "chromium", "--with-deps"], check=True)

import nest_asyncio
nest_asyncio.patch()
print("✓ nest_asyncio applied — Colab event loop patched")
```

Use `await` directly in all subsequent cells. Never use `asyncio.run()` in any notebook cell.

### Colab Secrets → TOML config

```python
# Cell 2 — write camera_discovery.toml from Colab Secrets
from google.colab import userdata
import tomli_w, pathlib

config = {
    "llm": {
        "provider": "ollama-cloud",
        "model": "gemma3:12b-it",
        "ollama": {
            "base_url": "https://ollama.com",
            "api_key": userdata.get("OLLAMA_API_KEY"),
        },
    },
    "discovery": {
        "profile": "fast",
        "enable_google_dorking": True,
    },
    "browser": {
        "backend": "cloakbrowser",
        "enabled": True,
    },
}

pathlib.Path("camera_discovery.toml").write_text(
    tomli_w.dumps(config), encoding="utf-8"
)
print("✓ camera_discovery.toml written from Colab Secrets")
```

### Async pipeline calls in notebooks

```python
# Cell 3 — run discovery
from camera_discovery.core.config import load_config, build_run_config
from camera_discovery.runners.discovery_run import execute_discovery_run
import asyncio

config = load_config()
run_config = build_run_config(config, query="San Francisco traffic cameras",
                               output_dir="./output")

queue: asyncio.Queue = asyncio.Queue()
result = await execute_discovery_run(run_config, queue)
print(f"Candidates: {len(result.candidates.unique)}")
```

### JSON in notebooks

```python
# Correct — always use json.loads / json.dumps(ensure_ascii=False)
import json
data = json.loads(pathlib.Path("output/logs/run_report.json").read_text(encoding="utf-8"))

# Never use eval(), ast.literal_eval(), or repr() for JSON
```

### Notebook files to generate

| File | Purpose |
|---|---|
| `notebooks/01_setup_and_config.ipynb` | Install, write `camera_discovery.toml`, verify install |
| `notebooks/02_discovery_run.ipynb` | End-to-end discovery run; display candidate table and map |
| `notebooks/03_harvest_run.ipynb` | End-to-end harvest; display URL inventory and summary |
| `notebooks/04_harvest_then_discover.ipynb` | Harvest → handoff → discovery pipeline demo |
| `notebooks/05_api_server_local.ipynb` | Start FastAPI server as local subprocess, test with httpx — for non-Colab or Colab Pro with port access only; clearly labeled as standalone use |

Each notebook must: begin with `nest_asyncio.patch()`, read config from Colab Secrets via the TOML setup pattern, use `await` directly (never `asyncio.run()`), handle JSON with `json.loads` / `json.dumps(ensure_ascii=False)`, include a cell verifying the install with `python -m compileall -q src`, and never import from other notebooks.

### Default LLM for all notebooks

Provider: `ollama-cloud`, base URL: `https://ollama.com`, model: `gemma3:12b-it`. API key from `userdata.get("OLLAMA_API_KEY")`.

---

## Pydantic v2 Domain Models

All models in `core/models.py` are Pydantic v2 `BaseModel` subclasses with `model_config = ConfigDict(extra="forbid")` on config models and `ConfigDict(extra="ignore")` on domain models (to tolerate additional artifact fields from older runs).

Required models (field contracts identical to reference implementation):
`RuntimeProfile`, `DiscoveryMode`, `HarvestInputMode`, `TrustPolicy`, `RunConfig`, `HarvestConfig`, `TargetIntent`, `GeocoderCandidate`, `TargetContext`, `CameraCandidate`, `CandidateSet`, `HarvestedMediaAsset`, `HarvestedCameraRecord`, `DiscoveredEndpointRecord`, `HarvestedUrlRecord`, `HarvestResult`, `ValidationSummary`, `OutputSummary`, `RunState`.

`RunConfig` no longer has `max_hls_candidates` or `max_image_snapshot_candidates`. All media types compete for `max_total_candidates` only.

`CandidateSet.merge()` preserves its first-seen deduplication contract exactly.

---

## Map Generation

`--map` (default on) writes `map.html`. `--no-map` skips all map generation. The `DiscoveryRequest` API body includes `generate_map: bool = True`.

When map is active: plot candidates colored by trust/scope status; geocoordinate-bearing candidates get larger markers and a distinct color; overlay target bounding box polygon; use `utils/geojson_viewer_template.html` (Leaflet.js, all CSS/JS inline); `utils/geojson_viewer.py` substitutes `{{GEOJSON_DATA}}`, `{{MAP_TITLE}}`, `{{CAMERA_COUNT}}`, `{{TARGET_BBOX}}`, and other named placeholders.

---

## Consolidated Output Artifact Contracts

### Discovery pipeline — top-level output

```text
{output_dir}/
  RUN_EXPLANATION.md
  run_report.json                         # master index: top-level stats + paths to all logs
  camera.geojson                          # trusted; only when trusted records exist
  camera_inventory.jsonl                  # trusted; only when trusted records exist
  cameras.md                              # trusted markdown; only when trusted records exist
  untrusted_camera_candidates.geojson     # review candidates when they exist
  camera_candidates_table.csv
  map.html                                # only when --map (default on)
  target_geometry.geojson
  review_artifacts.zip
  media_validation_dashboard.json
  playlists/
    trusted_media.m3u / .txt
    untrusted_review_media.m3u / .txt
    hls_candidates.m3u / .txt
    rtsp_candidates.m3u / .txt
    live_or_reachable_media.m3u / .txt
    dead_or_restricted_media.txt
    image_snapshots.txt
```

### Discovery pipeline — consolidated logs

```text
{output_dir}/logs/
  run_summary.json
  run_explanation.json
  pipeline_candidate_summary.json
  candidate_discovery_summary.json
  candidate_priority_summary.json
  candidate_priority_explanation.jsonl
  output_summary.json
  target_resolution_all.json
  target_geometry_geojson_status.json
  passive_intelligence_summary.json

  discovery/                              # search and source-row diagnostics
    search_queries.json
    search_results.jsonl
    blocked_source_rows.jsonl
    source_row_evidence_summary.jsonl
    source_policy_summary.json
    structured_endpoint_discovery.jsonl
    json_endpoint_records.jsonl
    json_endpoint_extraction_errors.jsonl
    page_discovery_signals.jsonl
    playlist_export_summary.json

  browser/                                # browser capture diagnostics
    preflight.jsonl
    decisions.jsonl
    results.jsonl
    errors.jsonl
    summary.json

  validation/                             # validation diagnostics
    results.jsonl
    summary.json
    priority_summary.json
    candidate_evidence_summary.jsonl

  targets/{target_id}/                    # per-target diagnostics
    target_intent.json
    geocoder_query_variants.json
    geocoder_candidate_scores.json
    target_resolution.json
    candidate_discovery_summary.json

  candidates/{target_id}/                 # per-target candidate data
    agentic_candidates.jsonl
    agentic_candidates_unique.jsonl
```

### `run_report.json` structure

```json
{
  "schema_version": "run-report/v1",
  "run_id": "...",
  "started_at": "...",
  "completed_at": "...",
  "duration_seconds": 0,
  "profile": "fast",
  "query": "...",
  "targets": [],
  "candidate_summary": {},
  "validation_summary": {},
  "output_summary": {},
  "passive_intelligence_summary": {},
  "log_paths": {
    "run_summary": "logs/run_summary.json",
    "search_results": "logs/discovery/search_results.jsonl",
    "browser_summary": "logs/browser/summary.json",
    "validation_results": "logs/validation/results.jsonl"
  }
}
```

### Harvest pipeline artifacts

```text
{output_dir}/
  source_rows.jsonl
  camera_urls.txt / .csv / .jsonl
  hls_urls.txt
  mjpeg_urls.txt
  image_snapshot_urls.txt
  video_file_urls.txt
  stream_urls.txt
  unknown_media_urls.txt
  camera_records.jsonl
  camera_media_assets.jsonl
  discovered_endpoints.jsonl
  harvest_camera_inventory.jsonl
  harvest_handoff.json                    # schema_version: harvest-handoff/v2
  harvest_summary.json
  playlists/
    harvested_media.m3u / .txt
    harvested_hls.m3u / .txt
    harvested_rtsp.m3u / .txt
    harvested_image_snapshots.txt
  logs/
    source_rows_summary.json
    harvest_summary.json
    handoff_summary.json
    endpoint_catalog_summary.json
    discovery/
      blind_search_diagnostics.jsonl
      blocked_source_rows.jsonl
      structured_endpoint_discovery.jsonl
      harvest_errors.jsonl
      playlist_export_summary.json
    browser/
      preflight.jsonl
      summary.json
```

### `media_validation_dashboard.json` required fields

```json
{
  "total_candidates": 0,
  "validated": 0,
  "trusted": 0,
  "untrusted_review": 0,
  "dead": 0,
  "restricted": 0,
  "not_validated": 0,
  "passive_intelligence": {}
}
```

---

## Passive Intelligence Layer (Regeneration Requirement)

Required in all agent-generated builds. Implement under `src/camera_discovery/passive_intelligence/`.

**`evidence.py`** — Deterministic 0–100 integer scoring. Bands: `none` (0), `weak` (1–24), `moderate` (25–49), `strong` (50–74), `very_strong` (75–100). Two-engine boost: +10 when both DDG and Bing returned the same URL independently. Geocoordinate boost applied for source-provided coordinates. Evidence score never bypasses scope, block policy, validation, or trust gates.

**`signatures.py`** — Generic camera/media path fragments in already-discovered evidence. Must not generate URLs or probe hosts.

**`protocol_labels.py`** — Labels: `hls`, `rtsp`, `mjpeg`, `image_snapshot`, `dash`, `webrtc`, `rtmp`, `srt`, `mp4`, `unknown_stream`, `unknown`.

**`http_metadata.py`** — Allowlisted HTTP metadata from existing requests. Never stores credentials, tokens, cookies, or auth headers.

---

## LLM Provider System

All clients implement the async protocol in `llm/base.py`. Default: `provider = "ollama-cloud"`, `model = "gemma3:12b-it"`, `base_url = "https://ollama.com"`. Providers: `ollama`, `ollama-cloud`, `openai`, `openai-compatible`, `openai_compatible`, `bedrock`. Never log API keys.

---

## Multi-Target Support

Multiple locations produce separate targets. Each gets independent resolution, geocoding, trust-policy, per-target artifacts. GeoJSON features carry `target_id`, `target_label`, `target_index`. Do not collapse multi-location queries.

---

## Trust Model

Trusted output requires: verified geometry + in-scope coordinates + successful validation + `TrustPolicy.TRUSTED_ALLOWED`. `fast` profile blocks trusted output. Remove stale trusted files when no trusted candidates exist.

---

## Browser Capture

CloakBrowser is the default. Both backends use `async_playwright` internally. If preflight fails: write `logs/browser/preflight.jsonl`, emit `browser_capture_preflight_failed`, skip browser capture for the run. Never fabricate browser success.

---

## Harvest Handoff

`run --harvest-input PATH` supports `handoff-only` (default) and `seed` modes. Schema version `harvest-handoff/v2` maintained for backward compatibility. All loaded records are untrusted until the full pipeline processes them.

---

## Source Registry and Block Policy

`SOURCES.md` format unchanged from reference. Blocked patterns are global. Never auto-edit `SOURCES.md`. Evidence score never bypasses block policy.

---

## `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "camera-discovery"
version = "2.0.0"
description = "Async public camera discovery pipeline with deterministic trust gates"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
dependencies = [
  "httpx>=0.27",
  "typer>=0.12",
  "rich>=13.7",
  "beautifulsoup4>=4.12",
  "lxml>=5.0",
  "pydantic>=2.7",
  "fastapi>=0.111",
  "uvicorn[standard]>=0.29",
  "sse-starlette>=2.1",
]

[project.optional-dependencies]
bedrock      = ["aiobotocore>=2.13"]
playwright   = ["playwright>=1.44"]
cloakbrowser = ["cloakbrowser>=0.3.29"]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "pytest-cov>=5.0",
  "respx>=0.21",
  "ruff>=0.8",
  "mypy>=1.8",
  "nest-asyncio>=1.6",
]
notebook = [
  "jupyter>=1.0",
  "nbformat>=5.9",
  "pandas>=2.0",
  "nest-asyncio>=1.6",
  "tomli-w>=1.0",
]
all = [
  "camera-discovery[bedrock,playwright,cloakbrowser,dev,notebook]",
]

[project.scripts]
camera-discovery        = "camera_discovery.cli:app"
camera-discovery-server = "camera_discovery.api.server:main"

[tool.pytest.ini_options]
testpaths    = ["tests"]
addopts      = "-q --cov=camera_discovery --cov-report=term-missing"
asyncio_mode = "auto"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
target-version = "py311"
line-length    = 120
src            = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "W"]
ignore = ["E501"]

[tool.mypy]
python_version       = "3.11"
warn_unused_ignores  = true
warn_redundant_casts = true
no_implicit_optional = true
ignore_missing_imports = true
```

---

## Test Requirements

All tests must be offline. Use `pytest-asyncio` with `asyncio_mode = "auto"`. Use `respx` for `httpx.AsyncClient` mocking. Use `unittest.mock` / `pytest-mock` for LLM clients, browser sessions, and file I/O.

### `tests/conftest.py` — required shared fixtures

```python
import asyncio
import pytest
import respx
import httpx
from pathlib import Path
from camera_discovery.core.config import AppConfig
from camera_discovery.core.models import RunConfig, CameraCandidate, TargetContext

@pytest.fixture
def app_config() -> AppConfig:
    """Default AppConfig with safe test values and no real network calls."""
    return AppConfig()

@pytest.fixture
def run_config(tmp_path: Path, app_config: AppConfig) -> RunConfig:
    """RunConfig for a synthetic test run."""
    return RunConfig(
        query="Synthetic test city cameras",
        output_dir=tmp_path / "output",
        **app_config.discovery.model_dump(),
    )

@pytest.fixture
def progress_queue() -> asyncio.Queue:
    """Fresh async queue for each test."""
    return asyncio.Queue()

@pytest.fixture
def mock_http():
    """respx mock router for httpx.AsyncClient — no real HTTP requests."""
    with respx.mock(assert_all_called=False) as mock:
        yield mock

@pytest.fixture
def synthetic_candidate() -> CameraCandidate:
    """A synthetic in-scope coordinate-bearing candidate."""
    return CameraCandidate(
        stream_url="https://example-dot.test/cam1.m3u8",
        source_url="https://example-dot.test/cameras",
        lat=9.5, lon=10.5,
        scope_status="in_scope",
        discovery_method="blind",
    )

@pytest.fixture
def out_of_scope_candidate() -> CameraCandidate:
    return CameraCandidate(
        stream_url="https://example-dot.test/cam2.m3u8",
        source_url="https://example-dot.test/cameras",
        lat=50.0, lon=50.0,
        scope_status="out_of_scope",
        discovery_method="blind",
    )

@pytest.fixture
def no_coord_candidate() -> CameraCandidate:
    return CameraCandidate(
        stream_url="https://example-dot.test/cam3.m3u8",
        source_url="https://example-dot.test/cameras",
        scope_status="unknown",
        discovery_method="blind",
    )
```

### Required test files

| File | Coverage |
|---|---|
| `test_config_loading.py` | TOML loading, CLI override precedence, first-run defaults with warning, `extra="forbid"` rejects unknown keys |
| `test_package_contracts.py` | All public imports valid; `__version__` matches `pyproject.toml`; `py.typed` exists |
| `test_cli_contracts.py` | All commands accept documented flags; `asyncio.run()` wrapper pattern enforced; invalid flags fail cleanly |
| `test_models.py` | Pydantic validation, `CandidateSet.merge()` dedup contract, `has_coordinates` computed field |
| `test_exceptions.py` | Exception hierarchy; `URLSafetyError` on private IPs and forbidden schemes |
| `test_url_safety.py` | RFC 1918 blocks (`10.x`, `172.16-31.x`, `192.168.x`); loopback blocks; `http`/`https`/`rtsp`/`rtsps` allowed; other schemes blocked |
| `test_nominatim_rate_limiting.py` | Semaphore enforces ≤1 req/sec; compliant User-Agent header sent; second call waits ≥1s |
| `test_progress_events.py` | All required `event_type` strings emitted; `None` sentinel closes stream; `ProgressEvent` validates correctly |
| `test_candidate_processing.py` | URL normalization, scope classification, dedup, blacklist |
| `test_candidate_priority.py` | Tier 1 (geocoord + in-scope) > Tier 2 (no-coord) > Tier 3 (out-of-scope) |
| `test_target_resolver_logic.py` | Geocoder scoring, trust-policy, geometry padding, LLM-referee advisory boundary |
| `test_evidence_scoring.py` | 0-100 deterministic scoring; two-engine boost; coordinate boost; block-policy non-bypass |
| `test_search_queries.py` | All camera types present in query pool regardless of intent |
| `test_search_parallel.py` | DDG and Bing dispatched simultaneously; both results merged; one engine error doesn't fail the other |
| `test_search_dork_both_engines.py` | Dork queries sent to both engines; no Bing restriction |
| `test_harvest_media_extraction.py` | Media type classification, dedup, quality filtering |
| `test_harvest_handoff.py` | `harvest-handoff/v2` schema loading, media-filter-aware handoff |
| `test_run_harvest_input.py` | `handoff-only` and `seed` modes; scope gating of handoff candidates |
| `test_validation_pipeline.py` | URL check, media probe, browser snap, LLM review — all mocked with `respx` / `pytest-mock` |
| `test_passive_intelligence.py` | Signatures, protocol labels, HTTP metadata, block-policy non-bypass |
| `test_browser_capture.py` | Preflight failure → skip; CloakBrowser default; Playwright selectable; no success fabrication |
| `test_async_file_io.py` | `asyncio.to_thread()` used; no sync file calls in async functions; `ensure_ascii=False` on all writes |
| `test_task_group_exception_handling.py` | `ExceptionGroup` caught with `except*`; single engine failure doesn't abort pipeline |
| `test_api_routes.py` | `/api/v1/discovery`, `/api/v1/harvest`, job lifecycle, SSE stream, concurrent job limit |
| `test_job_manager.py` | `asyncio.Lock` prevents race conditions; max concurrent jobs enforced |
| `test_geojson_viewer.py` | Template round-trip: identical output for identical input |
| `test_multi_target_contracts.py` | Multi-location query → separate targets; GeoJSON features carry target fields |
| `test_source_policy.py` | Block patterns global; evidence score cannot bypass |
| `test_google_dorking_guardrails.py` | Safety checks pass; dork queries ON by default; no forbidden targets |
| `test_map_flag.py` | `--map` writes `map.html`; `--no-map` skips it |
| `test_log_structure.py` | Consolidated log directories exist: `logs/discovery/`, `logs/browser/`, `logs/validation/`; `run_report.json` is valid JSON with required keys |
| `test_output_filtering.py` | Trusted output gating; stale trusted file removal |
| `test_no_media_type_caps.py` | No `max_hls_candidates` or `max_image_snapshot_candidates` in `RunConfig` |

### Synthetic data conventions

- Camera URLs: `https://example-dot.test/` or `rtsp://example-dot.test/` — never real hostnames.
- Bounding boxes: non-real coordinates e.g., `{"north": 10.0, "south": 9.0, "east": 11.0, "west": 10.0}`.
- Titles: clearly synthetic e.g., `"Synthetic traffic camera I-999"`.

---

## Inline Documentation Standards — Non-Negotiable

### Module docstrings

Every `.py` file begins with a module docstring stating: what it does (1–2 sentences), what it explicitly does NOT do (trust boundary, scope boundary, side-effect boundary), and which modules it coordinates with.

### Class docstrings

Every class has a docstring covering: purpose and single responsibility, key invariants, and async/threading safety.

### Function and method docstrings

Every public function and non-trivial private function (`_` prefixed, >5 lines or non-obvious algorithm) has a docstring with `Args:`, `Returns:`, `Raises:`, and `Notes:` blocks. Notes must explain trust boundaries, async contracts, and advisory-vs-authoritative distinctions where relevant.

### Inline comments required on

Every trust/scope gate, every concurrency pattern (`gather`, `TaskGroup`, `Semaphore`, `Queue`, `timeout`), every `ExceptionGroup`/`except*` block, every dedup key, every LLM advisory boundary, every `asyncio.to_thread()` call, every evidence score usage, every fallback path, and every magic number.

### Pydantic field documentation

Every `Field(...)` includes `description=`. Non-obvious defaults have a `# reason:` comment.

### TOML config documentation

Every key has a comment line above it. See the example config above for the required comment style.

### Test documentation

Every test function has a docstring stating what behavior it protects and what the expected outcome is.

### What NOT to do

No docstrings that restate the signature. No comments on obvious Python syntax. No speculative future behavior.

---

## Repository Hygiene — `.gitignore` and Cache Cleanup

### `.gitignore`

```gitignore
# Python bytecode
__pycache__/
*.py[cod]
*$py.class
*.pyo

# Distribution and build
dist/
build/
*.egg-info/
*.egg
.eggs/
MANIFEST

# Virtual environments
.venv/
venv/
env/
ENV/

# Test, coverage, and tool caches
.pytest_cache/
.coverage
.coverage.*
coverage.xml
htmlcov/
.mypy_cache/
.dmypy.json
.ruff_cache/

# Jupyter / IPython
.ipynb_checkpoints/
*.ipynb_checkpoints
profile_default/

# Runtime output (user-generated, never committed)
output/
outputs/

# Application config with secrets (user-generated, never committed)
camera_discovery.toml

# OS and editor artifacts
.DS_Store
Thumbs.db
.vscode/
.idea/
*.swp
*~

# Playwright browser binaries
.playwright/

# Temporary files
*.tmp
*.log
```

### Post-verification cache cleanup

After all verification steps pass, remove all generated cache artifacts before finalizing the response:

```bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".mypy_cache"   -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".ruff_cache"   -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "*.egg-info"    -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "htmlcov"       -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc"         -delete 2>/dev/null || true
find . -type f -name ".coverage"     -delete 2>/dev/null || true
find . -type f -name "coverage.xml"  -delete 2>/dev/null || true
```

This cleanup runs after all tests pass — never before. The working tree handed back must contain only committed source files, documentation, and configuration templates.

---

## Agent Markdown Files — Generate and Keep in Sync

### Purpose

The `agents/` directory contains per-component specifications that future Codex prompts and Claude Code sessions use as authoritative source of truth. Every agent file must be generated as part of this build and updated in the same commit as any source code change affecting the described component.

### Files to generate

```text
agents/
  cli_agent.md
  core_data_contracts_agent.md
  candidate_discovery_agent.md
  target_resolver_agent.md
  review_validation_pipeline_agent.md
  llm_provider_agent.md
  notebook_agent.md
  project_scaffold_agent.md
  tests_agent.md
  search_dispatcher_agent.md
  harvest_engine_agent.md
  fastapi_server_agent.md
  passive_intelligence_agent.md
  implementation_notes/
    AGENTS.md
    acceptance.md
    candidate_discovery_engine.md
    target_resolver.md
    review_validation_pipeline.md
    llm_provider_agent.md
    notebook_agent.md
    project_scaffold_agent.md
    search_dispatcher.md
    harvest_engine.md
    fastapi_server.md
    passive_intelligence.md
```

### Required sections in every agent file

1. Purpose and responsibility boundary (what it does and explicitly does NOT do)
2. Public interface (importable names, signatures matching actual source)
3. Behavioral invariants (numbered list)
4. Async and concurrency contract
5. Configuration surface (which `RunConfig`/`HarvestConfig` fields it reads)
6. Dependencies (which modules it imports from; circular import constraints)
7. Output artifacts (files written, paths, schemas)
8. What this component must never do
9. Verification (test files that protect this component)

### Sync enforcement rule

Any source change affecting a component's public interface, behavioral invariants, config surface, async contract, output artifacts, or dependencies must update the corresponding agent file in the same commit. A source change without an agent file update is incomplete.

---

## Documentation to Generate

| File | Notes |
|---|---|
| `README.md` | Install, quickstart CLI + API, `camera_discovery.toml.example` reference, Colab quick-start |
| `AGENTS.md` | Updated build rules for v2: async, Pydantic v2, TOML config, FastAPI, no env vars, consolidated logs |
| `REPOSITORY_LAYOUT.md` | Updated module map for v2 directory structure |
| `SOURCES.example.md` | Example `SOURCES.md` with commented allowed sources and blocked patterns |
| `Makefile` | Common dev commands: `make install`, `make test`, `make lint`, `make typecheck`, `make clean`, `make serve` |
| `docs/project_structure.md` | Updated module map |
| `docs/runtime_configuration.md` | TOML config reference, CLI flags — no env var section |
| `docs/output_artifacts.md` | Full artifact contracts including consolidated log structure |
| `docs/passive_intelligence.md` | Behavioral spec (unchanged) |
| `docs/sources_blueprint.md` | Unchanged |
| `docs/acceptance.md` | Updated verification commands + agent file drift detection step + Colab notebook checks |

---

## CI — GitHub Actions

`.github/workflows/tests.yml` — runs on push to `main` and `dev`, and all pull requests:

```yaml
- name: Install dependencies
  run: |
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev,cloakbrowser,playwright]"

- name: Install Chromium (used by both Playwright and CloakBrowser)
  run: python -m playwright install chromium --with-deps

- name: Compile check
  run: python -m compileall -q src tests

- name: Lint
  run: python -m ruff check src tests

- name: Type check
  run: python -m mypy src/camera_discovery/core src/camera_discovery/llm src/camera_discovery/api

- name: Test with coverage
  run: python -m pytest -q --cov=camera_discovery --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v4
```

Test matrix: Python 3.11 and 3.12.

---

## Final Response Required

When the implementation is complete, report:

1. **Files created** — complete list with one-line descriptions.
2. **Baseline verification** — compile, lint, type-check, and test results.
3. **Technology decisions** — confirm asyncio patterns used (TaskGroup, `except*`, `asyncio.timeout()`, `asyncio.to_thread()`), Pydantic v2 model strategy, TOML loading approach, FastAPI job manager design, parallel search dispatch design.
4. **Public contracts** — confirm all documented public imports are valid and `__version__` is correct.
5. **Test results** — exact output of `pytest -q --cov` and `ruff check`.
6. **Colab compatibility** — confirm `nest_asyncio`, JSON handling, CloakBrowser install cell, and TOML setup cell are present and correct in all notebooks.
7. **Documentation coverage** — confirm every module, class, public function, and non-trivial private function has a docstring; all trust/scope gates, concurrency patterns, `ExceptionGroup` blocks, `asyncio.to_thread()` calls, LLM advisory boundaries, fallback paths, and magic numbers have inline comments; all Pydantic `Field` definitions have `description=` strings.
8. **Agent file sync** — confirm all files under `agents/` and `agents/implementation_notes/` have been generated and accurately reflect the v2 source code.
9. **Cache cleanup** — confirm all `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `*.egg-info`, `htmlcov/`, `*.pyc`, `.coverage`, and `coverage.xml` artifacts have been removed from the working tree.
10. **Limitations** — anything deferred or requiring a follow-up.
11. **No fake evidence** — explicit confirmation that no fake/synthetic camera inventory, coordinates, validation results, GeoJSON, browser success, or source-specific hacks were introduced in source code.
