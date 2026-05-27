# Codex Prompt — Repository-Synced Harvest Handoff-Only and Seed Modes, Bounded Handoff Runs, Plain Progress, Interrupt Handling, and Notebook Updates

You are working in the **current `camera-discovery` repository**. This prompt is synchronized to the repository structure and behavior observed in the most recent `camera-discovery-dev(3).zip`.

Implement the focused fixes for the latest harvest handoff notebook failure: `camera-discovery run --harvest-input ...` currently loads harvest input **after** running normal native discovery, so a small HLS handoff can still trigger broad source-row scanning and coordinate enrichment over thousands of native candidates. The fix is to make harvest-input behavior explicit and bounded.

This prompt supersedes the earlier unsynced prompt named similar to:

```text
codex_prompt_harvest_handoff_run_mode_enrichment_progress_notebook_fixes.md
```

Do not implement stale recommendations from that earlier prompt if they conflict with the current repository.

---

## Current repository facts to preserve

The current source tree is organized as:

```text
src/camera_discovery/
  cli.py
  cli_commands/
  core/
  runners/
  services/
  discovery/
  extraction/
  harvest/
  enrichment/
  sources/
  llm/
  utils/
```

Important current files and modules:

```text
src/camera_discovery/cli.py
src/camera_discovery/core/config.py
src/camera_discovery/core/models.py
src/camera_discovery/runners/discovery_run.py
src/camera_discovery/runners/harvest_run.py
src/camera_discovery/services/discovery_engine.py
src/camera_discovery/services/harvest_engine.py
src/camera_discovery/services/harvest_handoff.py
src/camera_discovery/discovery/candidate_processing.py
src/camera_discovery/cli_commands/progress.py
src/camera_discovery/harvest/outputs.py
notebooks/camera_discovery_harvest_urls_test.ipynb
notebooks/camera_discovery_harvest_hls_handoff_full_validation_test.ipynb
notebooks/camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb
notebooks/camera_discovery_pipeline_only_profiles_test.ipynb
tests/test_run_harvest_input.py
tests/test_harvest_handoff.py
tests/test_cli_progress.py
tests/test_progress_events_contract.py
tests/test_harvest_urls_cli.py
docs/runtime_configuration.md
docs/output_artifacts.md
docs/project_structure.md
docs/acceptance.md
README.md
REPOSITORY_LAYOUT.md
AGENTS.md
```

The current repository already includes these earlier fixes. Preserve them; do not re-implement them from scratch:

1. `run` already exposes `--harvest-input`.
2. `run` already exposes `--browser-backend`.
3. `harvest-urls` already exposes `--browser-backend`.
4. `harvest_handoff.json` already uses `schema_version: harvest-handoff/v2`.
5. Media-filtered harvest handoffs already default to the filtered final URL artifact through `services/harvest_handoff.py`.
6. `HarvestHandoffLoad` already preserves metadata such as:
   - `source_path`
   - `source_file`
   - `schema_version`
   - `media_filter`
   - `handoff_default_scope`
   - `loaded_artifact`
   - `files`
7. `load_harvest_handoff_bundle()` already picks `camera_urls_jsonl` for media-filtered handoffs when appropriate.
8. `harvest_records_to_candidates()` already converts handoff records into untrusted `CameraCandidate` objects with `discovery_method="harvest_handoff"` and `source_metadata["harvest_input"] = True`.
9. `execute_discovery_run()` already applies deterministic scope gating to harvest-input candidates through `_scope_harvest_input_candidates()`.
10. Browser preflight support already exists in the current source for browser capture paths.
11. Rich/event progress already receives `coordinate_candidate_processed` and `coordinate_enrichment_complete` events.
12. `candidate_coordinate_enrichment.json` is already written by `discovery/candidate_processing.py`.
13. Current tests already cover parts of media-filter-aware handoff loading and deterministic scope gating.

The remaining bug is **run orchestration mode**, not media-filter parsing.

---

## Non-negotiable repository rules

Follow the root `AGENTS.md`, nested implementation notes, and current `/docs` conventions.

