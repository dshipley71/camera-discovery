# Codex Prompt — Improve Structured Endpoint Discovery and Extraction Recall

## Objective

Update the current `camera-discovery` repository to substantially improve discovery and extraction from public structured endpoints.

The highest-value goal is to find more real public camera records and media URLs from structured data already exposed by public pages and services, including:

- JSON and GeoJSON endpoints;
- ArcGIS REST `MapServer` and `FeatureServer` services and layers;
- public API/feed/data endpoints;
- JavaScript application state and configuration;
- endpoints referenced by public HTML and explicitly linked JavaScript bundles;
- structured endpoints observed through the existing optional browser/network-capture path;
- explicitly advertised OGC API Features or WFS endpoints when present.

Improve both:

1. the normal target-aware `camera-discovery run` workflow; and
2. the extraction-only `camera-discovery harvest-urls` workflow.

Do not change the trust model. Structured endpoint evidence may improve discovery, extraction, prioritization, and explanations, but it must not independently make a candidate trusted.

All application-facing schemas, log event names, summaries, documentation, and normalized output fields must remain in English. This task does not add multilingual output or translation behavior.

The intended high-level flow is:

```text
public source row or direct seed
  -> static public page fetch
  -> deterministic endpoint discovery from explicit public evidence
  -> endpoint classification, scoring, dedupe, source-policy checks, and bounded selection
  -> metadata-driven endpoint expansion
  -> bounded endpoint fetch and structured payload parsing
  -> existing normal-run candidate extraction OR existing harvest structured-record extraction
  -> existing scope/review/validation/trust/output behavior
```

---

## Critical Behavioral and Implementation Rules

Follow these rules exactly.

### 1. Inspect before editing; the current source is authoritative

Before making changes, inspect the current repository, root `AGENTS.md`, relevant nested agent/implementation notes, tests, configuration, documentation, and actual runtime paths.

Do not assume that a file, function, class, artifact, environment variable, or behavior described in this prompt still exists unchanged. Adapt to the verified source instead of creating duplicate implementations or parallel legacy paths.

In the final response, state what was verified before editing and identify any prompt requirement that had to be adapted to the current source.

### 2. Think before coding

Before implementation:

- identify the current normal-run structured-endpoint path;
- identify the current harvest structured-endpoint path;
- identify shared helpers and duplicated behavior;
- identify current endpoint budgets and artifact contracts;
- identify the smallest safe architecture change that improves both workflows;
- surface conflicts and tradeoffs instead of silently choosing an interpretation.

If uncertainty cannot be resolved from repository evidence, preserve existing behavior and report the uncertainty. Do not invent behavior.

### 3. Simplicity first and surgical changes

Implement the minimum cohesive source change that solves the problem.

Keep the current architecture intact:

- thin CLI commands;
- orchestration in runners/services;
- shared HTTP/HTML/endpoint/JSON helpers under `extraction/`;
- discovery-specific candidate behavior under `discovery/`;
- harvest-specific output behavior under `harvest/` and the harvest service;
- deterministic trust and output authority in the existing review/validation pipeline.

Do not collapse the repository into god files. Do not perform an unrelated broad refactor.

### 4. No stubs, placeholders, or incomplete implementations

Do not add:

- stub functions;
- placeholder implementations;
- `TODO`-only behavior;
- mock production paths;
- simulated endpoint discovery;
- code that claims support without implementing and testing it.

Every added production path must be functional, integrated, bounded, logged, and tested.

### 5. No fake runtime evidence

Do not create fake camera records, fake streams, fake coordinates, fake structured endpoints, fake validation results, fake GeoJSON, fake browser success, fake discovery summaries, or synthetic runtime inventories.

Unit tests may use small local fixtures and monkeypatches to verify deterministic parsing, routing, budgets, and contracts. Do not present fixture results as real-world discovery success.

### 6. No source-specific hacks or hard-coded real-world sources

Do not hard-code real agencies, cities, states, countries, source domains, endpoint URLs, real layer IDs, source-specific paths, or one-off camera schemas.

