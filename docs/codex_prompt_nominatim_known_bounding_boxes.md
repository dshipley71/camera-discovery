# Codex Prompt — Prefer Known Nominatim Bounding Boxes Over Generic Target Boxes

You are working in the `camera-discovery` repository. Implement a source-aligned target-geometry fix so known bounding boxes returned by Nominatim are used as the target bounding box instead of any generic/default/synthetic box. For example, a query targeting California must use the Nominatim bounding box for the State of California, not a generic box centered somewhere inside California. Only use a generic box when the resolved location has no known bounding box available. For very small precise locations, such as a house, building, monument, address, campus feature, or landmark, default to the Nominatim bounding box when it exists, but deterministically pad the effective search/scope bbox when the returned box is too small to be useful. The recommended default minimum footprint is approximately one square mile, implemented as a one-mile-by-one-mile minimum side-length search box unless the repository already has a better generic minimum target extent convention.

This prompt is intentionally limited to target-resolution bounding-box selection, geometry provenance, diagnostics, and regression tests. Do not change camera discovery semantics, harvest semantics, source policy, browser capture behavior, media validation, trust rules, or notebook runtime behavior except where directly required to preserve the corrected bounding-box contract.

---

## Non-Negotiable Rules

1. **Follow the root `AGENTS.md`, nested implementation notes, and current `/docs` conventions.** The current source code is authoritative. If this prompt mentions a stale file, function, class, option, artifact name, or module path, adapt to the verified current source instead of creating duplicate implementations.
2. **No fake runtime evidence.** Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime camera inventories.
3. **No source-specific hacks.** Do not hard-code California, any other real-world state, any agency, any source domain, source-specific behavior, or one-off camera type into source code. California is only an example for tests and documentation. Generic bounding-box normalization and generic geometry provenance diagnostics are allowed.
4. **LLMs remain advisory only.** LLMs may extract intent and suggest query variants, but deterministic geocoder results and deterministic geometry checks remain authoritative for target bounding boxes, coordinate acceptance, scope classification, trusted output authorization, and final artifact writing.
5. **Known geocoder bounding boxes beat generic boxes.** If Nominatim returns a usable `boundingbox` for the accepted geocoder candidate, use that normalized Nominatim bbox as the authoritative source geometry. For normal administrative or regional targets, preserve the full normalized bbox exactly. For very small precise targets, use the Nominatim bbox as the seed and apply only the deterministic minimum-footprint padding described below when the returned box is too small to be useful.
6. **Generic boxes are fallback only.** A generic/default/synthetic bbox may be used only when no accepted geocoder candidate provides a known bounding box. Generic fallback geometry must be clearly marked by provenance and must not be treated as an authoritative Nominatim bbox. Deterministic padding around a known tiny Nominatim bbox is not the same as a no-geocoder generic fallback, but it must still be explicitly diagnosed.
7. **Small precise targets need minimum useful extent.** For targets such as a house, building, monument, address, campus feature, or landmark, a real Nominatim bbox may be only the footprint of the object. If that bbox is below the repository's minimum practical target extent, expand the effective bbox to at least the recommended minimum footprint, defaulting to a one-mile-by-one-mile box, or the closest existing repository convention. Do not apply this small-target padding to state, county, city, metro, country, or other administrative/regional bboxes.
8. **Do not weaken tests.** Add or update tests to protect this behavior. Do not relax assertions to hide regressions. Avoid tests that require live network calls.
9. **Preserve public contracts unless explicitly changed.** Existing command names, CLI options, public imports, environment variables, artifact names, schema semantics, source block policy, and trusted-output gates must continue to work.
10. **Keep notebooks separate from source.** Notebook-specific helper/display code belongs in notebooks, not `src/`. Do not create `src/camera_discovery/notebook/`.
11. **Make surgical changes.** Keep the refactored architecture intact: thin CLI commands, orchestration in `runners/`, public service facades in `services/`, discovery helpers in `discovery/`, enrichment helpers in `enrichment/`, extraction helpers in `extraction/`, and source policy helpers in `sources/`.

---

## Baseline Verification Before Editing

Before changing files, inspect the current repository and record the relevant baseline in your final response:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

