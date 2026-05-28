# Output Artifacts

## Normal pipeline artifacts

The normal `camera-discovery run` workflow writes target-resolution, discovery, validation, and review artifacts under the selected output directory.

Common top-level files:

```text
RUN_EXPLANATION.md
camera.geojson                         # trusted output; only when trusted records exist
camera_inventory.jsonl                  # trusted inventory; only when trusted records exist
cameras.md                              # trusted markdown inventory; only when trusted records exist
untrusted_camera_candidates.geojson     # review/audit map output when review candidates exist
camera_candidates_table.csv             # non-rejected candidate table
map.html                                # embedded Leaflet review/trusted map
review_artifacts.zip                    # package of review artifacts
```

Common logs:

```text
logs/run_summary.json
logs/pipeline_candidate_summary.json
logs/candidate_discovery_summary.json
logs/candidate_priority_summary.json
logs/validation_priority_summary.json
logs/validation_results.jsonl
logs/validation_summary.json
logs/output_summary.json

`logs/validation_summary.json` includes validation concurrency/runtime fields such as `validation_workers`, `http_timeout`, and `parallel_validation`.
logs/run_explanation.json
logs/target_resolution_all.json
```

Per-target logs are written under:

```text
logs/targets/<target_id>/
candidates/<target_id>/
```

Examples:

```text
logs/targets/<target_id>/target_intent.json
logs/targets/<target_id>/geocoder_query_variants.json
logs/targets/<target_id>/geocoder_candidate_scores.json
logs/targets/<target_id>/target_resolution.json
logs/targets/<target_id>/candidate_discovery_summary.json
candidates/<target_id>/agentic_candidates.jsonl
candidates/<target_id>/agentic_candidates_unique.jsonl
```

Browser and extraction diagnostics include:

```text
logs/browser_capture_preflight.jsonl
logs/browser_capture_decisions.jsonl
logs/browser_capture_results.jsonl
logs/browser_capture_errors.jsonl
logs/browser_capture_summary.json
logs/page_discovery_signals.jsonl
logs/structured_endpoint_discovery.jsonl
logs/json_endpoint_records.jsonl
logs/json_endpoint_extraction_errors.jsonl
logs/source_policy_summary.json
logs/blocked_source_rows.jsonl
logs/search_queries.json
logs/search_results.jsonl
```


## Validation progress

During validation, plain progress prints candidate-level milestones such as:

```text
Progress: validation selected 2287 candidates; workers=24; timeout=10.0s; full_segment_check=False.
Progress: validating streams 229/2287; live=180; dead=30; unknown=19.
Progress: validation complete: attempted=2287; live=...; dead=...; unknown=...; skipped=0.
```

`--progress-style events` emits machine-readable `validation_candidates_selected`, `validation_candidate_processed`, and `validation_complete` records. No validation candidate cap is applied by these progress features.

## Trusted versus review artifacts

Trusted output requires:

```text
verified target geometry
+ in-scope coordinates
+ successful media validation
+ target trust_policy=trusted_allowed
```

`fast` profile disables validation, so trusted files should not be expected. The pipeline removes stale trusted files when no trusted candidates exist.

`untrusted_camera_candidates.geojson` is review/audit output. It is not a trusted inventory and may include review-only, unknown, or out-of-scope coordinate-bearing candidates.

## Candidate priority fields

Candidate tables and GeoJSON properties may include:

```text
candidate_priority_bucket
```

Coordinate-bearing, deterministically in-scope candidates are prioritized for validation and review ordering. This ordering does not change trust.

## Harvest artifacts

`camera-discovery harvest-urls` writes extraction-only artifacts:

```text
source_rows.jsonl
camera_urls.txt
camera_urls.csv
camera_urls.jsonl
hls_urls.txt
mjpeg_urls.txt
image_snapshot_urls.txt
video_file_urls.txt
stream_urls.txt
unknown_media_urls.txt
camera_records.jsonl
camera_media_assets.jsonl
discovered_endpoints.jsonl
harvest_camera_inventory.jsonl
harvest_handoff.json
harvest_summary.json
```

Harvest logs include:

```text
logs/source_rows_summary.json
logs/harvest_summary.json
logs/handoff_summary.json
logs/harvest_errors.jsonl
logs/harvest_blind_search_diagnostics.jsonl
logs/harvest_blocked_source_rows.jsonl
logs/harvest_structured_endpoint_discovery.jsonl
logs/browser_capture_preflight.jsonl
logs/browser_capture_summary.json
logs/endpoint_catalog_summary.json
```

When `--write-intermediate-records` is enabled, harvest also writes:

```text
raw_media_records.jsonl
unique_media_records.jsonl
media_filtered_records.jsonl
image_filtered_records.jsonl
logs/intermediate_records_summary.json
```

These files can be very large and should be used mainly for debugging.

## Harvest handoff

`harvest_handoff.json` currently uses:

```json
{
  "schema_version": "harvest-handoff/v2",
  "handoff_default_scope": "filtered_media_records"
}
```

For media-filtered harvests, normal `run --harvest-input harvest_handoff.json` loads filtered media records from `camera_urls.jsonl` by default. For all-media harvests, it may load structured inventory.

`run --harvest-input` writes candidate summaries with separate `native_discovery`, `harvest_input`, and `combined` sections. In the default `--harvest-input-mode handoff-only` path, native discovery is disabled and handoff candidate counts are bounded by the selected handoff records/assets and resolved target count. In `--harvest-input-mode seed`, the harvest input is merged with normal native discovery and may produce many additional candidates. The normal pipeline treats all loaded harvest records as untrusted data and still applies target resolution, deterministic scope gates, validation, and trust rules.
