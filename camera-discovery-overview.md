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
