# Acceptance Criteria

The implementation is accepted when the documentation and code agree on the following behavior.

## Architecture and trust boundary

1. The target-aware workflow is organized around thin CLI commands, `runners/discovery_run.py`, `TargetResolver`, `CandidateDiscoveryEngine`, and `ReviewAndValidationPipeline`.
2. `RunState` remains the canonical run snapshot written to `logs/run_summary.json`.
3. LLMs are advisory evidence interpreters for target intent, geocoder referee ranking, candidate location-name inference, and candidate semantic review.
4. Deterministic code remains the authority for geometry verification, coordinate acceptance, stream/image validation, trusted-output authorization, and artifact writing.
5. No trusted `camera.geojson` is created from LLM-only geometry, LLM-only coordinates, LLM-only stream judgments, or LLM-only semantic review.

## Target resolution

1. Multi-location queries are split into independent targets.
2. Every target has stable `target_id`, `target_index`, `target_label`, scope fields, target-specific diagnostics, and a trust policy.
3. LLM-provided bbox/coordinate hints are stored only as unverified review hints.
4. Geocoder candidates are deterministically rejected for invalid/missing/implausible bboxes, wrong admin hints, wrong result types for broad scopes, or invalid coordinate ranges.
5. The LLM geocoder referee cannot revive deterministic-rejected candidates.

## Discovery

1. `blind`, `directory`, `both`, and `direct` modes work through the same normalized extraction path.
2. In `both` mode, directory rows and blind-search rows are discovered in parallel before extraction.
3. `SOURCES.md` allowed rows are used only in `directory` and `both`; blocked rows are global deny rules for all modes.
4. Direct HLS seed/source URLs become candidates without browser capture.
5. Static extraction handles HLS URLs, image snapshot URLs, HTML image/source tags, JSON responses, linked JSON/API/feed/map-layer endpoints, GeoJSON features, ArcGIS-style records, and JavaScript config blobs.
6. Browser capture is optional, budgeted, logged, and available through Playwright by default or CloakBrowser when configured.
7. JSON endpoint metadata is preserved into candidates, tables, GeoJSON, and maps when available.
8. Candidate budgets separately account for HLS, image snapshot, and total candidates.

## Harvest

1. Harvest mode is extraction-only and is coordinated by `runners/harvest_run.py` and `CameraUrlHarvestEngine`.
2. Harvest mode bypasses target resolution, geocoding, validation, trust classification, scope enforcement, LLM review, GeoJSON/maps, `cameras.md`, and review ZIP generation.
3. `run --harvest-input` consumes source-provided harvest data only as candidate seed/enrichment data and still applies the normal target-aware trust, scope, validation, and output workflow.
4. Harvest helper responsibilities stay under `harvest/`; shared extraction helpers stay under `extraction/`.

## Coordinates and scope

1. Candidate coordinates come from source records, URL/metadata evidence, or Nominatim geocoding.
2. Optional LLM location inference can produce geocoder query strings only; it cannot return coordinates.
3. Candidate geocoder results are checked against verified target bbox when available.
4. Candidates without coordinates remain in `camera_candidates_table.csv` and JSONL diagnostics but are not written to GeoJSON.
5. Candidates outside a verified bbox are rejected.
6. Candidates with coordinates but without verified target geometry remain review-only.

## Validation and output

1. `fast` profile disables validation and blocks trusted output.
2. `balanced` profile validates HLS playlist responses and image snapshots with real HTTP checks.
3. `full` profile additionally checks first HLS segment/variant reachability through the current `ffprobe_enabled` code path.
4. Image snapshot validation rejects obvious static assets and non-image responses and marks unchanged image endpoints as untrusted/static-unverified rather than trusted.
5. Trusted outputs are created only when trusted candidates exist; empty trusted files are not created.
6. `camera_candidates_table.csv`, `map.html`, `RUN_EXPLANATION.md`, `review_artifacts.zip`, validation diagnostics, and output summaries are written when output writing runs.
7. The map merges trusted and untrusted GeoJSON when both exist, includes a camera type/trust legend, supports thumbnail/snapshot display, and provides HLS/native playback attempts.

## Tests and notebook

1. `PYTHONPATH=src python -m compileall src` passes.
2. `PYTHONPATH=src python -m pytest -q` passes in an environment with required optional dependencies available or skips optional integrations explicitly.
3. The notebook remains valid JSON and keeps notebook-specific helper code inside the notebook.
4. Tests and docs do not introduce synthetic camera inventories, fake streams, fabricated coordinates, fake validation results, or hard-coded real-world target/source behavior.
