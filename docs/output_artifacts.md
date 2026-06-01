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
target_geometry.geojson                 # portable resolved target boundary/search geometry
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



## Target geometry artifact

`target_geometry.geojson` is a portable GeoJSON FeatureCollection for plotting resolved target geography in another application. It follows the target-geometry hierarchy:

1. **Primary geometry**: Nominatim polygon/multipolygon border when available. For a California query, this should be the California border geometry, not the rectangular bbox.
2. **Fallback geometry**: rectangular Nominatim `boundingbox`, represented as a GeoJSON polygon, only when no usable Nominatim border geometry is available.
3. **Last fallback geometry**: generic padded bbox only when no usable Nominatim polygon/multipolygon or Nominatim bbox is available and existing review-only policy permits fallback geometry.

Feature properties include target identifiers and provenance fields such as `geometry_role`, `geometry_source`, `nominatim_bbox`, `effective_bbox`, `bbox_verified`, and padding diagnostics when applicable. `review_artifacts.zip` includes `target_geometry.geojson` whenever it is written.

Target geometry features are emitted only from explicit primary, fallback, or last-fallback geometry. The artifact writer must not synthesize features from legacy `bbox`, `effective_bbox`, or other convenience fields when those explicit geometry fields are absent.

`logs/target_resolution.json`, `logs/target_resolution_all.json`, and `logs/targets/<target_id>/target_resolution.json` retain detailed resolver diagnostics. `logs/target_geometry_geojson_status.json` summarizes whether the portable target-geometry artifact was written and how many primary/fallback/last-fallback features it contains.

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


## Playlist exports and media validation dashboard

Normal `camera-discovery run` writes playlist and text outputs under `playlists/` after deterministic validation/output classification:

```text
playlists/trusted_media.m3u
playlists/trusted_media.txt
playlists/untrusted_review_media.m3u
playlists/untrusted_review_media.txt
playlists/hls_candidates.m3u
playlists/hls_candidates.txt
playlists/rtsp_candidates.m3u
playlists/rtsp_candidates.txt
playlists/live_or_reachable_media.m3u
playlists/live_or_reachable_media.txt
playlists/dead_or_restricted_media.txt
playlists/image_snapshots.txt
logs/playlist_export_summary.json
```

TXT files contain one URL per line. M3U files use extended M3U metadata for playable stream-style media. Image snapshots are written to TXT only because they are refreshing image URLs, not video playlists. `dead_or_restricted_media.txt` is diagnostic only and intentionally has no `.m3u` companion. Playlist eligibility never changes trust: `trusted_media.*` contains only candidates already eligible for trusted output, while review playlists remain untrusted audit conveniences.

Normal runs also write `media_validation_dashboard.json` at the run-output top level and `logs/media_validation_dashboard.json`. Required top-level fields are:

```json
{
  "total_candidates": 0,
  "validated": 0,
  "trusted": 0,
  "untrusted_review": 0,
  "dead": 0,
  "restricted": 0,
  "not_validated": 0
}
```

Counts are derived from real candidate rows and validation statuses, not placeholders. Optional nested fields include `by_media_type`, `by_validation_status`, and `outputs`. `RUN_EXPLANATION.md`, `logs/run_explanation.json`, and `review_artifacts.zip` include or reference the dashboard and playlist summary.

Harvest mode remains extraction-only. When harvested media records exist, it writes:

```text
playlists/harvested_media.m3u
playlists/harvested_media.txt
playlists/harvested_hls.m3u
playlists/harvested_hls.txt
playlists/harvested_rtsp.m3u
playlists/harvested_rtsp.txt
playlists/harvested_image_snapshots.txt
logs/playlist_export_summary.json
```

