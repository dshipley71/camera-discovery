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
    camera_discovery_live_test.ipynb # Live test/review notebook
  src/camera_discovery/
    cli.py                          # Thin Typer CLI orchestration
    core/
      config.py                     # Environment/CLI-to-RunConfig loading
      models.py                     # Dataclass contracts and trust enums
      progress_events.py            # Progress event names
    llm/
      base.py                       # LLM protocol and chat message contract
      factory.py                    # Shared provider/stage factory
      ollama.py                     # Ollama and Ollama Cloud-compatible /api/chat client
      openai_compatible.py          # OpenAI-compatible /v1/chat/completions client
      bedrock.py                    # AWS Bedrock Converse client
    services/
      target_resolver.py            # Multi-target intent, geocoding, deterministic geometry trust
      discovery_engine.py           # Source rows, extraction, browser capture, metadata, scope gates
      review_validation_pipeline.py # Validation, trusted/review artifacts, maps, package
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

The CLI should remain thin. Business logic belongs in the three service modules. `RunState` is the canonical run snapshot, and output artifacts are projections of the service state.

Generated caches such as `__pycache__/` and `.pytest_cache/` are not required source artifacts and should not be committed in normal development.

### Harvest handoff modules

- `src/camera_discovery/services/structured_camera_records.py` — generic, source-agnostic extraction of structured camera records and grouped media assets from public JSON/API/GeoJSON/ArcGIS-style data.
- `src/camera_discovery/services/harvest_handoff.py` — loads `harvest_handoff.json` or `harvest_camera_inventory.jsonl` and converts source-provided harvest rows into normal `CameraCandidate` objects for `camera-discovery run --harvest-input`.
