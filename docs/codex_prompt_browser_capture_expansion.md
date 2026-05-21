> **Source-alignment note:** This is a historical Codex implementation prompt retained for traceability. The current runtime documentation is in the root `README.md`, `docs/runtime_configuration.md`, `docs/output_artifacts.md`, and the source-aligned agent docs. Do not treat this prompt as the authoritative description of the current code if it conflicts with `src/camera_discovery/`.

# Codex Prompt — Browser-Capture Expansion for Camera Discovery

You are working in the `camera-discovery` repository. Implement browser-capture expansion with minimal source-code and notebook changes. Follow the repository's `AGENTS.md` and all implementation notes. Do not skip verification. Do not invent functions, modules, classes, or CLI flags without first confirming the current source structure.

## Non-Negotiable Rules

1. **Verify before changing anything.** First inspect the actual repository files and identify the current implementations of:
   - `CandidateDiscoveryEngine`
   - directory source loading / `DirectorySourceProvider`
   - blind search / SearchAgent-equivalent logic
   - source-row selection
   - source-row extraction
   - dynamic browser capture / Playwright usage
   - `RunConfig` and config loading
   - notebook install/run/report cells
   - current tests related to discovery, dynamic sources, progress, and config alignment

2. **Do not make assumptions from this prompt alone.** If a function or file name in this prompt differs from the repository, adapt to the verified source code. Do not create duplicate parallel implementations because a name in this prompt was stale.

3. **No stubs. No placeholders. No fake implementations. No TODO-only code.** Every change must be functional.

4. **No synthetic data, no simulated discovery runs, and no fabricated camera inventories.** Do not create fake camera feeds, fake validation results, fake GeoJSON outputs, fake screenshots, or fake runtime success claims. Unit tests may verify pure routing/config/logging behavior, but do not present synthetic fixtures as proof of real discovery. Real-world validation will be performed in the Google Colab notebook.

5. **Do not hard-code real-world locations, agencies, source domains, source-specific behavior, or one-off camera types.** Generic camera-type normalization and generic dynamic-page indicators are allowed.

6. **SearchAgent and DirectoryAgent must run in parallel in `both` discovery mode.** Verify whether this is already true. If it is not truly parallel, minimally implement parallel row discovery for blind search and directory source rows while preserving provenance and block-policy behavior.

7. **Keep source and notebook changes independent.** Source code implements application behavior. The Google Colab notebook is only for installation, runtime configuration, execution, and artifact/report display. Do not move notebook-only helpers into source code. Do not create `src/camera_discovery/notebook/` or equivalent notebook-helper modules.

8. **Make the smallest coherent change set possible.** Prefer local helpers and existing architecture over broad rewrites. Preserve current public contracts unless the change is required by this task.

9. **Testing target is Google Colab notebook.** Update the notebook only where necessary to install/use browser capture, expose relevant environment settings, and display the new browser-capture logs/metrics. The notebook must not patch source files.

---

## Current Behavior to Verify

Before editing, confirm the current behavior from source code. In the uploaded repo version used to draft this prompt, the relevant facts appeared to be:

- `src/camera_discovery/services/discovery_engine.py` contains `CandidateDiscoveryEngine`.
- `_source_rows()` loads directory rows before blind search rows in `both` mode.
- `_collect_candidates_from_rows()` processes source rows using `concurrent.futures.ThreadPoolExecutor`.
- `_extract_from_source_row()` directly routes `source_kind == "dynamic"` to `_extract_from_dynamic_page()`.
- `_extract_from_dynamic_page()` imports `playwright.sync_api.sync_playwright`, launches Chromium, listens to request/response URLs, captures `.m3u8` and JSON/API-like URLs, and writes `logs/playwright_network_capture_errors.jsonl` on errors.
- `RunConfig` currently has candidate/search/directory/page budget fields but may not yet have browser-capture-specific fields.
- `pyproject.toml` already has a `playwright` optional extra.
- The notebook currently installs `.[playwright]` and runs `python -m playwright install chromium`.

These facts are provided only as orientation. Re-check the actual repository before making changes.

---

## Goal

Expand browser/network capture so that it is no longer used only for rows explicitly marked `dynamic`. Browser capture must become a shared, budgeted, logged second-stage routing decision for both:

1. **Blind search / SearchAgent results**, and
2. **DirectoryAgent / `SOURCES.md` results**.

Static extraction must still run first. Browser capture should be used only when generic dynamic-page evidence suggests that static extraction may have missed camera media or feed endpoints.

The result should be:

```text
source rows from directory + blind search + direct seeds + promoted asset hosts
  -> static extraction
  -> page-signal extraction
  -> browser-capture routing decision
  -> optional browser/network capture
  -> rendered/network/JSON/media extraction
  -> merge/dedupe
  -> existing geocoding/scope/review/validation/output pipeline
```

---

## Required Functional Changes

### 1. Ensure SearchAgent and DirectoryAgent run in parallel in `both` mode

Verify whether directory row loading and blind search row discovery are truly parallel in `both` mode.

If not, minimally update row discovery so that when discovery mode is `both`:

- Directory source rows and blind search rows are gathered concurrently.
- Provenance is preserved with existing metadata such as `source_provider`.
- Directory rows remain user-approved discovery inputs from `SOURCES.md`.
- Blind search remains independent and must not use `SOURCES.md` as a shortcut.
- Global block rules still apply to blind rows, directory rows, direct seed URLs, fetched pages, extracted stream URLs, and browser-captured URLs.
- Direct seed URLs may be appended after the parallel directory/blind row discovery unless the existing architecture requires another order.

Do not perform a broad agent rewrite. Use the smallest change that preserves the existing architecture.

### 2. Add browser-capture configuration

Add minimal browser-capture fields to the existing config model and loader. Use the existing env/config patterns.

Suggested fields, adjusted to actual source conventions:

```text
CAMERA_DISCOVERY_ENABLE_BROWSER_CAPTURE=true
CAMERA_DISCOVERY_BROWSER_CAPTURE_TIMEOUT_MS=15000
CAMERA_DISCOVERY_BROWSER_CAPTURE_MIN_SCORE=3
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES=20
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_BLIND=6
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_DIRECTORY=12
CAMERA_DISCOVERY_MAX_BROWSER_CAPTURE_PAGES_PER_HOST=3
CAMERA_DISCOVERY_BROWSER_CAPTURE_SETTLE_MS=1000
CAMERA_DISCOVERY_BROWSER_CAPTURE_SCROLL=false
CAMERA_DISCOVERY_MAX_BROWSER_JSON_ENDPOINTS_PER_PAGE=10
CAMERA_DISCOVERY_MAX_BROWSER_NETWORK_EVENTS_LOGGED_PER_PAGE=50
```

Use conservative defaults that do not make normal runs explode in runtime. If the existing profile system has fast/balanced/full behavior, align defaults with the existing style without broad changes.

### 3. Split extraction into static-first plus browser escalation

Refactor the current source-row extraction path with minimal disruption:

- Static/direct extraction should remain the first path.
- Direct `.m3u8` URLs should not go through browser capture.
- Obvious image snapshot URLs should not go through browser capture unless existing logic already requires it.
- Static page/feed/JSON extraction should produce candidates exactly as before.
- After static extraction, compute page/browser signals and decide whether browser capture should run.
- If browser capture runs, merge browser-discovered candidates with static candidates and dedupe using existing dedupe behavior.

Do not remove the existing static extractors. Do not make browser capture the default for every URL.

### 4. Add generic page-signal extraction

Add a lightweight signal object or dictionary that captures generic evidence from the static response and row metadata. Prefer a private dataclass in `discovery_engine.py` unless the data must be shared outside that file.

Signals should be generic, not source-specific. Useful indicators include:

```text
source_kind == dynamic
source_kind == site
source_kind == promoted_host
source_provider == directory
source_provider == blind
HTML/app-shell structure
large or multiple script tags
script URLs
__NEXT_DATA__ / __NUXT__ / window.__INITIAL_STATE__-style page state
map/player library references such as leaflet, mapbox, openlayers, video.js, hls.js, jwplayer, clappr
MapServer / FeatureServer / ArcGIS / layer / feed / API hints
camera/webcam/CCTV/live/snapshot/map text hints
.m3u8 text hints
JSON endpoint hints
static extraction returned zero candidates
static extraction returned only low-value image assets, if that can be determined safely
pagination hints
```

Do not add hard-coded domains, agencies, states, cities, or provider-specific paths.

### 5. Add browser-capture routing decisions

Add a deterministic routing decision layer. The exact implementation can be a private dataclass or dictionary, but every decision must be logged.

Each decision should include at least:

```text
url
source_provider
source_kind
source_name/title if present
selected true/false
score or priority
reasons
skip_reason, if skipped
static_candidate_count
budget_remaining or budget status
host
phase, such as primary or promoted_asset_hosts
```

Selection rules must be conservative:

Run browser capture when multiple generic signals indicate a dynamic camera page, for example:

```text
row is explicitly dynamic
static extraction found zero candidates and page has camera/map/player/API signals
row came from user-approved directory source and looks like a site/page/app shell
blind result has strong camera intent and JS/map/player/API signals
promoted asset host page has camera/media/feed/path signals
```

Skip browser capture when:

```text
browser capture is disabled
URL is blocked
URL is direct .m3u8
candidate budgets are full
host browser-capture budget is exhausted
provider browser-capture budget is exhausted
global browser-capture budget is exhausted
static extraction already produced enough useful candidates and there are no strong dynamic signals
row is a feed/direct endpoint already handled statically
routing score is below threshold
```

### 6. Apply routing to both blind search and directory search

The browser-capture decision must be applied to rows from:

```text
source_provider == blind
source_provider == directory
source_provider == direct, when not direct_hls and generic signals justify it
source_provider == asset_host_promotion
```

Directory rows may receive higher priority than blind rows because they come from user-approved `SOURCES.md`, but they must still be budgeted and logged.

Blind rows should be lower-budget and opportunistic. Do not allow blind search to consume the entire browser budget before directory rows are processed in `both` mode.

### 7. Improve browser capture output using the existing Playwright dependency

Use the existing Playwright optional dependency unless the repository already has a browser backend abstraction. Do not add CloakBrowser in this task unless it already exists in the repository and can be used without expanding scope.

Enhance the current browser capture minimally to collect:

```text
request URLs
response URLs
response content types
captured .m3u8 URLs
captured JSON/API/feed/map/layer URLs
rendered HTML after JS execution, if available
limited sample of network events for logging
elapsed time and timeout/error status
```

After rendering, run existing extraction logic against:

```text
captured HLS URLs
captured JSON/API/feed/map/layer endpoints
rendered HTML
rendered DOM image/media URLs when available
```

Keep actions conservative:

```text
navigate to page
wait for DOM/content/network according to current Playwright behavior
short settle delay if configured
optional single generic scroll only if configured
collect network and rendered DOM
close browser reliably
```

Do not add source-specific clicks, login behavior, CAPTCHA handling, form submission, or scraping tricks.

### 8. Add throttling and host cooldown

Browser capture must be bounded by:

```text
global max browser pages per run
max browser pages for blind rows
max browser pages for directory rows
max browser pages per host
timeout per page
max JSON/API endpoints fetched per browser-rendered page
max network events logged per page
candidate budget stop conditions
```

Track host-level failures during the run. If a host repeatedly fails due to timeouts, navigation errors, 401/403, DNS/connect errors, or browser errors, skip additional browser captures for that host and log the reason.

### 9. Add logs and summary artifacts

Add or update logs under the existing run `logs/` directory. Required artifacts:

```text
logs/browser_capture_decisions.jsonl
logs/browser_capture_results.jsonl
logs/browser_capture_errors.jsonl
logs/browser_capture_summary.json
logs/page_discovery_signals.jsonl
```

If an existing `playwright_network_capture_errors.jsonl` artifact is kept for backwards compatibility, also write the new generic `browser_capture_errors.jsonl`.

Each browser-discovered candidate should preserve metadata:

```text
discovery_method: browser_network_capture | browser_rendered_html | browser_json_endpoint, as appropriate
source_provider
source_kind
source_name
browser_capture_url
browser_capture_reason or browser_capture_reasons
browser_backend: playwright
media_type: hls | image_snapshot
```

Update existing candidate discovery/run summary artifacts to include browser-capture metrics when present. Do not break existing summary consumers.

### 10. Add progress events for Colab visibility

Emit machine-readable progress events through the existing progress callback/event system. Add only the events necessary for visibility.

Suggested events:

```text
browser_capture_planning_started
browser_capture_decision
browser_capture_started
browser_capture_page_complete
browser_capture_budget_exhausted
browser_capture_complete
source_discovery_parallel_started
source_discovery_parallel_complete
```

Payloads should include counts and useful fields, but avoid dumping huge HTML/network data into stdout.

### 11. Notebook updates

Update `notebooks/camera_discovery_live_test.ipynb` only as needed.

Required notebook changes:

- Keep installing the package with the Playwright extra unless the verified source requires a different extra.
- Keep installing Chromium for Playwright.
- Add or expose environment settings for browser capture using existing notebook style.
- Display whether browser capture is enabled and what the budgets are.
- Update the progress display to recognize the new browser-capture progress events if the notebook currently has event-specific rendering.
- Add the new browser-capture logs to the artifact existence/report cell.
- Add a concise browser-capture summary display if `logs/browser_capture_summary.json` exists.

Notebook restrictions:

- Do not patch source code from notebook cells.
- Do not move notebook display helpers into source code.
- Do not add fake/synthetic camera data to the notebook.
- Do not make the notebook dependent on a specific real-world test location.
- Do not remove existing user-editable settings for fast/balanced/full/query/output controls.

---

## Tests and Validation

### Required local checks

Run appropriate local checks after implementation, adjusted to the repository's actual tooling:

```bash
python -m compileall src tests
python -m pytest
```

If the full test suite cannot run in the environment, run the most relevant subset and clearly document exactly what passed and what could not be run.

### Required test coverage

Add/update tests for real source behavior and pure logic only. Do not create fake runtime discovery success.

Cover at least:

1. Browser capture is skipped when disabled.
2. Direct HLS URLs are not routed to browser capture.
3. Explicit `dynamic` rows are routed to browser capture when enabled and budget allows.
4. Directory rows receive browser-capture consideration.
5. Blind rows receive browser-capture consideration when generic dynamic/page signals justify it.
6. Browser budgets prevent unbounded capture.
7. Per-host budgets/cooldown prevent repeated failures.
8. Browser-capture decisions are logged.
9. Browser-capture candidate metadata includes source provider, source kind, browser backend, and capture URL.
10. In `both` mode, directory row discovery and blind search row discovery are parallelized or confirmed already parallel.
11. Config/env alignment tests include the new browser-capture fields.
12. Notebook JSON remains valid after updates.

### Real-world validation expectation

Do not claim real-world validation unless you actually run the Google Colab notebook against real public web sources. If you cannot run Colab from the current environment, state that live validation is pending and provide exact notebook steps/settings to run.

The Colab validation should compare browser capture disabled vs enabled for at least:

```text
blind-only
directory-only
both
```

Metrics to review from real runs:

```text
source rows considered
browser rows selected
browser pages attempted
browser HLS candidates found
browser image snapshot candidates found
static candidates found
unique candidates after dedupe
runtime increase
browser timeouts/errors
trusted GeoJSON count
untrusted/review GeoJSON count
```

---

## Acceptance Criteria

The task is complete only when all of the following are true:

1. Browser capture can be enabled/disabled via config/env.
2. Static extraction still runs first and remains functional.
3. Browser capture is no longer limited to `source_kind == "dynamic"`.
4. Browser routing applies to both blind search and `SOURCES.md` directory rows.
5. SearchAgent/blind search and DirectoryAgent/`SOURCES.md` row discovery run in parallel in `both` mode, or the implementation clearly verifies that they already did.
6. Browser capture is bounded by global, provider, and host budgets.
7. Browser capture does not run on every URL.
8. Browser-capture decisions, results, errors, and summary metrics are written to logs.
9. Browser-discovered candidates preserve provenance and browser-capture metadata.
10. Existing global block policy still applies to all source rows and extracted/captured URLs.
11. No hard-coded real-world source, agency, location, or domain behavior is added.
12. No synthetic camera data, fake streams, fake GeoJSON, fake validation, or simulated runtime success is added.
13. The notebook remains Colab-friendly and source-independent.
14. Local tests/compile checks pass, or any failures are documented with exact causes.
15. The final response summarizes changed files, validation commands run, and any live-Colab validation steps still required.

---

## Implementation Notes / Hints

- Prefer adding small private helpers in `discovery_engine.py` over creating a new subpackage.
- Prefer a simple `BrowserCaptureBudget` or equivalent in-memory run state over a large framework.
- Keep `write_jsonl()` and `write_json()` usage consistent with existing log artifacts.
- Preserve existing `playwright_network_capture_errors.jsonl` if tests or notebook cells already expect it, but add the new generic browser-capture logs.
- Be careful with thread safety when logging from parallel row extraction. If existing `write_jsonl(..., append=True)` is not safe under current usage, collect per-row results and write from the parent thread, or use a minimal lock local to `CandidateDiscoveryEngine`.
- If current extraction already uses a thread pool for source rows, avoid nested thread explosions. Browser capture should respect low concurrency/budgets.
- Do not broaden blind search query terms as part of this task unless necessary for browser-capture routing. This task is about routing/extraction/logging/validation visibility, not search-query expansion.
- Do not add source-specific browser actions.

---

## Final Response Required from Codex

When finished, report:

1. Files changed.
2. What was verified before editing.
3. Whether SearchAgent and DirectoryAgent row discovery were already parallel; if not, what changed.
4. New configuration fields and defaults.
5. New log artifacts.
6. Tests/checks run and exact results.
7. Any limitations or live Colab validation still required.