1. **Source is authoritative.** If this prompt mentions a stale path, function, option, test name, artifact, or schema key, inspect the checked-out repository and adapt to the verified current code.
2. **No fake runtime evidence.** Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime inventories.
3. **No source-specific hacks.** Do not hard-code California, Caltrans, `wzmedia.dot.ca.gov`, any real location, any agency, any source domain, or source-specific behavior. Generic handoff modes, media normalization, URL canonicalization, progress, diagnostics, and budget handling are allowed.
4. **LLMs remain advisory only.** Deterministic code remains authoritative for geometry verification, coordinate acceptance, scope classification, media validation, trusted output authorization, and artifact writing.
5. **Keep notebooks separate from source.** Notebook helper/display code belongs in notebooks. Do not create `src/camera_discovery/notebook/`.
6. **Keep CLI thin.** CLI option declarations and config loading remain in `cli.py`; orchestration belongs in `runners/`; service logic stays in focused service/stage modules.
7. **Do not weaken tests.** Add/update tests to protect behavior. Do not relax existing assertions to hide regressions.
8. **Preserve public contracts unless explicitly changed here.** This prompt explicitly changes the default behavior of `run --harvest-input` by introducing an explicit handoff mode default. Existing broader behavior must remain available through an explicit mode.

---

## Problem to fix

The notebook failure showed this workflow:

```bash
camera-discovery harvest-urls "California traffic cameras" \
  --media .m3u8 \
  --output-dir runs/harvest-california-hls \
  --write-intermediate-records
```

The harvest output was small after filtering, approximately:

```text
filtered_media_records: 12
camera_urls.jsonl records: 12
filtered_records_with_coordinates: 11
```

Then this run cell was executed:

```bash
camera-discovery run "California traffic cameras" \
  --output-dir runs/run-from-harvest-hls \
  --harvest-input runs/harvest-california-hls/harvest_handoff.json \
  --browser-backend cloakbrowser \
  --progress-style plain
```

Instead of processing only the handoff records, the current orchestration first ran normal native discovery and printed behavior similar to:

```text
scanning hundreds of source rows
accepted about 2207 candidates
enriching coordinates for about 2187 unique candidates
```

This happened because `execute_discovery_run()` currently runs `CandidateDiscoveryEngine.discover()` for each target before loading harvest input. The harvest input is merged after native discovery. That behavior is useful as a seed workflow, but it is wrong for a bounded handoff test unless explicitly requested.

---

## Required fix 1 — Add explicit harvest input modes

### Goal

Make `camera-discovery run --harvest-input ...` behavior explicit.

Add a CLI/config option:

```bash
--harvest-input-mode handoff-only|seed
```

Use this exact name unless the repository already has a naming convention that strongly suggests a better one. If you choose a different name, update docs/tests consistently and explain why.

### Recommended data model

Add a small enum or literal-backed config field in `core/models.py`, for example:

```python
class HarvestInputMode(str, Enum):
    HANDOFF_ONLY = "handoff-only"
    SEED = "seed"
```

and add to `RunConfig`:

```python
harvest_input_mode: HarvestInputMode = HarvestInputMode.HANDOFF_ONLY
```

Then update `load_run_config()` in `core/config.py` to accept and validate the option. Add an environment variable only if that matches current config style. A reasonable name is:

```bash
CAMERA_DISCOVERY_HARVEST_INPUT_MODE=handoff-only
```

If no env var is added, document that the mode is CLI-only.

### Mode semantics

There are exactly two supported modes: `handoff-only` and `seed`.

#### `handoff-only`

Use only the selected records from the supplied harvest handoff/inventory as candidate inputs.

In this mode:

- still perform target resolution;
- still apply deterministic scope gating to handoff candidates;
- still run validation/trust/output stages according to the selected profile;
- do **not** call `CandidateDiscoveryEngine.discover()`;
- do **not** run blind search;
- do **not** load or scan directory source rows for discovery;
- do **not** promote asset hosts;
- do **not** crawl pages/endpoints for additional discovery;
- do **not** enrich coordinates for native discovery candidates because there must be no native discovery candidates;
- if handoff candidate coordinate enrichment is implemented or already runs, it must be bounded to handoff-derived candidates only;
- if current policy leaves missing-coordinate handoff candidates as `unknown`, that is acceptable, but the run summary must make clear whether handoff candidate enrichment was run or skipped.

#### `seed`

Use harvest input as starting candidates and also run the normal native discovery pipeline. This preserves the broader current behavior, but makes it explicit.

In this mode:

- preserve current behavior as closely as possible;
- native discovery may scan source rows, crawl, promote asset hosts, enrich coordinates, and validate according to normal budgets;
- harvest candidates are merged with native candidates;
- diagnostics must state that broader discovery was intentionally enabled.