Generic support for public standards and common technical structures is allowed, including JSON, GeoJSON, ArcGIS REST metadata, OGC API Features, WFS metadata, JavaScript state, and explicit public API links.

### 7. Public-source discovery only; no active scanning or arbitrary probing

This task must not add:

- network, IP, or port scanning;
- arbitrary host/path enumeration;
- guessed API paths;
- guessed JSON filenames;
- guessed camera URLs;
- guessed ArcGIS layer IDs;
- brute-force pagination parameters;
- RTSP path probing;
- credential or login attempts;
- POST requests or other mutating requests to discovered endpoints;
- CAPTCHA handling, form submission, or source-specific browser interactions;
- Shodan, Censys, Zoomeye, FOFA, insecam, or similar internet-asset-index integrations.

Only follow endpoints that are explicitly referenced by allowed public content or explicitly advertised by public structured-service metadata. Standards-driven query URLs derived from verified public service metadata are allowed when bounded and read-only.

### 8. Preserve and enforce the global source-block policy

The existing global deny/block rules remain authoritative and must apply at every stage:

- source rows;
- direct seeds;
- fetched pages;
- explicitly linked scripts;
- discovered endpoints;
- endpoint child links;
- ArcGIS/OGC advertised layers and collections;
- browser-captured endpoint URLs;
- extracted media URLs;
- harvest records;
- normal-run candidates and final outputs.

Reuse existing public-network/private-network safeguards. Do not weaken them.

### 9. Preserve deterministic trust authority

Structured endpoint evidence may improve discovery and candidate metadata only.

It must not bypass or weaken:

- target resolution;
- verified target geometry;
- deterministic coordinate acceptance;
- scope classification;
- validation;
- trusted output authorization;
- final artifact filtering.

LLMs remain advisory only and are not required for this task.

### 10. Preserve workflow boundaries

`camera-discovery harvest-urls` remains extraction-only. It must continue to bypass target resolution, geocoding, scope filtering, validation, trust, GeoJSON/maps, and review ZIP generation.

`camera-discovery run` remains target-aware and must continue through the existing scope, review, validation, trust, and output pipeline.

Shared endpoint-discovery helpers are encouraged, but do not merge the two workflows or their output semantics.

### 11. Keep notebooks separate from source

Notebook-specific display and test orchestration belongs in notebooks, not under `src/`.

Do not create `src/camera_discovery/notebook/`. Do not duplicate structured-endpoint production logic in notebooks. Update relevant notebooks only when necessary to expose the new configuration, diagnostics, or artifact summaries.

### 12. Preserve public contracts unless explicitly extended

Preserve existing:

- CLI command names and options;
- public import paths;
- existing environment variables;
- existing artifact names and schema meanings;
- source-policy behavior;
- browser backend behavior;
- harvest handoff semantics;
- trusted/untrusted output rules.

Add fields and artifacts compatibly where practical. Do not rename or silently repurpose existing fields.

### 13. Do not weaken tests

Add or update behavior-focused tests. Do not relax assertions, remove coverage, or modify tests only to hide regressions.

### 14. English-canonical outputs

All new normalized field names, log event names, summaries, markdown documentation, and artifact descriptions must be English.

Raw source-provided text may be preserved in existing bounded raw/source metadata where current contracts allow it. Do not add translation or multilingual output logic in this task.

### 15. Clean generated caches before completion

Before final delivery, remove generated cache directories and compiled artifacts from the repository, including as applicable:

```text
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.ipynb_checkpoints/
*.pyc
*.pyo
```

Do not delete legitimate source, test fixtures, or required assets.

---

## Baseline Verification Before Editing

Before changing files, inspect and record the current relevant architecture and run the baseline checks.

At minimum, inspect the verified equivalents of:

```text
src/camera_discovery/extraction/endpoints.py
src/camera_discovery/extraction/pagination.py
src/camera_discovery/extraction/json_records.py
src/camera_discovery/services/structured_camera_records.py
src/camera_discovery/discovery/candidate_extraction.py
src/camera_discovery/discovery/browser_capture.py
src/camera_discovery/services/discovery_engine.py
src/camera_discovery/services/harvest_engine.py
src/camera_discovery/core/models.py
src/camera_discovery/core/config.py
```

Also inspect relevant tests, agents, and docs.

Verify whether the current source still:

- has separate normal-run and harvest loops for linked structured endpoints;
- extracts endpoint literals from HTML/JavaScript using `extract_endpoint_urls_from_text` or an equivalent;
- expands structured endpoints using `_expand_structured_endpoint_urls` or an equivalent;
- guesses ArcGIS layer IDs such as a fixed numeric range;
- requires URL hints such as `.json`, `/api/`, `/feed`, `MapServer`, or `FeatureServer` before selecting linked endpoints;
- limits endpoint discovery with `max_structured_endpoints_per_page`;
- feeds browser-captured JSON/API URLs through a separate fetch/extraction path;
- writes current normal and harvest structured-endpoint logs and harvest `discovered_endpoints.jsonl`.

Run before editing:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

If the full suite cannot run because of an environment or optional dependency, run the relevant targeted tests and report the exact limitation. Do not claim success for checks that did not run.

---

## Current Problem to Solve

The current application already recognizes some JSON, GeoJSON, ArcGIS, API, and JavaScript-state content. However, structured endpoint recall is limited when endpoints:

- do not use a `.json` suffix;
- are referenced inside JavaScript configuration or bounded script bundles;
- are returned through browser/network capture but do not match narrow URL hints;
- are service roots that require metadata-driven layer or collection discovery;
- expose records through explicit next links, transfer-limit metadata, or advertised collection links;
- use structured payloads without nearby English camera words;
- are duplicated across normal-run and harvest implementations with inconsistent behavior;
- are lower in an unranked endpoint list and lost to the endpoint budget.

If the verified source still generates fixed ArcGIS layer IDs, that behavior is both low-recall and unnecessarily probe-like. Replace it with public metadata-driven enumeration.

---

## Required Functional Changes

### 1. Create one shared structured-endpoint discovery and expansion layer

Centralize deterministic endpoint discovery, classification, scoring, canonicalization, bounded expansion, and lifecycle logging in a focused shared extraction module or cohesive package.

A likely location is under:

```text
src/camera_discovery/extraction/
```

Use the verified source conventions. Preserve compatibility wrappers for currently imported helpers when needed instead of breaking imports.

The shared layer must be reusable by both normal discovery and harvest mode. It must not itself create trusted candidates or harvest outputs.

Represent discovered endpoints with a focused internal model or dataclass. At minimum, preserve or derive:

```text
endpoint_url
canonical_endpoint_url
endpoint_type
source_page_url
parent_endpoint_url
source_provider
source_name
first_seen_method
endpoint_depth
discovery_reasons / evidence
priority_score or priority bucket
content_type, when known
status / fetch outcome
selected or skipped
skip_reason, when skipped
```

Do not require this exact class name or field layout if the current architecture supports an equivalent clean design.

### 2. Discover endpoint candidates from explicit public evidence

Improve endpoint extraction from public pages and already-collected public content.

Support bounded extraction from:

- `<a href>`, `<link href>`, `<script src>`, `<iframe src>`, and relevant generic `data-*` URL attributes;
- inline JavaScript string literals used by `fetch`, `axios`, `XMLHttpRequest`, jQuery AJAX, or equivalent existing patterns;
- generic object/config properties such as `url`, `endpoint`, `apiUrl`, `dataUrl`, `feedUrl`, `serviceUrl`, `layerUrl`, and `queryUrl` when the value is an explicit URL or deterministic relative URL;
- `<script type="application/json">` and similar embedded JSON blocks;
- common application-state containers already supported by the application, such as Next/Nuxt/initial-state payloads;
- structured response bodies that explicitly advertise related links, child endpoints, collections, layers, or next pages;
- endpoints observed through the existing browser/network-capture path;
- bounded, explicitly linked JavaScript bundles when page signals indicate a map/app/camera page and static endpoint extraction is incomplete.

