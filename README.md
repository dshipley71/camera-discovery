# Camera Discovery

`camera-discovery` is a Python CLI and notebook-supported application for discovering public camera media for a user-specified geography, such as public traffic, weather, webcam, HLS, or refreshing image snapshot cameras. The current implementation is built around three services:

1. `TargetResolver`
2. `CandidateDiscoveryEngine`
3. `ReviewAndValidationPipeline`

The important trust boundary is unchanged: LLMs interpret and rank evidence, while deterministic code verifies geometry, validates media, authorizes trusted output, and writes artifacts.

## Pipeline diagram

![Pipeline](architecture.svg)

## Architecture

### 1. Target resolution

`TargetResolver.resolve_all()` resolves one or more geographic targets from the user query. It uses a deterministic phrase parser as a guardrail and an LLM target-intent call to produce structured target intent: canonical target, place name, scope type, admin/country hints, camera-type intent, and geocoder query variants.

Each target is geocoded with Nominatim. Candidate geocoder results are scored with deterministic checks for bbox validity, bbox plausibility, result type, admin-region match, and country hints. An LLM geocoder referee may rank or comment on geocoder candidates, but it cannot override deterministic hard rejections. A target receives one of these trust policies:

| Trust policy | Meaning |
|---|---|
| `trusted_allowed` | Verified target geometry exists and validation is enabled. |
| `review_only` | Discovery may proceed, but trusted output is blocked. This is normal in `fast` profile. |
| `stop` | Discovery should not proceed for that target. |

Multi-location queries are processed as separate targets. Each target gets a stable `target_id`, target-specific diagnostics, and target metadata on each candidate and GeoJSON feature.

### 2. Candidate discovery

`CandidateDiscoveryEngine` discovers candidate media rows from four modes:

| Mode | Source rows |
|---|---|
| `blind` | DuckDuckGo HTML search results generated from target/camera-intent queries. |
| `directory` | Enabled user-approved rows from `SOURCES.md`. |
| `both` | Directory rows and blind-search rows discovered in parallel, then merged. This is the default. |
| `direct` | User-provided `--seed-url` rows. |

For each accepted source row, the engine runs generic extraction paths for:

- direct HLS `.m3u8` URLs;
- static page/feed text scanning for HLS and image media;
- structured HTML image/source tags;
- JSON responses and linked JSON/API/feed/map-layer endpoints;
- GeoJSON and ArcGIS-style feature records;
- JavaScript configuration/state blobs embedded in HTML;
- browser-rendered/network capture when the page looks dynamic.

Candidate media can be HLS video or `image_snapshot`. Structured JSON metadata is preserved when available, including fields such as `camera_id`, `camera_name`, `camera_type`, `raw_camera_type`, route/direction/location fields, owner/agency, refresh-rate fields, `json_endpoint_url`, `json_record_path`, and `json_record_schema_hint`.

### 3. Coordinate enrichment and scope gates

The discovery engine never invents coordinates. It enriches candidates in this order:

1. coordinates already present in structured source records, GeoJSON, ArcGIS geometry, metadata, or URL query parameters;
2. Nominatim geocoding from specific candidate title/location metadata;
3. optional LLM candidate location-name inference, followed by Nominatim geocoding and target-scope validation.

The LLM location-inference stage may propose place-name/geocoder query strings from candidate evidence. It may not return latitude/longitude. Accepted coordinates still come from Nominatim and are checked against the verified target bbox when one exists.

Candidate scope status is deterministic:

| Scope status | Meaning |
|---|---|
| `in_scope` | Candidate coordinates fall inside verified target bbox. |
| `out_of_scope` | Candidate coordinates fall outside verified target bbox and the candidate is rejected. |
| `review` | Candidate has coordinates, but target geometry is not verified. |
| `unknown` | Candidate lacks coordinates. |

An LLM semantic review can mark candidates `in_scope`, `out_of_scope`, `review`, or `unknown`. It can downgrade high-confidence out-of-scope candidates, but it cannot validate media, create trusted coordinates, or authorize trusted output.

### 4. Browser capture

Browser/network capture is optional and enabled by default. Static extraction runs first. Browser capture is selected only when page signals and budgets justify it, such as dynamic app-shell pages, map/player libraries, JSON endpoint hints, HLS text hints, or camera text signals.

Supported browser backends:

| Backend | Setting | Install |
|---|---|---|
| Playwright | `CAMERA_DISCOVERY_BROWSER_BACKEND=playwright` | `python -m pip install -e .[playwright]` and `python -m playwright install chromium` |
| CloakBrowser | `CAMERA_DISCOVERY_BROWSER_BACKEND=cloakbrowser` | `python -m pip install -e .[cloakbrowser]` |

Playwright is the default backend. Capture diagnostics are written to `logs/browser_capture_decisions.jsonl`, `logs/browser_capture_results.jsonl`, `logs/browser_capture_errors.jsonl`, `logs/page_discovery_signals.jsonl`, and `logs/browser_capture_summary.json`.

### 5. Validation and outputs

`ReviewAndValidationPipeline` owns validation and artifact writing. In `fast`, validation is disabled and trusted output is blocked. In `balanced`, HLS validation fetches playlists and accepts playlist bodies containing `#EXTM3U`; image snapshot validation fetches image endpoints twice with cache-busting and checks whether they look refreshable. In `full`, the HLS path also checks the first media or variant segment URL for reachability through the code path currently named `ffprobe_enabled`.

Validation statuses include:

| Status | Meaning |
|---|---|
| `not_validated` | Validation was disabled or trusted output was blocked. |
| `active_live_unknown` | HLS playlist is reachable and decodable, but segment reachability was not checked. |
| `active_live_verified` | HLS playlist and first segment/variant are reachable. |
| `active_image_snapshot_refreshing` | Snapshot endpoint returns images that changed between refresh checks. |
| `active_image_snapshot_static_unverified` | Snapshot endpoint returns an image but did not change during the sampling window. |
| `decode_failed` | HLS response did not look like a valid playlist. |
| `dead_link`, `offline_http`, `restricted_http` | Network, HTTP, or access failure. |
| `active_playlist_dead_segments` | Playlist was reachable but first segment/variant was not. |
| `static_image_asset`, `image_snapshot_not_image` | Snapshot candidate was rejected as a static asset or non-image. |

Trusted `camera.geojson` is written only when every deterministic gate passes: trusted target policy, verified target bbox, in-scope candidate coordinates, successful validation, and trusted candidate state.

## Runtime profiles

| Profile | Validation | Trusted output |
|---|---|---|
| `fast` | Disabled | Blocked; review artifacts only. |
| `balanced` | HLS playlist GET + `#EXTM3U`; image snapshot refresh checks | Allowed when deterministic gates pass. |
| `full` | Balanced checks plus first HLS segment/variant reachability | Allowed when deterministic gates pass. |

## Install

```bash
python -m pip install -e .[dev,notebook]
```

Install browser extras only when needed:

```bash
python -m pip install -e .[playwright]
python -m playwright install chromium
# or
python -m pip install -e .[cloakbrowser]
```

## LLM provider configuration

The default provider is `ollama-cloud` with default model `gemma4:31b-cloud`. For Ollama Cloud, set `OLLAMA_API_KEY`. Local Ollama uses `CAMERA_DISCOVERY_LLM_PROVIDER=ollama` and defaults to `http://localhost:11434` unless `OLLAMA_BASE_URL` is set.

Supported providers:

| Provider value | Client |
|---|---|
| `ollama-cloud` | Ollama-compatible `/api/chat` at `https://ollama.com` unless `OLLAMA_BASE_URL` overrides it. |
| `ollama` | Ollama-compatible `/api/chat`, default `http://localhost:11434`. |
| `openai-compatible`, `openai`, `openai_compatible` | `/v1/chat/completions`, configured with `OPENAI_COMPATIBLE_BASE_URL` and `OPENAI_COMPATIBLE_API_KEY`. |
| `bedrock` | AWS Bedrock Runtime Converse API, configured with AWS credentials and region. |

Global provider/model settings:

```bash
CAMERA_DISCOVERY_LLM_PROVIDER=ollama-cloud
CAMERA_DISCOVERY_LLM_MODEL=gemma4:31b-cloud
OLLAMA_API_KEY=...
```

Stage-specific overrides are supported:

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

## Common run commands

```bash
camera-discovery run "Get me all public live cameras in California" --profile fast --output-dir runs/test-fast
```

```bash
camera-discovery run "Get me public traffic cameras from California" \
  --profile balanced \
  --discovery-mode both \
  --sources-file SOURCES.md \
  --output-dir runs/california-balanced
```

