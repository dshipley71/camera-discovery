> **Source-alignment note:** This is a historical Codex implementation prompt retained for traceability. The current runtime documentation is in the root `README.md`, `docs/runtime_configuration.md`, `docs/output_artifacts.md`, and the source-aligned agent docs. Do not treat this prompt as the authoritative description of the current code if it conflicts with `src/camera_discovery/`.

# Codex Prompt — Harvest Handoff and Pipeline Follow-Up Fixes

You are working in the `camera-discovery` repository after the structural refactor and blind-search repair. Implement the requested follow-up fixes for the harvest handoff into normal pipeline runs. Follow the repository's root `AGENTS.md`, nested implementation notes, and current `/docs` conventions. The source code is authoritative. If this prompt mentions a stale file, function, class, option, or artifact name, adapt to the verified current source instead of creating duplicate implementations.

This task is **not** about initial HLS harvest discovery. The blind-search repair has worked: harvest mode can now discover Caltrans/DOT HLS sources and produce thousands of `.m3u8` URLs. The remaining problems are in the handoff from harvest mode into `camera-discovery run`, browser preflight behavior, URL canonicalization, and run-summary clarity.

---

## Non-Negotiable Rules

1. **Follow `AGENTS.md` and implementation notes.**
   - No fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, or synthetic runtime success.
   - No hard-coded real-world locations, agencies, source domains, source-specific behavior, or one-off camera types.
   - Generic camera/media normalization and generic URL canonicalization rules are allowed.
   - LLMs remain advisory only.
   - Deterministic code remains authoritative for bbox/geometry verification, coordinate acceptance, validation, trusted output authorization, and final artifact writing.
   - Notebook-specific helper code belongs in notebooks, not `src/`.

2. **Verify before changing anything.** First inspect the actual repository files and identify the current implementations of:
   - `camera_discovery.cli.run`
   - `camera_discovery.cli.harvest_urls`
   - `RunConfig`, `HarvestConfig`, and config/env loading
   - `runners/discovery_run.py`
   - `runners/harvest_run.py`
   - `CameraUrlHarvestEngine`
   - `CandidateDiscoveryEngine`
   - harvest handoff writing and reading
   - harvest inventory/media asset conversion into normal-run candidates
   - deterministic target/bbox/scope-gating logic
   - browser backend selection and browser-capture session/preflight behavior
   - URL canonicalization helpers
   - summary/artifact writing for `candidate_discovery_summary.json` and run explanation output
   - tests covering harvest handoff, run-from-harvest, browser capture, CloakBrowser, CLI contracts, source policy, and URL/media helpers

3. **Do not make assumptions from this prompt alone.** If the source has already implemented part of this work, preserve it and fill only the gaps. Do not create parallel workflows or duplicate handoff formats.

4. **Make surgical changes.** Keep the refactored architecture intact:
   - CLI commands should remain thin.
   - Workflow orchestration belongs in `runners/` and services.
   - Shared extraction helpers belong in `extraction/`.
   - Harvest-specific helpers belong in `harvest/`.
   - Do not collapse code back into god files.

5. **Preserve public behavior unless this prompt explicitly changes it.** Existing CLI options, output names, artifact schemas, environment variables, and tests must continue working.

6. **Do not weaken tests.** Add or update tests to verify the requested behavior. Do not relax assertions to hide regressions.

7. **No brittle line-count or formatting tests.** Tests should protect behavior and contracts.

---

## Problems to Fix

The recent HLS harvest and downstream pipeline run showed:

1. HLS-only harvest handoff injected tens of thousands of image snapshots into the normal pipeline run.
2. Coordinate-bearing harvest records outside the verified target bbox stayed `scope_status=unknown` instead of becoming `out_of_scope`.
3. Browser capture repeatedly attempted Playwright pages even when the browser executable was missing.
4. URL canonicalization allowed small duplicates such as trailing backslashes/escaped quotes and default `:443` host variants.
5. `candidate_discovery_summary.json` and run explanation output made native discovery counts and harvest-input counts hard to distinguish.
6. `camera-discovery run ...` does not expose `--browser-backend`, even though `harvest-urls` does.
7. Pipeline run output printed in notebooks does not clearly state what mode/input/backend/settings are being run.

---

## Required Functional Changes

### 1. Make harvest handoff media-filter aware

When harvest mode is run with a media filter such as:

