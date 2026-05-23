# Runtime Configuration

## CLI

```bash
camera-discovery run "Get me all public live cameras in California" \
  --profile fast \
  --output-dir runs/test-fast
```

Options implemented by `camera_discovery.cli run`:

| Option | Default | Meaning |
|---|---|---|
| `query` | required | Natural-language camera discovery request. |
| `--output-dir`, `-o` | `runs/latest` | Run output directory. |
| `--profile` | `fast` | `fast`, `balanced`, or `full`. |
| `--seed-url` | none | One or more direct source/media URLs. |
| `--sources-file` | `SOURCES.md` | Source registry path. |
| `--discovery-mode` | `both` | `blind`, `directory`, `both`, or `direct`. |
| `--block-pattern` | none | Extra global block pattern; may be repeated. |
| `--progress / --no-progress` | progress enabled | Enable/disable progress rendering. |
| `--progress-style` | `auto` | `auto`, `rich`, `plain`, or `events`. |

## Profiles

| Profile | Validation behavior | Trusted output |
|---|---|---|
| `fast` | Disabled. Candidates get `not_validated`. | Blocked; review-only outputs may be written. |
| `balanced` | HLS playlist GET and `#EXTM3U` check; image snapshot refresh checks. | Allowed only after deterministic target, scope, coordinate, and validation gates pass. |
| `full` | Balanced checks plus first HLS segment/variant reachability check. | Allowed only after deterministic gates pass. |

## Provider settings

Supported provider values are `ollama-cloud`, `ollama`, `openai-compatible`, `openai`, `openai_compatible`, and `bedrock`.

Global settings:

```bash
CAMERA_DISCOVERY_LLM_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_LLM_MODEL=gemma4:31b-cloud
```

Stage-specific settings:

```bash
CAMERA_DISCOVERY_TARGET_INTENT_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_TARGET_INTENT_MODEL=qwen3.5:4b
CAMERA_DISCOVERY_TARGET_INTENT_FALLBACK_MODEL=qwen3.5:4b
CAMERA_DISCOVERY_TARGET_INTENT_TIMEOUT=45
CAMERA_DISCOVERY_TARGET_INTENT_ATTEMPTS=1

CAMERA_DISCOVERY_GEOCODER_REFEREE_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL=gemma4:31b-cloud
CAMERA_DISCOVERY_GEOCODER_REFEREE_TIMEOUT=45

CAMERA_DISCOVERY_LOCATION_INFERENCE_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL=gemma4:31b-cloud
CAMERA_DISCOVERY_LOCATION_INFERENCE_TIMEOUT=45

CAMERA_DISCOVERY_CANDIDATE_REVIEW_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL=gemma4:31b-cloud
CAMERA_DISCOVERY_CANDIDATE_REVIEW_TIMEOUT=45
CAMERA_DISCOVERY_CANDIDATE_REVIEW_BATCH_SIZE=8
CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS=150
```

Provider-specific environment variables:

| Provider | Variables |
|---|---|
| Ollama Cloud | `OLLAMA_API_KEY`; optional `OLLAMA_BASE_URL`, default `https://ollama.com`. |
| Local Ollama | optional `OLLAMA_BASE_URL`, default `http://localhost:11434`; optional `OLLAMA_API_KEY`. |
| OpenAI-compatible | `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_API_KEY`, `OPENAI_COMPATIBLE_MODEL` if not using `CAMERA_DISCOVERY_LLM_MODEL`. |
| Bedrock | AWS credentials, `AWS_REGION` or `AWS_DEFAULT_REGION`, and model through `CAMERA_DISCOVERY_LLM_MODEL` or `BEDROCK_MODEL_ID`. |

## Discovery and candidate budgets

| Variable | Default | Meaning |
|---|---:|---|
| `CAMERA_DISCOVERY_DISCOVERY_MODE` | `both` | Default discovery mode. |
| `CAMERA_DISCOVERY_SOURCES_FILE` | `SOURCES.md` | Source registry path. |
| `CAMERA_DISCOVERY_BLOCK_PATTERNS` | empty | Comma-separated global block patterns. |
| `CAMERA_DISCOVERY_MAX_SEARCH_QUERIES` | `4` | Blind-search query limit per target. |
| `CAMERA_DISCOVERY_MAX_SEARCH_RESULTS_PER_QUERY` | `5` | Search results per query. |
| `CAMERA_DISCOVERY_MAX_PAGES` | `25` | General page budget retained in config. |
| `CAMERA_DISCOVERY_MAX_DIRECTORY_PAGES` | `8` | Pagination rows followed for directory/direct rows. |
| `CAMERA_DISCOVERY_MAX_HLS_CANDIDATES` | `100` | HLS candidate budget. |
| `CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES` | `50` | Image snapshot candidate budget. |
| `CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES` | HLS + snapshot budgets | Overall candidate budget. |
| `CAMERA_DISCOVERY_MAX_STREAMS` | total candidate budget | Backward-compatible field retained in config. |
| `CAMERA_DISCOVERY_MAX_STRUCTURED_ENDPOINTS_PER_PAGE` | `20` | Structured endpoint/page extraction budget. |
| `CAMERA_DISCOVERY_ASSET_HOST_PROMOTION_THRESHOLD` | `3` | Repeated media-host threshold for promoted host discovery rows. |