Handle deterministic URL forms safely:

- absolute HTTP(S) URLs;
- scheme-relative URLs;
- relative URLs resolved against the containing page or endpoint;
- escaped slash forms such as `\/` and `\u002F`;
- HTML entities;
- simple concatenation of literal strings only when it can be resolved without executing code.

Do not execute JavaScript, use `eval`, interpret arbitrary expressions, or recursively crawl script imports.

### 3. Use structural signals, not English camera words alone

Do not require nearby English words such as `camera`, `cameras`, or `feed` before parsing embedded structured data.

Use deterministic structural evidence such as:

- GeoJSON `FeatureCollection` / `Feature` structures;
- ArcGIS `features`, `attributes`, `geometry`, `layers`, or `tables` structures;
- arrays or objects containing coordinate-like fields plus media-like URL fields;
- repeated records with media URLs;
- map-marker arrays;
- explicit public endpoint links;
- response content type and body shape.

English camera terms may remain useful supporting evidence, but they must not be the only gate.

### 4. Classify and prioritize endpoint candidates deterministically

Add deterministic endpoint classification and priority so strong structured endpoints consume budgets before weak URL hints.

Useful endpoint classes include, adjusted to verified source behavior:

```text
json
geojson
arcgis_service
arcgis_layer
arcgis_query
ogc_api_features
wfs
javascript_bundle
unknown_json_api
```

Priority should favor evidence such as:

1. browser response or HTTP response with JSON/GeoJSON content type;
2. explicit ArcGIS service/layer metadata URL;
3. explicit endpoint URL used by fetch/XHR/AJAX;
4. explicit structured links advertised by a parsed response;
5. explicit application-state endpoint/config value;
6. HTML links or script literals with strong endpoint patterns;
7. weak generic URL hints.

A weak occurrence of `camera`, `data`, or `json` alone must not outrank a verified structured response.

Endpoint priority affects fetch order only. It must not affect candidate trust.

### 5. Canonicalize and deduplicate endpoints without collapsing distinct data requests

Add or improve endpoint canonicalization so equivalent endpoint URLs are deduplicated while distinct layers, collections, or queries remain distinct.

At minimum:

- normalize scheme/host case and default ports;
- remove fragments;
- resolve relative URLs;
- remove known tracking-only parameters when safe;
- preserve query parameters that select layers, collections, filters, formats, or records;
- do not collapse different ArcGIS layer IDs, OGC collections, or meaningful query URLs into one endpoint;
- preserve endpoint ancestry and first-seen provenance after dedupe.

### 6. Replace blind ArcGIS layer guessing with metadata-driven ArcGIS discovery

If the verified source still guesses fixed ArcGIS layer IDs, remove that behavior.

Implement bounded, read-only ArcGIS REST discovery from explicit public ArcGIS URLs:

1. When a public `MapServer` or `FeatureServer` service root is explicitly discovered, request its public service metadata using the documented JSON format parameter.
2. Read advertised `layers` and `tables` from the service metadata.
3. Follow only advertised numeric layer/table IDs, subject to source policy and configured limits.
4. For an explicitly discovered layer URL, request public layer metadata when needed.
5. Construct a read-only query only when the public metadata shows that the layer supports query access or otherwise explicitly advertises a query endpoint.
6. Request geometry and fields needed by the existing structured-record extractors.
7. Preserve service URL, layer URL, query URL, layer name, layer ID, and endpoint ancestry in provenance.

Do not enumerate unadvertised layer IDs. Do not probe arbitrary ArcGIS services or paths.

Implement bounded ArcGIS record paging using public response/service metadata where available, such as:

- advertised `maxRecordCount`;
- `exceededTransferLimit`;
- advertised object ID fields / object IDs;
- supported result offsets/counts;
- explicit next links or equivalent documented metadata.