If the full test suite is too slow or the environment lacks optional browser dependencies, run the targeted tests listed in this prompt and clearly report what was skipped and why. Do not fake optional dependency success.

Also inspect and summarize the current target-geometry path before editing:

1. how `TargetResolver` builds geocoder queries;
2. how Nominatim `boundingbox` values are parsed and normalized;
3. how the accepted geocoder candidate is selected;
4. whether any code creates a generic/default/synthetic bbox from a center point or scope;
5. how `TargetContext.bbox`, `bbox_verified`, `geometry_source`, `geometry_status`, and `trust_policy` are set;
6. how candidate scope checks consume the target bbox downstream.

Use the current file locations. Likely relevant areas include, but are not limited to:

```text
src/camera_discovery/services/target_resolver.py
src/camera_discovery/core/models.py
src/camera_discovery/discovery/candidate_processing.py
src/camera_discovery/runners/discovery_run.py
src/camera_discovery/services/review_validation_pipeline.py
tests/test_target_and_extraction_regressions.py
tests/test_multi_target_contracts.py
```

---

## Problem

Some target-resolution paths can behave as if the application has a generic target box even when a known Nominatim bounding box exists. This is wrong for large or well-defined administrative targets. It is also incomplete for tiny precise targets: a house, building, monument, address, campus feature, or landmark may have a real Nominatim bbox, but that bbox can be too small for useful camera discovery unless the effective search/scope bbox is padded to a minimum practical footprint.

Expected examples:

```text
Get me all traffic cameras from California
Get all public cameras from the State of California
Get weather cameras from New York State
Get public cameras from Fairfax County, Virginia
```

For these queries, if Nominatim returns an accepted result with a real `boundingbox`, the target bbox must be the known Nominatim bbox for that accepted target. It must not be replaced by a generic bbox around a centroid, a fixed-size state/city/metro rectangle, a fallback radius, or an LLM-provided bbox.

A generic bbox is appropriate only for a location where no known bounding box is available from the accepted geocoder result, and even then it must be clearly treated as fallback geometry according to existing trust policy. Small-target minimum-footprint padding is different: when a real Nominatim bbox exists but is too small, the resolver should default to that Nominatim bbox as the authoritative seed and then deterministically expand the effective bbox to a documented minimum size.

---

## Required Behavior

### 1. Preserve known Nominatim bounding boxes exactly after normalization

When Nominatim returns `boundingbox` for the accepted geocoder candidate:

- parse the Nominatim order correctly: `[south, north, west, east]`;
- normalize it to the repository's target bbox schema:

```python
{
    "min_lat": south,
    "max_lat": north,
    "min_lon": west,
    "max_lon": east,
}
```

- set `TargetContext.bbox` to that normalized Nominatim bbox, except for the small-location minimum-footprint padding case described below;
- set `TargetContext.bbox_verified = True` only after existing deterministic plausibility and result-type/admin/country checks pass;
- set `TargetContext.geometry_source = "geocoder"` or the current source-aligned equivalent;
- set `TargetContext.geometry_status = "verified"` or the current source-aligned equivalent;
- ensure downstream scope checks use this full bbox.

Do not round, simplify, clamp, center, buffer, shrink, expand, or otherwise alter a known Nominatim bbox except for safe float conversion, schema normalization, and the explicitly required small-location minimum-footprint padding described below.

### 2. Never override a known bbox with generic fallback geometry

If both a Nominatim candidate bbox and an LLM/generic/fallback bbox are available, the Nominatim bbox wins.

The following must not override an accepted Nominatim bbox:

- `llm_bbox`;
- `llm_center_lat` / `llm_center_lon`;
- any center-point radius calculation;
- any default city/county/state/metro rectangle;
- metro fallback policy;
- scope-specific fallback size tables;
- administrative-name heuristics;
- prior/default target geometry carried from another target.

### 3. Use generic boxes only when no known bbox exists

A generic/default/synthetic bbox may be used only if all of the following are true:

1. no accepted geocoder candidate has a usable Nominatim `boundingbox`;
2. the current source-aligned fallback policy permits proceeding with unverified/review-only geometry;
3. the generic bbox is clearly marked with fallback provenance, such as `geometry_source = "generic_fallback"`, `"llm_hint"`, or the existing equivalent;
4. the target is not allowed to produce trusted output solely because of a generic bbox.

If the current source does not already support generic bbox fallback, do not add a broad new fallback mechanism just to satisfy this prompt. The main requirement is to prevent generic geometry from replacing known Nominatim geometry. If preserving existing behavior requires a fallback, keep it review-only/untrusted unless a verified geocoder bbox later becomes available.

### 4. Pad very small precise-location bboxes to a minimum practical footprint

For very small targets, such as a house, building, monument, address, campus feature, park feature, attraction, facility, or landmark, a real Nominatim bbox may represent only the object footprint. That can be too small for discovery because nearby public cameras may reasonably be just outside the object footprint.

Required behavior for these small precise-location targets:

1. Default to the accepted Nominatim bbox when it exists. Do not ignore it and jump directly to a generic box.
2. Determine whether the normalized Nominatim bbox is below a minimum practical footprint.
3. If it is below the minimum, expand the effective target bbox around the center of the Nominatim bbox to at least the minimum practical footprint.
4. Use a default minimum of approximately **one square mile**, implemented as a **one-mile-by-one-mile minimum side-length box**, unless the repository already defines a better source-aligned minimum target extent. If a different minimum is chosen, document the reason in code comments and diagnostics.
5. Apply padding generically using latitude/longitude math or existing geospatial helpers. Account for longitude degrees narrowing by latitude where practical, and clamp final lat/lon values to valid ranges.
6. Preserve the original Nominatim bbox in diagnostics even if `TargetContext.bbox` must contain the effective padded bbox for downstream scope checks.
7. Mark the effective geometry provenance clearly, for example `geometry_source = "geocoder_padded"`, `bbox_padding_applied = true`, or the closest current source-aligned equivalent. Do not label this as a no-geocoder generic fallback.
8. Keep `bbox_verified = True` only if the original Nominatim candidate passed the existing deterministic acceptance checks and the padded effective bbox was deterministically derived from that accepted bbox.
9. Do not apply minimum-footprint padding to state, county, city, metro, country, or other administrative/regional bboxes. Those should use the full Nominatim bbox exactly after normalization.
10. Do not use LLM-generated coordinates as the authority for this padding when a real Nominatim bbox exists. LLM center/bbox data remains lower priority and advisory.

Suggested diagnostics fields, using existing artifact structures where possible:

```json
{
  "nominatim_bbox": {"min_lat": 38.0, "max_lat": 38.0001, "min_lon": -77.0, "max_lon": -76.9999},
  "effective_bbox": {"min_lat": 37.9928, "max_lat": 38.0072, "min_lon": -77.0092, "max_lon": -76.9908},
  "bbox_padding_applied": true,
  "bbox_padding_reason": "known_geocoder_bbox_below_minimum_precise_target_extent",
  "bbox_min_side_miles": 1.0,
  "geometry_source": "geocoder_padded"
}
```

If current schemas do not support these exact names, use the closest current names and avoid unnecessary public schema churn.

### 5. Keep deterministic authority over geometry trust

Do not trust an LLM bbox. Do not trust a generic bbox. Do not mark a target as `TRUSTED_ALLOWED` unless the existing deterministic trusted-output prerequisites are met, including verified target geometry from a real geocoder bbox/polygon.

A target with only fallback/generic/LLM geometry may still produce review-only artifacts if current configuration allows that, but it must not write trusted `cameras.geojson` features on that basis alone.

### 6. Preserve multi-target behavior

Do not collapse multiple locations into one combined bbox. If a query asks for multiple places, each target must preserve its own Nominatim bbox or its own fallback geometry provenance.

Example:

```text
Get traffic cameras from California and New York State
```

Expected:

- target 1 gets the accepted Nominatim bbox for California, if available;
- target 2 gets the accepted Nominatim bbox for New York State, if available;
- candidates and output features preserve `target_id`, `target_label`, and `target_index` as before.

### 7. Improve diagnostics without changing artifact contracts unnecessarily

Ensure the existing target-resolution diagnostics make it clear which bbox was used and why. Use existing diagnostic files where possible, such as:

```text
logs/target_resolution.json
logs/target_resolution_all.json
logs/targets/<target_id>/target_resolution.json
logs/targets/<target_id>/geocoder_candidate_scores.json
```

At minimum, diagnostics should make the following clear:

- chosen candidate display name;
- chosen candidate result type/class if available;
- normalized Nominatim bbox returned by the accepted geocoder candidate;
- effective bbox used by `TargetContext`;
- whether small-target padding was applied, and the minimum footprint used;
- whether the bbox came from Nominatim/geocoder, geocoder-derived padding, or fallback geometry;
- whether the bbox is verified;
- warnings or stop reason when only fallback geometry exists.

Avoid adding new artifact names unless existing diagnostics cannot represent this cleanly.

---

## Implementation Guidance

1. Inspect `TargetResolver._geocode`, `_bbox_from_nominatim`, `_score_candidate`, `_resolve_intent`, and any fallback geometry helpers in the current source.
2. Ensure `_bbox_from_nominatim` parses Nominatim's `[south, north, west, east]` correctly and rejects malformed values.
3. Ensure candidate scoring and selection do not accidentally prefer a generic fallback over a valid Nominatim bbox.
4. If there is code that creates a generic bbox from a center point, make it run only after the resolver has confirmed that no accepted geocoder candidate has a usable bbox. Do not confuse this no-geocoder fallback with deterministic small-target padding around a known Nominatim bbox.
5. Add or reuse a small-target minimum-footprint helper if needed. It should accept a normalized Nominatim bbox, a center latitude, a minimum side length in miles, and return a valid expanded bbox only when the input bbox is below the minimum size.
6. Use Nominatim result class/type, scope type, and existing target classification to decide whether the bbox represents a precise/small location. Generic examples include building, house, address, amenity, attraction, monument, landmark, facility, or similar point/feature-level results. Do not use hard-coded real-world place names.
7. Ensure large administrative/regional bboxes are never padded to the small-location minimum and never replaced by small generic boxes.
8. If `intent.llm_bbox` exists, keep it lower priority than Nominatim geometry and keep it unverified.
9. If `intent.llm_center_lat` and `intent.llm_center_lon` exist, do not create a trusted bbox from them. If a fallback bbox is generated from those values under existing policy, mark it unverified/review-only.
10. Keep existing plausibility checks, but tune only if they wrongly reject real administrative Nominatim bboxes. For example, a state-scale bbox should pass state-scope plausibility; a country-scale bbox should pass country-scope plausibility.
11. Do not add hard-coded known bboxes for California or any other location. Tests may use sample bbox values returned by mocked Nominatim responses.
12. Avoid network-dependent tests. Use monkeypatching, mock transports, or direct `GeocoderCandidate` objects.
13. Keep any changed public schema fields backward-compatible.

---

## Required Tests

Add or update focused regression tests. Prefer deterministic unit tests that do not call live Nominatim.

### 1. Nominatim bbox normalization

Add a test proving Nominatim's raw bbox order is normalized correctly:

```python
raw = ["32.0", "42.0", "-125.0", "-114.0"]
assert _bbox_from_nominatim(raw) == {
    "min_lat": 32.0,
    "max_lat": 42.0,
    "min_lon": -125.0,
    "max_lon": -114.0,
}
```

Use current import paths and helper visibility. If the helper is private and tests already use private helpers in this repository, it is acceptable to test it directly. Otherwise test through `TargetResolver`.

### 2. Known Nominatim bbox wins over LLM/generic bbox

Add a resolver test with a mocked accepted geocoder candidate for California and an intentionally smaller `llm_bbox` or generic fallback. The resolved target must use the Nominatim bbox exactly.

Expected assertions:

- `ctx.bbox == nominatim_bbox`;
- `ctx.bbox != llm_bbox`;
- `ctx.bbox_verified is True`;
- `ctx.geometry_source == "geocoder"` or current equivalent;
- `ctx.geometry_status == "verified"` or current equivalent;
- no warning says a generic/LLM bbox was used.

Do not use live network calls in this test.

### 3. State-scope bbox is not replaced by a small generic box

