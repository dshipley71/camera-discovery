# Genesis Prompt — camera-discovery v2 Ground-Up Rebuild
# UPDATED: Incorporates corrections from live Colab testing sessions

> **Revision history**
> - v2.0 — original genesis prompt
> - v2.1 — corrections from live Colab testing (see `## Changes from Original` at end)

You are building `camera-discovery` from scratch. This is a complete, clean reimplementation of the public-camera discovery application. Do not port old code line-by-line. Use the behavioral specification below as the authoritative source of truth and implement it with the modern technology stack defined here.

The existing repository at `dshipley71/camera-discovery` (dev branch) contains a working reference implementation. Its behavioral rules, output artifact contracts, trust model, and domain logic are the reference. Its technology choices (synchronous code, plain `@dataclass` models, environment variables, monolithic service files) are explicitly replaced by the decisions in this prompt.

---

## Technology Stack — Non-Negotiable

| Concern | Choice |
|---|---|
| Python version | `>=3.11` — use `tomllib`, `TaskGroup`, `ExceptionGroup`, `except*`, `asyncio.timeout()`, `Self` |
| Data models | **Pydantic v2 `BaseModel`** for all domain and config models; **`@dataclass`** for `SourceEntry`, `BlockedSource`, `SourcePolicy` (see Sources section) |
| Configuration | **TOML file** loaded with `tomllib` + CLI overrides. **Zero environment variables** in application code. Colab notebooks write a TOML file from Colab Secrets — see Colab section. |
| HTTP client | **`httpx.AsyncClient`** used as an async context manager per run. No sync `httpx.Client` in the pipeline. |
| Concurrency | **`asyncio`** throughout. `asyncio.gather`, `asyncio.TaskGroup`, `asyncio.Semaphore`, `asyncio.timeout()`. No `ThreadPoolExecutor` in the pipeline. |
| Async file I/O | **`asyncio.to_thread()`** wrapping sync `pathlib.Path` operations. No `aiofiles` dependency needed. |
| CLI | **`typer`** — all pipeline commands are sync wrappers that call `asyncio.run()` on an internal async function. |
| API server | **`fastapi`** with `uvicorn`. Shares the same async pipeline as the CLI. Tested in standalone deployment only. |
| Browser capture | **`async_playwright`** (Playwright async API). **CloakBrowser is the default backend**; Playwright selectable as alternative. |
| HTML parsing | `beautifulsoup4` with `lxml` parser where available, falling back to `html.parser` |
| Terminal output | `rich` |
| Logging | Python stdlib `logging` with a single root configuration in `cli.py` and `api/server.py` |
| Linting | `ruff` |
| Type checking | `mypy` |
| Testing | `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"`) and `respx` for httpx mocking |

**Environment variables are forbidden in application code.** All configuration lives in a TOML file and/or CLI flags. Colab notebooks read from Colab Secrets and write a `camera_discovery.toml` — the application code itself never reads `os.environ`.

---

## Non-Negotiable Behavioral Rules

1. **No fake runtime evidence.** Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime camera inventories anywhere in source code.
2. **No source-specific hacks.** Do not hard-code real-world locations, agencies, source domains, source-specific behavior, or one-off camera types.
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
13. **Private network requests are forbidden.** The application must never make HTTP requests to RFC 1918 private addresses, loopback addresses, or link-local addresses.

---

## Application Overview

`camera-discovery` has three top-level commands:

### 1. `camera-discovery run` — Discovery pipeline
Target-aware pipeline: config → target resolution → concurrent source discovery (DDG + Bing simultaneously + directory rows + direct seeds) → extraction → coordinate enrichment → passive intelligence scoring → candidate priority ordering → optional validation → artifact writing → optional map.

### 2. `camera-discovery harvest-urls` — Harvest pipeline
Extraction-only. Bypasses target resolution, geocoding, validation, trust, scope, LLM review, GeoJSON/maps, `cameras.md`, and review ZIP. Produces raw camera/media URL inventory and `harvest_handoff.json`.