### Default behavior

When `--harvest-input` is supplied, the default must be:

```text
handoff-only
```

This is an intentional behavior change to prevent the notebook failure and make handoff tests bounded by default.

When `--harvest-input` is **not** supplied, `--harvest-input-mode` must have no effect on normal runs.

### Startup diagnostics

At run start, print a clear summary:

```text
Harvest input: <path> (exists=True)
Harvest input mode: handoff-only
Harvest handoff filter: ['.m3u8'] default=filtered_media_records artifact=camera_urls_jsonl
Harvest input trust: source-provided, unvalidated, untrusted seed data
Normal discovery: disabled by handoff-only harvest input mode
```

For `seed`, print that normal discovery remains enabled.

### Current code anchor

The main orchestration change is likely in:

```text
src/camera_discovery/runners/discovery_run.py
```

Current behavior starts native discovery before this harvest-input block. Refactor the orchestration so mode selection decides whether native discovery futures are submitted at all.

Do not implement the mode in notebook cells.

---

## Required fix 2 — Add candidate explosion guard for handoff-only mode

### Goal

Prevent a small handoff from silently becoming a large candidate set in `handoff-only` mode.

### Required behavior

After loading and converting the handoff records in `handoff-only` mode, compare:

- selected handoff record count, ideally `len(handoff.records)`;
- converted handoff candidate count per target and total;
- combined unique candidate count.

In `handoff-only`, candidate count may exceed the raw record count only when the input artifact legitimately contains multiple media assets per record. For `camera_urls_jsonl` / `filtered_media_records`, one candidate per URL is expected.

Implement a generic guard that detects impossible or suspicious expansion caused by native discovery leaking into the handoff-only path.

Example user-facing message:

```text
Harvest handoff-only mode loaded 12 source records but candidate preparation produced 2207 candidates.
Aborting because handoff-only mode must not run broad discovery or asset-host expansion.
Use --harvest-input-mode seed to intentionally combine harvest input with normal discovery.
```

Do not hard-code `12`, `2207`, `.m3u8`, California, or any source domain.

### Suggested guard logic

A reasonable implementation:

- If `cfg.harvest_input_mode == handoff-only`:
  - native discovery candidate count must be `0`;
  - any `CandidateDiscoveryEngine.discover()` call in this mode is a bug;
  - for `loaded_artifact in {"camera_urls_jsonl", "filtered_media_records"}`, total handoff candidates per target should be no more than `len(handoff.records)`;
  - if multiple targets exist, total across all targets may be `len(handoff.records) * len(runnable_targets)`;
  - for structured inventory artifacts, allow expansion by media-assets-per-record, but base the guard on actual media asset counts if available.

Fail fast with `typer.BadParameter` or `typer.Exit(2)` and a clear message if the guard trips.

### Acceptance criteria

- In handoff-only mode, monkeypatching `CandidateDiscoveryEngine.discover()` to raise must not fail the run, because it should not be called.
- If native candidates appear in a handoff-only run, the run fails with a clear error.
- A HLS handoff containing 12 URL rows cannot produce thousands of candidates unless the user explicitly selects `seed`.

---

## Required fix 3 — Bound handoff-only budgets and summaries

### Goal

Make candidate and enrichment counts understandable for handoff-only runs.

### Required behavior

Update `candidate_discovery_summary.json` and `pipeline_candidate_summary.json` so they include the handoff mode.

Add or preserve fields similar to:

```json
{
  "harvest_input": {
    "loaded": true,
    "mode": "handoff-only",
    "source_path": ".../harvest_handoff.json",
    "loaded_artifact": "camera_urls_jsonl",
    "source_file": ".../camera_urls.jsonl",
    "schema_version": "harvest-handoff/v2",
    "media_filter": [".m3u8"],
    "handoff_default_scope": "filtered_media_records",
    "record_count": 12,
    "candidate_count": 12,
    "filtered_by_handoff_media_filter": true,
    "normal_discovery_enabled": false
  },
  "native_discovery": {
    "enabled": false,
    "unique_candidates": 0
  }
}
```

Use existing summary naming where possible. Do not break current top-level backward-compatible fields.

### Handoff enrichment policy

If you choose to enrich missing-coordinate handoff candidates in handoff-only mode, add bounded summary fields such as:

```json
{
  "handoff_coordinate_enrichment": {
    "enabled": true,
    "input_candidates": 12,
    "attempted": 1,
    "enriched": 0,
    "skipped": 11,
    "bounded_by_handoff_candidates": true
  }
}
```

If you do not add handoff enrichment, explicitly summarize:

```json
{
  "handoff_coordinate_enrichment": {
    "enabled": false,
    "reason": "handoff candidates use source-provided coordinates only in this path"
  }
}
```

Either choice is acceptable if it is documented, tested, and does not reintroduce broad native discovery.

---

## Required fix 4 — Plain progress should show coordinate-enrichment liveness

### Current state

`discovery/candidate_processing.py` already emits:

```text
coordinate_enrichment_started
coordinate_candidate_processed
coordinate_enrichment_complete
```

The rich progress callback in `cli_commands/progress.py` already handles those detailed events. The plain progress callback currently prints only the starting line and then can remain silent during long enrichment.

### Required behavior

Update `_make_plain_discovery_progress_callback()` in:

```text
src/camera_discovery/cli_commands/progress.py
```

so plain mode prints low-noise coordinate-enrichment updates.

Example:

```text
Progress: California — enriching coordinates for 2187 unique candidates...
Progress: California — enriching coordinates 250/2187; mapped 117; metadata 10; geocoded 20; LLM 4.
Progress: California — enriching coordinates 500/2187; mapped 180; metadata 22; geocoded 33; LLM 8.
Progress: California — coordinate enrichment complete: mapped 360/2187; metadata 25; geocoded 80; LLM 40.
```

Do not print every candidate for large runs. Use coarse buckets similar to the existing source-row progress callback.

### Tests

Update `tests/test_cli_progress.py` so plain progress verifies:

- it emits a coordinate-enrichment progress line after `coordinate_candidate_processed`;
- it emits a coordinate-enrichment complete line;
- it remains low-noise.

Do not remove existing rich progress tests.

---

## Required fix 5 — Clean interrupt handling for native discovery futures

### Goal

When a long run is interrupted, the CLI should emit a clear message and avoid confusing executor/thread shutdown output where practical.

### Required behavior

Add clean `KeyboardInterrupt` handling around long-running workflow boundaries in:

```text
src/camera_discovery/runners/discovery_run.py
```

At minimum, handle interrupts around:

- native discovery `ThreadPoolExecutor` submission/result collection;
- validation/output stage if practical.

On interrupt:

1. cancel pending futures if applicable;
2. avoid submitting new work;
3. write a partial `logs/run_summary.json` if the state can be serialized safely;
4. print a concise message, for example:

```text
Run interrupted during native discovery after <completed>/<total> target tasks.
Partial artifacts may be available under <output_dir>.
```

or:

```text
Run interrupted during validation/output writing.
Partial artifacts may be available under <output_dir>.
```

5. exit non-zero with `typer.Exit(130)` or another conventional non-zero code;
6. do not report success.

### Important

Do not swallow ordinary exceptions as successful runs. Preserve existing concise LLM authentication/configuration error handling.

### Tests

Where practical, monkeypatch `CandidateDiscoveryEngine.discover()` or `ReviewAndValidationPipeline.run()` to raise `KeyboardInterrupt` and assert:

- non-zero exit;
- clear interrupted message;
- no success claim.

If fully testing executor shutdown is too brittle, add a smaller unit-level helper test and document any limitation.

---

## Required fix 6 — Notebook updates synchronized to current notebooks

### Current notebook issue

`notebooks/camera_discovery_harvest_urls_test.ipynb` currently contains handoff run cells that omit `--profile` and have no handoff input mode. One cell sets:

```python
RUN_PROFILE = "balanced"
```

but the direct shell command does not pass:

```bash
--profile balanced
```

so the CLI defaults to `fast`.

### Required updates

Update the current notebooks as follows.

#### `notebooks/camera_discovery_harvest_urls_test.ipynb`

1. Update the handoff section to explain:
   - `handoff-only` is the default when `--harvest-input` is supplied;
   - `seed` intentionally combine harvest input with normal discovery and can be much larger/slower.
2. Update direct shell handoff run cells to include:
   - `--profile "$RUN_PROFILE"` or an equivalent explicit profile mechanism;
   - `--harvest-input-mode handoff-only`;
   - `--progress-style plain`.
3. Update subprocess-based handoff run cells to include:
   - `--profile`, `RUN_PROFILE`;
   - `--harvest-input-mode`, `handoff-only`.