```bash
camera-discovery harvest-urls "California traffic cameras" \
  --media .m3u8 \
  --output-dir runs/harvest-california-hls \
  --write-intermediate-records
```

then the generated harvest handoff must preserve that filtered intent. A downstream normal pipeline run like:

```bash
camera-discovery run "California traffic cameras" \
  --output-dir runs/run-from-harvest \
  --harvest-input runs/harvest-california-hls/harvest_handoff.json
```

must not inject unrelated media assets such as tens of thousands of image snapshots by default.

Implement the smallest coherent change so that:

- `harvest_handoff.json` records the harvest media filter that produced it.
- `harvest_handoff.json` clearly indicates which artifact(s) are filtered final URL records versus broader structured inventory artifacts.
- Normal `run --harvest-input harvest_handoff.json` defaults to the **filtered final media record set** when the handoff was produced with `--media`.
- For HLS-only handoff, downstream candidates should default to HLS candidates only.
- Broader structured inventory assets may still be available for explicit future use, but they must not be injected by default into a media-filtered handoff.
- Preserve compatibility with older harvest handoff manifests if practical. If older handoffs lack media-filter metadata, use existing behavior or a safe documented default.

Do **not** hard-code `.m3u8` or Caltrans-specific logic. The behavior must be generic for all media filters.

Suggested implementation direction, adjusted to actual source:

- Add handoff metadata such as:

```json
{
  "handoff_schema_version": 2,
  "media_filter": [".m3u8"],
  "handoff_default_scope": "filtered_media_records",
  "filtered_media_records": "camera_urls.jsonl",
  "structured_inventory_records": "harvest_camera_inventory.jsonl"
}
```

- In the normal-run harvest-input loader, read the filtered final records by default when `handoff_default_scope == "filtered_media_records"` or when `media_filter` is non-empty.
- Preserve `camera_records.jsonl`, `camera_media_assets.jsonl`, and `harvest_camera_inventory.jsonl` as diagnostics/inventory artifacts, but do not inject them all into normal runs unless explicitly requested by an existing option or a small, documented new option is necessary.

If a new option is required, keep it narrow and explicit, for example:

```text
--harvest-input-scope filtered|inventory|all
```

Do not add this option unless the existing source makes a default-only solution impractical.

Acceptance evidence:

- A unit/integration test where a harvest handoff has `media_filter=[".m3u8"]` and also contains image media assets; `run --harvest-input` should load only HLS candidates by default.
- Existing unfiltered/all-media handoff behavior remains compatible.

---

### 2. Apply deterministic scope gating to harvest-handoff candidates

Coordinate-bearing harvest records must be scoped deterministically during normal pipeline runs.

Current bad behavior observed:

```text
scope_status unknown: 50,317+
coordinate-bearing out-of-state records still appear in untrusted review GeoJSON
```

Expected behavior:

- If the target has a verified bbox/polygon and a harvest-handoff candidate has coordinates:
  - inside target geometry => `scope_status=in_scope`
  - outside target geometry => `scope_status=out_of_scope`
- Coordinate-bearing out-of-scope candidates should not remain `unknown`.
- Missing-coordinate harvest candidates may remain `unknown`/`review` according to current pipeline policy.
- Scope gating must use deterministic geometry/bbox code only.
- Do not use an LLM to decide coordinates or trusted scope.
- Do not hard-code California or any target.

Find the existing deterministic scope-gating logic used for normal discovery candidates and apply/reuse it for harvest-input candidates before review GeoJSON/table output.

Acceptance evidence:

- Test with a verified bbox target and harvest-input candidates containing:
  - one inside coordinate;
  - one outside coordinate;
  - one missing coordinate.
- The outside coordinate must become `out_of_scope`, not `unknown`.
- The result must preserve target metadata on harvest-input candidates.

---

### 3. Fix Playwright/browser preflight

Browser capture is optional and budgeted. Playwright is the default backend. CloakBrowser is optional. Do not attempt hundreds of browser captures when the browser executable is unavailable.

Implement a backend preflight layer that runs once per normal discovery or harvest run before repeated browser-capture attempts.

Expected behavior:

- If browser capture is disabled, no preflight is needed.
- If selected backend is `playwright` and Playwright Python package or Chromium executable is missing:
  - emit one clear warning/diagnostic;
  - disable browser capture for that run;
  - do not attempt page-by-page browser launches that repeatedly fail;
  - write a clear summary field such as `browser_capture.preflight_ok=false` and `browser_capture.disabled_reason`.