### 3. `camera-discovery serve` — API server
FastAPI server wrapping both pipelines for UI consumption. Accepts discovery/harvest requests, streams progress via SSE, serves artifacts.

---

## Sources System — Use Dataclasses, Not Pydantic

**IMPORTANT CORRECTION from original prompt:** `sources/models.py` must use Python `@dataclass`, not Pydantic `BaseModel`. `SourcePolicy` is the combined allowed+blocked container and must include `is_blocked()`, `block_reason()`, `filter_urls()`, and `enabled_allowed_sources()` as methods.

```python
# sources/models.py — use dataclasses, not Pydantic
from dataclasses import dataclass, field
from fnmatch import fnmatch
from urllib.parse import urlparse

@dataclass
class SourceEntry:
    name: str
    url: str
    source_type: str = "page"   # page | feed | direct_hls | site | dynamic
    scope_hint: str | None = None
    enabled: bool = True
    notes: str | None = None

@dataclass
class BlockedSource:
    pattern: str
    reason: str | None = None

@dataclass
class SourcePolicy:
    allowed_sources: list[SourceEntry] = field(default_factory=list)
    blocked_sources: list[BlockedSource] = field(default_factory=list)
    source_file: Path | None = None

    def enabled_allowed_sources(self) -> list[SourceEntry]:
        return [e for e in self.allowed_sources if e.enabled and e.url]

    def is_blocked(self, url: str | None) -> bool:
        return self.block_reason(url) is not None

    def block_reason(self, url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        host = (parsed.netloc or "").casefold()
        normalized_url = url.casefold()
        for blocked in self.blocked_sources:
            pattern = blocked.pattern.strip().casefold()
            if _matches_pattern(pattern, host, normalized_url):
                return blocked.reason or f"blocked_by_pattern:{blocked.pattern}"
        return None

    def filter_urls(self, urls: list[str]) -> list[str]:
        return [u for u in urls if not self.is_blocked(u)]
```

`_matches_pattern(pattern, host, url)` uses `fnmatch` and hostname suffix matching — **not regex**. Block patterns in `SOURCES.md` are plain domain strings (`evil.com`, `*.evil.com`) not regex strings. Do NOT construct `SourcePolicy` with a list of regex strings.

### SOURCES.md format

```markdown
## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| EarthCam | https://www.earthcam.com | site | global | true | |

## Blocked Sources

| pattern | reason |
|---|---|
| insecam.org | User-blocked camera directory |
```

`sources/registry.py` must implement `load_source_policy(source_file, extra_block_patterns)` that:
- Parses `## Allowed Sources` and `## Blocked Sources` tables
- Returns a single `SourcePolicy` with both populated
- Returns an empty `SourcePolicy` if file not found (never raises)
- Appends `extra_block_patterns` as `BlockedSource` entries with `reason="cli_block_pattern"`

Also provide backward-compatible `load_sources(sources_file) -> list[SourceEntry]` wrapper.

Engine files that previously did `SourcePolicy(config.block_patterns)` must instead construct:
```python
SourcePolicy(blocked_sources=[
    BlockedSource(pattern=p, reason="cli_block_pattern")
    for p in (config.block_patterns or []) if p and p.strip()
])
```

---

## LLM Provider — Ollama Client Endpoint

**IMPORTANT CORRECTION from original prompt:** The Ollama native API endpoint is `/api/chat`, **not** `/v1/chat/completions`.

```python
# llm/ollama.py — CORRECT endpoint
def _api_url(self) -> str:
    base = self._base_url.rstrip("/")
    if base.endswith("/api"):
        return base + "/chat"
    return base + "/api/chat"   # ← /api/chat, NOT /v1/chat/completions
```

The OpenAI-compat shim at `/v1/chat/completions` requires a different auth scheme and returns 401 with a valid Ollama Cloud API key. Always use `/api/chat`.

Response parsing for `/api/chat`:
```python
data = response.json()
content = (data.get("message") or {}).get("content")
if content is None:
    content = data.get("response", "")  # fallback for some Ollama versions
```