4. Before the handoff run, preview `harvest_handoff.json` counts:
   - `schema_version`
   - `handoff_default_scope`
   - `media_filter`
   - selected/default artifact
   - `counts.filtered_media_records` or equivalent
5. Print expected bounded behavior before running:

```text
Expected handoff-only behavior: normal discovery disabled; candidate count should be bounded by selected handoff records and target count.
```

6. Do not implement application logic in notebook cells.

#### Split harvest/full-validation notebooks

Update these notebooks if they run `camera-discovery run --harvest-input`:

```text
notebooks/camera_discovery_harvest_hls_handoff_full_validation_test.ipynb
notebooks/camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb
```

For the default demonstration path, add:

```bash
--harvest-input-mode handoff-only
```

If a notebook intentionally wants the broader native-discovery-plus-handoff behavior, make it explicit with:

```bash
--harvest-input-mode seed
```

and explain the larger runtime.

### Notebook tests

Update or add tests so:

- notebooks are valid JSON;
- handoff run cells contain `--harvest-input-mode`;
- handoff run cells explicitly pass `--profile`;
- notebooks do not import or create `src/camera_discovery/notebook/`;
- no notebook cell monkeypatches source behavior.

---

## Required fix 7 — Documentation updates

Update current docs to include the new harvest input mode.

At minimum inspect and update:

```text
README.md
docs/runtime_configuration.md
docs/output_artifacts.md
docs/project_structure.md
docs/acceptance.md
REPOSITORY_LAYOUT.md
notebooks/README.md
AGENTS.md
```

Do not rewrite historical `docs/codex_prompt_*.md` files except to add a source-alignment note if repository convention requires it.

Docs must explain:

1. `harvest-urls` remains extraction-only.
2. `run --harvest-input` now has exactly two explicit modes:
   - `handoff-only`
   - `seed`.
3. Default with `--harvest-input` is `handoff-only`.
4. In `handoff-only`, normal native discovery is disabled.
5. In `handoff-only`, candidate counts are bounded by selected handoff records/assets and target count.
6. In `seed`, normal discovery intentionally remains enabled and may produce many additional candidates.
7. Handoff candidates remain source-provided, unvalidated, and untrusted until normal validation/trust rules process them.
8. Media-filter-aware handoff loading from `camera_urls.jsonl` remains preserved.
9. Plain progress now reports coordinate-enrichment liveness.
10. Notebook examples pass an explicit profile.

---

## Required tests

Add/update tests using local fixtures and monkeypatches. Do not perform live web discovery.

### 1. CLI/config contract tests

Update:

```text
tests/test_cli_contracts.py
tests/test_run_harvest_input.py
```

Verify:

- `camera-discovery run --help` shows `--harvest-input-mode`.
- Allowed values are accepted.
- Invalid values fail with a clear Typer/config error.
- `load_run_config()` stores the selected mode.
- Without `--harvest-input`, the mode does not change normal behavior.

### 2. Handoff-only skip-native-discovery test

In `tests/test_run_harvest_input.py`, create a small handoff fixture with a few URL records.

Monkeypatch:

```python
CandidateDiscoveryEngine.discover
```

to raise `AssertionError("native discovery must not run in handoff-only mode")`.

Run:

```bash
camera-discovery run test cameras \
  --harvest-input <manifest> \
  --harvest-input-mode handoff-only \
  --no-progress
```

Assert:

- exit code is `0`;
- native discovery was not called;
- review/validation received only harvest-derived candidates;
- `candidate_discovery_summary.json` reports native discovery disabled/zero;
- `harvest_input.mode == "handoff-only"`.

### 3. Seed preserves broad behavior test

Add a test where `CandidateDiscoveryEngine.discover()` returns one native candidate and the handoff fixture returns one handoff candidate.

Run with:

```bash
--harvest-input-mode seed
```

Assert:

- native discovery was called;
- both candidates are present;
- summary states native discovery enabled and handoff mode is `seed`.

### 4. Candidate explosion guard test

Construct or monkeypatch a path that would create native candidates in `handoff-only` mode or otherwise exceed the selected handoff artifact bound.

Assert:

- run exits non-zero;
- message tells user to use `--harvest-input-mode seed` if expansion is intentional.

### 5. Plain progress test

Update `tests/test_cli_progress.py` to call `_make_plain_discovery_progress_callback()` with:

```text
coordinate_enrichment_started
coordinate_candidate_processed
coordinate_enrichment_complete
```

Assert that plain output contains coarse progress and complete messages.

### 6. Interrupt handling tests

Add targeted tests for `KeyboardInterrupt` around native discovery and/or validation.

Assert:

- non-zero exit;
- clear interruption message;
- no success output.

### 7. Notebook tests

Update existing notebook tests or add a focused test:

- all notebooks are valid JSON;
- harvest handoff run cells include `--harvest-input-mode`;
- harvest handoff run cells include `--profile`;
- notebooks do not contain source monkeypatching or implementation logic.

### 8. Regression tests to preserve already-completed behavior

Do not remove current tests that verify:

- media-filtered handoff loads final URL records by default;
- deterministic scope gating marks coordinate-bearing outside candidates `out_of_scope`;
- `--browser-backend` is advertised and config overrides env;
- harvest mode stays extraction-only.

---

## Implementation guidance by file

### `src/camera_discovery/core/models.py`

Add `HarvestInputMode` and `RunConfig.harvest_input_mode`.

### `src/camera_discovery/core/config.py`

Update `load_run_config()` signature and validation. Support CLI argument and optional env var if implemented.

### `src/camera_discovery/cli.py`

Add the Typer option to `run()`:

```python
harvest_input_mode: str = typer.Option("handoff-only", "--harvest-input-mode", help="How --harvest-input is used: handoff-only .")
```

Pass it to `load_run_config()`.

### `src/camera_discovery/runners/discovery_run.py`

Refactor orchestration so native discovery is conditional:

```text
if cfg.harvest_input and cfg.harvest_input_mode == HANDOFF_ONLY:
    skip CandidateDiscoveryEngine.discover()
else:
    run native discovery as current code does
```

Then load handoff candidates and merge. Ensure summary fields distinguish:

```text
native_discovery.enabled
harvest_input.mode
harvest_input.normal_discovery_enabled
combined
```

Add the candidate explosion guard.

Add clean `KeyboardInterrupt` handling around executor/result collection and validation.

### `src/camera_discovery/cli_commands/progress.py`

Add low-noise plain handling for coordinate progress events.

### `src/camera_discovery/services/harvest_handoff.py`

Preserve current media-filter-aware behavior. Only change this file if needed for mode diagnostics, selected-record counts, or guard metadata. Do not break existing `load_harvest_handoff()` compatibility.

### `src/camera_discovery/services/harvest_engine.py`

Preserve current handoff writing. Only add summary clarity for empty structured files if straightforward and non-breaking.

If `camera_records.jsonl` or `camera_media_assets.jsonl` are empty by design, add summary fields such as:

```json
{
  "structured_camera_records_empty_reason": "No structured source camera records were extracted; URL-level records were written to camera_urls.jsonl and harvest_camera_inventory.jsonl."
}
```

Do not remove files if tests or downstream contracts expect them.

### Notebooks

Update current notebooks in place. Do not create `src/camera_discovery/notebook/`.

---

## Verification commands

Run the broadest practical verification set:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

Also run targeted checks while developing:

```bash
PYTHONPATH=src python -m pytest tests/test_run_harvest_input.py -q
PYTHONPATH=src python -m pytest tests/test_harvest_handoff.py -q
PYTHONPATH=src python -m pytest tests/test_cli_progress.py -q
PYTHONPATH=src python -m pytest tests/test_harvest_urls_cli.py -q
PYTHONPATH=src python -m pytest tests/test_cli_contracts.py -q
PYTHONPATH=src python -m pytest tests/test_progress_events_contract.py -q
```

If available and configured:

```bash
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/llm
```

If optional browser dependencies are missing, do not fake browser success. Report skipped browser-dependent checks honestly.

---

## Final response requirements for Codex

In the final response, report:

1. Files inspected before editing.
2. Files changed.
3. New `--harvest-input-mode` semantics and default.
4. Evidence that `handoff-only` does not call `CandidateDiscoveryEngine.discover()`.
5. Evidence that `seed` preserves the broader combined behavior.
6. Candidate summary fields added/updated.
7. Plain progress updates added.
8. Interrupt-handling behavior added.
9. Notebook updates made.
10. Documentation updates made.
11. Tests run and results.
12. Any skipped checks and why.
13. Remaining limitations or follow-up recommendations.

Do not claim a live camera run succeeded unless an actual live run was performed and real output artifacts support the claim.
