# Repository Layout

```text
camera-discovery/
  AGENTS.md                         # Coding-agent guardrails and source-aligned build rules
  Makefile                          # Convenience test/validation commands
  README.md                         # Main user/developer documentation
  REPOSITORY_LAYOUT.md              # This file
  SOURCES.md                        # Optional runtime source registry, empty by default
  SOURCES.example.md                # Example source registry schema
  architecture.svg / architecture.png
  camera-discovery-overview.md      # Architecture overview copy of the main docs
  docs/
    README.md
    acceptance.md
    output_artifacts.md
    project_structure.md
    runtime_configuration.md
    sources_blueprint.md
    codex_prompt_*.md               # Historical implementation prompts, retained as references
  agents/
    *.md                            # Coding-agent responsibility docs
    implementation_notes/*.md       # Lower-level implementation notes
  notebooks/
    camera_discovery_live_test.ipynb
    camera_discovery_harvest_urls_test.ipynb
  src/camera_discovery/
    cli.py                          # Thin Typer command declarations
    cli_commands/
      progress.py                   # Rich/plain/event progress callback construction
      output.py                     # CLI-friendly message formatting
    core/
      config.py                     # Environment/CLI-to-RunConfig/HarvestConfig loading
      models.py                     # Dataclass contracts, trust enums, harvest/run state models
      progress_events.py            # Progress event names/emission helper
    discovery/
      source_rows.py                # Directory/direct/source-row construction and row dedupe
    enrichment/
      location.py                   # Candidate location evidence and coordinate sanity helpers
    extraction/
      browser.py                    # Browser capture dataclasses and Playwright/CloakBrowser helpers
      html.py                       # Static HTML/media/metadata parsing helpers
      http.py                       # Shared HTTP retry helper
      json_records.py               # Generic JSON/GeoJSON/ArcGIS camera record extraction helpers
      media.py                      # Media URL classification, HLS/image/non-camera checks, dedupe
      pagination.py                 # Pagination, structured endpoint, and asset-host expansion helpers
    harvest/
      json_records.py               # Harvest JSON payload parsing and metadata helpers
      media_filter.py               # Harvest media filters and image-asset filtering
      outputs.py                    # Harvest URL/CSV/JSONL/summary writers
      records.py                    # Harvest record conversion, merge, dedupe, query helpers
    llm/
      base.py                       # LLM protocol and chat message contract
      factory.py                    # Shared provider/stage factory
      ollama.py                     # Ollama and Ollama Cloud-compatible /api/chat client
      openai_compatible.py          # OpenAI-compatible /v1/chat/completions client
      bedrock.py                    # AWS Bedrock Converse client
    runners/
      discovery_run.py              # Full target-aware run workflow used by the CLI
      harvest_run.py                # Extraction-only harvest workflow used by the CLI
    services/
      target_resolver.py            # Multi-target intent, geocoding, deterministic geometry trust
      discovery_engine.py           # CandidateDiscoveryEngine orchestration/public compatibility module
      harvest_engine.py             # CameraUrlHarvestEngine orchestration/public compatibility module
      harvest_handoff.py            # Harvest handoff/inventory loader for run --harvest-input
      structured_camera_records.py  # Source-provided structured camera record extraction/inventory rows
      review_validation_pipeline.py # Validation, trusted/review artifacts, maps, review package
    sources/
      models.py                     # SourceEntry, BlockedSource, SourcePolicy
      registry.py                   # SOURCES.md parser
    utils/
      geojson_viewer.py             # GeoJSON selection, table flattening, embedded Leaflet map
      io.py                         # JSON/JSONL writers
      json_utils.py                 # Robust JSON extraction helpers
  tests/
    test_*.py                       # Contract and regression tests
```

The CLI should remain thin. Command bodies parse arguments, load configuration, create progress callbacks, delegate to `runners/`, and format user-facing summaries. Workflow/business logic belongs in the runners and services. Low-level reusable parsing/extraction logic belongs in the focused `extraction/`, `discovery/`, `harvest/`, and `enrichment/` modules rather than in `cli.py` or monolithic service files.

`RunState` is the canonical target-aware run snapshot, and output artifacts are projections of the service state. Harvest output remains source-provided, extraction-only data until consumed by the normal `run --harvest-input` workflow.

Generated caches such as `__pycache__/` and `.pytest_cache/` are not required source artifacts and should not be committed in normal development.

## Public compatibility modules

- `src/camera_discovery/services/discovery_engine.py` — keeps `CandidateDiscoveryEngine` importable from the historical path while delegating HTTP, HTML, media, JSON, pagination, browser, source-row, and location helper work to focused modules.
- `src/camera_discovery/services/harvest_engine.py` — keeps `CameraUrlHarvestEngine` importable from the historical path while delegating media filtering, JSON parsing, record conversion, and output writing to `harvest/` and shared extraction helpers.
- `src/camera_discovery/services/structured_camera_records.py` — generic, source-agnostic extraction of structured camera records and grouped media assets from public JSON/API/GeoJSON/ArcGIS-style data.
- `src/camera_discovery/services/harvest_handoff.py` — loads `harvest_handoff.json` or `harvest_camera_inventory.jsonl` and converts source-provided harvest rows into normal `CameraCandidate` objects for `camera-discovery run --harvest-input`.