The Ollama client must re-read `OLLAMA_API_KEY` from `os.environ` at **request time** (not just at construction), so keys loaded from Colab Secrets after construction are picked up:
```python
def _headers(self) -> dict[str, str]:
    key = os.environ.get("OLLAMA_API_KEY") or self._api_key
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers
```

### Ollama Cloud model names

When calling `https://ollama.com/api/chat` directly, use **plain model names without the `-cloud` suffix**:

| Use case | Model |
|---|---|
| Main/fallback model | `gemma3:27b` |
| Target intent extraction | `gemma3:12b` |
| Geocoder referee | `gemma3:27b` |
| Location inference | `gemma3:27b` |
| Candidate review | `gemma3:12b` |

The `-cloud` suffix (e.g. `gemma3:27b-cloud`) is only for **local Ollama's cloud-offload feature** when calling a local Ollama instance. Never use `-cloud` suffix when `base_url = "https://ollama.com"`.

Default config:
```toml
[llm]
provider = "ollama-cloud"
model    = "gemma3:27b"

[llm.ollama]
base_url = "https://ollama.com"
api_key  = "your-ollama-api-key-here"

[llm.stage_overrides]
target_intent_model          = "gemma3:12b"
target_intent_fallback_model = "gemma3:12b"
geocoder_referee_model       = "gemma3:27b"
location_inference_model     = "gemma3:27b"
candidate_review_model       = "gemma3:12b"
```

---

## Intent Parser — Regex Fallback for LLM Failures

**IMPORTANT ADDITION:** `targeting/intent_parser.py` must implement a regex-based location fallback for when the LLM is unavailable or fails. The fallback must extract the geographic location from the query, stripping camera/intent noise words, so Nominatim receives `"Austin Texas"` not `"live webcams downtown Austin Texas"`.

```python
_FULL_PREAMBLE = re.compile(
    r"^\s*"
    r"(?:get\s+me\s+(?:all\s+)?)?"
    r"(?:find\s+(?:all\s+)?)?"
    r"(?:show\s+(?:me\s+)?(?:all\s+)?)?"
    r"(?:all\s+)?"
    r"(?:live\s+|public\s+|outdoor\s+|indoor\s+|street\s+|highway\s+|freeway\s+"
    r"|security\s+|traffic\s+|weather\s+|cctv\s+|ip\s+)*"  # * not ? — multiple modifiers
    r"(?:webcams?\s+|cameras?\s+|cams?\s+|streams?\s+|feeds?\s+"
    r"|video\s+feeds?\s+|hls\s+|rtsp\s+|mjpeg\s+)?"
    r"(?:from\s+|in\s+|at\s+|near\s+|around\s+|for\s+)?",
    re.IGNORECASE,
)
```

Always fall back to this regex extractor (not the raw query) when the LLM fails, times out, or returns an error. The fallback also strips `"downtown "` prefix from the result.

---

## CLI Specification

### `camera-discovery run`

| Flag | Default | Notes |
|---|---|---|
| `--config PATH` | (search order) | TOML config path |
| `--output / -o PATH` | `./output` | Output directory |
| `--profile / -p` | `fast` | `fast \| balanced \| full` |
| `--mode / --discovery-mode / -m` | `both` | `blind \| directory \| both \| direct` |
| `--sources-file PATH` | `SOURCES.md` | |
| `--seed-url TEXT` | | Repeatable |
| `--block-pattern TEXT` | | Repeatable |
| `--harvest-input PATH` | | Path to `harvest_handoff.json` |
| `--harvest-input-mode` | `handoff-only` | `handoff-only \| seed` |
| `--browser-backend` | `cloakbrowser` | `cloakbrowser \| playwright` |
| `--http-timeout SECONDS` | `20.0` | |
| `--map / --no-map` | `--map` | Generate Leaflet map |
| `--progress-style` | `auto` | `auto \| rich \| plain \| events` |
| `--log-level` | `INFO` | `DEBUG \| INFO \| WARNING \| ERROR` |
| `--verbose / -v` | off | Shorthand for `--log-level DEBUG` |

