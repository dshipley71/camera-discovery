# Camera Discovery — Architecture Overview

## Pipeline Diagram

```svg
<svg width="100%" viewBox="0 0 680 580" role="img" xmlns="http://www.w3.org/2000/svg">
<title>Camera Discovery — 3-stage pipeline architecture</title>
<desc>Flowchart showing TargetResolver, CandidateDiscoveryEngine, and ReviewAndValidationPipeline stages with LLM advisory and deterministic trust boundaries</desc>
<defs>
<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="#888" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker>
</defs>

<!-- INPUT -->
<rect x="240" y="20" width="200" height="40" rx="8" fill="#e8e6e0" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="340" y="44" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Natural language query</text>
<line x1="340" y1="60" x2="340" y2="88" stroke="#888" stroke-width="1.2" marker-end="url(#arrow)"/>

<!-- STAGE 1 container -->
<rect x="60" y="88" width="560" height="110" rx="12" fill="#e1f5ee" stroke="#1d9e75" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="340" y="107" text-anchor="middle" fill="#085041">Stage 1 — TargetResolver</text>

<!-- Stage 1 boxes -->
<rect x="80" y="118" width="150" height="68" rx="8" fill="#f1efe8" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="155" y="143" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Deterministic</text>
<text font-family="sans-serif" font-size="11" x="155" y="161" text-anchor="middle" fill="#5f5e5a">regex + phrase parsing</text>
<text font-family="sans-serif" font-size="11" x="155" y="175" text-anchor="middle" fill="#5f5e5a">Nominatim geocoding</text>

<rect x="265" y="118" width="150" height="68" rx="8" fill="#eeedfe" stroke="#7f77dd" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="340" y="143" text-anchor="middle" dominant-baseline="central" fill="#26215c">LLM advisory</text>
<text font-family="sans-serif" font-size="11" x="340" y="161" text-anchor="middle" fill="#534ab7">intent extraction</text>
<text font-family="sans-serif" font-size="11" x="340" y="175" text-anchor="middle" fill="#534ab7">geocoder referee</text>

<rect x="450" y="118" width="150" height="68" rx="8" fill="#f1efe8" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="525" y="143" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Trust gate</text>
<text font-family="sans-serif" font-size="11" x="525" y="161" text-anchor="middle" fill="#5f5e5a">bbox plausibility</text>
<text font-family="sans-serif" font-size="11" x="525" y="175" text-anchor="middle" fill="#5f5e5a">scope/admin check</text>

<line x1="340" y1="198" x2="340" y2="226" stroke="#888" stroke-width="1.2" marker-end="url(#arrow)"/>
<text font-family="sans-serif" font-size="11" x="356" y="215" dominant-baseline="central" fill="#5f5e5a">TargetContext + trust policy</text>

<!-- STAGE 2 container -->
<rect x="60" y="226" width="560" height="130" rx="12" fill="#e6f1fb" stroke="#185fa5" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="340" y="245" text-anchor="middle" fill="#042c53">Stage 2 — CandidateDiscoveryEngine</text>

<rect x="80" y="258" width="140" height="86" rx="8" fill="#f1efe8" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="150" y="279" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Source providers</text>
<text font-family="sans-serif" font-size="11" x="150" y="297" text-anchor="middle" fill="#5f5e5a">blind DDG search</text>
<text font-family="sans-serif" font-size="11" x="150" y="311" text-anchor="middle" fill="#5f5e5a">SOURCES.md directory</text>
<text font-family="sans-serif" font-size="11" x="150" y="325" text-anchor="middle" fill="#5f5e5a">direct seed URLs</text>

<rect x="240" y="258" width="160" height="86" rx="8" fill="#f1efe8" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="320" y="279" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Extraction</text>
<text font-family="sans-serif" font-size="11" x="320" y="297" text-anchor="middle" fill="#5f5e5a">m3u8 regex + HTML tags</text>
<text font-family="sans-serif" font-size="11" x="320" y="311" text-anchor="middle" fill="#5f5e5a">JSON / GeoJSON walk</text>
<text font-family="sans-serif" font-size="11" x="320" y="325" text-anchor="middle" fill="#5f5e5a">JS blob + coord enrich</text>

<rect x="420" y="258" width="180" height="86" rx="8" fill="#eeedfe" stroke="#7f77dd" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="510" y="279" text-anchor="middle" dominant-baseline="central" fill="#26215c">LLM advisory</text>
<text font-family="sans-serif" font-size="11" x="510" y="297" text-anchor="middle" fill="#534ab7">semantic review (scope)</text>
<text font-family="sans-serif" font-size="11" x="510" y="311" text-anchor="middle" fill="#534ab7">deterministic bbox gate</text>
<text font-family="sans-serif" font-size="11" x="510" y="325" text-anchor="middle" fill="#534ab7">block list applied</text>

<line x1="340" y1="356" x2="340" y2="384" stroke="#888" stroke-width="1.2" marker-end="url(#arrow)"/>
<text font-family="sans-serif" font-size="11" x="356" y="372" dominant-baseline="central" fill="#5f5e5a">CandidateSet (raw / unique / scoped)</text>

<!-- STAGE 3 container -->
<rect x="60" y="384" width="560" height="110" rx="12" fill="#faece7" stroke="#993c1d" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="340" y="403" text-anchor="middle" fill="#4a1b0c">Stage 3 — ReviewAndValidationPipeline</text>

<rect x="80" y="415" width="155" height="68" rx="8" fill="#f1efe8" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="157" y="440" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Stream validation</text>
<text font-family="sans-serif" font-size="11" x="157" y="458" text-anchor="middle" fill="#5f5e5a">HTTP HEAD + #EXTM3U</text>
<text font-family="sans-serif" font-size="11" x="157" y="472" text-anchor="middle" fill="#5f5e5a">ffprobe (FULL profile)</text>

<rect x="263" y="415" width="155" height="68" rx="8" fill="#f1efe8" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="340" y="440" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Trust decision</text>
<text font-family="sans-serif" font-size="11" x="340" y="458" text-anchor="middle" fill="#5f5e5a">in_scope + active stream</text>
<text font-family="sans-serif" font-size="11" x="340" y="472" text-anchor="middle" fill="#5f5e5a">+ verified bbox → trusted</text>

<rect x="446" y="415" width="154" height="68" rx="8" fill="#f1efe8" stroke="#aaa" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="13" font-weight="500" x="523" y="440" text-anchor="middle" dominant-baseline="central" fill="#2c2c2a">Artifact writing</text>
<text font-family="sans-serif" font-size="11" x="523" y="458" text-anchor="middle" fill="#5f5e5a">GeoJSON / JSONL / CSV</text>
<text font-family="sans-serif" font-size="11" x="523" y="472" text-anchor="middle" fill="#5f5e5a">Leaflet map + ZIP</text>

<!-- Output arrows -->
<line x1="200" y1="494" x2="200" y2="532" stroke="#888" stroke-width="1.2" marker-end="url(#arrow)"/>
<line x1="340" y1="494" x2="340" y2="532" stroke="#888" stroke-width="1.2" marker-end="url(#arrow)"/>
<line x1="480" y1="494" x2="480" y2="532" stroke="#888" stroke-width="1.2" marker-end="url(#arrow)"/>

<!-- Output boxes -->
<rect x="80" y="532" width="230" height="36" rx="8" fill="#e1f5ee" stroke="#1d9e75" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="11" x="195" y="554" text-anchor="middle" dominant-baseline="central" fill="#085041">camera.geojson (trusted only)</text>

<rect x="330" y="532" width="270" height="36" rx="8" fill="#faeeda" stroke="#ba7517" stroke-width="0.5"/>
<text font-family="sans-serif" font-size="11" x="465" y="554" text-anchor="middle" dominant-baseline="central" fill="#633806">untrusted_camera_candidates.geojson</text>
</svg>
```

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
