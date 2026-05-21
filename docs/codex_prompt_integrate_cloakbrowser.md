# Codex Prompt — Optional CloakBrowser Backend for Camera Discovery

You are working in the `camera-discovery` repository. Integrate CloakBrowser as an optional browser-capture backend while keeping Playwright as the default backend. Use the existing browser-capture implementation and the existing Google Colab notebook workflow as the foundation. Make the smallest coherent change set possible.

This prompt is intentionally narrower than the prior browser-capture expansion prompt. Do **not** re-implement browser-capture routing, page-signal extraction, directory/blind parallelization, candidate discovery, scope enforcement, geocoding, validation, map rendering, or notebook helper architecture unless the current source code proves a small change is required for backend selection.

---

## Non-Negotiable Rules

1. **Verify before changing anything.** First inspect the actual repository files and identify the current implementations of:
   - `CandidateDiscoveryEngine`
   - current browser/network capture code
   - Playwright launch/import code
   - browser-capture routing and logging, if already implemented
   - `RunConfig` and config/env loading
   - `pyproject.toml` optional dependencies
   - notebook install/config/run/report cells
   - tests related to browser capture, dynamic sources, config alignment, and notebook JSON validity

2. **Do not make assumptions from this prompt alone.** If a function, class, file, or config name in this prompt differs from the repository, adapt to the verified source code. Do not create duplicate parallel implementations because a name in this prompt was stale.

3. **No stubs. No placeholders. No fake implementations. No TODO-only code.** Every change must be functional.

4. **No synthetic data, no simulated discovery runs, and no fabricated camera inventories.** Unit tests may verify pure backend-selection/config/logging behavior, but do not present synthetic fixtures as proof of real-world camera discovery.

5. **Do not hard-code real-world locations, agencies, source domains, source-specific behavior, or one-off camera types.**

6. **Keep Playwright as the default backend.** CloakBrowser must be opt-in.

7. **Keep source and notebook changes independent.** Source code implements application behavior. The Google Colab notebook is only for installation, runtime configuration, execution, and artifact/report display. Do not move notebook-only helpers into source code. Do not create `src/camera_discovery/notebook/` or equivalent notebook-helper modules.

8. **Make the smallest coherent source change possible.** Prefer a small launch helper or private backend-selection helper near the existing browser-capture code over introducing a broad new framework.

9. **Testing target is Google Colab notebook.** Update the notebook only where necessary to let a user install/select CloakBrowser and see which backend is active. The notebook must not patch source files.

10. **Public/authorized discovery only.** CloakBrowser may be used as a browser runtime alternative for public camera discovery. Do not add CAPTCHA solving, login automation, credential workflows, account creation, anti-abuse bypass workflows, or source-specific evasion behavior. Do not enable human-like interaction by default.

---

## Upstream CloakBrowser Facts to Verify

Before implementation, check the current CloakBrowser documentation/package behavior if network access is available. At the time this prompt was written, the relevant upstream behavior appeared to be:

- CloakBrowser is advertised as a drop-in Playwright/Puppeteer replacement for Python and JavaScript.
- The Python quick-start pattern is:

```python
from cloakbrowser import launch

browser = launch()
page = browser.new_page()
page.goto("https://example.com")
browser.close()
```

- The migration example replaces:

```python
from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
browser = pw.chromium.launch()
```

with:

```python
from cloakbrowser import launch

browser = launch()
```

- CloakBrowser downloads its own patched Chromium binary on first run, roughly 200 MB, cached locally.
- The wrapper source is MIT-licensed, but the compiled Chromium binary has a separate binary license. Do not bundle, redistribute, or preinstall the CloakBrowser binary in repository artifacts or Docker images unless the license allows that use.

These facts are orientation only. Confirm the current package/API before coding if possible.

---

## Goal

Add a browser backend selector so the application can run browser/network capture using either:

```text
playwright     # default
cloakbrowser   # optional, selected explicitly
```

The resulting behavior should be:

```text
browser-capture routing chooses a page
  -> backend selector reads config/env
  -> default path launches Playwright exactly as before
  -> optional path launches CloakBrowser
  -> existing page/network capture logic runs with minimal branching
  -> logs and candidate metadata record the backend used
```

Playwright must remain the default and must continue to work without installing CloakBrowser.

---

## Required Functional Changes

### 1. Add browser backend configuration

Add a minimal config field to the existing config model and loader using existing repository conventions.

Suggested environment variable:

```text
CAMERA_DISCOVERY_BROWSER_BACKEND=playwright
```

Allowed values:

```text
playwright
cloakbrowser
```

Default:

```text
playwright
```

Validation requirements:

- Invalid values must fail fast or be normalized consistently with existing config behavior.
- The selected backend should be visible in run summaries/logs.
- Existing browser-capture enable/disable settings must remain separate from backend selection.
- Do not rename existing browser-capture environment variables unless the current source requires it.