## Candidate coordinate enrichment

| Variable | Default | Meaning |
|---|---:|---|
| `CAMERA_DISCOVERY_ENABLE_CANDIDATE_GEOCODING` | `true` | Enable Nominatim geocoding of specific candidate metadata. |
| `CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES` | total candidate budget | Candidate metadata geocoding budget. |
| `CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES` | total candidate budget | Effective geocode budget for broad/state-scale targets. |
| `CAMERA_DISCOVERY_ENABLE_LLM_LOCATION_INFERENCE` | `true` | Enable LLM candidate place-name inference. |
| `CAMERA_DISCOVERY_MAX_LLM_LOCATION_INFERENCES` | total candidate budget | Inference budget. |
| `CAMERA_DISCOVERY_LOCATION_INFERENCE_MIN_CONFIDENCE` | `0.70` | Minimum confidence before using inferred names for geocoding. |

## Browser capture

| Variable | Default | Meaning |
|---|---:|---|
| `CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE` | `true` | Enable browser/network capture routing. |
| `CAMERA_DISCOVERY_BROWSER_BACKEND` | `playwright` | `playwright` or `cloakbrowser`. |
| `CAMERA_DISCOVERY_BROWSER_CAPTURE_TIMEOUT_MS` | `15000` | Page load timeout. |
| `CAMERA_DISCOVERY_BROWSER_CAPTURE_MIN_SCORE` | `3` | Routing score threshold. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES` | `20` | Global browser page budget. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_BLIND` | `6` | Blind-row browser budget. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_DIRECTORY` | `12` | Directory-row browser budget. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_PER_HOST` | `3` | Per-host browser budget. |
| `CAMERA_DISCOVERY_BROWSER_CAPTURE_SETTLE_MS` | `1000` | Post-load settle wait. |
| `CAMERA_DISCOVERY_BROWSER_CAPTURE_SCROLL` | `false` | Scroll page before collecting rendered HTML. |
| `CAMERA_DISCOVERY_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE` | `10` | Fetch budget for browser-discovered JSON endpoints. |
| `CAMERA_DISCOVERY_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE` | `50` | Network event sample limit in logs. |

## Image snapshots

| Variable | Default | Meaning |
|---|---:|---|
| `CAMERA_DISCOVERY_IMAGE_SNAPSHOT_REFRESH_DELAY_SECONDS` | `2.0` | Fallback delay between cache-busted snapshot fetches when source metadata has no refresh rate. |

Image snapshot validation uses real HTTP requests. Static assets, non-image responses, and long-lived cached assets are rejected or left untrusted.

## Harvest handoff input for normal runs

The normal target-aware workflow can be seeded with extraction-only harvest artifacts:

```bash
camera-discovery run "California traffic cameras" \
  --output-dir runs/run-from-harvest \
  --harvest-input runs/harvest-california/harvest_handoff.json
```

`--harvest-input` also accepts a direct `harvest_camera_inventory.jsonl` path. Handoff rows are treated as source-provided candidate data only. They are not trusted, validated, live/dead classified, geocoded, or scope-filtered merely because they came from harvest output. Normal `run` behavior still resolves the target, applies scope/review/validation/trust/output behavior according to configuration, and writes normal inventory artifacts. Source-provided coordinates are preserved when plausible so the application does not need to rediscover metadata that public endpoints already supplied.


## Harvest debug/intermediate outputs

`camera-discovery harvest-urls` normally writes only final URL/media outputs plus structured harvest artifacts. For debugging the raw → unique → media-filtered → written pipeline, use:

```bash
camera-discovery harvest-urls "California traffic cameras"   --output-dir runs/harvest-california-hls   --media .m3u8   --write-intermediate-records
```

The same behavior can be enabled by environment variable:

| Variable | Default | Meaning |
|---|---:|---|
| `CAMERA_DISCOVERY_HARVEST_WRITE_INTERMEDIATE_RECORDS` | `false` | When true, write `raw_media_records.jsonl`, `unique_media_records.jsonl`, `media_filtered_records.jsonl`, and `logs/intermediate_records_summary.json`. |

The raw intermediate file is written after block-policy filtering and before deduplication so blocked URLs are not persisted. The media-filtered file is written before the final `--max-urls` cap.
