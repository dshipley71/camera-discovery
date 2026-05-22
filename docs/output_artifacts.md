# Output Artifacts

`ReviewAndValidationPipeline` owns output writing. Empty trusted files are not left behind: if there are no trusted candidates, stale `camera.geojson` is removed and no trusted `cameras.md` or `camera_inventory.jsonl` is created.

## Trusted outputs

| File | Created when | Meaning |
|---|---|---|
| `camera.geojson` | Trusted candidates exist. | Validated, in-scope, coordinate-bearing trusted camera inventory. |
| `camera_inventory.jsonl` | Trusted candidates exist. | One dataclass record per trusted candidate. |
| `cameras.md` | Trusted candidates exist. | Markdown table of trusted candidates with name, location, camera type, ID, media type, refresh rate, coordinates, media URL, and source URL. |

Trusted output requires all of these conditions:

1. target has `trust_policy=trusted_allowed`;
2. target bbox is verified;
3. candidate has real coordinates;
4. candidate scope is `in_scope`;
5. validation marks the candidate trusted;
6. the candidate target ID is in the trusted target set.

## Review outputs

| File | Created when | Meaning |
|---|---|---|
| `untrusted_camera_candidates.geojson` | Coordinate-bearing non-trusted review candidates exist. | Review map inventory for candidates not written to trusted output. |
| `candidates/untrusted_camera_candidates_source_rows.jsonl` | Untrusted GeoJSON rows exist. | JSONL records for coordinate-bearing review candidates. |
| `camera_candidates_table.csv` | Every run reaching output writing. | All non-rejected candidates, including rows without coordinates that cannot be mapped. |
| `map.html` | Every run reaching output writing. | Embedded Leaflet map that merges trusted and untrusted GeoJSON when present. |
| `RUN_EXPLANATION.md` | Every run reaching output writing. | Plain-language summary of target count, candidates, GeoJSON coverage, media/provider counts, and output meaning. |
| `review_artifacts.zip` | Every run reaching output writing. | Packaged available outputs plus `logs/` and `candidates/`. |

## Diagnostics

Target-resolution diagnostics:

```text
logs/target_intent.json
logs/target_intent_llm_raw.json
logs/target_intent_llm_error.json
logs/target_resolution_all.json
logs/target_resolution.json
logs/geocoder_query_variants.json
logs/geocoder_candidate_scores.json
logs/targets/<target_id>/target_intent.json
logs/targets/<target_id>/geocoder_query_variants.json
logs/targets/<target_id>/geocoder_referee.json
logs/targets/<target_id>/geocoder_referee_llm_raw.json
logs/targets/<target_id>/geocoder_candidate_scores.json
logs/targets/<target_id>/target_resolution.json
```

Discovery diagnostics:

```text
logs/source_policy_summary.json
logs/blocked_source_rows.jsonl
logs/search_queries.json
logs/search_results.jsonl
logs/page_discovery_signals.jsonl
logs/browser_capture_decisions.jsonl
logs/browser_capture_results.jsonl
logs/browser_capture_errors.jsonl
logs/playwright_network_capture_errors.jsonl
logs/browser_capture_summary.json
logs/promoted_asset_host_rows.jsonl
logs/candidate_coordinate_enrichment.json
logs/candidate_semantic_review.json
logs/candidate_semantic_review_llm_raw.json
logs/targets/<target_id>/candidate_discovery_summary.json
candidates/<target_id>/agentic_candidates.jsonl
candidates/<target_id>/agentic_candidates_unique.jsonl
```

Validation/output diagnostics:

```text
logs/validation_results.jsonl
logs/validation_summary.json
logs/trusted_camera_geojson_status.json
logs/untrusted_camera_candidates_geojson_status.json
logs/camera_candidates_table_status.json
logs/camera_map_status.json
logs/output_summary.json
logs/run_explanation.json
logs/run_summary.json
```

## GeoJSON feature metadata

GeoJSON properties preserve candidate dataclass fields and source metadata. Common top-level properties include:

```text
name
location_display
camera_type
raw_camera_type
camera_id
camera_name
route
direction
intersection
cross_street
city
county
district
owner
agency
json_endpoint_url
json_record_path
json_record_schema_hint
media_type
snapshot_url
thumbnail_url
camera_refresh_rate
map_refresh_rate_seconds
trust_level
output_policy
review_required
untrusted_reason
target_bbox_trusted
target_id
target_label
target_index
```

## Harvest architecture outputs

`camera-discovery harvest-urls` is an extraction-only workflow. It does not validate, trust, geocode, scope-filter, LLM-review, or write GeoJSON/map/review artifacts. In addition to the plain URL files, harvest mode writes structured source-provided artifacts when public JSON/API/feed endpoints expose camera records.

Harvest outputs include:

- `camera_urls.txt` — plain direct media URLs, one URL per line.
- `camera_urls.csv` — flattened URL/media rows with grouping, source endpoint, location, service-status, refresh, and timestamp fields when source-provided.
- `camera_urls.jsonl` — one JSON object per media URL.
- `camera_records.jsonl` — one JSON object per structured source camera record, including normalized fields, field map, grouped media assets, and the raw source record.
- `camera_media_assets.jsonl` — one JSON object per media asset extracted from a camera record, including `camera_record_id`, `asset_id`, `asset_role`, `asset_field`, `field_path`, `media_type`, and provenance.
- `discovered_endpoints.jsonl` — catalog of discovered JSON/API/GeoJSON/ArcGIS/feed endpoints and source-completeness counts.
- `harvest_camera_inventory.jsonl` — handoff-oriented camera inventory rows marked source-provided, unvalidated, untrusted, ungeocoded, and not scope-filtered.
- `harvest_handoff.json` — manifest that points to the handoff files and records counts.
- `harvest_summary.json` — summary counts for URLs, structured records, media assets, endpoints, coordinates, orientation, source-reported `inService`, timestamps, update frequencies, and source-row provenance. The `source_rows` object reports whether `SOURCES.md` existed, was loaded, and contributed directory rows, plus counts by provider (`directory`, `blind`, `direct`) and source kind.
- `logs/source_rows_summary.json` — the same source-row provenance summary written as a standalone log for quick debugging of `--discovery-mode both`, `--sources-file`, and directory-vs-blind behavior.

`source_url` and `source_endpoint_url` are provenance fields. If a URL row came from a JSON endpoint, those fields should remain the endpoint URL; the direct media URL remains in `url` / `media_url`.
