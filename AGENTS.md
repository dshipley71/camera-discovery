# AGENTS.md — Camera Discovery Source-Aligned Build Rules

This repository implements a public-camera discovery CLI with two deliberately separate workflows:

1. `camera-discovery run` — the normal target-aware pipeline: target resolution, discovery, coordinate/scope handling, optional validation, trusted/review artifacts, and review packaging.
2. `camera-discovery harvest-urls` — extraction-only raw camera/media URL harvesting: no target resolution, geocoding, validation, trust, scope filtering, GeoJSON/map output, `cameras.md`, or review ZIP.

The current source is organized around thin CLI commands, workflow runners, focused stage modules, and public service/facade classes. Do not collapse code back into god files. The canonical public service imports remain:

```python
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
```

## Current architecture boundaries

```text
src/camera_discovery/
  cli.py                       # Typer command declarations and config loading only
  cli_commands/                # progress renderers and console-output helpers
  core/                        # dataclasses, runtime config, progress-event contracts
  runners/                     # execute_discovery_run and execute_harvest_run
  services/                    # public workflow facades / long-lived service classes
  discovery/                   # discovery stage helpers: source rows, extraction dispatch, priority, artifacts
  extraction/                  # shared HTTP/HTML/media/JSON/search/browser/pagination helpers
  harvest/                     # harvest-specific media filters, records, JSON metadata, outputs
  enrichment/                  # coordinate/location enrichment helpers
  sources/                     # SOURCES.md registry and global block policy
  llm/                         # shared provider factory and provider adapters
  utils/                       # JSONL/GeoJSON/map helpers
```

## Behavioral rules

- Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime inventories.
- Do not hard-code real-world locations, agencies, source domains, source-specific behavior, or one-off camera types. Generic media normalization, URL canonicalization, candidate-priority scoring, and diagnostics are allowed.
- Notebook-specific helper/display code belongs in notebooks, not in `src/`.
- Keep source and notebook logic separate. Do not create `src/camera_discovery/notebook/`.
- Do not weaken tests to make a change pass.
- Existing CLI names/options, public import paths, environment variables, artifact names, schemas, and source-block semantics must remain compatible unless explicitly changed.

## LLM usage and deterministic authority

LLMs are advisory evidence interpreters/rankers only. Current advisory stages are:

1. target intent extraction and geocoder-query expansion;
2. geocoder candidate referee/ranking;
3. candidate location-name inference for later real geocoding;
4. candidate semantic review.

The candidate location-name inference stage may return place names/query variants only. It must never return coordinates.

Deterministic code/tools remain authoritative for:

1. bbox and geometry verification;
2. candidate coordinate acceptance;
3. scope classification;
4. media validation;
5. trusted output authorization;
6. final artifact writing.

## Target and multi-location rules

Users may specify one or more places/locations in a single query. Do not collapse multi-location queries into one combined target.

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive stable target metadata, target-specific diagnostics, target-specific candidate artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.

## Source providers and global block policy

`DirectorySourceProvider` is an input adapter used by the discovery workflow, not a separate orchestration layer. Its implementation lives with source-row helpers in `discovery/source_rows.py` and reads enabled allowed source URLs from `SOURCES.md`.

Allowed source rows are used only in `directory` and `both` modes. Blocked rows are global deny rules and must apply to blind search, directory rows, direct seed URLs, fetched pages/endpoints, extracted media URLs, harvest outputs, and final candidates.

`both` mode should discover blind rows and directory rows, then normalize them into the same extraction path.

## Browser capture

Browser capture is optional, budgeted, and preflighted. Playwright is the default backend. CloakBrowser is optional and may be selected with either `CAMERA_DISCOVERY_BROWSER_BACKEND=cloakbrowser` or `--browser-backend cloakbrowser` on both `run` and `harvest-urls`.

If the selected backend is unavailable, the application should emit a clear preflight diagnostic and avoid repeated page-level browser failures. Do not fake browser success.

## Harvest mode and handoff

Harvest mode is extraction-only. It bypasses target resolution, geocoding, validation, trust, scope gates, LLM review, GeoJSON/maps, `cameras.md`, and review ZIPs.

`harvest_handoff.json` currently uses `schema_version: harvest-handoff/v2`. Media-filtered harvests default to filtered media records such as `camera_urls.jsonl`; all-media harvests may default to structured inventory. Normal `run --harvest-input` then treats harvested records as untrusted seed data and applies target resolution, deterministic scope gates, validation, and trust rules.

## Candidate priority

Coordinate-bearing, deterministically in-scope candidates should be prioritized for validation budgets, candidate tables, and review/GeoJSON ordering. Coordinates alone never make a candidate trusted; existing validation, scope, and trust gates remain authoritative. Coordinate-bearing out-of-scope candidates must not be promoted above in-scope candidates.

## Provider support

Use the shared provider factory in `src/camera_discovery/llm/factory.py`. Supported provider values are:

- `ollama` and `ollama-cloud` through Ollama-compatible `/api/chat`;
- `openai-compatible`, `openai`, or `openai_compatible` through `/v1/chat/completions`;
- `bedrock` through AWS Bedrock Runtime Converse API.

Stage-specific provider/model overrides must share the common factory path. Never log secrets.

## Verification expectations

Before returning changes, run the most relevant checks. For broad source changes, run:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/llm
```

Browser dependencies are optional. Do not pretend browser-dependent behavior succeeded when the backend was missing.


## Media playlist, RTSP, dashboard, and dorking guardrails

- Playlist/TXT exports are derived convenience artifacts only. They must not promote candidates to trusted output or bypass source-policy, scope, validation, geometry, or private-network checks.
- RTSP support is limited to explicit user-supplied URLs or RTSP/RSTS URLs extracted verbatim from allowed public source content. Do not synthesize RTSP URLs, probe default/common paths, enumerate ports, infer vendors, or test credentials.
- `media_validation_dashboard.json` counts must come from actual candidate/validation state.
- Google dorking support is bounded public-source discovery only. Do not add dorks for exposed device UIs, admin pages, default credentials, vendor fingerprints, RTSP hunting, private-network hosts, or blocked internet-asset indexes.


## Passive intelligence regeneration requirement

Agent-generated implementations must include the passive intelligence layer under `src/camera_discovery/passive_intelligence/` or an equivalent cohesive package. The layer may score and label already-discovered evidence only. It must not add active scanning, host probing, RTSP brute-force path generation, credential probing, packet capture, vulnerability enrichment, or security-index integrations. Evidence score may prioritize extraction/validation/review order, but source policy, target scope, validation, and trust gates remain authoritative.
