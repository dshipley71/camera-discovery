# Project Structure

The runnable application lives under `src/camera_discovery/` and is organized around thin command entry points, reusable extraction/harvest helpers, service orchestrators, and shared contracts.

```text
src/camera_discovery/
  cli.py
  cli_commands/
    progress.py
    output.py
  core/
    config.py
    models.py
    progress_events.py
  discovery/
    artifact_writer.py
    browser_capture.py
    candidate_extraction.py
    candidate_processing.py
    search_dispatch.py
    source_rows.py
  enrichment/
    location.py
  extraction/
    browser.py
    html.py
    http.py
    json_records.py
    media.py
    pagination.py
  harvest/
    json_records.py
    media_filter.py
    outputs.py
    records.py
  llm/
    base.py
    factory.py
    ollama.py
    openai_compatible.py
    bedrock.py
  runners/
    discovery_run.py
    harvest_run.py
  services/
    discovery_engine.py
    harvest_engine.py
    harvest_handoff.py
    structured_camera_records.py
    target_resolver.py
    review_validation_pipeline.py
  sources/
    models.py
    registry.py
  utils/
    geojson_viewer.py
    io.py
    json_utils.py
```

## Responsibilities

| Module | Responsibility |
|---|---|
| `cli.py` | Thin Typer app/command declarations. It parses CLI options, loads config, delegates workflow execution to runners, and prints user-facing summaries/errors. |
| `cli_commands/progress.py` | CLI progress callback construction for rich/plain/event progress modes. |
| `cli_commands/output.py` | Console summary formatting for CLI commands. |
| `core/config.py` | Loads environment variables and CLI parameters into `RunConfig` / `HarvestConfig`. Defines defaults for provider/model stages, candidate budgets, browser capture, geocoding, and profile selection. |
| `core/models.py` | Dataclass contracts for run config, targets, candidates, validation summaries, harvest records, output summaries, and run state. `CandidateSet.merge()` defines the canonical first-seen dedupe contract using `(stream_url without fragment, target_id)` so same-stream candidates remain separate across targets while duplicate candidates for the same target retain the earliest candidate without silently merging later enrichment. |
| `discovery/artifact_writer.py` | Discovery candidate artifact and per-target summary writing helpers used by `CandidateDiscoveryEngine`. |
| `discovery/browser_capture.py` | Browser preflight, routing, budget accounting, Playwright/CloakBrowser session handling, and dynamic-page extraction helpers. |
| `discovery/candidate_extraction.py` | Static page, linked endpoint, text, HTML, and structured JSON candidate extraction helpers. |
| `discovery/candidate_processing.py` | Candidate metadata normalization, dedupe, coordinate enrichment, deterministic scoping, and advisory LLM review helpers. |
| `discovery/search_dispatch.py` | Blind/directory/direct source-row dispatch, DuckDuckGo parsing, row filtering, and promoted asset-host row helpers. |
| `discovery/source_rows.py` | Directory/direct/source-row construction, target-aware site row expansion, target/category slug helpers, and row deduplication. |
| `enrichment/location.py` | Deterministic coordinate sanity helpers shared by extraction and discovery flows. |
| `extraction/http.py` | Shared HTTP retry helper. |
| `extraction/html.py` | Static HTML parsing and metadata extraction helpers. |
| `extraction/media.py` | Shared media URL classification, URL deduplication, HLS/image/non-camera-asset checks, and scalar coercion helpers. |
| `extraction/json_records.py` | Generic JSON/GeoJSON/ArcGIS-style record walking and camera candidate extraction helpers. |
| `extraction/pagination.py` | Pagination row expansion, structured endpoint expansion, and promoted asset-host URL generation. |
| `extraction/browser.py` | Browser capture dataclasses and Playwright/CloakBrowser capture helpers. Playwright remains the default backend; CloakBrowser remains opt-in through existing config/environment paths. |
| `harvest/media_filter.py` | Harvest media filter parsing, URL classification, record filtering, camera-record grouping, and summary metric helpers. |
| `harvest/json_records.py` | Harvest JSON payload parsing, metadata extraction, and JSON record counting helpers. |
| `harvest/records.py` | Harvest URL/media/candidate/structured-record conversion helpers. |
| `harvest/outputs.py` | Harvest URL, CSV, JSONL, inventory, endpoint, and summary artifact writing helpers. |
| `llm/factory.py` | Shared provider factory for target intent, geocoder referee, candidate location inference, and candidate semantic review. |
| `runners/discovery_run.py` | Full discovery workflow runner used by the CLI. It resolves targets, runs discovery, invokes validation/output writing, and creates `logs/run_summary.json`. |
| `runners/harvest_run.py` | Harvest workflow runner used by the CLI. |
| `services/target_resolver.py` | Multi-target LLM intent extraction, deterministic geocoder scoring, advisory geocoder referee, verified bbox/trust-policy assignment, and target diagnostics. |
| `services/discovery_engine.py` | Public compatibility/orchestration module for `CandidateDiscoveryEngine`. It keeps the historical import path while delegating stage implementation to `discovery/`, `extraction/`, and `enrichment/` modules. |
| `services/harvest_engine.py` | Public compatibility module for `CameraUrlHarvestEngine`. The engine now focuses on harvest orchestration and delegates media filtering, JSON parsing, record conversion, and output writing to focused modules. |
| `services/structured_camera_records.py` | Source-provided structured camera record extraction and inventory conversion. |
| `services/harvest_handoff.py` | Loads harvest handoff manifests or inventory JSONL and converts source-provided rows into normal `CameraCandidate` seed/enrichment records for `run --harvest-input`. |
| `services/review_validation_pipeline.py` | HLS/image validation, trusted vs review-only output decisions, GeoJSON/CSV/Markdown/map writing, run explanation, and review zip packaging. |
| `sources/registry.py` | Parses `SOURCES.md` allowed and blocked tables. |
| `utils/geojson_viewer.py` | Selects/merges GeoJSON outputs, flattens camera rows, and writes the embedded Leaflet map. |

Notebook-specific display code belongs in notebooks, not in `src/`.

## Candidate merge contract

`CandidateSet.merge()` is the canonical cross-target/per-target candidate-set merge helper. It deduplicates unique candidates by `(stream_url without URL fragment, target_id)`. This means:

- the same stream URL discovered for different `target_id` values is preserved once per target;
- duplicate candidates for the same stream and same target retain the first-seen candidate in deterministic input order;
- later duplicates do not silently override coordinates, validation status, source metadata, reasons, or target provenance;
- any future quality-priority or enrichment-aware merge behavior must be implemented as an explicit strategy and covered by contract tests.
