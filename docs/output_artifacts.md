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
camera_candidates_table.csv             # all unique candidates table
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

Feature properties include target identifiers and explicit geometry provenance fields such as `geometry_role`, `geometry_source`, `primary_geometry_source`, `fallback_geometry_source`, `last_fallback_geometry_source`, `bbox_verified`, and geometry status. `review_artifacts.zip` includes `target_geometry.geojson` only when at least one explicit target geometry feature is written.

Target geometry features are emitted only from explicit primary, fallback, or last-fallback geometry fields: `primary_geometry_geojson`, `fallback_geometry_bbox`, or `last_fallback_geometry_bbox`. The artifact writer and map overlay helper must not synthesize features from legacy/convenience fields such as `bbox`, `effective_bbox`, `nominatim_bbox`, `polygon`, LLM hints, or geocoder point coordinates when those explicit geometry fields are absent.

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


## Passive intelligence artifacts

Normal discovery runs can write passive intelligence artifacts under `logs/`: `passive_intelligence_summary.json`, `source_row_evidence_summary.jsonl`, `candidate_evidence_summary.jsonl`, and `candidate_priority_explanation.jsonl`. `media_validation_dashboard.json` includes a `passive_intelligence` section with evidence bands, protocol label counts, signature family counts, and top evidence reasons. Candidate CSV and GeoJSON properties include compact evidence score, band, protocol, HTTP status/content type/final URL, and why-candidate-mattered fields.

## Candidate CSV, full HLS validation, and search-service diagnostics

`camera_candidates_table.csv` is now the complete tabular candidate artifact for a normal run. It includes every unique candidate considered by the output stage, including trusted inventory rows, untrusted review rows, dead/offline rows, restricted rows, out-of-scope rows, unknown-location rows that cannot be represented in GeoJSON, and not-validated rows. The table includes `candidate_disposition`, `validation_status`, `trust_level`, `scope_status`, normalized `camera_type`, source-only `raw_camera_type`, stream/source/provider fields, coordinates when available, display image fields, and `source_metadata_json`. Its row count is reported in `media_validation_dashboard.json -> outputs -> candidate_table_rows` and in `logs/camera_candidates_table_status.json`; the dedupe key is `stream_url` without fragment plus `target_id`.

Trusted `camera.geojson` remains limited to trusted, validated, in-scope, coordinate-bearing records. `untrusted_camera_candidates.geojson` remains coordinate-only, so candidates without geometry may appear only in the CSV/JSONL artifacts.

HLS validation statuses are:

- `active_live_verified` — playlist reachable and a bounded real media segment or nested variant/media playlist check succeeded.
- `active_live_unknown` — playlist reachable, but full segment/live verification was not requested or was inconclusive.
- `active_playlist_dead_segments` — playlist reachable, but the selected segment/variant/media check failed.
- `dead` — playlist unreachable or not a valid HLS playlist.
- `restricted` — HTTP access was forbidden/restricted.
- `not_validated` — validation was skipped by profile or never reached.

Use `--profile full` to enable full HLS segment/variant checks. `--profile balanced` keeps lightweight playlist validation and may report `active_live_unknown`. The full path uses HTTP segment validation and does not require `ffprobe` for HLS segment success.

`run/logs/run_summary.json` is summary-only. Candidate-level details remain in `camera_candidates_table.csv`, `logs/validation_results.jsonl`, `logs/candidate_evidence_summary.jsonl`, per-target candidate JSONL files, and source-row JSONL files.

Harvest runs write `harvest/logs/search_service_summary.json`. It always contains `ddg`, `bing`, `searxng`, and `google_dork` entries with configured/attempted/status/query/result/selected/blocked/duplicate/error/skip fields, even when a service is skipped or returns zero rows. `harvest/logs/search_engine_diagnostics.jsonl` remains the detailed per-query diagnostic stream.


## Media validation dispatcher

Validation dispatch is based on media/protocol evidence, not semantic camera category. For example, traffic, beach, and weather cameras that point to `.m3u8` URLs all use the HLS validator; camera category never routes validation. The dispatcher normalizes each candidate to one primary media validator and records `media_type`, `normalized_media_type`, `validator_name`, `validation_status`, `validation_reason`, `validation_error` when present, `validation_elapsed_ms`, and whether full validation was enabled. These fields are available in candidate CSV rows and candidate metadata JSONL/GeoJSON properties.

Supported validators and status semantics:

- HLS (`hls`) fetches a playlist and verifies `#EXTM3U`. In `full` profile it follows bounded variant/media playlists and checks at least one resolved segment or nested media URL before returning `active_live_verified`. Lightweight/balanced validation returns `active_live_unknown` for reachable playlists whose segment/live status was not proven. Other HLS statuses include `active_playlist_dead_segments`, `invalid_hls`, `dead`, `restricted`, and `not_validated`.
- Image snapshot (`image_snapshot`) preserves the existing bounded image validation: it fetches with cache-busting, checks HTTP status and image content, rejects static assets/icons/placeholders when detected, and may return `active_image_snapshot_refreshing`, `active_image_snapshot_static_unverified`, `image_snapshot_not_image`, `static_image_asset`, `dead`, `restricted`, or `not_validated`.
- RTSP (`rtsp`) validates only discovered RTSP/RSTS URLs or explicit RTSP-classified candidates. It uses bounded `ffprobe` only when the effective profile/config enables ffprobe validation and `ffprobe` is available; disabled validation returns `rtsp_validation_disabled`, missing ffprobe returns `rtsp_validation_unavailable`, and attempted probes may return `active_rtsp_verified`, `auth_required_rtsp`, `offline_rtsp`, or `dead_rtsp`. It never guesses paths, ports, credentials, or undiscovered URLs.
- MJPEG (`mjpeg`) performs a bounded HTTP stream read and checks for `multipart/x-mixed-replace`, MJPEG content types, boundaries, and JPEG frame markers. It can return `active_mjpeg_verified`, `active_mjpeg_unknown`, `invalid_mjpeg`, `dead`, `restricted`, or `not_validated`.
- Video file (`video_file`, including MP4/MOV/WEBM/M4V) uses bounded `HEAD` and ranged `GET` checks for video content. Reachable direct video files return `video_file_reachable_unknown_live`; they are not automatically treated as live camera streams and do not produce `active_live_verified` without a live/segment/stream proof. Invalid, dead, restricted, and not-validated outcomes remain distinct.
- Unknown media (`unknown_media`) performs a bounded classification pass from URL, headers, and a small content sample. If evidence proves a supported media type, it delegates once to the matching validator. If not, it returns `unknown_media_unclassified` or `unsupported_media_type` and does not pretend validation succeeded.

`media_validation_dashboard.json` preserves top-level `total_candidates`, `validated`, `trusted`, `untrusted_review`, `dead`, `restricted`, and `not_validated` fields and now includes `by_validator_name` alongside `by_media_type` and `by_validation_status`. HLS playlist exports remain HLS-only; RTSP/MJPEG/video-file candidates are not inserted into HLS playlist artifacts.
