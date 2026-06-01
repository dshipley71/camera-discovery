# Codex Prompt 04 — Prioritize Located In-Scope Candidates for Validation and Review

You are working in the `camera-discovery` repository after the harvest handoff and deterministic scope-gating fixes. Implement deterministic candidate prioritization so coordinate-bearing, deterministically in-scope candidates are processed before unlocated candidates for validation, review tables, review maps, and candidate budgets.

Coordinates **do not** by themselves make a candidate trusted. Trust still requires passing existing media validation and existing trust/output gates. Out-of-scope coordinate-bearing candidates must not be promoted above in-scope candidates.

---

## Non-Negotiable Rules

1. **Follow the root `AGENTS.md`, nested implementation notes, and current `/docs` conventions.** The source code is authoritative. If this prompt mentions a stale file, function, class, option, artifact name, or module path, adapt to the verified current source instead of creating duplicate implementations.
2. **No fake runtime evidence.** Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime camera inventories.
3. **No source-specific hacks.** Do not hard-code real-world locations, agencies, source domains, source-specific behavior, or one-off camera types. Generic media normalization, generic URL canonicalization, generic candidate-priority scoring, and generic diagnostics are allowed when requested.
4. **LLMs remain advisory only.** Deterministic code/tools remain authoritative for bbox/geometry verification, coordinate acceptance, scope classification, media validation, trusted output authorization, and final artifact writing.
5. **Keep notebooks separate from source.** Notebook-specific helper code belongs in notebooks, not `src/`. Source modules must not import from notebooks.
6. **Make surgical changes.** Keep the refactored architecture intact: thin CLI commands, workflow orchestration in `runners/` and services, shared extraction helpers in `extraction/`, harvest-specific helpers in `harvest/`, and discovery helpers in `discovery/` / `enrichment/`. Do not collapse code back into god files.
7. **Do not weaken tests.** Add or update tests to protect behavior. Do not relax assertions to hide regressions. Avoid brittle line-count-only tests.
8. **Preserve public contracts unless explicitly changed.** Existing command names, existing options, public imports, environment variables, output artifact names, schema semantics, and global source block policy must continue to work.
9. **Do not assume or add unrequested behavior.** Do not infer, synthesize, or add helper workflows, notebook bootstrap behavior, artifact branches, compatibility behavior, fallback logic, source behavior, model behavior, or output artifacts that this prompt did not explicitly require or that is not confirmed by repository evidence. When in doubt, preserve existing behavior and document the uncertainty instead of adding unrequested behavior.

---

## Baseline Verification Before Editing

Before changing files, inspect the current repository and record the relevant baseline in your final response:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

If the full test suite is too slow or the environment lacks optional browser dependencies, run the targeted tests listed in this prompt and clearly report what was skipped and why. Do not fake optional dependency success.

---

## Problem

For HLS-focused runs such as California traffic camera harvesting, the highest-value candidates are direct HLS/image candidates that already have coordinates and are deterministically inside the verified target bbox/polygon. These should be validated early and appear first in review outputs. Unlocated media candidates and camera-like records without coordinates should not consume validation/review budget before located in-scope cameras.

Recent runs showed thousands of HLS candidates, including many Caltrans records with coordinates. The pipeline should bubble those located in-scope records to the top without weakening trust rules.

---

## Required Inventory Before Editing

Inspect and report current behavior for:

1. candidate ordering after discovery and after `run --harvest-input`;
2. validation candidate selection and validation budget application;
3. review table ordering;
4. review GeoJSON/map feature ordering;
5. trusted GeoJSON selection;
6. scope statuses currently used (`in_scope`, `out_of_scope`, `review`, `unknown`, etc.);
7. fields available for coordinates, coordinate source, media type, target ID, target label, and validation status.

---

## Required Behavior

Implement a deterministic priority function or sort key that is generic and source-agnostic. Suggested order:

1. `in_scope` candidates with accepted coordinates and direct media URL (`hls` / `image_snapshot`, and any other first-class normal-run media if supported).
2. `review` candidates with accepted coordinates and direct media URL.
3. `unknown` candidates with accepted coordinates and direct media URL.
4. direct media candidates without coordinates.
5. structured camera-like records without coordinates or without direct media evidence.
6. out-of-scope coordinate-bearing candidates.
7. weak/asset/page candidates.

Tune the exact categories to the verified current source model, but preserve these principles:

- located + deterministically in-scope candidates come first;
- out-of-scope never outranks in-scope;
- coordinates alone do not create trust;
- validation/trust gates remain unchanged;
- ordering is deterministic and stable.

---

## Required Implementation Scope

### 1. Centralize priority logic

Add the priority logic in one focused place, for example:

```text
src/camera_discovery/discovery/candidate_priority.py
```

or an existing candidate-processing module if one already exists.

The priority helper should be pure and easy to test. It should not perform network calls, LLM calls, geocoding, or validation.

### 2. Apply priority before validation budgets

When validation is enabled and there is any validation/candidate cap, located in-scope candidates should consume validation budget first. This is especially important for `balanced` and `full` profiles.

Do not validate out-of-scope candidates before in-scope candidates.

### 3. Apply priority to review outputs

Sort review tables and review feature outputs so located in-scope candidates appear first. Review map features may only include coordinate-bearing candidates, but their ordering/properties should still reflect priority.

Do not remove out-of-scope audit records unless the current output contract already excludes them. If output filtering exists, preserve it. If out-of-scope records are emitted, clearly mark them and place them after in-scope/review/unknown located candidates.

### 4. Preserve trusted output rules

Trusted output still requires:

- deterministic target and scope acceptance;
- accepted coordinates;
- media validation success;
- existing trusted output authorization.

Do not make coordinate-bearing candidates trusted without validation.

### 5. Add summary diagnostics

Add useful summary counts to existing summaries where appropriate:

- located candidates;
- located in-scope candidates;
- located out-of-scope candidates;
- unlocated candidates;
- validation candidates selected by priority bucket;
- trusted candidates by priority bucket if useful.

Keep schemas backward-compatible if practical; add fields rather than renaming existing fields.

---

## Tests to Add or Update

Add behavior-focused tests:

1. Priority ordering ranks located in-scope above unlocated candidates.
2. Out-of-scope coordinate-bearing candidates do not outrank in-scope candidates.
3. Validation budget selects located in-scope candidates first.
4. Review table ordering places located in-scope candidates before unlocated candidates.
5. Coordinates alone do not make a candidate trusted when validation is disabled or fails.
6. Harvest-input HLS candidates with coordinates get the same prioritization as native discovery candidates.

Use small synthetic Python objects in unit tests only to test pure ordering behavior; do not fabricate runtime camera inventories or claim real-world discovery success.

---

## Suggested Targeted Verification

Run at least:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q \
  tests/test_output_filtering.py \
  tests/test_coordinate_enrichment_and_tables.py \
  tests/test_run_harvest_input.py \
  tests/test_target_and_extraction_regressions.py \
  tests/test_quality_fixes_regressions.py
PYTHONPATH=src python -m pytest -q
```

If CI/lint exists, run it too.

---

## Final Response Required from Codex

When finished, report:

1. Files changed.
2. What was verified before editing.
3. Summary of implementation decisions.
4. Public contracts preserved.
5. Tests/checks run and exact results.
6. Any limitations or follow-up work.
7. Confirmation that no fake/synthetic camera inventory, coordinates, validation results, GeoJSON, browser success, or source-specific hacks were introduced.

