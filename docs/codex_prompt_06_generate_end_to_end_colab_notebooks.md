# Codex Prompt 06 — Generate End-to-End Google Colab Test Notebooks

You are working in the `camera-discovery` repository after the source and documentation changes from Prompts 01–05. Generate Google Colab notebooks that thoroughly test the application end-to-end for harvest and normal pipeline workflows. Use the existing harvest notebook as a guide, but do not move notebook helper code into `src/`.

The attached/current guide notebook is `camera_discovery_harvest_urls_test_handoff_pipeline_fixes.ipynb` or the closest current equivalent under `notebooks/`. Preserve its useful inspection patterns, but split the workflows into focused notebooks so each test case is easier to run and debug.

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

## Required Notebook Use Cases

Create notebooks under `notebooks/` for these use cases:

1. `camera_discovery_harvest_hls_only_test.ipynb`
   - Harvest HLS-only camera/media URLs.
   - Focus on `.m3u8` extraction, source-row diagnostics, Caltrans-like generic structured endpoint behavior, and output summaries.
   - Do not require full validation.

2. `camera_discovery_harvest_hls_handoff_full_validation_test.ipynb`
   - Harvest HLS-only URLs.
   - Feed the harvest handoff into `camera-discovery run`.
   - Use `--profile full` for full validation when practical.
   - Verify media-filter-aware handoff remains HLS-only.
   - Verify deterministic scope gating and trusted/untrusted output behavior.

3. `camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb`
   - Harvest all supported media types.
   - Feed the handoff into `camera-discovery run` for full validation.
   - Clearly explain that normal pipeline first-class validation/trust may focus on supported camera candidate types, while harvest can collect broader media.
   - Inspect how non-HLS/non-image media is represented.

4. `camera_discovery_pipeline_only_profiles_test.ipynb`
   - Run pipeline only, without harvest input.
   - Include fast, balanced, and full profile cells.
   - Compare validation/trust/artifact behavior across profiles.

If four notebooks create too much duplication, factor repeated notebook-only helper cells into copy-pasted cells inside each notebook. Do not create a `src/camera_discovery/notebook/` package.

---

## Required Common Notebook Structure

Each notebook must include:

### 1. Clear title and purpose

Each notebook should begin with Markdown explaining:

- what workflow it tests;
- what it does not test;
- expected runtime/cost/size implications;
- how to interpret trusted versus review-only outputs.

### 2. Repository setup cell

Use a Colab-friendly setup pattern. The notebook should make it clear whether it clones from GitHub or uses an uploaded repository zip. A practical default is:

```python
!git clone -b "dev" "https://github.com/dshipley71/camera-discovery.git"
%cd camera-discovery
%pip install -e .[cloakbrowser] --no-build-isolation
```

If the repository branch should be configurable, define a top-level variable such as:

```python
REPO_BRANCH = "dev"
```

Do not patch source code from the notebook. The notebook should install and run the repository code.

### 3. Ollama Cloud / API key retrieval

Add an explicit Colab credential cell using `google.colab.userdata`. It must support Ollama Cloud and avoid printing secrets:

```python
import os
from google.colab import userdata

OLLAMA_API_KEY = userdata.get('OLLAMA_API_KEY')
if OLLAMA_API_KEY:
    os.environ['OLLAMA_API_KEY'] = OLLAMA_API_KEY
    os.environ.setdefault('CAMERA_DISCOVERY_LLM_PROVIDER', 'ollama-cloud')
    os.environ.setdefault('CAMERA_DISCOVERY_LLM_MODEL', 'gemma3:27b-cloud')
    print('Loaded OLLAMA_API_KEY from Colab userdata')
else:
    print('OLLAMA_API_KEY not found in Colab userdata. LLM-backed stages may fail unless another provider is configured.')
```

Also include optional cells/instructions for local Ollama, OpenAI-compatible, or Bedrock only if they already exist in project docs. Do not invent provider behavior.

### 4. CLI/import smoke test

Every notebook should run:

```bash
camera-discovery --help
camera-discovery run --help
camera-discovery harvest-urls --help
```

And Python import checks for public imports:

```python
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
import camera_discovery.cli
print('camera-discovery imports OK')
```

### 5. Browser backend setup/preflight

Add cells that make browser behavior explicit:

- default to `--disable-browser-capture` for HLS/Caltrans-like structured endpoint tests unless dynamic capture is specifically being tested;
- provide an optional CloakBrowser/Playwright preflight cell;
- do not fake browser success;
- make failures visible and non-mysterious.

### 6. Run commands with completion-aware guards

Avoid skip guards that only check whether the output directory exists. Check for expected completion artifacts such as:

- `harvest_summary.json`;
- `harvest_handoff.json`;
- `logs/run_summary.json`;
- `review_artifacts.zip` or relevant GeoJSON/table artifacts.

If rerunning is desired, delete the output directory intentionally at the top of the run cell.

### 7. Inspection cells

Each notebook should include cells to inspect:

- source row counts;
- blind search diagnostics;
- harvest summary counts;
- media type distribution;
- source host distribution;
- handoff manifest fields;
- pipeline run summary;
- validation summary;
- trusted versus untrusted artifacts;
- candidate table sample;
- GeoJSON feature counts;
- warnings/errors logs.

### 8. Artifact packaging cells

Include optional cells to zip and download outputs, but do not make them mandatory for test completion.

---

## Use-Case Specific Requirements

### Notebook 1 — Harvest HLS only

Use a routine command similar to:

```bash
camera-discovery harvest-urls "California traffic cameras" \
  --output-dir runs/harvest-california-hls \
  --discovery-mode both \
  --max-search-queries 12 \
  --max-search-results-per-query 25 \
  --max-source-rows 1000 \
  --max-pages-per-source 10 \
  --max-urls 0 \
  --media .m3u8 \
  --disable-browser-capture \
  --progress-style plain
```

Include optional debug/stress cells with `--write-intermediate-records`, but mark them as expensive and not required for routine testing.

### Notebook 2 — HLS harvest handoff to full validation

Use HLS-only harvest first, then run:

```bash
camera-discovery run "California traffic cameras" \
  --profile full \
  --output-dir runs/run-from-harvest-hls-full \
  --harvest-input runs/harvest-california-hls/harvest_handoff.json \
  --disable-browser-capture \
  --progress-style plain
```

Inspect that handoff candidates are HLS-only unless the user explicitly chooses broader handoff behavior.

### Notebook 3 — Harvest all media types to full validation

Use `--media all` or omit `--media`, depending on current CLI semantics. Inspect media distribution and explain that harvest can collect media types that the normal pipeline may not fully validate/trust.

### Notebook 4 — Pipeline only profiles

Run pipeline-only commands without harvest input for:

```bash
camera-discovery run "California traffic cameras" --profile fast ...
camera-discovery run "California traffic cameras" --profile balanced ...
camera-discovery run "California traffic cameras" --profile full ...
```

Use distinct output directories. Compare:

- candidate counts;
- validation attempted/skipped;
- trusted output presence;
- review artifacts;
- warnings/errors.

---

## Documentation Updates

Update docs as needed:

- `docs/README.md` list the new notebooks.
- `README.md` or notebook section mention which notebook to use for each scenario.
- `docs/runtime_configuration.md` if commands/settings are clarified.

Do not update historical prompt files except to add this prompt into `/docs` if requested by the maintainer.

---

## Acceptance Criteria

1. All requested notebooks are created under `notebooks/`.
2. Notebooks are valid `.ipynb` JSON and open in Colab.
3. Notebooks install and run repository code; they do not patch source code at runtime.
4. Ollama Cloud / `OLLAMA_API_KEY` retrieval from Colab userdata is included.
5. Each notebook has clear Markdown documentation and inspection cells.
6. HLS-only harvest notebook uses practical routine defaults and clearly marks expensive debug cells.
7. HLS handoff notebook verifies media-filter-aware handoff.
8. Full-validation notebooks clearly explain expected runtime and validation/trust behavior.
9. Pipeline-only notebook covers fast, balanced, and full profiles.
10. Source code is changed only if required for notebooks to call existing public CLI/API correctly; otherwise notebook work stays in `notebooks/`.

---

## Verification

Run:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q tests/test_package_contracts.py tests/test_cli_contracts.py
python - <<'PY'
import json
from pathlib import Path
for path in Path('notebooks').glob('*.ipynb'):
    json.loads(path.read_text(encoding='utf-8'))
print('notebook json ok')
PY
```

If a notebook execution test is practical, run at least a smoke execution of setup/import cells. Do not run long harvest/full-validation cells in CI unless the repo already supports such integration tests.

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