Do not guess pagination blindly. Stop when configured budgets are reached, no new records are returned, the service says there are no more records, or the endpoint fails.

Preserve spatial-reference metadata. Do not interpret projected coordinates as WGS84 latitude/longitude unless the source explicitly identifies a supported CRS and deterministic conversion is correctly implemented and tested. Never invent coordinates.

### 7. Improve generic JSON, GeoJSON, and public API handling

Recognize JSON/GeoJSON responses by content type and body structure even when the URL has no `.json` suffix or obvious API path.

Support common safe wrapper forms only when they can be unwrapped deterministically without executing code, such as a bounded JSONP-style wrapper around valid JSON.

For parsed structured responses:

- reuse the existing normal-run JSON candidate extraction path;
- reuse the existing harvest structured-camera-record/media-asset path;
- discover explicitly advertised child endpoint URLs and next links;
- follow only explicit links and bounded standards metadata;
- preserve endpoint and record provenance;
- stop on source-policy rejection, depth limit, host limit, response-size limit, endpoint/page limit, candidate/media budget, repeated payload/page, or no-new-record condition.

Do not invent `page=`, `offset=`, `start=`, cursor, or API paths unless the response explicitly advertises the next request or the verified public standard metadata provides the required paging contract.

### 8. Add bounded OGC API Features and WFS discovery when explicitly advertised

Improve international and domestic open-data recall by supporting explicitly discovered public OGC endpoints.

For OGC API Features:

- follow advertised public `links` and `collections` metadata;
- select collection item endpoints only from advertised links/IDs;
- request JSON/GeoJSON representations when explicitly supported;
- apply existing structured-record extraction to returned features.

For WFS:

- only act on an explicitly discovered WFS endpoint or advertised WFS metadata link;
- parse public capabilities metadata without executing code;
- follow only advertised feature types and public read-only feature links/requests;
- use configured limits.

Do not treat WMS tiles, basemap tiles, vector tiles, legends, or generic map images as camera records merely because they are map services.

Do not guess OGC service URLs, collection names, or feature types.

### 9. Add bounded explicitly linked JavaScript-bundle inspection

Modern public map applications often hide their API URLs inside linked JavaScript bundles. Add conservative static inspection of explicitly linked bundles.

Requirements:

- run static page extraction first;
- inspect bundles only when generic page signals indicate a map/app/camera page or static endpoint discovery produced insufficient results;
- prioritize same-origin/first-party bundles;
- allow explicitly linked cross-origin bundles only when source policy permits and budgets allow;
- enforce maximum bundles per page and maximum bytes per bundle;
- inspect text only for explicit endpoint literals/config values;
- do not execute bundle code;
- do not recursively fetch imported chunks or guess chunk URLs;
- feed discovered endpoints into the same shared endpoint pipeline;
- log selected, skipped, failed, oversized, and blocked bundles.

### 10. Route browser-captured endpoints through the shared structured-endpoint pipeline

The optional browser/network-capture path already observes request/response URLs. Route structured endpoint URLs captured there through the same shared classification, dedupe, expansion, source-policy, fetch, parsing, and logging behavior used for static discovery.

Do not maintain a separate lower-quality browser JSON fetch loop if it can be safely replaced by the shared path.

Preserve browser-capture budgets, optional dependency preflight, backend selection, and error behavior. Do not fake browser success.

### 11. Integrate consistently with both normal discovery and harvest

Normal discovery and harvest must use the shared endpoint discovery/expansion behavior.

For normal discovery:

- structured endpoints produce normal `CameraCandidate` objects through the existing extraction path;
- candidate metadata preserves source page and endpoint provenance;
- candidates continue through existing dedupe, coordinate/scope handling, review, validation, trust, and output rules.

For harvest:

- structured endpoints produce existing harvested URL records, structured camera records, media assets, and endpoint catalog records;
- harvest remains extraction-only;
- `discovered_endpoints.jsonl` remains compatible and gains useful provenance/summary fields where practical.

