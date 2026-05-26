# 06 — CLI Agent

Keep `camera_discovery.cli` thin. It should declare Typer commands/options, load configuration, construct progress callbacks, delegate to runner modules, and format user-facing summaries/errors. It should not contain workflow/business logic.

## Implemented commands

```bash
camera-discovery run "Get me all public live cameras in California" \
  --profile fast \
  --output-dir runs/test

camera-discovery harvest-urls "California traffic cameras" \
  --output-dir runs/harvest \
  --media .m3u8
```

Key `run` options:

```text
--output-dir / -o
--profile
--seed-url
--sources-file
--discovery-mode
--block-pattern
--harvest-input
--progress / --no-progress
--progress-style auto|rich|plain|events
```

Key `harvest-urls` options:

```text
--output-dir / -o
--sources-file
--discovery-mode
--seed-url
--block-pattern
--media
--image-asset-filter raw|exclude-page-assets|camera-evidence
--write-intermediate-records
--progress / --no-progress
--progress-style auto|rich|plain|events
```

## CLI responsibility boundary

`camera_discovery.cli` should:

1. expose the `camera-discovery` Typer app;
2. declare command arguments/options and help text;
3. call `load_run_config()` or `load_harvest_config()`;
4. build a progress callback with `cli_commands/progress.py`;
5. call `runners/discovery_run.py` or `runners/harvest_run.py`;
6. format summaries through `cli_commands/output.py` or simple console output.

`camera_discovery.cli` should not directly implement target resolution, source-row construction, candidate discovery, validation, artifact writing, harvest record extraction, or handoff conversion. Those behaviors belong in runners, services, and focused helper modules.

## Target-aware `run` workflow

`runners/discovery_run.py` owns the target-aware workflow:

1. Create `RunState`.
2. Run `TargetResolver.resolve_all()`.
3. Stop only targets with `trust_policy=stop`; continue runnable targets.
4. Run `CandidateDiscoveryEngine.discover(target)` once per runnable target, in parallel across targets when configured.
5. Merge candidate sets.
6. Load `--harvest-input` rows as source-provided candidate seed/enrichment data when configured.
7. Run `ReviewAndValidationPipeline` with runnable targets and merged candidates.
8. Write `logs/run_summary.json`.
9. Return a result object for CLI summary formatting.

## Extraction-only `harvest-urls` workflow

`runners/harvest_run.py` owns harvest execution. `CameraUrlHarvestEngine` performs extraction-only harvesting and writes harvest URL/media/structured-record artifacts. Harvest mode bypasses target resolution, geocoding, validation, trust classification, scope enforcement, LLM review, GeoJSON/maps, `cameras.md`, and review ZIP generation.

## Progress

Support rich, plain, and event-stream progress. Event mode emits machine-readable JSON lines for external UIs.
