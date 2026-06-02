# Review and Validation Pipeline Agent

Maintain `ReviewAndValidationPipeline.run(targets, candidates)` as the centralized validation and artifact-writing service.

## Responsibilities

- deterministic HLS validation;
- deterministic image snapshot validation;
- trusted vs review-only output decisions;
- trusted `camera.geojson`, `camera_inventory.jsonl`, and `cameras.md`;
- untrusted review `untrusted_camera_candidates.geojson` and candidate JSONL;
- `camera_candidates_table.csv`;
- embedded `map.html`;
- `RUN_EXPLANATION.md` and `logs/run_explanation.json`;
- `review_artifacts.zip` packaging;
- validation/output/candidate-priority summaries.

## Validation behavior

`fast` profile skips validation and blocks trusted output.

`balanced` profile validates HLS playlists and image snapshots deterministically.

`full` profile adds deeper HLS segment/variant checks through the current full-profile path.

## Candidate priority

Validation and review ordering should prioritize coordinate-bearing, in-scope candidates. Coordinates alone do not make a camera trusted. Out-of-scope candidates must not be promoted above in-scope candidates.

## Output rules

Trusted output requires verified target geometry, in-scope coordinates, successful validation, and target `trust_policy=trusted_allowed`.

Review-only output may include coordinate-bearing untrusted candidates with explicit labels and reasons. Never create empty trusted files. Remove stale `camera.geojson` when no trusted candidates exist.

## Multi-location requirement

Merged outputs must preserve `target_id`, `target_label`, and `target_index` for every feature and table row.


## Passive validation intelligence

Review/validation must carry passive evidence fields into validation handoff, candidate tables, GeoJSON, dashboards, and run explanations. HTTP metadata may be captured from validation requests that already occur. Evidence scores can affect priority order inside existing validation buckets, but trusted output still requires validation, coordinates, in-scope status, and target trust policy.