Do not unnecessarily rewrite the normal-run JSON record parser or harvest structured-record parser. Reuse and improve them only where required for endpoint recall and consistent provenance.

### 12. Apply strict budgets and stop conditions

Structured endpoint discovery must be bounded independently from final candidate/media limits.

Reuse existing configuration where appropriate, including the verified equivalent of:

```text
max_structured_endpoints_per_page
max_browser_json_endpoints_per_page
max_pages / max_pages_per_source
HTTP timeout
candidate/media limits
```

Add only the minimum necessary source-aligned configuration. Suggested capabilities, adapted to existing conventions:

```text
max_structured_endpoint_depth
max_structured_endpoints_per_host
max_structured_endpoint_response_bytes
max_structured_endpoint_pages_per_endpoint
max_structured_records_per_endpoint
max_arcgis_layers_per_service
max_script_bundles_per_page
max_script_bundle_bytes
```

Use conservative normal-run defaults and larger but still bounded harvest defaults consistent with existing configuration patterns.

Requirements:

- all limits must be deterministic and logged;
- no unlimited endpoint recursion;
- no host may consume the entire endpoint budget;
- repeated failures should trigger bounded host/endpoint cooldown or skip behavior using existing patterns where possible;
- endpoint fetching must stop when relevant candidate/media budgets are full;
- do not add arbitrary sleeps that make normal runs unusable.

### 13. Preserve complete provenance on extracted candidates and records

Where current schemas allow, preserve useful structured-endpoint provenance on normal candidates and harvest records/assets:

```text
source_page_url
source_endpoint_url
structured_endpoint_type
endpoint_discovery_method
endpoint_parent_url
endpoint_depth
endpoint_layer_id / collection_id, when source-provided
endpoint_layer_name / collection_name, when source-provided
endpoint_content_type
json_record_path / field_path
```

Use English canonical field names. Do not store unbounded payloads or secrets.

### 14. Improve structured-endpoint diagnostics and summaries

Preserve existing artifact names and enrich them compatibly.

At minimum, normal discovery must continue writing the verified equivalent of:

```text
logs/structured_endpoint_discovery.jsonl
logs/json_endpoint_records.jsonl
logs/json_endpoint_extraction_errors.jsonl
```

Harvest must continue writing the verified equivalent of:

```text
logs/harvest_structured_endpoint_discovery.jsonl
discovered_endpoints.jsonl
logs/endpoint_catalog_summary.json
```

Add or extend structured-endpoint summary output so analysts can determine:

```text
endpoint candidates discovered
endpoints selected
endpoints skipped by reason
endpoints blocked by source policy
endpoints fetched
endpoints parsed
endpoint fetch/parse errors
endpoints by type
endpoints by discovery method
endpoints by source provider
ArcGIS services/layers advertised and selected
OGC collections/feature types advertised and selected
explicit next pages followed
script bundles selected/skipped
records considered
camera records extracted
media assets/candidates extracted
endpoints producing zero camera/media records
limits/budgets reached
```

Each endpoint lifecycle log row should include enough English-canonical context to explain:

- where the endpoint came from;
- why it was selected or skipped;
- what was fetched;
- what was parsed;
- what records/candidates it produced;
- why processing stopped.

Do not log secrets, full unbounded payloads, or sensitive headers.

### 15. Add progress events without noisy per-record console spam

Use the existing progress callback/event system for meaningful structured-endpoint stages.

Add only useful events, adapted to current conventions, such as:

```text
structured_endpoint_discovery_started
structured_endpoint_candidates_selected
structured_endpoint_fetch_started
structured_endpoint_parsed
structured_endpoint_expanded
structured_endpoint_budget_exhausted
structured_endpoint_discovery_complete
```

Progress events and user-facing messages must be in English. Avoid printing one console line for every individual record in large endpoints.

### 16. Keep structured endpoint evidence advisory for priority only

Structured endpoints with strong deterministic evidence may be processed before weak page/image candidates and may receive richer explanation metadata.

They must not automatically become trusted, in-scope, live, or validated. Existing deterministic gates remain authoritative.

