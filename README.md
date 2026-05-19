# Camera Discovery — Architecture Overview

## Pipeline Diagram

---
![Pipeline](architecture.svg)
---

---

## What the Application Is and How It Works

`camera-discovery` is a three-stage agentic pipeline for finding publicly accessible live camera streams — primarily HLS `.m3u8` feeds — for a given geographic query like "Get me all traffic cameras in California." Its defining architectural principle is that the LLM is advisory only: it interprets evidence and ranks candidates, but every trust decision, geometry verification, stream validation, and final artifact write is handled by deterministic code. This is a deliberate and well-maintained boundary.

### Stage 1 — `TargetResolver`

Parses the natural language query, first deterministically extracting location phrases with regex, then calling the LLM to produce structured intent (canonical place name, scope type, camera type intent, geocoder query variants). It geocodes against Nominatim (OpenStreetMap) and scores each geocoder result deterministically — checking bbox plausibility against scope-appropriate area thresholds, result type against expected scope, and admin region presence in the display name. The LLM acts a second time as a "geocoder referee," adjusting scores for the candidates that passed hard gates. The output is a `TargetContext` carrying a `TrustPolicy` of `TRUSTED_ALLOWED`, `REVIEW_ONLY`, or `STOP`, and a verified bounding box when geometry checks pass.

### Stage 2 — `CandidateDiscoveryEngine`

Operates in one of four modes: blind search (DuckDuckGo HTML scraping), directory (approved URLs from `SOURCES.md`), both, or direct seed URL. For every accepted source URL it fetches the page and runs a layered extraction pipeline: regex scan for `.m3u8` and image URLs, structured HTML tag parsing, JSON endpoint detection and walking, GeoJSON feature extraction, JavaScript config blob detection, and linked feed following. Candidates are then coordinate-enriched from source metadata, URL query parameters, and optionally Nominatim geocoding. A bbox scope gate (`in_scope` / `out_of_scope` / `review` / `unknown`) is applied deterministically, then the LLM does a final semantic review pass (advisory only — it can downgrade candidates but not elevate them past deterministic rejections). All of this propagates `target_id` / `target_label` / `target_index` metadata through to each candidate, enabling multi-location queries to be processed and merged cleanly.

### Stage 3 — `ReviewAndValidationPipeline`

Validates candidate streams via HTTP HEAD requests that check for `#EXTM3U` in the response body. Only candidates that are `in_scope`, pass validation as `active_live`, have real coordinates, and whose target has a verified bbox and `TRUSTED_ALLOWED` policy get written to `camera.geojson`. Everything else flows to `untrusted_camera_candidates.geojson`, a CSV candidates table, an embedded Leaflet HTML map, and a packaged review ZIP.

### Core architectural rule

```
LLM  = evidence interpreter and ranker
Code = geometry verification, stream validation, trusted-output authorization, artifact writing
```

The LLM is used in exactly three advisory places:

1. Target intent extraction and geocoder-query expansion.
2. Geocoder candidate ranking/referee.
3. Candidate semantic review.

The LLM is **not** permitted to verify geometry, validate streams, authorize trusted output, or write final artifacts.

### Runtime profiles

| Profile | Validation | Trusted output |
|---|---|---|
| `fast` | Disabled | Blocked — review-only artifacts only |
| `balanced` | HTTP + `#EXTM3U` | Allowed when all deterministic gates pass |
| `full` | HTTP + `#EXTM3U` + ffprobe | Allowed when all deterministic gates pass |

### Discovery modes

| Mode | Sources used |
|---|---|
| `blind` | DuckDuckGo search only |
| `directory` | Approved `SOURCES.md` entries only |
| `both` | DuckDuckGo + `SOURCES.md` (default) |
| `direct` | User-supplied `--seed-url` values only |

Blocked patterns in `SOURCES.md` are a global deny list applied to all modes, including blind search result URLs, extracted stream URLs, and direct seed URLs.

### Output artifacts

**Trusted** (written only when all deterministic gates pass):

- `camera.geojson` — GeoJSON FeatureCollection of validated, in-scope cameras
- `camera_inventory.jsonl` — one record per trusted camera
- `cameras.md` — flat stream URL list with target labels

**Review-only** (always written when candidates exist):

- `untrusted_camera_candidates.geojson` — all non-rejected candidates with coordinates
- `camera_candidates_table.csv` — full candidate table including rows without coordinates
- `map.html` — embedded Leaflet map with popup thumbnails and HLS playback buttons
- `review_artifacts.zip` — packaged bundle of all of the above

**Diagnostics** (always written):

- `logs/target_intent.json` — raw LLM intent extraction output
- `logs/geocoder_candidate_scores.json` — scored geocoder candidates per target
- `logs/candidate_semantic_review.json` — LLM semantic review decisions
- `logs/candidate_coordinate_enrichment.json` — coordinate enrichment diagnostics
- `logs/run_summary.json` — complete `RunState` snapshot

## Install

```bash
python -m pip install -e .[dev,notebook]
```

## Providers

Supported LLM providers:

- `ollama` / Ollama Cloud-compatible `/api/chat`
- `openai-compatible` `/v1/chat/completions`
- `bedrock` using AWS Bedrock Runtime Converse API

Copy `.env.example` and configure your provider.

Advisory LLM stages can use separate models:

```bash
CAMERA_DISCOVERY_LLM_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_LLM_MODEL=gemma4:31b-cloud
CAMERA_DISCOVERY_TARGET_INTENT_MODEL=gemma3:12b-cloud
CAMERA_DISCOVERY_TARGET_INTENT_FALLBACK_MODEL=gemma3:12b-cloud
CAMERA_DISCOVERY_TARGET_INTENT_TIMEOUT=45
CAMERA_DISCOVERY_TARGET_INTENT_ATTEMPTS=2
CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL=gemma4:31b-cloud
CAMERA_DISCOVERY_LOCATION_INFERENCE_MODEL=gemma4:31b-cloud
CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL=gemma3:12b-cloud
CAMERA_DISCOVERY_CANDIDATE_REVIEW_TIMEOUT=60
CAMERA_DISCOVERY_CANDIDATE_REVIEW_BATCH_SIZE=8
```

## Run

```bash
camera-discovery run "Get me all public live cameras in California" --profile fast --output-dir runs/test-fast
```

`camera_discovery.cli run` shows Rich progress bars by default for target resolution, per-target source-row discovery, and validation/output writing. During discovery the per-target bar reports source rows processed plus accepted candidate counts split by HLS and image snapshots. Use `--no-progress` for plain logs in environments that do not render carriage-return progress output cleanly.

Fast mode is review-only and blocks trusted `camera.geojson`. Balanced/Full enable validation and can write trusted output only if deterministic target and stream gates pass.

## Outputs

Trusted output, only when deterministic gates pass:

```text
camera.geojson
camera_inventory.jsonl
cameras.md
```

Review-only output:

```text
untrusted_camera_candidates.geojson
candidates/untrusted_camera_candidates_source_rows.jsonl
review_artifacts.zip
```

Diagnostics include:

```text
logs/target_intent.json
logs/geocoder_referee.json
logs/candidate_semantic_review.json
logs/geocoder_candidate_scores.json
logs/run_summary.json
```

## Notebook

Use `notebooks/camera_discovery_live_test.ipynb` for live tests.

## Multi-location queries

The pipeline supports queries that contain more than one place or location, such as:

```bash
camera-discovery run "Get me all cameras from Greenville, Texas"
camera-discovery run "Get me all cameras from London, England and New York, New York"
```

`TargetResolver.resolve_all()` extracts each requested location into a separate `TargetContext` with a stable `target_id`, resolves and verifies geometry per target, and writes per-target diagnostics under:

```text
logs/targets/<target_id>/
candidates/<target_id>/
```

`CandidateDiscoveryEngine` runs independently for each runnable target. Candidates carry `target_id`, `target_label`, and `target_index` through review, validation, GeoJSON output, maps, and review packages.

Final outputs are merged across targets:

```text
camera.geojson                         # trusted candidates only, when validation and geometry allow
untrusted_camera_candidates.geojson    # review-only candidates from any target
logs/target_resolution_all.json        # all resolved target contexts
logs/run_summary.json                  # complete multi-target RunState
```

If one target cannot safely proceed but another can, the runnable target continues. If all targets stop, the CLI exits with a controlled error and writes diagnostics.


## Directory sources and global block policy

The application supports four discovery modes:

```bash
camera-discovery run "Get me all cameras from Greenville, Texas" --discovery-mode blind
camera-discovery run "Get me all cameras from Greenville, Texas" --discovery-mode directory --sources-file SOURCES.md
camera-discovery run "Get me all cameras from Greenville, Texas" --discovery-mode both --sources-file SOURCES.md
camera-discovery run "Review this public HLS URL" --discovery-mode direct --seed-url "https://your-public-source/path/camera.m3u8"
```

`SOURCES.md` has two sections:

- **Allowed Sources** are user-approved source pages, feeds, sites, or direct HLS URLs. They are used only by `directory` and `both` modes.
- **Blocked Sources** are global deny patterns. They are respected by `blind`, `directory`, `both`, and `direct` modes, including blind search results, pages, feeds, direct seed URLs, and extracted stream URLs.

This keeps the simplified architecture intact: `DirectorySourceProvider` is an input provider inside `CandidateDiscoveryEngine`, not a separate orchestration layer.


## Candidate Coordinate Enrichment

Discovery may find valid public camera records before coordinates are available. The pipeline therefore performs a real, evidence-based coordinate enrichment step before scope gating and output finalization:

1. Extract latitude/longitude directly from JSON, GeoJSON, ArcGIS-style `attributes` + `geometry`, JavaScript config objects, map-layer feeds, URL query parameters, and source metadata.
2. If coordinates are still missing and candidate metadata is specific enough, optionally geocode the candidate title/location text with the configured public geocoder.
3. If a verified target bbox exists, geocoded candidate coordinates must fall inside it before they are accepted.
4. Candidates that still lack coordinates remain in `camera_candidates_table.csv` and JSONL review artifacts but are not written to GeoJSON.

This step does not invent or synthesize coordinates. Candidate coordinates are either present in source evidence or returned by an explicit geocoder call. Configure it with:

```bash
CAMERA_DISCOVERY_ENABLE_CANDIDATE_GEOCODING=true
# Candidate geocoding and review budgets are derived from MAX_HLS_CANDIDATES + MAX_IMAGE_SNAPSHOT_CANDIDATES.
```


## Colab GeoJSON Review Table and Map

The live-test notebook can display either `camera.geojson` or `untrusted_camera_candidates.geojson`. It adds:

- a table of camera URL rows with name, target/location, stream URL, source URL, latitude, longitude, trust level, validation status, scope status, and thumbnail URL when present;
- `camera_candidates_table.csv` written to the run directory;
- an embedded Leaflet map that works in Colab;
- marker popups with GeoJSON properties, optional thumbnail/snapshot image, source/stream links, and a **Play video** button;
- HLS playback through hls.js when the browser supports the stream and CORS permits access.

Thumbnail display uses GeoJSON properties such as `thumbnail_url`, `snapshot_url`, `image_url`, `preview_image_url`, or the same keys inside `source_metadata`. If no image URL exists, the popup clearly states that no thumbnail URL is present.