If the repository already has a browser backend config, extend it minimally rather than adding a duplicate field.

---

### 2. Add optional dependency support

Update `pyproject.toml` using existing optional-dependency style.

Expected behavior:

- Existing `playwright` extra remains unchanged.
- Add a `cloakbrowser` optional extra.
- If the repository has an `all`, `dev`, or notebook-related extra, update only if consistent with current project conventions.
- Do not make CloakBrowser a required dependency.
- Do not remove Playwright.
- Do not vendor or download the CloakBrowser binary into the repository.

Suggested shape, adjusted to actual project style:

```toml
[project.optional-dependencies]
playwright = ["playwright>=..."]
cloakbrowser = ["cloakbrowser>=..."]
```

Use a reasonable version specifier consistent with repository style. If exact version pinning is used elsewhere, follow that style. If loose lower bounds are used elsewhere, follow that style.

---

### 3. Refactor browser launch with minimal branching

Find the existing Playwright launch code. It may look like:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(...)
    ...
```

Refactor only enough to support two backends.

A minimal implementation might be a private helper near the existing browser-capture function:

```python
def _launch_browser_for_capture(self):
    ...
```

or:

```python
@contextmanager
def _browser_capture_session(self):
    ...
```

Requirements:

- For `playwright`, preserve current launch behavior and cleanup.
- For `cloakbrowser`, use the verified CloakBrowser API, expected to be similar to:

```python
from cloakbrowser import launch

browser = launch(headless=True)
```

- Ensure `browser.close()` is always called.
- If Playwright currently uses a context manager that also closes the Playwright driver, preserve equivalent cleanup.
- Do not directly import CloakBrowser unless the selected backend is `cloakbrowser`.
- Do not directly import Playwright unless the selected backend is `playwright`, except where existing tests/import contracts require it.
- Keep current browser-capture behavior, request/response handlers, timeouts, rendered HTML collection, scrolling, and network logging intact.
- Do not add source-specific browser actions.

If CloakBrowser returns an object that supports `new_page()`, the current capture code should remain almost unchanged after browser creation.

---

### 4. Dependency-missing behavior

When backend is `playwright` and Playwright is missing, preserve the current behavior if one already exists.

When backend is `cloakbrowser` and CloakBrowser is missing:

- Do not crash the entire application unexpectedly if the current Playwright-missing behavior is graceful.
- Produce a clear error message in browser-capture logs.
- Include the selected backend in the error payload.
- Provide a clear install hint, for example:

```text
Install with: pip install -e .[cloakbrowser]
```

- Do not silently fall back to Playwright unless the repository already has an explicit fallback config pattern. Backend selection should be predictable.

---

### 5. Logging and summary updates

Where browser-capture results/errors/summary metadata already exist, include the backend name.

At minimum, ensure the following payloads include:

```text
browser_backend: playwright | cloakbrowser
```

Apply this to the verified existing artifacts, likely including some or all of:

```text
logs/browser_capture_decisions.jsonl
logs/browser_capture_results.jsonl
logs/browser_capture_errors.jsonl
logs/browser_capture_summary.json
logs/playwright_network_capture_errors.jsonl, if preserved for compatibility
candidate metadata for browser-discovered candidates
run summary / candidate discovery summary
progress events
```

Do not rename `playwright_network_capture_errors.jsonl` if existing tests/notebook cells expect it. It may remain for backwards compatibility, but new generic browser-capture logs should be preferred if they exist.

---

### 6. Candidate metadata

For candidates discovered through browser capture, preserve existing provenance and add or verify:

```text
browser_backend: playwright | cloakbrowser
browser_capture_url
discovery_method
source_provider
source_kind
source_name
```

If this metadata already exists, only add `browser_backend` or correct backend values where needed.

Do not change candidate identity/deduplication semantics unless tests reveal a backend-specific bug.

---

### 7. Notebook updates

Update the Google Colab notebook only where necessary.

Required notebook changes:

- Preserve the existing Playwright default install path.
- Add a user-editable setting for browser backend:

```python
BROWSER_BACKEND = "playwright"  # "playwright" or "cloakbrowser"
```

or follow the notebook's existing settings style.

- When `BROWSER_BACKEND == "playwright"`:
  - install/use the existing Playwright extra
  - run the existing `python -m playwright install chromium` step

- When `BROWSER_BACKEND == "cloakbrowser"`:
  - install/use the CloakBrowser optional extra
  - do not run `python -m playwright install chromium` unless the verified source still requires Playwright for another reason
  - display a note that CloakBrowser may download its own browser binary on first use

- Set the backend environment variable before running the application:

```python
os.environ["CAMERA_DISCOVERY_BROWSER_BACKEND"] = BROWSER_BACKEND
```

- Display the selected backend alongside existing browser-capture settings.
- Add the backend field to the artifact/report display if browser-capture summary exists.

Notebook restrictions:

- Do not patch source code from notebook cells.
- Do not move notebook display helpers into source code.
- Do not add fake/synthetic camera data to the notebook.
- Do not make the notebook dependent on a specific real-world test location.
- Do not remove existing user-editable settings for fast/balanced/full/query/output controls.

---

### 8. Tests

Add or update tests for pure logic and config behavior only. Do not create fake runtime discovery success.

Required test coverage:

1. Default browser backend is `playwright`.
2. `CAMERA_DISCOVERY_BROWSER_BACKEND=cloakbrowser` configures the CloakBrowser backend.
3. Invalid backend value is rejected or normalized according to existing config behavior.
4. Playwright backend still uses the existing Playwright launch path.
5. CloakBrowser backend imports/launches CloakBrowser only when selected.
6. Missing CloakBrowser dependency produces a clear logged error or clear exception consistent with existing browser-capture error handling.
7. Browser-capture result/error/summary payloads include `browser_backend`.
8. Browser-discovered candidate metadata includes `browser_backend`.
9. Existing Playwright tests still pass.
10. Notebook JSON remains valid after updates.

If browser launch tests would require real browser binaries, mock only the import/launch boundary. Do not run fake discovery and claim it validates real capture.

---

## Required Local Checks

Run the repository's actual validation commands. At minimum, attempt:

```bash
python -m compileall src tests
python -m pytest
```

Also validate notebook JSON if the notebook was edited, for example:

```bash
python - <<'PY'
import nbformat
from pathlib import Path
for path in Path("notebooks").glob("*.ipynb"):
    nbformat.read(path, as_version=4)
    print(f"valid notebook: {path}")
