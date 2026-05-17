# 06 — CLI Agent

Implement a thin CLI:

```bash
camera-discovery run "Get me all public live cameras in California" --profile fast --output-dir runs/test
```

CLI flow:

1. Load `RunConfig`.
2. Create `RunState`.
3. Run `TargetResolver`.
4. Stop or continue based on `TargetContext.trust_policy`.
5. Run `CandidateDiscoveryEngine`.
6. Run `ReviewAndValidationPipeline`.
7. Write `logs/run_summary.json`.

The CLI should not contain large business logic.

## Multi-location requirement

Users may specify one or more places/locations in a single query. The application must not collapse multi-location queries into a single combined target. It must extract and process each requested target independently:

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive a stable `target_id`, target-specific target-resolution diagnostics, target-specific candidate discovery artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.
