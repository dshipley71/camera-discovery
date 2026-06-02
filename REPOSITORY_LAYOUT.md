# Repository Layout

This file describes the implemented source tree. It is not an aspirational design document.

```text
camera-discovery/
  AGENTS.md
  README.md
  REPOSITORY_LAYOUT.md
  SOURCES.md
  SOURCES.example.md
  Makefile
  pyproject.toml
  .github/workflows/tests.yml
  docs/
  agents/
  notebooks/
  tests/
  src/camera_discovery/
```

## Source package

```text
src/camera_discovery/
  cli.py
  cli_commands/
    output.py
    progress.py
  core/
    config.py
    models.py
    progress_events.py
  runners/
    discovery_run.py
    harvest_run.py
  services/
    discovery_engine.py
    harvest_engine.py
    harvest_handoff.py
    review_validation_pipeline.py
    structured_camera_records.py
    target_resolver.py
  discovery/
    artifact_writer.py
    browser_capture.py
    candidate_extraction.py
    candidate_priority.py
    candidate_processing.py
    search_dispatch.py
    source_rows.py
  extraction/
    browser.py
    html.py
    http.py
    json_records.py
    media.py
    pagination.py
    search.py
  harvest/
    json_records.py
    media_filter.py
    outputs.py
    records.py
  enrichment/
    location.py
  sources/
    __init__.py
    models.py
    registry.py
  llm/
    base.py
    bedrock.py
    factory.py
    ollama.py
    openai_compatible.py
  utils/
    geojson_viewer.py
    io.py
    json_utils.py
```

## Responsibility boundaries

| Area | Responsibility |
|---|---|
| `cli.py` | Thin Typer command declarations, config loading, progress-mode resolution, runner delegation. |
| `cli_commands/` | Console progress and friendly output helpers. |
| `core/` | Runtime dataclasses, config/environment loading, progress-event contract. |
| `runners/` | Executable workflow entry points used by CLI and notebooks. |
| `services/` | Public long-lived service classes and compatibility/facade modules. |
| `discovery/` | Normal pipeline stage helpers: source rows, extraction dispatch, browser capture, candidate processing, candidate priority, artifact writing. |
| `extraction/` | Shared low-level HTTP/HTML/media/JSON/search/browser/pagination helpers used by discovery and harvest. |
| `harvest/` | Harvest-specific media filtering, record conversion, JSON metadata promotion, output helpers. |
| `enrichment/` | Coordinate/location evidence helpers. |
| `sources/` | `SOURCES.md` parsing and global source block policy. |
| `llm/` | Shared provider factory and provider clients. |
| `utils/` | File IO and GeoJSON/map rendering helpers. |

## Public compatibility imports

These public imports must continue to work:

```python
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
```

## Notebooks and tests

Current notebooks:

```text
notebooks/camera_discovery_live_test.ipynb
notebooks/camera_discovery_harvest_urls_test.ipynb
```

Notebook-specific helper/display code belongs in notebooks, not `src/`.

Tests live under `tests/` and cover CLI contracts, config alignment, source policy, blind search parsing, harvest media/structured records/handoff, browser backend/preflight behavior, multi-target contracts, candidate priority, output filtering, and provider configuration.


## Passive intelligence package

`src/camera_discovery/passive_intelligence/` contains deterministic passive evidence scoring, safe signature matching, HTTP metadata normalization/redaction, protocol labeling, and artifact summary helpers. This package is passive-only and is consumed by discovery, validation, playlists/dashboard, and review artifacts.