```bash
camera-discovery run "Review this public HLS URL" \
  --discovery-mode direct \
  --seed-url "https://example.org/live/camera.m3u8" \
  --profile balanced \
  --output-dir runs/direct-review
```

Progress is enabled by default. Use `--no-progress` to suppress progress rendering or `--progress-style events` for machine-readable progress JSON lines.

## Main configuration knobs

| Variable | Default | Purpose |
|---|---:|---|
| `CAMERA_DISCOVERY_PROFILE` | `fast` | Runtime profile if `--profile` is not supplied. |
| `CAMERA_DISCOVERY_DISCOVERY_MODE` | `both` | `blind`, `directory`, `both`, or `direct`. |
| `CAMERA_DISCOVERY_SOURCES_FILE` | `SOURCES.md` | Markdown source registry. |
| `CAMERA_DISCOVERY_MAX_SEARCH_QUERIES` | `4` | Max blind-search queries per target. |
| `CAMERA_DISCOVERY_MAX_SEARCH_RESULTS_PER_QUERY` | `5` | DuckDuckGo result rows per search query. |
| `CAMERA_DISCOVERY_MAX_HLS_CANDIDATES` | `100` | HLS candidate budget. |
| `CAMERA_DISCOVERY_MAX_IMAGE_SNAPSHOT_CANDIDATES` | `50` | Image snapshot candidate budget. |
| `CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES` | HLS + snapshot budgets | Overall candidate budget. |
| `CAMERA_DISCOVERY_MAX_CANDIDATE_GEOCODES` | total candidate budget | Candidate metadata geocoding budget. |
| `CAMERA_DISCOVERY_MAX_STATE_SCALE_CANDIDATE_GEOCODES` | total candidate budget | Candidate geocoding budget for state-scale targets. |
| `CAMERA_DISCOVERY_ENABLE_LLM_LOCATION_INFERENCE` | `true` | Enable LLM place-name inference followed by geocoding. |
| `CAMERA_DISCOVERY_MAX_LLM_LOCATION_INFERENCES` | total candidate budget | LLM location-name inference budget. |
| `CAMERA_DISCOVERY_LOCATION_INFERENCE_MIN_CONFIDENCE` | `0.70` | Minimum accepted LLM inference confidence before geocoding. |
| `CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE` | `true` | Enable browser/network capture routing. |
| `CAMERA_DISCOVERY_BROWSER_BACKEND` | `playwright` | `playwright` or `cloakbrowser`. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES` | `20` | Global browser capture page budget. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_BLIND` | `6` | Browser capture budget for blind rows. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_DIRECTORY` | `12` | Browser capture budget for directory rows. |
| `CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_PER_HOST` | `3` | Per-host browser capture budget. |
| `CAMERA_DISCOVERY_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE` | `10` | Browser-discovered JSON/API endpoint fetch budget per page. |
| `CAMERA_DISCOVERY_IMAGE_SNAPSHOT_REFRESH_DELAY_SECONDS` | `2.0` | Fallback delay between snapshot image refresh checks. |

## Source registry

`SOURCES.md` is optional and starts empty. It has two sections:

- **Allowed Sources** are user-approved source pages, feeds, dynamic sites, direct HLS URLs, or site roots. They are used only in `directory` and `both` modes.
- **Blocked Sources** are global deny patterns. They are enforced for blind search rows, directory rows, direct seed URLs, fetched page URLs, extracted media URLs, and final candidate rows.

Allowed source `type` values are `page`, `feed`, `direct_hls`, `site`, and `dynamic`.

## Output artifacts

Trusted files are written only when trusted candidates exist. Empty trusted GeoJSON/Markdown inventory files are removed instead of being left behind.

| Artifact | Meaning |
|---|---|
| `camera.geojson` | Trusted, validated, in-scope coordinate-bearing inventory. |
| `camera_inventory.jsonl` | Trusted inventory records. |
| `cameras.md` | Trusted inventory table with name, location, type, ID, media, refresh rate, coordinates, and URLs. |
| `untrusted_camera_candidates.geojson` | Coordinate-bearing candidates not written to trusted output. |
| `candidates/untrusted_camera_candidates_source_rows.jsonl` | Review JSONL for coordinate-bearing untrusted candidates. |
| `camera_candidates_table.csv` | CSV table for all non-rejected candidates, including rows without coordinates. |
| `map.html` | Self-contained Leaflet map merging trusted and untrusted GeoJSON when present. |
| `RUN_EXPLANATION.md` | Human-readable run summary. |
| `review_artifacts.zip` | Packaged review bundle containing available outputs, logs, and candidates. |

Important diagnostics include:

```text
logs/target_intent.json
logs/target_intent_llm_raw.json
logs/target_resolution_all.json
logs/targets/<target_id>/target_resolution.json
logs/targets/<target_id>/geocoder_referee.json
logs/targets/<target_id>/geocoder_candidate_scores.json
logs/source_policy_summary.json
logs/search_queries.json
logs/search_results.jsonl
logs/page_discovery_signals.jsonl
logs/browser_capture_decisions.jsonl
logs/browser_capture_results.jsonl
logs/browser_capture_summary.json
logs/candidate_coordinate_enrichment.json
logs/candidate_semantic_review.json
logs/validation_results.jsonl
logs/validation_summary.json
logs/output_summary.json
logs/run_explanation.json
logs/run_summary.json
candidates/<target_id>/agentic_candidates.jsonl
candidates/<target_id>/agentic_candidates_unique.jsonl
```

## Notebook

Use `notebooks/camera_discovery_live_test.ipynb` for live Colab runs. The notebook keeps notebook-specific helpers inside the notebook and uses the application CLI/source modules for the actual run. It displays profile/provider settings, target diagnostics, candidate summaries, output counts, artifact links, the CSV review table, and a Colab-friendly embedded Leaflet map.

The map supports HLS playback attempts through hls.js and native playback when browser/CORS conditions allow it. Image snapshot cameras display snapshots and refresh metadata when available.

## Development checks

```bash
PYTHONPATH=src python -m compileall src
PYTHONPATH=src python -m pytest -q
```

No tests or docs should add fake camera inventories, synthetic streams, fabricated coordinates, simulated validation success, or hard-coded real-world target/source behavior.

### Harvest architecture and run handoff

`camera-discovery harvest-urls` now has two extraction lanes: a structured camera/feed harvester for public JSON/API/GeoJSON/ArcGIS-style endpoints and a raw camera/media URL harvester for HTML, JavaScript, browser/network capture, direct seeds, linked endpoints, and escaped/encoded text. Harvest mode remains extraction-only: it bypasses target resolution, geocoding, validation, trust classification, scope enforcement, LLM review, GeoJSON/maps, `cameras.md`, and review ZIP generation.

When structured endpoints expose fields such as coordinates, direction/bearing/heading, `inService`, timestamps, image descriptions, refresh/update frequencies, `streamingVideoURL`, `currentImageURL`, and `referenceImageURL`, harvest mode preserves the full raw camera record, normalizes useful fields, groups media assets by `camera_record_id`, and writes `camera_records.jsonl`, `camera_media_assets.jsonl`, `discovered_endpoints.jsonl`, `harvest_camera_inventory.jsonl`, and `harvest_handoff.json` alongside the existing URL files.

Harvest summaries also include source-row provenance so users can verify whether `SOURCES.md` was actually used. Check `harvest_summary.json` → `source_rows` or `logs/source_rows_summary.json` for `sources_file_used`, `selected_by_provider`, `selected_directory_rows`, `selected_blind_rows`, and `selected_direct_rows`.

For debug/analysis runs, add `--write-intermediate-records` to write `raw_media_records.jsonl`, `unique_media_records.jsonl`, `media_filtered_records.jsonl`, and `image_filtered_records.jsonl`. These opt-in files expose the raw block-policy-filtered records before deduplication, the deduped records before media filtering, the media-filtered records before image-asset filtering, and the post-image-filter records before the final `--max-urls` cap. They can be large, so normal harvest runs do not write them by default.

Use `--image-asset-filter raw|exclude-page-assets|camera-evidence` to control image snapshot filtering. `raw` preserves broad extraction, `exclude-page-assets` removes obvious logos/icons/social/static page assets, and `camera-evidence` keeps image records only when camera/snapshot evidence is present.

A normal run can consume the handoff without bypassing normal inventory behavior:

```bash
camera-discovery run "California traffic cameras" \
  --output-dir runs/run-from-harvest \
  --harvest-input runs/harvest-california/harvest_handoff.json
```

Harvest handoff data is source-provided and unvalidated. It seeds/enriches candidates so the run workflow can avoid rediscovering metadata the source already exposed, while still applying normal target-aware processing.