Add a regression test for a state-style query such as:

```text
Get me all traffic cameras from California
```

Mock Nominatim to return a state-scale bbox and confirm the final target bbox still covers the state-scale extent. The exact numbers can be the mocked Nominatim values. Do not assert against live Nominatim output.

### 4. Generic bbox only when no known bbox exists

Add a test for the no-known-bbox path. Depending on current source behavior, either:

- verify the resolver stops with `geometry_status = "missing"` / `trust_policy = STOP`; or
- verify the resolver uses fallback geometry only as unverified/review-only, with explicit fallback provenance.

In either case, assert that fallback/generic geometry does not set `bbox_verified = True` and does not authorize trusted output.

### 5. Small precise-location bbox is padded when too small

Add a resolver test with a mocked accepted Nominatim candidate representing a tiny building, monument, address, landmark, or similar precise feature. The raw Nominatim bbox should be intentionally much smaller than the minimum practical footprint.

Expected assertions:

- the resolver defaults to the Nominatim bbox as the authoritative source geometry;
- the effective `TargetContext.bbox` is expanded beyond the tiny raw bbox when current schemas use one effective bbox downstream;
- the effective bbox is at least the configured/default minimum practical footprint, approximately one mile by one mile unless the repository uses another documented minimum;
- the effective bbox remains centered on or very near the original Nominatim bbox center;
- diagnostics preserve the original Nominatim bbox separately from the effective padded bbox;
- provenance indicates geocoder-derived padding, not no-geocoder generic fallback;
- `bbox_verified` is true only because the original geocoder candidate was accepted and the padding was deterministic.

### 6. Small-target padding is not applied to administrative bboxes

Add or update a test proving that a state/county/city/metro/country bbox returned by mocked Nominatim is not padded, shrunk, or replaced. A mocked California state bbox should remain exactly the normalized mocked Nominatim bbox.

### 7. Multi-target bbox independence

If existing multi-target tests can be extended without broad churn, add a test that mocked Nominatim candidates for two targets preserve separate bboxes and target identities. Do not collapse them into one combined bbox.

---

## Targeted Verification Commands

After implementing the change, run at least:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q \
  tests/test_target_and_extraction_regressions.py \
  tests/test_multi_target_contracts.py \
  tests/test_candidate_priority.py \
  tests/test_output_filtering.py