---

## Configuration and Compatibility Requirements

- Preserve existing endpoint-related environment variables and CLI behavior.
- Add new configuration using current `RunConfig` / `HarvestConfig` and loader patterns only when required.
- Where harvest-specific overrides already exist, maintain that convention.
- Do not add a new required dependency unless the functionality cannot be implemented safely with current dependencies. Prefer the standard library and current HTTP/HTML/JSON stack.
- Do not require Playwright or CloakBrowser for static structured-endpoint discovery.
- Browser capture remains optional.
- Preserve current source-block behavior and current HTTP timeout configuration.
- Preserve existing public imports. Add compatibility wrappers when moving private/shared helpers would otherwise break imports or tests.

---

## Required Tests

Add focused behavior tests using local fixture payloads and monkeypatched HTTP calls. Do not use live public sites as required unit tests.

At minimum, test:

1. Explicit absolute, relative, scheme-relative, escaped, and HTML-entity endpoint URLs are normalized correctly.
2. Endpoint discovery from fetch/XHR/AJAX/config literals works without executing JavaScript.
3. Embedded JSON/application state is recognized from structural evidence even without nearby English camera words.
4. JSON content-type/body detection works when the URL lacks `.json` or `/api/`.
5. Weak endpoint hints do not outrank verified structured responses.
6. Endpoint canonicalization deduplicates equivalent URLs but preserves distinct ArcGIS layers, OGC collections, and meaningful queries.
7. Blocked, private-network, non-HTTP(S), and disallowed endpoints are never fetched or emitted.
8. Explicitly linked JavaScript bundle inspection is bounded by bundle count/size, does not execute code, and feeds endpoints into the shared pipeline.
9. Browser-captured structured endpoints use the shared endpoint path.
10. ArcGIS service metadata enumerates only advertised layers/tables.
11. No blind fixed-range ArcGIS layer-ID generation remains.
12. ArcGIS layer queries are constructed only from explicitly discovered/advertised query-capable layers.
13. ArcGIS paging follows advertised transfer-limit/object-ID/offset behavior and stops at configured limits.
14. Projected ArcGIS coordinates are not silently treated as WGS84 coordinates.
15. GeoJSON and generic JSON structured records continue to produce existing normal candidates and harvest records/assets.
16. Explicit next links are followed; guessed generic pagination is not added for structured endpoints.
17. Explicit OGC API Features/WFS metadata links are followed within limits; unadvertised collections/types are not guessed.
18. WMS/basemap/tile endpoints do not become camera candidates merely because they are map services.
19. Endpoint depth, host, response-size, page, record, and candidate/media budgets stop processing and log clear skip reasons.
20. Normal discovery and harvest use consistent endpoint selection/expansion behavior while preserving their separate output semantics.
21. Extracted candidates/records preserve endpoint provenance.
22. Structured endpoint evidence does not bypass validation, scope, trust, or source policy.
23. Existing JSON endpoint metadata, browser capture, harvest structured-record, source-policy, and output contracts remain passing.

Use synthetic objects only inside unit tests for deterministic behavior. Do not claim fixture tests prove real-world discovery success.

---

## Documentation, Agents, and Notebook Alignment

Update only the documentation and agent files affected by the implementation. At minimum, inspect and update the verified equivalents of:

```text
AGENTS.md
agents/candidate_discovery_agent.md
agents/implementation_notes/candidate_discovery_engine.md
agents/tests_agent.md
docs/output_artifacts.md
docs/project_structure.md
docs/runtime_configuration.md
docs/acceptance.md
README.md, only if user-facing behavior/configuration changes
```

Document:

- the shared structured-endpoint discovery flow;
- metadata-driven ArcGIS behavior;
- explicit-link-only OGC behavior;
- script-bundle inspection limits;
- normal-run versus harvest semantics;
- source-policy and no-probing guardrails;
- new configuration fields;
- endpoint diagnostics and summary artifacts;
- English-canonical output behavior.