- If selected backend is `cloakbrowser` and CloakBrowser import/launch dependency is missing:
  - fail gracefully in the same style;
  - do not fall back silently to Playwright unless current source explicitly documents that behavior.
- If backend is available, browser capture should work as before.
- Do not add CAPTCHA solving, login automation, credential workflows, proxy/session/profile manager behavior, or source-specific evasion.

Acceptance evidence:

- Test missing Playwright executable/import behavior without requiring real browser download.
- Verify only one preflight warning/diagnostic is produced and page-by-page capture is skipped.
- Existing CloakBrowser backend tests continue to pass.

---

### 4. Tighten URL canonicalization

Fix generic URL canonicalization so duplicate/slightly malformed media URLs collapse properly.

Required generic cleanup:

- Strip trailing backslashes.
- Strip trailing escaped quotes and raw quotes.
- Strip common trailing punctuation introduced by text/JSON/HTML extraction when it is clearly not part of a URL.
- Normalize default HTTPS port `:443` away.
- Normalize default HTTP port `:80` away.
- Preserve non-default ports.
- Preserve query strings and fragments unless existing canonicalization intentionally removes fragments.
- Do not remove meaningful signed-token query parameters.
- Do not hard-code any source domain.

Example cases to cover:

```text
https://host.example/live.m3u8\\
https://host.example/live.m3u8\"
https://host.example:443/live.m3u8?a=token
http://host.example:80/snapshot.jpg
https://host.example:8443/live.m3u8
```

Acceptance evidence:

- Add tests in the relevant media/canonicalization test module.
- Existing harvest dedupe tests still pass.

---

### 5. Improve summary clarity for native, harvest-input, and combined candidates

The downstream run currently produces confusing summary output where `candidate_discovery_summary.json` may show native discovery counts such as `raw=50`, `unique=18`, while the run explanation reports `50,333` combined candidates after harvest input.

Update summaries so counts are clearly separated:

```json
{
  "native_discovery": {
    "raw_candidates": 50,
    "unique_candidates": 18
  },
  "harvest_input": {
    "loaded": true,
    "source_path": ".../harvest_handoff.json",
    "candidate_count": 5000,
    "by_media_type": {"hls": 5000},
    "filtered_by_handoff_media_filter": true
  },
  "combined": {
    "candidate_count_before_scope": 5018,
    "candidate_count_after_scope": 5000,
    "by_scope_status": {"in_scope": 4000, "out_of_scope": 1000}
  }
}
```

The exact schema can follow current artifact style, but it must explicitly distinguish:

- native discovery candidates;
- harvest-input candidates;
- combined final candidates.

Update run explanation / console output to match. Do not remove existing fields unless tests/docs are updated and compatibility is preserved where needed.

Acceptance evidence:

- Test summary JSON for a run with harvest input and native discovery candidates.
- Test or snapshot basic console output if current tests support it.

---

### 6. Add `--browser-backend` to `camera-discovery run`

`harvest-urls` already exposes:

```text
--browser-backend playwright|cloakbrowser
```

Add the same option to the normal pipeline command:

```bash
camera-discovery run "California traffic cameras" \
  --output-dir runs/run-from-harvest \
  --harvest-input runs/harvest-california-hls/harvest_handoff.json \
  --browser-backend cloakbrowser
```

Requirements:

- The option must override `CAMERA_DISCOVERY_BROWSER_BACKEND` for that invocation.
- Allowed values remain whatever the source currently supports, expected `playwright` and `cloakbrowser`.
- Invalid values must fail with a clear Typer/config error.
- Keep environment-variable behavior intact when the CLI option is omitted.
- Update CLI docs/help tests.
- Keep CLI thin: parse/pass the value to config; do not place workflow logic in `cli.py`.

Acceptance evidence:

- CLI contract test verifies `run --help` includes `--browser-backend`.
- Config test verifies CLI arg overrides env var when supplied.

---

### 7. Improve pipeline run output for notebook/cell visibility

Normal pipeline output should make it obvious what is being run, especially for harvest-input runs in notebooks.

Add concise console output near the start of `camera-discovery run` showing:

- mode: normal discovery pipeline;
- query;
- output directory;
- profile;
- discovery mode;
- sources file path/exists if applicable;
- harvest input path and whether it exists;
- selected browser backend;
- browser capture enabled/disabled/preflight status when known;
- any harvest handoff media filter/scope if applicable;
- validation enabled/disabled if current config exposes that;
- note that trusted outputs require validation.

Keep this output concise. It should be helpful in notebook cell output without becoming a huge report. Do not print secrets, API keys, tokens, signed URLs, or full candidate inventories.

Acceptance evidence:

- Running `camera-discovery run ... --harvest-input ... --browser-backend cloakbrowser` prints the selected backend and harvest-input path/filter.
- Existing progress output styles still work.

---

## Documentation Updates

Update Markdown documentation only where it describes these behaviors:

- `README.md`
- `docs/runtime_configuration.md`
- `docs/output_artifacts.md`
- `docs/project_structure.md` if new modules/functions are introduced
- relevant `agents/*.md` or implementation notes only if they would otherwise contradict the new behavior

Documentation should mention:

- `run --browser-backend` option;
- harvest handoff media-filter behavior;
- browser preflight behavior;
- summary count separation;
- recommendation to use `--max-urls 0` for true all-URL harvests when appropriate.

Do not rewrite historical Codex prompts except for source-alignment notes if that is already repository convention.

---

## Tests to Add or Update

Add/update focused tests. Use existing test style and fixtures.

Suggested test coverage:

1. **Harvest handoff media filter**
   - HLS-only handoff loads HLS candidates only by default.
   - Broader media inventory exists but is not injected by default.
   - Unfiltered handoff compatibility remains.

2. **Scope gating for harvest-input candidates**
   - coordinate inside bbox => `in_scope`;
   - coordinate outside bbox => `out_of_scope`;
   - missing coordinate remains current review/unknown behavior.

3. **Browser preflight**
   - missing Playwright browser executable disables browser capture once;
   - repeated page attempts are skipped;
   - diagnostic summary is written.

4. **URL canonicalization**
   - trailing backslash/quotes are stripped;
   - default ports are normalized;
   - non-default ports and signed query parameters are preserved.

5. **Summary clarity**
   - `candidate_discovery_summary.json` or equivalent includes native, harvest-input, and combined counts.

6. **CLI contract**
   - `camera-discovery run --help` includes `--browser-backend`;
   - CLI option overrides env var;
   - invalid backend is rejected clearly.

Do not add tests that rely on live web access, real Caltrans availability, or installed browser binaries. Use pure fixtures/mocks for unit tests. Real-world discovery validation will happen in the notebook.

---

## Verification Required

Run at minimum:

```bash
python -m compileall src tests

PYTHONPATH=src python -m pytest -q \
  tests/test_package_contracts.py \
  tests/test_cli_contracts.py \
  tests/test_cli_progress.py \
  tests/test_config_parameter_alignment.py \
  tests/test_source_policy.py \
  tests/test_browser_capture_expansion.py \
  tests/test_cloakbrowser_backend.py \
  tests/test_harvest_handoff.py \
  tests/test_run_harvest_input.py \
  tests/test_harvest_media_extraction.py \
  tests/test_harvest_structured_records.py
```

Also run any new tests you add.

Then run the full suite:

```bash
PYTHONPATH=src python -m pytest -q
```

If optional browser dependencies are missing, tests should verify missing-dependency behavior without faking browser success. Do not claim real browser capture succeeded unless it actually did.

Run a smoke test:

```bash
PYTHONPATH=src python - <<'PY'
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
from camera_discovery.core.config import load_run_config, load_harvest_config
import camera_discovery.cli as cli
print("imports ok")
PY
```

Before packaging any zip/artifact, remove generated caches:

```bash
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
```

---

## Final Response Required from Codex

When finished, report:

1. Files changed.
2. What was verified before editing.
3. How harvest handoff became media-filter aware.
4. How harvest-input scope gating is applied deterministically.
5. Browser preflight behavior and diagnostics.
6. URL canonicalization changes.
7. Summary/count schema changes.
8. `run --browser-backend` behavior and docs/tests.
9. Pipeline console-output changes.
10. Tests/checks run and exact results.
11. Any limitations or follow-up recommendations.
12. Confirmation that no fake/synthetic camera inventory, coordinates, validation results, GeoJSON, browser success, or source-specific hacks were introduced.