### `camera-discovery harvest-urls`

| Flag | Default | Notes |
|---|---|---|
| `--config PATH` | (search order) | |
| `--output / -o PATH` | `./output/harvest` | |
| `--max-urls INTEGER` | `10000` | `0` = unlimited |
| `--mode / --discovery-mode / -m` | `both` | |
| `--sources-file PATH` | `SOURCES.md` | |
| `--seed-url TEXT` | | Repeatable |
| `--seed-file PATH` | | File of seed URLs, one per line |
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
| `--http-timeout SECONDS` | `20.0` | |
| `--progress-style` | `auto` | |
| `--log-level` | `INFO` | |
| `--verbose / -v` | off | |

### `camera-discovery serve`

| Flag | Default | Notes |
|---|---|---|
| `--config PATH` | (search order) | |
| `--host TEXT` | `0.0.0.0` | |
| `--port INTEGER` | `8000` | |
| `--log-level` | `INFO` | |
| `--verbose / -v` | off | |

---

## Colab Notebook Requirements

### Critical: combined install cell

**IMPORTANT CORRECTION from original prompt:** In Google Colab, `%pip install` only makes a package importable within the **same cell** it runs in. Clone and install must be in **one combined cell**. Also add `sys.path.insert(0, str(src_path))` as a safety net and verify with `importlib.util.find_spec()`.

```python
# ── Cell 1: Clone + Install (must be ONE cell — do NOT split) ────────────────
REPO_BRANCH = "claude-camera-discovery-v2"
REPO_URL    = "https://github.com/dshipley71/camera-discovery.git"
REPO_DIR    = "/content/camera-discovery"

import subprocess, sys
from pathlib import Path

repo_dir = Path(REPO_DIR)
if not repo_dir.exists():
    !git clone -b "{REPO_BRANCH}" "{REPO_URL}" "{REPO_DIR}"
else:
    !git -C "{REPO_DIR}" pull --ff-only

%cd {REPO_DIR}
%pip install -e ".[dev]" --no-build-isolation -q

# Safety net: ensure src/ is on sys.path even if editable install
# doesn't register immediately in non-Colab Jupyter environments
src_path = Path(REPO_DIR) / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

import importlib
spec = importlib.util.find_spec("camera_discovery")
if spec is None:
    raise ImportError(f"camera_discovery not found. src_path={src_path}, sys.path[:5]={sys.path[:5]}")
print("camera_discovery found at:", spec.origin)
print("Install OK ✓")
```

### Colab Secrets → TOML config

Colab notebooks write a TOML file from Colab Secrets. The application reads TOML — it never reads `os.environ`:

```python
# ── Cell 2: Write camera_discovery.toml from Colab Secrets ──────────────────
import os

# Load secrets into os.environ FIRST, THEN read them
try:
    from google.colab import userdata
    for _key in ["OLLAMA_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"]:
        if not os.environ.get(_key):
            try:
                _v = userdata.get(_key)
                if _v:
                    os.environ[_key] = _v
                    print(f"Loaded {_key} from Colab userdata")
            except Exception:
                pass
except ImportError:
    pass  # Not in Colab

# Read AFTER loading (not before)
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")

# Write TOML config file
import tomli_w, pathlib
config = {
    "llm": {
        "provider": "ollama-cloud",
        "model": "gemma3:27b",
        "ollama": {
            "base_url": "https://ollama.com",
            "api_key": OLLAMA_API_KEY,
        },
        "stage_overrides": {
            "target_intent_model":          "gemma3:12b",
            "target_intent_fallback_model": "gemma3:12b",
            "geocoder_referee_model":       "gemma3:27b",
            "location_inference_model":     "gemma3:27b",
            "candidate_review_model":       "gemma3:12b",
        },
    },
    "discovery": {
        "profile": "fast",
        "enable_google_dorking": True,
    },
}
pathlib.Path("camera_discovery.toml").write_text(tomli_w.dumps(config))
print("camera_discovery.toml written ✓")
print("OLLAMA_API_KEY:", "set ✓" if OLLAMA_API_KEY else "NOT SET ⚠️")
```