PY
```

If the full test suite cannot run in the current environment, run the most relevant subset and document exactly what passed and what could not be run.

---

## Real-World / Colab Validation Expectation

Do not claim live CloakBrowser validation unless the Google Colab notebook is actually run against real public web sources with `BROWSER_BACKEND="cloakbrowser"`.

If live Colab validation is not run, state that it is pending and provide the exact settings to use:

```text
BROWSER_BACKEND = "playwright"
ENABLE_BROWSER_CAPTURE = true
```

then:

```text
BROWSER_BACKEND = "cloakbrowser"
ENABLE_BROWSER_CAPTURE = true
```

Compare:

```text
browser pages attempted
browser HLS candidates found
browser image snapshot candidates found
browser errors/timeouts
runtime
candidate validation success
trusted GeoJSON count
untrusted/review GeoJSON count
```

Recommended validation modes:

```text
blind-only
directory-only
both
```

Do not fabricate or summarize real-world success unless those runs were actually performed.

---

## Acceptance Criteria

The task is complete only when all of the following are true:

1. Playwright remains the default browser backend.
2. CloakBrowser is available as an optional backend selected by config/env.
3. CloakBrowser is not a required dependency.
4. Existing Playwright browser capture still works.
5. Browser-capture routing behavior is not broadened or rewritten as part of this task.
6. Existing static extraction remains unchanged except where needed to pass backend metadata.
7. Browser-capture logs/results/errors/summaries include the selected backend.
8. Browser-discovered candidates include `browser_backend`.
9. Missing CloakBrowser dependency produces a clear install hint.
10. Notebook can select either Playwright or CloakBrowser without patching source files.
11. Notebook remains Colab-friendly and source-independent.
12. No real-world source/domain/location-specific behavior is added.
13. No synthetic camera data, fake streams, fake GeoJSON, fake validation, or simulated runtime success is added.
14. Local compile/tests pass, or failures are documented with exact causes.
15. Final response summarizes changed files, verified source behavior, new config, tests run, and live Colab validation still required.

---

## Implementation Notes / Hints

- Prefer a small backend launch helper over a new package.
- Keep current Playwright code path as close to unchanged as possible.
- CloakBrowser's Python API is expected to return a browser object compatible with Playwright-style `new_page()`.
- Avoid directly importing `patchright` or other internal dependencies unless CloakBrowser's current docs require it.
- Do not enable `humanize=True` by default. If adding a config for it is unavoidable, default it to false and do not add behavioral automation actions.
- Do not add proxy, profile manager, persistent session, login, or CAPTCHA-related features.
- Avoid broad test rewrites. Add targeted tests around backend selection, missing dependency, and metadata/log payloads.
- If the browser-capture expansion from the prior prompt is not present in the source, integrate CloakBrowser only into the verified current dynamic/browser capture path and do not implement the full browser-capture expansion here.
- If the prior browser-capture expansion is present, do not duplicate it. Add only the backend selector and metadata/reporting changes.

---

## Final Response Required from Codex

When finished, report:

1. Files changed.
2. What was verified before editing.
3. Whether Playwright remains the default.
4. How to enable CloakBrowser.
5. New/updated configuration fields and defaults.
6. New/updated optional dependency extras.
7. Updated logs/metadata that include `browser_backend`.
8. Tests/checks run and exact results.
9. Any limitations or live Colab validation still required.
