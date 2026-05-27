# Candidate Discovery Agent

Maintain normal-run candidate discovery as a target-aware workflow coordinated by `CandidateDiscoveryEngine` and the discovery stage modules.

## Public service

```python
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
```

`services/discovery_engine.py` is the public orchestration/compatibility path. Stage implementation belongs in focused modules under `discovery/`, `extraction/`, and `enrichment/`.

## Source rows

Discovery modes:

```text
blind       DuckDuckGo/search-derived rows
directory   enabled user-approved `SOURCES.md` rows
both        blind + directory rows
direct      user-provided `--seed-url` rows
```

`SOURCES.md` allowed rows are only for `directory` and `both`. Blocked source patterns apply globally.

## Extraction

Support generic extraction from:

- direct HLS `.m3u8` URLs;
- static text/HTML HLS and image media;
- structured HTML image/source tags;
- JSON/API/feed/map-layer endpoints;
- GeoJSON and ArcGIS-style features;
- JavaScript configuration/state blobs;
- optional browser-rendered/network capture.

Do not add source-specific agency/domain hacks. Improve generic extraction helpers instead.

## Candidate processing

Coordinates must come from source evidence or real geocoding. LLM location inference may produce geocoder query strings only, never coordinates.

Apply deterministic scope statuses:

```text
in_scope
out_of_scope
review
unknown
```

Candidate semantic review is advisory and does not validate streams or authorize trusted output.

## Candidate priority

Use `discovery/candidate_priority.py` for ordering. Located, deterministically in-scope candidates should be prioritized for validation/review budgets and output ordering. Coordinates alone do not make a candidate trusted.

## Required artifacts

Maintain per-target and aggregate diagnostics, including:

```text
logs/source_policy_summary.json
logs/search_queries.json
logs/search_results.jsonl
logs/page_discovery_signals.jsonl
logs/browser_capture_*.jsonl/json
logs/structured_endpoint_discovery.jsonl
logs/json_endpoint_records.jsonl
candidates/<target_id>/agentic_candidates.jsonl
candidates/<target_id>/agentic_candidates_unique.jsonl
logs/targets/<target_id>/candidate_discovery_summary.json
```
