# 06 — CLI Agent

Keep `camera_discovery.cli` thin. It should orchestrate services, not contain business logic.

## Implemented command

```bash
camera-discovery run "Get me all public live cameras in California" \
  --profile fast \
  --output-dir runs/test
```

Options:

```text
--output-dir / -o
--profile
--seed-url
--sources-file
--discovery-mode
--block-pattern
--progress / --no-progress
--progress-style auto|rich|plain|events
```

## CLI flow

1. Load `RunConfig` from CLI and environment.
2. Create `RunState`.
3. Run `TargetResolver.resolve_all()`.
4. Stop only targets with `trust_policy=stop`; continue runnable targets.
5. Run `CandidateDiscoveryEngine.discover(target)` once per runnable target, in parallel across targets.
6. Merge candidate sets.
7. Run `ReviewAndValidationPipeline` with runnable targets and merged candidates.
8. Write `logs/run_summary.json`.
9. Print trusted/untrusted GeoJSON counts, review package path, and run explanation summary.

## Progress

Support rich, plain, and event-stream progress. Event mode emits machine-readable JSON lines for external UIs.