```

If available and practical, also run:

```bash
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/llm
PYTHONPATH=src python -m pytest -q
```

Clearly report any skipped commands and the reason. Do not claim success for commands that were not run.

---

## Acceptance Criteria

The task is complete when all of the following are true:

1. A valid Nominatim `boundingbox` from the accepted geocoder candidate is used as the target bbox exactly after normalization.
2. Known Nominatim bboxes are never replaced by LLM, generic, radius, center-point, metro, city, county, state, or other synthetic fallback boxes.
3. Generic boxes are used only when no known bbox exists and remain clearly identified as fallback/unverified according to existing trust policy.
4. Very small precise-location Nominatim bboxes are padded to a documented minimum practical footprint, defaulting to roughly one square mile / one mile by one mile, while preserving the original Nominatim bbox in diagnostics.
5. Small-target padding is not applied to administrative or regional bboxes.
6. A California-targeting query with mocked Nominatim state bbox resolves to the mocked State of California bbox, not a generic small box.
7. A house/building/monument-style query with a tiny mocked Nominatim bbox resolves to a padded effective bbox derived from the Nominatim bbox, not an unrelated generic fallback.
8. A target with only fallback/generic/LLM geometry cannot produce trusted output solely from that fallback geometry.
9. Multi-target resolution preserves separate target bboxes and target IDs.
10. Existing CLI contracts, output artifact names, source policy, validation behavior, and notebook/source separation remain intact.
11. Regression tests cover the corrected behavior without live network dependency.
12. Baseline and final verification results are reported honestly.

---

## Final Response Requirements for Codex

In your final response, include:

1. a concise summary of what changed;
2. the files modified;
3. the exact tests/commands run and their results;
4. any commands skipped and why;
5. a short note confirming that known Nominatim bboxes now take precedence over generic/fallback boxes;
6. a short note confirming how very small Nominatim bboxes are padded to the minimum practical footprint and where that is diagnosed;
7. a short note confirming that no hard-coded real-world bbox table or location-specific hack was added.

---

## Addendum — Nominatim Primary Geometry Hierarchy

Update the Nominatim target-geometry contract so the resolver uses a three-level geometry hierarchy instead of treating the rectangular bbox as the only verified shape:

1. **Primary geometry:** request and preserve Nominatim `geojson` polygon or multipolygon output (`polygon_geojson=1`) for the accepted geocoder candidate. When a valid polygon/multipolygon exists, it is the primary target boundary for map overlays and candidate scope checks. For a state such as California, the map should show the border-following polygon/multipolygon, not a full rectangular envelope.
2. **Fallback geometry:** preserve the normalized Nominatim `boundingbox` as the rectangular fallback/search envelope. Use it when no usable Nominatim polygon/multipolygon is returned and retain it for fast bbox filtering, map fitting, diagnostics, and small-target padding calculations.
3. **Last fallback geometry:** create a generic padded search bbox only when no usable Nominatim polygon/multipolygon and no usable Nominatim bbox exist. This fallback must be explicitly marked as unverified/review-only and must not authorize trusted output.

Required source behavior:

- Keep using `polygon_geojson=1` in Nominatim requests.
- Validate that returned `geojson` is a usable `Polygon` or `MultiPolygon` before storing it as primary geometry.
- Store primary/fallback/last-fallback provenance in target-resolution diagnostics. Source-aligned field names are preferred, but diagnostics must make these concepts visible, for example:

```json
{
  "target_geometry_geojson": {"type": "MultiPolygon", "coordinates": []},
  "primary_geometry_source": "nominatim_polygon",
  "fallback_geometry_bbox": {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -125.0, "max_lon": -114.0},
  "fallback_geometry_source": "nominatim_bbox",
  "last_fallback_geometry_bbox": null,
  "last_fallback_geometry_source": null,
  "effective_bbox": {"min_lat": 32.0, "max_lat": 42.0, "min_lon": -125.0, "max_lon": -114.0},
  "geometry_source": "nominatim_polygon"
}
```

- Candidate scope checks should use the verified primary polygon/multipolygon when available. Use the rectangular fallback bbox only when no primary polygon exists. Use last-fallback generic geometry only as review-only fallback according to existing trust policy.
- Map rendering should add `L.geoJSON(...)` border-only overlays for primary polygons/multipolygons. Draw `L.rectangle(...)` only when the rectangle is actually the fallback geometry, or as a dashed effective search extent for a padded small target. Do not fill target geometry overlays.
- For small precise locations, preserve the Nominatim polygon if present, preserve the Nominatim bbox as fallback, and separately compute the padded effective search bbox when needed. Do not replace a real polygon with only a generic square.
- Add regression tests that do not perform live network calls:
  - accepted Nominatim polygon/multipolygon becomes primary geometry;
  - Nominatim bbox remains fallback geometry and effective search bbox;
  - map HTML contains primary `L.geoJSON` overlay code;
  - rectangle rendering is fallback-only when primary geometry is unavailable;
  - point-only geocoder results, when supported, use clearly unverified last-fallback generic geometry;
  - polygon-aware candidate scope checks reject coordinates that are inside the rectangular envelope but outside the target polygon.

Also update notebooks so target-resolution inspection cells print the primary/fallback/last-fallback geometry fields and regenerate maps with the current local source code rather than relying on stale maps from an older checkout.

## Addendum — Default LLM Models

Update source-code defaults, documentation, and notebooks to use these model defaults unless the user overrides the corresponding environment variable:

- global provider: `ollama-cloud`
- main/default LLM model: `gemma3:27b-cloud`
- target-intent model: `gemma3:12b-cloud`
- target-intent fallback model: `gemma3:12b-cloud`
- geocoder-referee model: `gemma3:27b-cloud`
- location-inference model: `gemma3:27b-cloud`

Do not paste notebook-style `os.environ.setdefault(...)` blocks into source code. Update the actual source configuration variables/default helpers so CLI, notebooks, and tests inherit the correct defaults.