Update relevant Colab notebooks only if required to expose or summarize the new endpoint configuration/logs. Do not place production extraction logic in notebooks. Preserve existing notebook settings and profiles.

Copy this completed prompt into the repository as:

```text
docs/codex_prompt_improved_structured_endpoint_discovery.md
```

The copied prompt must be standalone and must not refer to unavailable previous prompts.

---

## Explicit Non-Goals

Do not include unrelated work in this implementation:

- multilingual query planning or translation;
- broad search-query redesign;
- new camera-type taxonomy;
- new trust rules;
- new validation methods unrelated to structured endpoints;
- active vulnerability or device discovery;
- RTSP path discovery or probing;
- source-specific scraping logic;
- UI redesign;
- broad notebook rewrite;
- dependency modernization unrelated to this task.

---

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. Normal discovery and harvest use a shared, bounded structured-endpoint discovery/expansion layer.
2. Explicit public endpoint evidence from HTML, JavaScript state/config, bounded linked bundles, structured responses, and browser capture reaches the shared layer.
3. JSON/GeoJSON endpoints are recognized by response structure/content type even without obvious URL suffixes.
4. Embedded structured data no longer requires nearby English camera words when structural camera/media evidence exists.
5. ArcGIS services/layers are discovered from public metadata; fixed-range layer-ID guessing is removed.
6. Explicitly advertised ArcGIS paging is bounded and supported.
7. Explicit OGC API Features/WFS metadata can be followed within limits without guessing endpoints.
8. Source-policy checks apply before every page, bundle, endpoint, child link, layer, collection, and extracted media fetch/output.
9. No arbitrary path probing, POST requests, authentication, or active scanning is added.
10. Endpoint budgets, size limits, depth limits, host limits, and stop reasons are enforced and logged.
11. Normal candidates and harvest records preserve structured-endpoint provenance.
12. Structured endpoint evidence does not change scope, validation, trust, or final-output authority.
13. Existing public contracts and artifacts remain compatible.
14. Relevant documentation, agents, tests, and notebooks are aligned.
15. All new logs, summaries, normalized fields, and docs are English-canonical.
16. No stubs, fake runtime evidence, source-specific hacks, or synthetic production data are added.
17. Relevant checks pass, and any skipped checks are explicitly reported.
18. Generated cache directories and compiled artifacts are removed before final delivery.

---

## Suggested Targeted Verification

Run at least the verified equivalents of:

```bash
python -m compileall -q src tests

PYTHONPATH=src python -m pytest -q \
  tests/test_json_endpoint_metadata_integration.py \
  tests/test_harvest_structured_records.py \
  tests/test_multi_engine_harvest_search.py \
  tests/test_browser_capture_expansion.py \
  tests/test_source_policy.py \
  tests/test_target_and_extraction_regressions.py \
  tests/test_discovery_upgrade_contracts.py

PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/extraction src/camera_discovery/harvest
```

Add the new structured-endpoint tests to the targeted command.

If optional browser dependencies are unavailable, verify missing-dependency/preflight behavior and report that real browser execution was not run. Do not fake browser-dependent success.

---

## Final Response Required from Codex

When finished, report:

1. Files changed.
2. Current behavior and architecture verified before editing.
3. Exact structured-endpoint gaps found.
4. Summary of the shared endpoint-discovery architecture implemented.
5. How ArcGIS metadata-driven discovery and paging work.
6. How explicit JSON/GeoJSON, JavaScript state/bundles, browser-captured endpoints, and OGC endpoints are handled.
7. Configuration fields and defaults added or changed.
8. Logs, summaries, progress events, and provenance fields added or changed.
9. Public contracts and workflow boundaries preserved.
10. Documentation, agent, and notebook updates.
11. Tests/checks run with exact results.
12. Any limitations or follow-up work.
13. Confirmation that no fake/synthetic runtime evidence, source-specific hacks, arbitrary probing, active scanning, credential behavior, trust bypass, or incomplete stubs were introduced.
14. Confirmation that generated cache directories and compiled artifacts were removed.
