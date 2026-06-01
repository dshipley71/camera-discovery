# Runtime Configuration

## CLI options

### `camera-discovery run`

```text
--output-dir / -o PATH
--profile fast|balanced|full
--seed-url TEXT
--sources-file PATH
--discovery-mode blind|directory|both|direct
--block-pattern TEXT
--harvest-input PATH
--harvest-input-mode handoff-only|seed
--browser-backend playwright|cloakbrowser
--http-timeout SECONDS
--progress / --no-progress
--progress-style auto|rich|plain|events
```

### `camera-discovery harvest-urls`

```text
--output-dir / -o PATH
--max-urls INTEGER              # 0 means unlimited final output
--discovery-mode blind|directory|both|direct
--seed-url TEXT
--seed-file PATH
--sources-file PATH
--block-pattern TEXT
--enable-browser-capture / --disable-browser-capture
--browser-backend playwright|cloakbrowser
--max-search-queries INTEGER
--max-search-results-per-query INTEGER
--max-source-rows INTEGER
--max-pages-per-source INTEGER
--max-structured-endpoints-per-page INTEGER
--max-browser-pages INTEGER
--max-browser-pages-per-host INTEGER
--media TEXT                    # repeatable/comma-separated filter
--include-source-metadata / --no-source-metadata
--write-intermediate-records / --no-write-intermediate-records
--image-asset-filter raw|exclude-page-assets|camera-evidence
--progress / --no-progress
--progress-style auto|rich|plain|events
```


## Harvest input modes for `run`

`camera-discovery run --harvest-input PATH` supports two modes:

| Mode | Behavior |
|---|---|
| `handoff-only` | Default when `--harvest-input` is supplied. Load only the selected harvest handoff records and skip native blind/directory discovery, promoted asset-host expansion, and browser crawl expansion. Candidate counts are bounded by the selected handoff records/assets and resolved target count. |
| `seed` | Load the harvest handoff records as starting candidates, then run the normal discovery pipeline and merge both candidate sets. Use this only when broader discovery expansion is intentional. |

All harvest-input candidates remain source-provided, unvalidated, and untrusted until normal validation and trust rules process them. The mode can also be set with `CAMERA_DISCOVERY_HARVEST_INPUT_MODE`.

## LLM provider variables

```bash
CAMERA_DISCOVERY_LLM_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_LLM_MODEL=gemma3:27b-cloud
OLLAMA_MODEL=
OLLAMA_API_KEY=
OLLAMA_BASE_URL=https://ollama.com
```

Supported provider values through `llm/factory.py`:

```text
ollama
ollama-cloud
openai
openai-compatible
openai_compatible
bedrock
```

OpenAI-compatible variables:

```bash
OPENAI_COMPATIBLE_BASE_URL=
OPENAI_COMPATIBLE_API_KEY=
OPENAI_COMPATIBLE_MODEL=
```

Bedrock variables:

```bash
BEDROCK_MODEL_ID=
AWS_REGION=
AWS_DEFAULT_REGION=
```

Stage-specific overrides:

```bash
CAMERA_DISCOVERY_TARGET_INTENT_MODEL=
CAMERA_DISCOVERY_TARGET_INTENT_FALLBACK_MODEL=
CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL=
CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL=
CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL=
CAMERA_DISCOVERY_TARGET_INTENT_ATTEMPTS=1
CAMERA_DISCOVERY_TARGET_INTENT_TIMEOUT=45
CAMERA_DISCOVERY_GEOCODER_REFEREE_TIMEOUT=45
CAMERA_DISCOVERY_LOCATION_INFERENCE_TIMEOUT=45
CAMERA_DISCOVERY_CANDIDATE_REVIEW_TIMEOUT=45
```


## Validation and HTTP runtime

```bash
CAMERA_DISCOVERY_HTTP_TIMEOUT=20
CAMERA_DISCOVERY_VALIDATION_WORKERS=24
```

`camera-discovery run --http-timeout SECONDS` overrides `CAMERA_DISCOVERY_HTTP_TIMEOUT` for that run. The value must be greater than zero. The timeout is used by network discovery, enrichment, and validation requests.

Validation uses a bounded worker pool for selected validation candidates. `CAMERA_DISCOVERY_VALIDATION_WORKERS` defaults to `24` and is clamped to the safe range `1..64`. This is not a candidate cap: every selected validation candidate is still attempted. The worker count only controls concurrency.

