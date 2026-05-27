# Codex Prompt 02 — Split `discovery_engine.py` Along Existing Stage Boundaries

You are working in the `camera-discovery` repository after the refactor and follow-up fixes. Continue reducing `src/camera_discovery/services/discovery_engine.py`, which is still too large and remains the primary maintainability risk.

This is a structural refactor only. Do not add discovery features, media types, source-specific behavior, new target behavior, new validation behavior, or new CLI flags. The goal is to move existing cohesive stage logic out of the service file while preserving behavior and public imports.

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

---

## Baseline Verification Before Editing

Before changing files, inspect the current repository and record the relevant baseline in your final response:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

If the full test suite is too slow or the environment lacks optional browser dependencies, run the targeted tests listed in this prompt and clearly report what was skipped and why. Do not fake optional dependency success.

---

## Current Problem

`services/discovery_engine.py` has already been reduced from the original god file, but it remains too large. The service layer should orchestrate the workflow. It should not directly implement every detail of target iteration, source dispatch, harvest-input conversion, candidate processing, output writing, and summary generation.

Split along existing stage boundaries. Do not invent a speculative plugin framework or a new orchestration model.

---

## Required Inventory Before Editing

Inspect and record:

1. Current size/line count of `src/camera_discovery/services/discovery_engine.py`.
2. All top-level classes/functions in `discovery_engine.py`.
3. Methods on `CandidateDiscoveryEngine` and their rough responsibilities.
4. Existing modules under `discovery/`, `extraction/`, `enrichment/`, `harvest/`, `runners/`, and `services/`.
5. Current tests that import from `camera_discovery.services.discovery_engine`, including private helper imports.
6. Artifact-writing paths and summary-writing paths used by discovery and `run --harvest-input`.

---

## Target Shape

Keep `CandidateDiscoveryEngine` importable from:

```python
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
```

But move implementation details into focused modules such as:

```text
src/camera_discovery/discovery/
  engine.py                  # optional home for CandidateDiscoveryEngine, if practical
  target_flow.py             # target iteration / per-target workflow glue
  search_dispatch.py         # blind/directory/direct source row dispatch orchestration
  candidate_processing.py    # candidate normalization, merge prep, scope status helpers
  harvest_input.py           # harvest-input manifest/inventory loading and conversion
  artifact_writer.py         # discovery candidate artifacts and review handoff artifacts
  run_summary.py             # candidate discovery summary / explanation helpers
```

This exact layout is not mandatory. Create only modules that map to existing cohesive responsibilities.

`services/discovery_engine.py` may either:

- keep the public `CandidateDiscoveryEngine` class and delegate to stage helpers; or
- become a compatibility façade that imports `CandidateDiscoveryEngine` from `discovery/engine.py`.

Do whichever causes the least risk and churn.

---

## Refactor Requirements

### 1. Preserve behavior

The following must remain unchanged unless the current tests prove an existing bug directly related to this refactor:

- public import compatibility;
- CLI behavior;
- `run --harvest-input` behavior, including recent media-filter-aware handoff behavior;
- deterministic scope gating for harvest-input candidates;
- source-policy blocking;
- browser capture/preflight behavior;
- validation/trust gates;
- artifact names and schemas;
- progress events;
- run summaries and candidate summary semantics.

### 2. Move one cohesive group at a time

Recommended order:

1. Move harvest-input loading/conversion helpers first.
2. Move candidate-processing/scoping helpers.
3. Move discovery summary/run-explanation helpers.
4. Move artifact writing helpers.
5. Move source-dispatch coordination if it is still embedded in the service.

After each stage, run targeted tests if practical.

### 3. Keep compatibility shims where necessary

If tests or external callers import old private helpers from `services.discovery_engine`, keep short compatibility imports/re-exports with comments. Do not preserve large duplicate implementations.

### 4. Avoid circular imports

The stage modules should not create cycles between `services/`, `runners/`, and `discovery/`. Prefer pure helper modules that accept explicit data objects and return explicit results.

### 5. Improve discoverability without behavior changes

Add concise module docstrings explaining responsibility boundaries. Do not add broad architectural essays inside source files.

---

## Tests to Add or Update

Add behavior-focused tests only where useful:

1. Public import contract for `CandidateDiscoveryEngine`.
2. Harvest-input loading remains media-filter aware.
3. Candidate summary still separates native, harvest-input, and combined counts.
4. Scope gating of coordinate-bearing harvest-input candidates remains deterministic.
5. No private helper import from `harvest_engine.py` into `discovery_engine.py` is reintroduced.

Do not add tests that assert a file must be under a specific byte/line count.

---

## Suggested Targeted Verification

Run at least:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q \
  tests/test_package_contracts.py \
  tests/test_cli_contracts.py \
  tests/test_run_harvest_input.py \
  tests/test_harvest_handoff.py \
  tests/test_target_and_extraction_regressions.py \
  tests/test_output_filtering.py
PYTHONPATH=src python -m pytest -q
```

If Ruff exists from Prompt 01, run:

```bash
python -m ruff check src tests
```

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

