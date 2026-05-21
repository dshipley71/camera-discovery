# 05 — ReviewAndValidationPipeline Agent

Maintain `ReviewAndValidationPipeline.run(targets, candidates)` as the centralized validation and artifact-writing service.

## Responsibilities

- deterministic HLS validation;
- deterministic image snapshot validation;
- trusted vs review-only output decisions;
- trusted `camera.geojson`, `camera_inventory.jsonl`, and `cameras.md`;
- review `untrusted_camera_candidates.geojson` and candidate JSONL;
- `camera_candidates_table.csv` for all non-rejected candidates;
- embedded `map.html`;
- `RUN_EXPLANATION.md` and `logs/run_explanation.json`;
- `review_artifacts.zip` packaging;
- validation/output summaries.

## Validation behavior

`fast` profile skips validation and blocks trusted output.

`balanced` profile:

- HLS: GET playlist, require `#EXTM3U`.
- Image snapshot: cache-busted HTTP image checks, refresh comparison, static-asset filtering.

`full` profile:

- Balanced checks plus first HLS segment/variant reachability check through the current `ffprobe_enabled` code path.

## Output rules

Trusted output requires verified target geometry, in-scope coordinates, successful validation, and target `trust_policy=trusted_allowed`.

Review-only output may include coordinate-bearing untrusted candidates with explicit labels and reasons.

Never create empty trusted files. Remove stale `camera.geojson` when no trusted candidates exist.

## Multi-location requirement

Merged outputs must preserve `target_id`, `target_label`, and `target_index` for every feature and table row.