**Critical ordering rule:** Load Colab Secrets into `os.environ` **before** capturing any variable that reads `os.environ.get(key)`. Capturing the variable first and loading secrets second produces an empty string even when the secret is set.

### Async in notebooks — do NOT use nest_asyncio for CLI

The CLI commands (`camera-discovery run`, `camera-discovery harvest-urls`) use `asyncio.run()` internally and work correctly from notebook `!` shell cells. Do not use `nest_asyncio` when calling the CLI. Use `await` only when calling library functions directly.

### Notebook files to generate

| File | Purpose |
|---|---|
| `notebooks/01_setup_and_config.ipynb` | Install, write `camera_discovery.toml` from Colab Secrets, verify imports and smoke tests |
| `notebooks/02_discovery_run.ipynb` | End-to-end discovery run via CLI; inspect artifacts; render map inline |
| `notebooks/03_harvest_run.ipynb` | End-to-end harvest via CLI; inspect inventory; handoff file |
| `notebooks/04_output_exploration.ipynb` | Explore artifacts from any completed run |
| `notebooks/05_api_server_local.ipynb` | Start FastAPI server in background thread; submit jobs via httpx |

### Smoke tests in 01_setup_and_config.ipynb

```python
# SourcePolicy uses dataclasses and hostname/fnmatch patterns (not regex)
from camera_discovery.sources.models import SourcePolicy, BlockedSource
p = SourcePolicy(blocked_sources=[BlockedSource(pattern="evil.com")])
assert p.is_blocked("https://evil.com/stream"),             "evil.com should be blocked"
assert p.is_blocked("https://sub.evil.com/cam"),            "subdomain should be blocked"
assert not p.is_blocked("https://good.example.com/stream"), "should not be blocked"

# RunConfig and HarvestConfig are in core.config, not core.models
from camera_discovery.core.config import RunConfig, HarvestConfig, AppConfig

# SourcePolicy construction in engine/service code:
# SourcePolicy([patterns])           ← WRONG (old Pydantic version)
# SourcePolicy(blocked_sources=[...]) ← CORRECT (dataclass version)
```

---

## Harvest Handoff Integration

`camera-discovery run --harvest-input PATH` loads a `harvest_handoff.json` and uses it as discovery input.

```bash
# Step 1: harvest
camera-discovery harvest-urls "California traffic cameras" \
    --output runs/harvest \
    --max-urls 5000

# Step 2: discover from handoff
camera-discovery run "California traffic cameras" \
    --harvest-input runs/harvest/harvest_handoff.json \
    --harvest-input-mode handoff-only \
    --profile balanced \
    --output runs/discovery-from-harvest
```

`handoff-only` mode: only handoff URLs are used; blind search and directory discovery are skipped.
`seed` mode: handoff URLs are added as seed URLs alongside normal discovery.

Schema version `harvest-handoff/v2` maintained for backward compatibility. All loaded records are untrusted until the full pipeline processes them.

---

## Config Schema — Complete TOML Reference

