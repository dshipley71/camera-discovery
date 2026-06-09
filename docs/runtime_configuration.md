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


## RTSP, playlist, dashboard, and Google dorking settings

RTSP is supported as a media type for explicit or verbatim extracted URLs only. Harvest filters accept:

```bash
camera-discovery harvest-urls "Example City cameras" --media rtsp
camera-discovery harvest-urls "Example City cameras" --media rtsp,hls
camera-discovery harvest-urls "Example City cameras" --media stream
```

The `stream` category includes generic streams and RTSP records. RTSP validation uses bounded `ffprobe` only when the effective profile/config enables ffprobe validation (currently the `full` profile) and the binary is available. If ffprobe is disabled by profile/config, the candidate receives `rtsp_validation_disabled`; if ffprobe is enabled but unavailable, it receives `rtsp_validation_unavailable`. Both cases remain review/unknown rather than trusted, and RTSP validation never probes beyond the discovered URL.

Playlist export and `media_validation_dashboard.json` are normal output artifacts and do not require a separate CLI flag. They inherit the active source policy and block/private-network checks.

Guarded Google dorking is on by default and remains bounded by configuration:

```bash
CAMERA_DISCOVERY_ENABLE_GOOGLE_DORKING=true
CAMERA_DISCOVERY_MAX_DORK_QUERIES=8
# Set CAMERA_DISCOVERY_ENABLE_GOOGLE_DORKING=false to disable it for a run.
```

When enabled, SearchAgent adds a bounded number of operator-enhanced public-source discovery query patterns. Dorks are query patterns, not a search backend: each generated `query_type=dork` string is submitted to configured supported engines such as DDG, Bing, and SearXNG when its base URL is configured; Google appears only if a real supported/configured Google backend exists. Queries must include a target/location term and a public-camera or camera-type term. `site:`-scoped queries prefer allowed `SOURCES.md` domains. Results from unknown domains, where supported, are only source leads and still pass through source-policy, extraction, scope, validation, and trust gates. Dorking never targets device UIs, admin/login pages, credentials, vendor fingerprints, common RTSP paths, private networks, or blocked internet-asset search engines.


## Passive intelligence runtime behavior

Passive intelligence is part of the normal source/candidate processing flow and does not require a separate runtime profile. It only analyzes evidence already discovered by the configured discovery mode and source policy. It may affect source and validation priority ordering, but it does not change fast/balanced/full validation semantics or trusted-output authorization.


## Metadata-driven structured endpoint discovery

`max_structured_endpoints_per_page` bounds the number of structured endpoints selected from each source page. Structured endpoints include explicit JSON/GeoJSON/API links, endpoint literals in page or script text, advertised ArcGIS REST layers/tables, OGC API Features links, and explicit WFS links. ArcGIS service roots are expanded from fetched public service metadata only; fixed layer-ID guessing is intentionally not used.

## Efficient harvest-first HLS full-validation preset

For harvest-first HLS validation runs, use harvest-first with an HLS media filter, handoff-only ingestion, browser capture disabled unless intentionally needed, bounded timeouts, and the `full` runtime profile:

```bash
CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE=false \
camera-discovery run "California traffic cameras" \
  --harvest-first \
  --harvest-media .m3u8 \
  --harvest-input-mode handoff-only \
  --profile full \
  --http-timeout 10 \
  --discovery-mode both \
  --progress-style plain
```

This preset harvests HLS media evidence first, feeds only the generated handoff into the normal target-aware run, scope-gates before expensive validation, and validates each normalized stream URL once with result reuse for duplicate candidate rows. It does not bypass source policy, target resolution, deterministic scope checks, media validation, or trust gates.

Search-service diagnostics for harvest mode are summarized in `logs/search_service_summary.json` with rows for real backends (`ddg`, `bing`, `searxng`, `google`) and a global query-plan summary. Query attempts are deduplicated before execution by `engine + query_type + normalized_query`; the same query text across different engines is intentional and remains separately attributed. Missing SearXNG configuration appears only on SearXNG attempts, Google is shown as unsupported/not configured unless a real backend exists, and zero-result services remain visible instead of being hidden. Detailed query attempts live in `logs/search_engine_diagnostics.jsonl` and source-row summaries include `blind_search_query_attempts` plus nested `blind_search_results_by_query`.


## Media validation modes and ffprobe availability

The existing runtime profile controls media-validation depth. `--profile balanced` performs lightweight validation: HLS playlist reachability/structure, image snapshot checks, and bounded media-specific checks that do not require proving live segments. `--profile full` enables full media validation behavior, including HLS segment/variant checks and full MJPEG/video-file validators. No extra CLI flag is required.

The validation dispatcher chooses among HLS, image snapshot, RTSP, MJPEG, video-file, and unknown-media validators using URL scheme, extension, declared media type, response headers, and bounded content sniffing. It does not use camera category (`traffic`, `weather`, `beach`, etc.) as the media type.

When RTSP ffprobe validation is disabled by profile/config, RTSP validation reports `rtsp_validation_disabled` without checking for or invoking `ffprobe`. When ffprobe validation is enabled but the binary is unavailable, RTSP validation reports `rtsp_validation_unavailable` rather than success. HLS, MJPEG, image snapshot, video-file, and unknown-media HTTP validators continue to run with configured HTTP timeouts and safe bounded reads. Validation summaries and run explanations include the media validation mode, full-segment setting, HTTP fallback availability, enabled validators, worker count, and timeout.

Full-validation notebooks are expected to set `RUN_PROFILE = "full"`, print `Effective RUN_PROFILE: full`, and pass the CLI profile through visibly rather than hiding a balanced profile in shell arguments.
