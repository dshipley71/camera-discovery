# Codex Prompt — Parallel Stream Validation, HTTP Client Reuse, Validation Progress, and `--http-timeout`

You are working in the current `camera-discovery` repository. Implement targeted validation-stage performance and observability improvements for large HLS handoff validation runs.

This prompt follows the behavioral and rules style used by the existing `/docs/codex_prompt_*.md` files in the repository. Make the smallest coherent source, notebook, docs, and tests changes required. Do not add validation caps.

---

## Context

Large HLS handoff runs can produce thousands of candidates. A recent notebook run showed:

```text
Pipeline mode: normal discovery pipeline
Query: California traffic cameras
Profile: full
Validation enabled: True (trusted outputs require validation)
Harvest input mode: handoff-only
Harvest input candidates: 2287 from 2287 record(s) in camera_urls_jsonl
Candidates: native_unique=0 harvest_input=2287 combined_unique=2287 coordinate_bearing=2285 targets=1
Progress: validating streams and writing outputs...
```

The run then appeared stuck because validation currently prints only a coarse start line. In the current repository, validation is implemented mainly in:

```text
src/camera_discovery/services/review_validation_pipeline.py
```

and currently validates candidates sequentially. HLS validation opens a new `httpx.Client` per candidate in `_validate_hls()`, and image snapshot validation opens a new `httpx.Client` per candidate in `_validate_image_snapshot()`.

The existing config already has:

```text
RunConfig.http_timeout
CAMERA_DISCOVERY_HTTP_TIMEOUT
```

but the `run` command does **not** expose a direct CLI option like:

```bash
--http-timeout 10
```

---

## Non-Negotiable Rules

1. **Follow the root `AGENTS.md`, nested implementation notes, and current `/docs` conventions.** The source code is authoritative. If this prompt mentions a stale file, function, class, option, artifact name, test name, or module path, adapt to the verified current source instead of creating duplicate implementations.

2. **No fake runtime evidence.** Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime camera inventories. Tests may use local fixtures and monkeypatches, but do not present fixture results as real discovery.

3. **No source-specific hacks.** Do not hard-code California, Caltrans, Skyline, `wzmedia.dot.ca.gov`, `skylinewebcams.com`, any real-world location, any agency, any source domain, or source-specific behavior. Generic HLS validation, generic HTTP timeout handling, generic client reuse, generic progress reporting, and generic worker-bounded concurrency are allowed.

4. **LLMs remain advisory only.** This task must not add LLM-based validation. Deterministic/network validation remains authoritative for stream validation and trusted output authorization.

5. **Keep notebooks separate from source.** Notebook-only display or helper logic belongs in notebooks. Do not create `src/camera_discovery/notebook/` or import notebook helpers from source.

6. **Make surgical changes.** Keep the refactored architecture intact:
   - CLI declarations remain thin in `cli.py`;
   - config loading remains in `core/config.py`;
   - models/data contracts remain in `core/models.py`;
   - workflow orchestration remains in `runners/`;
   - validation/output logic remains in `services/review_validation_pipeline.py`;
   - progress rendering remains in `cli_commands/progress.py`.

7. **Do not weaken tests.** Add or update tests to protect the new behavior. Do not relax existing assertions to hide regressions.

8. **Preserve public contracts unless explicitly changed here.** Existing CLI options, output artifact names, validation statuses, summary schemas, trust behavior, profile semantics, environment variables, and handoff behavior must continue working.

9. **Do not add validation caps.** Do **not** add `--max-validation-candidates`, `CAMERA_DISCOVERY_MAX_VALIDATION_CANDIDATES`, notebook validation caps, truncation defaults, sampling limits, or any source-code behavior that silently validates only a subset of candidates. Every selected validation candidate should still be considered unless existing profile/trust/scope logic excludes it.

---

## Required Baseline Inspection Before Editing

Before editing, inspect and record in the final response:

1. `src/camera_discovery/services/review_validation_pipeline.py`
2. `src/camera_discovery/core/models.py`
3. `src/camera_discovery/core/config.py`
4. `src/camera_discovery/cli.py`
5. `src/camera_discovery/runners/discovery_run.py`
6. `src/camera_discovery/cli_commands/progress.py`
7. tests covering validation, progress, CLI contracts, config alignment, handoff input, and output artifacts.

Pay special attention to:

```text
ReviewAndValidationPipeline.run()
ReviewAndValidationPipeline._validate()
ReviewAndValidationPipeline._validate_candidate()
ReviewAndValidationPipeline._validate_hls()
ReviewAndValidationPipeline._validate_image_snapshot()
ValidationSummary
RunConfig.http_timeout
load_run_config()
camera-discovery run
_make_plain_discovery_progress_callback()
_make_discovery_progress_callback()
_emit_progress_stream_event()
```

---

## Required Change 1 — Parallelize validation with a bounded worker pool

### Goal

Validate large HLS candidate sets faster by using bounded concurrency.

### Required behavior

Refactor `ReviewAndValidationPipeline._validate()` so validation work can run concurrently over the selected validation rows.

Use a bounded `ThreadPoolExecutor` or equivalent standard-library concurrency primitive. The default worker count should be reasonable for network I/O, such as **24** workers, and must be bounded.

Recommended model/config addition:

```python
validation_workers: int = 24
```

Recommended environment variable:

```bash
CAMERA_DISCOVERY_VALIDATION_WORKERS=24
```

Validation workers must be clamped to a safe range, for example:

```text
min 1
max 64
```

Do not add a candidate-count cap.

### Ordering and determinism

Validation completion order may differ under concurrency, but output artifact ordering should remain deterministic.

Recommended approach:

1. Build `rows = prioritize_candidates(...)` as now.
2. Preserve original row order with an index.
3. Submit validation tasks concurrently.
4. Store `(index, candidate, status)` results.
5. Apply status/trust mutations back to candidates deterministically.
6. Write outputs using the existing prioritization/order logic.

### Error isolation

A validation exception for one candidate must not abort the entire validation run. Existing behavior generally converts exceptions to statuses such as `dead_link`; preserve that behavior.

### Thread safety

Do not mutate shared `ValidationSummary` counters from worker threads. Instead, workers should return statuses, and the main thread should update counters/trust fields.

### Profile behavior

Preserve existing profile semantics:

```text
fast      -> validation disabled / review-only
balanced  -> playlist/image validation enabled; no full segment verification
full      -> validation enabled and HLS segment/variant check enabled
```

Do not alter trust policy rules.

---

## Required Change 2 — Reuse HTTP clients during validation

### Goal

Avoid creating a brand-new `httpx.Client` for every candidate.

### Required behavior

Refactor validation HTTP calls so workers reuse HTTP clients when possible.

Acceptable approaches:

1. **Thread-local clients:** one `httpx.Client` per worker thread, lazily created and closed after validation completes.
2. **Shared client:** a single shared `httpx.Client` only if you verify the current `httpx` usage pattern is safe enough for the way this code uses it.
3. **Client pool helper:** a small local helper inside `review_validation_pipeline.py` or a focused utility module, if that keeps the code cleaner.

Prefer thread-local clients unless the current repository already has an HTTP client reuse abstraction.

### Required details

- Preserve current timeout and user-agent behavior.
- Preserve `follow_redirects=True`.
- HLS playlist GET and full-profile segment HEAD should use the same client.
- Image snapshot first/second GET should use the same client for that candidate.
- Clients must be closed after validation completes.
- Do not leak open sockets.

### Suggested signature changes

Instead of:

```python
def _validate_hls(self, url: str) -> str:
    with httpx.Client(...) as client:
        ...
```

use something like:

```python
def _validate_hls(self, url: str, client: httpx.Client) -> str:
    ...
```

and:

```python
def _validate_image_snapshot(self, url: str, metadata: dict | None, client: httpx.Client) -> str:
    ...
```

Then `_validate_candidate()` can accept a client:

```python
def _validate_candidate(self, candidate: CameraCandidate, client: httpx.Client) -> str:
    ...
```

Use the actual repository style.

---

## Required Change 3 — Add validation progress per candidate

### Goal

The notebook should not appear stuck at:

```text
Progress: validating streams and writing outputs...
```

It should show coarse validation progress such as:

```text
Progress: validating streams 100/2287
Progress: validating streams 500/2287
Progress: validating streams 1000/2287
Progress: validation complete: attempted=2287 live=... dead=... unknown=...
```

### Required behavior

Add progress callbacks/events for the validation stage.

Recommended events:

```text
validation_candidates_selected
validation_candidate_processed
validation_complete
```

Payloads should include useful counts:

```json
{
  "completed": 500,
  "total": 2287,
  "attempted": 500,
  "live": 320,
  "dead": 120,
  "unknown": 60,
  "validation_workers": 24,
  "ffprobe_enabled": true
}
```

Use existing event/progress conventions where possible.

### Wiring

Currently `execute_discovery_run()` prints or emits:

```text
validation_started
validation_complete
```

around the entire `ReviewAndValidationPipeline(cfg).run(...)` call. Extend this so `ReviewAndValidationPipeline` can receive a progress callback, for example:

```python
ReviewAndValidationPipeline(cfg, progress_callback=progress_callback).run(...)
```

or:

```python
pipeline.run(..., progress_callback=progress_callback)
```

Choose the option that fits the current style.

The callback should work for:

```text
rich
plain
events
off/no-progress
```

### Plain progress

Update `_make_plain_discovery_progress_callback()` or the validation progress plumbing so plain mode prints low-noise validation progress.

Use coarse buckets, not one line per candidate for large runs. A good rule:

- print at start;
- print at roughly each 10% bucket;
- print at completion;
- for small runs, do not spam more than necessary.

Example:

```text
Progress: validation selected 2287 candidates; workers=24; timeout=10.0s; full_segment_check=True.
Progress: validating streams 229/2287; live=... dead=... unknown=...
Progress: validating streams 458/2287; live=... dead=... unknown=...
...
Progress: validation complete: attempted=2287; live=... dead=... unknown=... skipped=...
```

### Rich progress

If rich progress already uses a validation task with `total=1`, update it so it can display candidate-level progress when total is known.

### Event progress

For `--progress-style events`, emit machine-readable validation progress events. Preserve existing event names if already used and add the new detailed events.

### Summary artifacts

Update `logs/validation_summary.json` to include:

```json
{
  "validation_workers": 24,
  "http_timeout": 10.0,
  "parallel_validation": true
}
```

or equivalent fields on `ValidationSummary`.

Do not break existing fields:

```text
validation_enabled
ffprobe_enabled
attempted
live
dead
unknown
skipped
```

---

## Required Change 4 — Add `--http-timeout` CLI option for `run`

### Goal

Let users set validation/network timeout directly in notebook-visible commands.

### Required CLI behavior

Add to `camera-discovery run`:

```bash
--http-timeout 10
```

This should override `CAMERA_DISCOVERY_HTTP_TIMEOUT` for the run command.

Recommended CLI declaration:

```python
http_timeout: Optional[float] = typer.Option(
    None,
    "--http-timeout",
    help="HTTP timeout in seconds for network discovery, enrichment, and validation requests; overrides CAMERA_DISCOVERY_HTTP_TIMEOUT.",
)
```

Then pass it to `load_run_config()`.

### Config behavior

Update `load_run_config()` to accept:

```python
http_timeout: float | None = None
```

Resolution order:

1. CLI `--http-timeout`, if provided;
2. `CAMERA_DISCOVERY_HTTP_TIMEOUT`;
3. existing default, currently `20.0`.

Validate:

```text
must be > 0
```

A reasonable minimum clamp such as `0.1` is acceptable if consistent with the repository style, but do not silently accept `0` or negative values.

### Harvest command

This prompt only requires `--http-timeout` for `camera-discovery run`, because the problem is validation-stage timeout. Do not add it to `harvest-urls` unless doing so is trivial, consistent with the codebase, documented, and tested. If you add it to `harvest-urls`, make sure this does not distract from the validation work.

### Notebook usage

Update relevant handoff/full-validation notebook cells to use visible shell commands with:

```bash
--http-timeout 10
```

Do not rely only on:

```python
os.environ["CAMERA_DISCOVERY_HTTP_TIMEOUT"] = "10"
```

The env var may remain documented as a fallback, but the notebook command should show the CLI option.

---

## Required Change 5 — No validation caps

Do not add any of the following:

```bash
--max-validation-candidates
```

```bash
CAMERA_DISCOVERY_MAX_VALIDATION_CANDIDATES
```

```python
RunConfig.max_validation_candidates
```

Do not update notebooks to validate only the first N candidates.

Do not silently skip candidates to improve speed.

The performance improvement must come from:

1. bounded parallelism;
2. HTTP client reuse;
3. configurable timeout;
4. visible progress.

---

## Required Change 6 — Notebook updates

Update the relevant notebooks, especially:

```text
notebooks/camera_discovery_harvest_hls_handoff_full_validation_test.ipynb
notebooks/camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb
```

If the current notebooks still use a helper such as:

```python
run_cli(...)
```

for long-running `camera-discovery run` or `camera-discovery harvest-urls` commands, replace those long-running command cells with visible shell cells using:

```python
!camera-discovery ...
```

so processing output streams directly in Colab.

For the full HLS handoff validation notebook, use a visible command shape like:

```bash
!camera-discovery run "{QUERY}" \
  --profile balanced \
  --output-dir "{RUN_DIR}" \
  --harvest-input "{HARVEST_DIR / 'harvest_handoff.json'}" \
  --harvest-input-mode handoff-only \
  --browser-backend "{BROWSER_BACKEND}" \
  --http-timeout 10 \
  --progress-style plain
```

Use `full` profile only if the notebook section explicitly explains it will perform additional segment checks and may take longer. For practical interactive validation over thousands of HLS URLs, `balanced` should be the default demonstration profile.

Do not add validation caps in notebooks.

Notebook cells should clearly state:

```text
Validation is parallel and bounded by worker count, not by candidate count.
No validation candidate cap is applied.
Use --http-timeout to fail slow network requests faster.
```

---

## Required Change 7 — Documentation updates

Update current docs to describe:

1. Parallel validation behavior.
2. Default validation worker count.
3. Optional `CAMERA_DISCOVERY_VALIDATION_WORKERS`, if implemented.
4. `camera-discovery run --http-timeout`.
5. Existing `CAMERA_DISCOVERY_HTTP_TIMEOUT`.
6. Validation progress events and plain progress output.
7. That no validation cap is applied.
8. Difference between `balanced` and `full` validation:
   - `balanced`: playlist/image validation;
   - `full`: HLS segment/variant check in addition to playlist validation.

At minimum inspect and update as appropriate:

```text
README.md
docs/runtime_configuration.md
docs/output_artifacts.md
docs/acceptance.md
docs/project_structure.md
notebooks/README.md
REPOSITORY_LAYOUT.md
AGENTS.md
```

Do not rewrite historical `docs/codex_prompt_*.md` files except to add a source-alignment note if that is the repository convention.

---

## Required Tests

Add/update tests using local fixtures and monkeypatches only. Do not perform live web validation.

### 1. CLI/config tests

Update or add tests in:

```text
tests/test_cli_contracts.py
tests/test_config_parameter_alignment.py
```

Verify:

- `camera-discovery run --help` shows `--http-timeout`.
- `load_run_config(..., http_timeout=10)` stores `RunConfig.http_timeout == 10.0`.
- CLI `--http-timeout` overrides `CAMERA_DISCOVERY_HTTP_TIMEOUT`.
- invalid `--http-timeout 0` or negative values fail clearly.
- `CAMERA_DISCOVERY_VALIDATION_WORKERS`, if implemented, is parsed and clamped/validated.
- `RunConfig.validation_workers` exists if added.

### 2. Parallel validation tests

Add focused unit tests, probably in a new file such as:

```text
tests/test_validation_parallelism.py
```

or an existing validation test file if one exists.

Verify:

- validation submits multiple candidates through a bounded executor when workers > 1;
- every selected candidate is attempted exactly once;
- output counters are correct;
- candidate trust/status mutation still matches existing rules;
- exceptions for individual candidates become appropriate statuses and do not abort the entire validation run;
- output ordering remains deterministic.

Use monkeypatched `_validate_candidate()` or local fake HTTP behavior rather than live URLs.

### 3. HTTP client reuse tests

Use monkeypatching to count `httpx.Client` construction or to inject a fake client factory if you add one.

Verify:

- validation no longer constructs one `httpx.Client` per HLS candidate;
- HLS playlist GET and full-profile segment HEAD use the same client for a candidate;
- image snapshot first/second GET use the same client for a candidate;
- clients are closed after validation completes.

The exact assertion depends on implementation. For thread-local clients, assert client count is less than or equal to worker count plus a small allowance, not equal to candidate count.

### 4. Validation progress tests

Update:

```text
tests/test_cli_progress.py
tests/test_progress_events_contract.py
```

Verify:

- `validation_candidates_selected` prints/emits selected count, worker count, and timeout;
- `validation_candidate_processed` prints/emits coarse progress;
- `validation_complete` prints/emits final counters;
- plain progress is low-noise for large totals;
- event progress emits machine-readable records with the expected keys.

### 5. Notebook tests

Update notebook tests or add focused checks to verify:

- relevant notebooks are valid JSON;
- long-running `camera-discovery run` cells use visible `!camera-discovery ...`;
- full-validation handoff notebook includes `--http-timeout 10`;
- no notebook contains validation caps;
- no notebook implements source validation logic in cells.

### 6. Regression tests

Do not remove or weaken existing tests that cover:

- harvest handoff loading;
- handoff-only and seed behavior;
- URL cleanup/canonicalization;
- target resolver behavior;
- trusted/untrusted output rules;
- validation status names;
- profile behavior;
- image snapshot validation semantics.

---

## Implementation Guidance

### `src/camera_discovery/core/models.py`

Add fields to `RunConfig` and `ValidationSummary` as needed, for example:

```python
validation_workers: int = 24
```

and:

```python
validation_workers: int = 0
http_timeout: float = 0.0
parallel_validation: bool = False
```

Use names consistent with the repository.

### `src/camera_discovery/core/config.py`

Add `http_timeout` parameter to `load_run_config()` and resolve:

```text
CLI > env > default
```

Add validation worker parsing if implemented:

```bash
CAMERA_DISCOVERY_VALIDATION_WORKERS
```

Clamp/validate worker values.

### `src/camera_discovery/cli.py`

Add `--http-timeout` to the `run` command and pass it through.

Do not add validation caps.

### `src/camera_discovery/services/review_validation_pipeline.py`

Main changes belong here.

Recommended direction:

- Accept a progress callback in the pipeline constructor or `run()`.
- Create/reuse HTTP clients per worker.
- Run validation tasks through a bounded executor.
- Collect results in main thread.
- Update `ValidationSummary` in main thread.
- Emit progress at start, each coarse milestone, and completion.
- Preserve current output writing behavior.

### `src/camera_discovery/runners/discovery_run.py`

Pass the active progress callback into `ReviewAndValidationPipeline`.

Avoid leaving the validation task as total `1` if detailed progress is now available. Ensure `validation_started` / `validation_complete` event behavior remains backward compatible or is cleanly superseded by detailed events.

### `src/camera_discovery/cli_commands/progress.py`

Add validation event handling for:

```text
validation_candidates_selected
validation_candidate_processed
validation_complete
```

to:

```text
_make_discovery_progress_callback()
_make_plain_discovery_progress_callback()
_make_event_stream_discovery_progress_callback()
```

or the common event stream function if that is where the current code centralizes event output.

### Notebooks

Replace long-running `run_cli(...)` executions with visible shell commands using `!camera-discovery ...`.

Do not remove helper functions if they are still useful for short setup/inspection steps. The requirement is that long-running CLI runs stream output visibly.

---

## Verification Commands

Run the broadest practical verification set:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

Also run targeted tests while developing:

```bash
PYTHONPATH=src python -m pytest tests/test_cli_contracts.py -q
PYTHONPATH=src python -m pytest tests/test_config_parameter_alignment.py -q
PYTHONPATH=src python -m pytest tests/test_cli_progress.py -q
PYTHONPATH=src python -m pytest tests/test_progress_events_contract.py -q
PYTHONPATH=src python -m pytest tests/test_run_harvest_input.py -q
PYTHONPATH=src python -m pytest tests/test_harvest_handoff.py -q
PYTHONPATH=src python -m pytest tests/test_validation_parallelism.py -q
```

Use the actual test filenames present in the repository. If you add a different test file name, run that file.

If optional tools are available, run:

```bash
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/services
```

If optional dependencies or tools are missing, report that honestly. Do not fake optional dependency success.

---

## Acceptance Criteria

The implementation is complete when:

1. `camera-discovery run --help` includes `--http-timeout`.
2. `--http-timeout 10` overrides `CAMERA_DISCOVERY_HTTP_TIMEOUT` for the run.
3. Validation uses bounded concurrency.
4. Validation does not create a fresh `httpx.Client` per candidate.
5. Validation progress is visible in plain notebook output during large runs.
6. Event progress includes validation progress records.
7. Every selected validation candidate is still attempted; no validation cap is added.
8. Existing validation statuses and trusted-output rules remain intact.
9. Relevant notebooks use visible `!camera-discovery ...` commands for long-running CLI execution.
10. Relevant notebooks include `--http-timeout 10`.
11. Tests pass.

---

## Final Response Requirements for Codex

In the final response, report:

1. Files inspected before editing.
2. Files changed.
3. How validation is parallelized and bounded.
4. Default and configurable validation worker count.
5. How HTTP clients are reused and closed.
6. How validation progress is emitted in plain/rich/events modes.
7. How `--http-timeout` is parsed and how it overrides the environment variable.
8. Confirmation that no validation caps were added.
9. Notebook updates made.
10. Documentation updates made.
11. Tests run and results.
12. Any skipped checks and why.
13. Remaining limitations or follow-up recommendations.

Do not claim live validation speedups from real-world camera runs unless you actually performed such a run and have real output artifacts to support the claim.