```toml
# camera_discovery.toml.example
# Copy to camera_discovery.toml and fill in values.
# NEVER commit this file with real API keys.

[discovery]
profile          = "fast"      # fast | balanced | full
discovery_mode   = "both"      # blind | directory | both | direct
http_timeout     = 20.0
validation_workers = 24
max_search_queries = 4
max_search_results_per_query = 5
max_pages        = 25
max_total_candidates = 150     # single budget cap for ALL media types
max_directory_pages = 8
max_structured_endpoints_per_page = 20
enable_candidate_geocoding = true
max_candidate_geocodes = 150
enable_llm_location_inference = true
max_llm_location_inferences = 150
location_inference_min_confidence = 0.70
candidate_review_batch_size = 8
max_candidate_reviews = 150
max_state_scale_candidate_geocodes = 150
asset_host_promotion_threshold = 3
enable_google_dorking = true
max_dork_queries = 8
user_agent = "camera-discovery/2.0 (+public-camera-research)"

[browser]
backend          = "cloakbrowser"   # cloakbrowser | playwright
enabled          = true
capture_timeout_ms = 15000
min_score        = 3
max_pages        = 20
max_pages_blind  = 6
max_pages_directory = 12
max_pages_per_host  = 3
settle_ms        = 1000
scroll           = false
max_json_endpoints_per_page = 10
max_network_events_logged_per_page = 50

[search]
mode = "parallel"   # DDG and Bing run simultaneously for every query

[harvest]
max_urls         = 10000
max_search_queries = 40
max_search_results_per_query = 50
max_source_rows  = 5000
max_pages_per_source = 25
max_structured_endpoints_per_page = 500
max_browser_pages = 1000
max_browser_pages_per_host = 100
max_browser_json_endpoints_per_page = 100
max_browser_network_events_logged_per_page = 100
image_asset_filter = "raw"   # raw | exclude-page-assets | camera-evidence

# ── LLM ─────────────────────────────────────────────────────────────────────
# Ollama Cloud model names when calling https://ollama.com/api/chat directly:
#   gemma3:12b, gemma3:27b, gemma4:31b, gpt-oss:20b, gpt-oss:120b
# NOTE: The -cloud suffix (e.g. gemma3:27b-cloud) is for LOCAL Ollama's
# cloud-offload feature ONLY. Do NOT use -cloud suffix here.
[llm]
provider = "ollama-cloud"
model    = "gemma3:27b"   # main/fallback model

[llm.ollama]
base_url = "https://ollama.com"
api_key  = "your-ollama-api-key-here"   # never commit real keys

[llm.openai_compatible]
base_url = ""
api_key  = "your-api-key-here"
model    = ""

[llm.bedrock]
model_id = ""
region   = ""

[llm.stage_overrides]
# Empty string = use llm.model
target_intent_model          = "gemma3:12b"
target_intent_fallback_model = "gemma3:12b"
geocoder_referee_model       = "gemma3:27b"
location_inference_model     = "gemma3:27b"
candidate_review_model       = "gemma3:12b"
target_intent_timeout        = 45.0
geocoder_referee_timeout     = 45.0
location_inference_timeout   = 45.0
candidate_review_timeout     = 45.0
target_intent_attempts       = 1

[api]
host = "0.0.0.0"
port = 8000
cors_origins = ["*"]
max_concurrent_jobs = 4
```

---

## Complete Module Structure

```
src/camera_discovery/
  __init__.py                         # exports __version__ = "2.0.0"
  py.typed                            # PEP 561 marker
  cli.py                              # Typer commands: run, harvest-urls, serve, status
  api/
    __init__.py
    server.py
    job_manager.py
    routes/
      __init__.py
      discovery.py
      harvest.py
      progress.py
      artifacts.py
      config.py
      health.py
    schemas.py
  core/
    __init__.py
    config.py                         # TOML loading, AppConfig, RunConfig, HarvestConfig
    models.py                         # All domain Pydantic v2 models (NOT SourcePolicy)
    progress.py
    exceptions.py
  runners/
    __init__.py
    discovery_run.py
    harvest_run.py
  services/
    __init__.py
    target_resolver.py
    discovery_engine.py
    harvest_engine.py
    validation_pipeline.py
    harvest_handoff.py
    structured_camera_records.py
  targeting/
    __init__.py
    intent_parser.py                  # LLM intent + regex fallback location extractor
    geocoder.py
    geocoder_referee.py
    trust_policy.py
    geometry.py
  discovery/
    __init__.py
    search/
      __init__.py
      ddg.py
      bing.py
      queries.py
      dispatcher.py
    source_rows.py
    candidate_extraction.py
    browser_capture.py
    candidate_processing.py
    candidate_priority.py
    artifact_writer.py
  extraction/
    __init__.py
    http.py
    html.py
    media.py
    json_records.py
    pagination.py
    browser.py
  harvest/
    __init__.py
    source_dispatch.py
    media_filter.py
    catalog.py
    output_writer.py
  validation/
    __init__.py
    url_check.py
    media_probe.py
    browser_snap.py
    llm_review.py
  enrichment/
    __init__.py
    location.py
  passive_intelligence/
    __init__.py
    evidence.py
    signatures.py
    protocol_labels.py
    http_metadata.py
  sources/
    __init__.py
    registry.py                       # load_source_policy(), parse_sources_markdown()
    policy.py                         # re-export shim for backward compat
    models.py                         # SourceEntry, BlockedSource, SourcePolicy — dataclasses
  llm/
    __init__.py
    base.py
    factory.py
    ollama.py                         # /api/chat endpoint — NOT /v1/chat/completions
    openai_compatible.py
    bedrock.py
  utils/
    __init__.py
    io.py
    json_utils.py
    geojson_viewer.py
    geojson_viewer_template.html
    playlists.py
    url_safety.py
```

