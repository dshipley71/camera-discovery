# Camera Discovery — Simplified 3-Stage Pipeline

This is a from-scratch, streamlined implementation of an agentic public-camera discovery application.

The architecture is intentionally small:

1. **TargetResolver** — understands the user query, resolves target geography, and decides trusted/review-only/stop policy.
2. **CandidateDiscoveryEngine** — searches/fetches public pages, extracts HLS `.m3u8` candidates, and performs candidate semantic review.
3. **ReviewAndValidationPipeline** — validates or preserves candidates, writes trusted or untrusted artifacts, maps, and review packages.

Core rule:

```text
LLM = evidence interpreter and ranker
Deterministic code/tools = geometry verification, stream validation, trusted-output authorization, final artifact writing
```

The LLM is used in three advisory places:

1. Target intent extraction and geocoder-query expansion.
2. Geocoder candidate ranking/referee.
3. Candidate semantic review.

The LLM is **not** allowed to verify geometry, validate streams, authorize trusted output, or write final artifacts.

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
CAMERA_DISCOVERY_TARGET_INTENT_MODEL=qwen3.5:4b
CAMERA_DISCOVERY_TARGET_INTENT_FALLBACK_MODEL=qwen3.5:4b
CAMERA_DISCOVERY_TARGET_INTENT_TIMEOUT=30
CAMERA_DISCOVERY_TARGET_INTENT_ATTEMPTS=1
CAMERA_DISCOVERY_GEOCODER_REFEREE_MODEL=gemma4:31b-cloud
CAMERA_DISCOVERY_CANDIDATE_REVIEW_MODEL=qwen3.5:4b
CAMERA_DISCOVERY_CANDIDATE_REVIEW_TIMEOUT=60
CAMERA_DISCOVERY_CANDIDATE_REVIEW_BATCH_SIZE=8
CAMERA_DISCOVERY_MAX_CANDIDATE_REVIEWS=50
```

## Run

```bash
camera-discovery run "Get me all public live cameras in California" --profile fast --output-dir runs/test-fast
```

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
CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES=25
```


## Colab GeoJSON Review Table and Map

The live-test notebook can display either `camera.geojson` or `untrusted_camera_candidates.geojson`. It adds:

- a table of camera URL rows with name, target/location, stream URL, source URL, latitude, longitude, trust level, validation status, scope status, and thumbnail URL when present;
- `camera_candidates_table.csv` written to the run directory;
- an embedded Leaflet map that works in Colab;
- marker popups with GeoJSON properties, optional thumbnail/snapshot image, source/stream links, and a **Play video** button;
- HLS playback through hls.js when the browser supports the stream and CORS permits access.

Thumbnail display uses GeoJSON properties such as `thumbnail_url`, `snapshot_url`, `image_url`, `preview_image_url`, or the same keys inside `source_metadata`. If no image URL exists, the popup clearly states that no thumbnail URL is present.
