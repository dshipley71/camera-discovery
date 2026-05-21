# Project Structure

The runnable application lives under `src/camera_discovery/` and is organized around three services plus shared contracts.

```text
src/camera_discovery/
  cli.py
  core/
    config.py
    models.py
    progress_events.py
  llm/
    base.py
    factory.py
    ollama.py
    openai_compatible.py
    bedrock.py
  services/
    target_resolver.py
    discovery_engine.py
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
| `cli.py` | Thin Typer command that loads `RunConfig`, resolves targets, runs discovery per runnable target, validates/writes outputs, and writes `logs/run_summary.json`. |
| `core/config.py` | Loads environment variables and CLI parameters into `RunConfig`. Defines defaults for provider/model stages, candidate budgets, browser capture, geocoding, and profile selection. |
| `core/models.py` | Dataclass contracts: `RunConfig`, `TargetIntent`, `GeocoderCandidate`, `TargetContext`, `CameraCandidate`, `CandidateSet`, `ValidationSummary`, `OutputSummary`, and `RunState`. |
| `llm/factory.py` | Shared provider factory for target intent, geocoder referee, candidate location inference, and candidate semantic review. |
| `services/target_resolver.py` | Multi-target LLM intent extraction, deterministic geocoder scoring, advisory geocoder referee, verified bbox/trust-policy assignment, and target diagnostics. |
| `services/discovery_engine.py` | Blind/directory/direct row discovery, parallel `both` mode, source policy, static extraction, browser capture, JSON/GeoJSON/HTML extraction, metadata preservation, coordinate enrichment, scope gates, and LLM semantic review. |
| `services/review_validation_pipeline.py` | HLS/image validation, trusted vs review-only output decisions, GeoJSON/CSV/Markdown/map writing, run explanation, and review zip packaging. |
| `sources/registry.py` | Parses `SOURCES.md` allowed and blocked tables. |
| `utils/geojson_viewer.py` | Selects/merges GeoJSON outputs, flattens camera rows, and writes the embedded Leaflet map. |

Notebook-specific display code belongs in `notebooks/camera_discovery_live_test.ipynb`, not in `src/`.