---

## Async Implementation Patterns — Non-Negotiable

(Same as original genesis prompt — `asyncio.TaskGroup`, `except*`, `asyncio.timeout()`, `asyncio.to_thread()`, single `httpx.AsyncClient` per run. See original for full code examples.)

---

## URL Safety Specification

(Same as original — RFC 1918, loopback, link-local blocking; `http`/`https`/`rtsp`/`rtsps` scheme allowlist.)

---

## Nominatim Usage Policy

(Same as original — 1 req/sec semaphore, compliant User-Agent, `format=jsonv2`.)

---

## ProgressEvent Model and Event Types

(Same as original — all 25 `event_type` constants, `emit()` helper, `None` sentinel.)

---

## Comprehensive Camera Type Discovery

(Same as original — all camera types in every run, dork queries on both engines, three-tier candidate priority.)

---

## FastAPI Server Specification

(Same as original — all endpoints, `asyncio.Lock` job manager, `DiscoveryRequest`/`HarvestRequest` schemas.)

---

## Pydantic v2 Domain Models

All models in `core/models.py` use Pydantic v2 `BaseModel`. Note: `SourcePolicy`, `SourceEntry`, `BlockedSource` are dataclasses in `sources/models.py`, not Pydantic models.

`RunConfig` and `HarvestConfig` live in `core/config.py` (not `core/models.py`). Callers that do `from camera_discovery.core.models import RunConfig` will get an `ImportError`. Correct import:

```python
from camera_discovery.core.config import RunConfig, HarvestConfig, AppConfig
from camera_discovery.core.models import CameraCandidate, CandidateSet, RunState
```

---

## Passive Intelligence Layer

(Same as original — `evidence.py`, `signatures.py`, `protocol_labels.py`, `http_metadata.py`.)

---

## Map Generation

(Same as original — `--map`/`--no-map`, Leaflet.js standalone template, three-tier marker colours, target bbox overlay.)

---

## Consolidated Output Artifact Contracts

(Same as original — full discovery/harvest artifact tree, `run_report.json` schema, `harvest_handoff.json` schema.)

---

## Trust Model

(Same as original — deterministic trust gates, fast profile blocks, stale trusted file removal.)

---

## pyproject.toml

(Same as original — Python 3.11+, all dependencies including `sse-starlette`.)

---

## Test Requirements

All tests must be offline. Use `respx` for httpx mocking. Use `unittest.mock`/`pytest-mock` for LLM clients.

**Correction from original:** `RunConfig` must be imported from `core.config`, not `core.models`:

```python
# tests/conftest.py — CORRECT imports
from camera_discovery.core.config import AppConfig, LLMConfig, RunConfig  # RunConfig is in config
from camera_discovery.core.models import CameraCandidate, CandidateSet    # domain models only

# SourcePolicy smoke test — use dataclass constructor with BlockedSource objects
from camera_discovery.sources.models import SourcePolicy, BlockedSource
p = SourcePolicy(blocked_sources=[BlockedSource(pattern="evil.com")])
assert p.is_blocked("https://evil.com/stream")   # plain hostname pattern, not regex
```

---

## CI — GitHub Actions

(Same as original — Python 3.11 and 3.12, lint, type check, test with coverage.)

---

## Changes from Original Genesis Prompt (v2.1)

The following corrections are based on live Colab testing against the built codebase:

### 1. Colab install cell — must be ONE combined cell
`%pip install` in Colab only makes a package importable within the same cell. Clone + install must be combined. Add `sys.path.insert(0, src_path)` + `importlib.util.find_spec()` verification.

### 2. Colab Secrets ordering — load secrets BEFORE reading env vars
Load all Colab Secrets into `os.environ` at the top of any cell that reads those keys. Capturing `os.environ.get("OLLAMA_API_KEY")` before the userdata loop always returns empty string even when the secret is set.

### 3. Ollama client endpoint — `/api/chat` not `/v1/chat/completions`
The Ollama native endpoint is `/api/chat`. The `/v1/chat/completions` OpenAI shim requires different auth and returns 401 with a valid Ollama Cloud key.

### 4. Ollama Cloud model names — no `-cloud` suffix
When `base_url = "https://ollama.com"`, use `gemma3:27b` not `gemma3:27b-cloud`. The `-cloud` suffix is only for local Ollama's cloud-offload feature.

### 5. Intent parser — regex fallback for LLM failures
When LLM fails, the fallback must strip camera/intent noise and send `"Austin Texas"` to Nominatim, not `"live webcams downtown Austin Texas"` (which returns 0 geocoder results).

### 6. Sources system — dataclasses not Pydantic
`SourcePolicy`, `SourceEntry`, `BlockedSource` are `@dataclass`, not Pydantic. `SourcePolicy` combines allowed + blocked sources. Block patterns are hostname/fnmatch strings, not regex. `SourcePolicy` constructor takes `blocked_sources=[]`, not a positional list.

### 7. RunConfig location — `core.config` not `core.models`
`RunConfig` and `HarvestConfig` are defined in `core/config.py`. Importing from `core.models` raises `ImportError`.

### 8. CLI — all flags from spec must be implemented
`cli.py` must implement all flags from the spec including `--harvest-input`, `--harvest-input-mode`, `--sources-file`, `--block-pattern`, `--browser-backend`, `--http-timeout`, `--log-level`, `--progress-style` for `run`; and all harvest-urls flags.

### 9. SOURCES.md table format
Allowed Sources table columns: `name | url | type | scope_hint | enabled | notes`. Blocked Sources table columns: `pattern | reason`. The old registry parser only matched URLs as the first column — this is wrong.

---

## Final Response Required

When the implementation is complete, report:

1. **Files created** — complete list with one-line descriptions.
2. **Baseline verification** — compile, lint, type-check, and test results.
3. **Technology decisions** — confirm asyncio patterns, Pydantic v2 strategy, TOML loading, FastAPI job manager, parallel search dispatch.
4. **Public contracts** — confirm all documented public imports are valid and `__version__` is correct. Specifically confirm `RunConfig` is importable from `core.config` and `SourcePolicy` from `sources.models`.
5. **Test results** — exact output of `pytest -q --cov` and `ruff check`.
6. **Colab compatibility** — confirm combined install cell, TOML setup from Secrets, correct import order, all smoke tests pass.
7. **Documentation coverage** — confirm module docstrings, trust/scope gate comments, LLM advisory boundaries.
8. **Agent file sync** — confirm `agents/` files generated and reflect v2.1 corrections.
9. **Cache cleanup** — confirm `__pycache__`, `.pytest_cache`, `.mypy_cache` removed.
10. **Limitations** — anything deferred.
11. **No fake evidence** — explicit confirmation no synthetic camera data in source code.