Validation reuses HTTP clients per worker thread so HLS playlist checks and full-profile segment checks do not create a brand-new `httpx.Client` for every candidate.

Profile behavior remains:

| Profile | Validation behavior |
|---|---|
| `fast` | Validation disabled; trusted output is blocked. |
| `balanced` | HLS playlist and image snapshot validation. |
| `full` | Balanced validation plus HLS segment/variant checks. |

## Discovery budgets

```bash
CAMERA_DISCOVERY_PROFILE=fast
CAMERA_DISCOVERY_DISCOVERY_MODE=both
CAMERA_DISCOVERY_SOURCES_FILE=SOURCES.md
CAMERA_DISCOVERY_BLOCK_PATTERNS=
CAMERA_DISCOVERY_MAX_SEARCH_QUERIES=4
CAMERA_DISCOVERY_MAX_SEARCH_RESULTS_PER_QUERY=5
CAMERA_DISCOVERY_MAX_PAGES=25
CAMERA_DISCOVERY_MAX_HLS_CANDIDATES=100
CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES=50
CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES=150
CAMERA_DISCOVERY_MAX_DIRECTORY_PAGES=8
CAMERA_DISCOVERY_MAX_STRUCTURED_ENDPOINTS_PER_PAGE=20
```

`CAMERA_DISCOVERY_MAX_STREAMS` is deprecated and retained only as a compatibility alias. Explicit use emits a `DeprecationWarning`; prefer `CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES` plus media-specific caps.

## Candidate enrichment and review budgets

```bash
CAMERA_DISCOVERY_ENABLE_CANDIDATE_GEOCODING=true
CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES=150
CAMERA_DISCOVERY_ENABLE_LLM_LOCATION_INFERENCE=true
CAMERA_DISCOVERY_MAX_LLM_LOCATION_INFERENCES=150
CAMERA_DISCOVERY_LOCATION_INFERENCE_MIN_CONFIDENCE=0.70
CAMERA_DISCOVERY_CANDIDATE_REVIEW_BATCH_SIZE=8
CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS=150
CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES=150
```

LLM location inference may produce geocoder query variants only. It never supplies coordinates.

## Browser capture

```bash
CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE=true
CAMERA_DISCOVERY_BROWSER_BACKEND=playwright
CAMERA_DISCOVERY_BROWSER_CAPTURE_TIMEOUT_MS=15000
CAMERA_DISCOVERY_BROWSER_CAPTURE_MIN_SCORE=3
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES=20
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_BLIND=6
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_DIRECTORY=12
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_PER_HOST=3
CAMERA_DISCOVERY_BROWSER_CAPTURE_SETTLE_MS=1000
CAMERA_DISCOVERY_BROWSER_CAPTURE_SCROLL=false
CAMERA_DISCOVERY_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE=10
CAMERA_DISCOVERY_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE=50
```

Both `run` and `harvest-urls` accept `--browser-backend playwright|cloakbrowser` for per-command override. Browser preflight diagnostics are written before repeated page attempts.

## Harvest budgets

```bash
CAMERA_DISCOVERY_HARVEST_MAX_URLS=10000
CAMERA_DISCOVERY_HARVEST_MAX_SEARCH_QUERIES=40
CAMERA_DISCOVERY_HARVEST_MAX_SEARCH_RESULTS_PER_QUERY=50
CAMERA_DISCOVERY_HARVEST_MAX_SOURCE_ROWS=5000
CAMERA_DISCOVERY_HARVEST_MAX_PAGES_PER_SOURCE=25
CAMERA_DISCOVERY_HARVEST_MAX_STRUCTURED_ENDPOINTS_PER_PAGE=500
CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_PAGES=1000
CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_PAGES_PER_HOST=100
CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE=100
CAMERA_DISCOVERY_HARVEST_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE=500
CAMERA_DISCOVERY_HARVEST_IMAGE_ASSET_FILTER=raw
```

Use `--max-urls 0` when a harvest should write all unique filtered URLs.

## Progress

```bash
CAMERA_DISCOVERY_PROGRESS_STYLE=auto|rich|plain|events
```

`events` emits machine-readable progress records for external UIs.
