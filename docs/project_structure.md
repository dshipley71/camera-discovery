# Project Structure

The source tree is split by workflow layer and stage responsibility.

## High-level flow

```text
camera_discovery.cli
  -> core.config.load_run_config / load_harvest_config
  -> runners.discovery_run.execute_discovery_run
       -> TargetResolver
       -> CandidateDiscoveryEngine when native discovery is enabled
       -> harvest_handoff loader when --harvest-input is used
       -> ReviewAndValidationPipeline
  -> runners.harvest_run.execute_harvest_run
       -> CameraUrlHarvestEngine
```

## Runtime modules

| Path | Responsibility |
|---|---|
| `cli.py` | Thin Typer command declarations. |
| `cli_commands/progress.py` | Rich/plain/events progress callbacks for CLI/notebook logs. |
| `cli_commands/output.py` | Friendly console error/output helpers. |
| `core/config.py` | Runtime config and environment-variable loading. |
| `core/models.py` | Dataclasses and public contracts such as `RunConfig`, `HarvestConfig`, `CameraCandidate`, `CandidateSet`. |
| `core/progress_events.py` | Small machine-readable progress event contract. |
| `runners/discovery_run.py` | Normal pipeline orchestration, including `handoff-only` versus `seed` harvest-input modes. |
| `runners/harvest_run.py` | Harvest CLI orchestration and user-facing harvest summary. |
| `services/target_resolver.py` | Target intent, geocoding, deterministic target-geometry decisions. |
| `services/discovery_engine.py` | Public `CandidateDiscoveryEngine` facade/orchestration import path. |
| `services/harvest_engine.py` | Public `CameraUrlHarvestEngine` and harvest orchestration. |
| `services/harvest_handoff.py` | Handoff manifest loading and conversion to untrusted seed candidates. |
| `services/review_validation_pipeline.py` | Validation, trusted/review output writing, run explanations, review ZIP. |
| `services/structured_camera_records.py` | Structured camera-record extraction helpers. |
| `discovery/search_dispatch.py` | Blind/directory/direct source-row discovery and dispatch. |
| `discovery/source_rows.py` | Source-row dataclass/adapters, including `SOURCES.md` directory rows. |
| `discovery/candidate_extraction.py` | Normal-run extraction from pages/endpoints/records. |
| `discovery/browser_capture.py` | Browser preflight, capture decisions, browser/network extraction diagnostics. |
| `discovery/candidate_processing.py` | Candidate metadata, coordinate enrichment, scope review, semantic review. |
| `discovery/candidate_priority.py` | Candidate ordering for validation/review/map/table budgets. |
| `discovery/artifact_writer.py` | Candidate-discovery stage artifact writing. |
| `extraction/http.py` | Shared HTTP retry helper. |
| `extraction/html.py` | Shared HTML parsing helpers. |
| `extraction/media.py` | Shared media detection, URL cleaning, canonicalization, dedupe. |
| `extraction/json_records.py` | Shared JSON/GeoJSON/ArcGIS record walking and metadata helpers. |
| `extraction/search.py` | Shared DuckDuckGo result URL cleaning and result parsing. |
| `extraction/browser.py` | Shared browser backend/session helpers. |
| `extraction/pagination.py` | Pagination and structured endpoint expansion helpers. |
| `harvest/media_filter.py` | Harvest media-type parsing/filtering and image asset evidence. |
| `harvest/records.py` | Harvest URL record creation, dedupe, search query construction. |
| `harvest/json_records.py` | Harvest-specific JSON metadata promotion. |
| `harvest/outputs.py` | Harvest output summary/source-row summary helpers. |
| `enrichment/location.py` | Coordinate and location-evidence helpers. |
| `sources/` | Source registry and global block policy. |
| `llm/` | Provider factory and provider-specific clients. |
| `utils/` | File IO and GeoJSON/map rendering. |

## Current CLI commands

```bash
camera-discovery run [OPTIONS] QUERY
camera-discovery harvest-urls [OPTIONS] QUERY
```

`run` exposes `--browser-backend playwright|cloakbrowser`. `harvest-urls` exposes `--browser-backend`, media filters, harvest budgets, browser budgets, and intermediate-record writing.

## Harvest handoff

`harvest_handoff.json` uses `schema_version: harvest-handoff/v2`. Its `handoff_default_scope` determines which artifact the pipeline loads by default:

- media-filtered harvests: `camera_urls.jsonl` / filtered media records;
- all-media harvests: structured inventory when available.

The normal pipeline always treats loaded harvest candidates as unvalidated/untrusted seed data.

## Candidate priority

`discovery/candidate_priority.py` centralizes ordering. It promotes located, in-scope, first-class media candidates for validation/review ordering while preserving trust boundaries.
