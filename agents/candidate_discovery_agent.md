# 04 — CandidateDiscoveryEngine Agent

`CandidateDiscoveryEngine` is the single discovery service and public orchestration/import contract. Keep discovery providers as input adapters inside this service, but keep reusable helper logic in focused modules such as `discovery/source_rows.py`, `extraction/`, and `enrichment/location.py`. Do not move low-level parsing, HTTP, browser, JSON, pagination, or media-classification logic back into a monolithic engine file.

## Discovery providers

Current providers:

```text
BlindSearchSourceProvider-equivalent logic  query-driven DuckDuckGo HTML search
DirectorySourceProvider                     enabled user-approved SOURCES.md entries
DirectUrlSourceProvider                     user-provided --seed-url values
```

`both` mode discovers directory rows and blind-search rows in parallel, then merges them into the same extraction path.

## Discovery modes

```text
blind       = blind search only
directory   = SOURCES.md allowed sources only
both        = blind search + SOURCES.md allowed sources
direct      = seed URLs only
```

CLI/config exposes:

```bash
--discovery-mode blind|directory|both|direct
--sources-file SOURCES.md
--seed-url <url>
--block-pattern <pattern>
```

Environment variables:

```bash
CAMERA_DISCOVERY_DISCOVERY_MODE=both
CAMERA_DISCOVERY_SOURCES_FILE=SOURCES.md
CAMERA_DISCOVERY_BLOCK_PATTERNS=
```

## SOURCES.md format

```markdown
## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|

## Blocked Sources

| pattern | reason |
|---|---|
```

Allowed source `type` values parsed by the current code:

```text
page
feed
direct_hls
site
dynamic
```

## Extraction duties

For every accepted source row, support generic extraction from:

- direct HLS `.m3u8` URLs;
- static text/HTML for HLS and image snapshot URLs;
- structured HTML image/source tags;
- JSON responses and JSON-like page state;
- linked JSON/API/feed/map-layer endpoints;
- GeoJSON and ArcGIS-style features;
- browser network capture/rendered HTML for dynamic pages.

Preserve structured metadata such as `camera_id`, `camera_name`, `camera_type`, `raw_camera_type`, location fields, route/direction, owner/agency, refresh-rate fields, `json_endpoint_url`, `json_record_path`, and `json_record_schema_hint`.

## Browser capture

Browser capture is optional and budgeted. Static extraction runs first. Use Playwright by default and CloakBrowser only when `CAMERA_DISCOVERY_BROWSER_BACKEND=cloakbrowser`.

Required diagnostics include:

```text
logs/page_discovery_signals.jsonl
logs/browser_capture_decisions.jsonl
logs/browser_capture_results.jsonl
logs/browser_capture_errors.jsonl
logs/browser_capture_summary.json
```

## Coordinate and scope duties

Coordinates must come from source evidence or Nominatim geocoding. Optional LLM location inference may produce geocoder query strings only, never coordinates.

Apply deterministic scope gates before final output:

```text
in_scope
out_of_scope
review
unknown
```

LLM semantic review does not validate stream liveness and does not authorize trusted output.

## Required artifacts

```text
logs/source_policy_summary.json
logs/blocked_source_rows.jsonl
logs/search_queries.json
logs/search_results.jsonl
logs/candidate_coordinate_enrichment.json
logs/candidate_semantic_review.json
candidates/<target_id>/agentic_candidates.jsonl
candidates/<target_id>/agentic_candidates_unique.jsonl
logs/targets/<target_id>/candidate_discovery_summary.json
```

## Guardrails

- Do not let blind search read allowed rows from `SOURCES.md`.
- Do apply blocked patterns globally.
- Do not auto-edit `SOURCES.md`.
- Do not treat directory sources as trusted evidence.
- Do not bypass deterministic validation/trust gates.
- Do not add source-specific agency/domain logic.
