# 05 — ReviewAndValidationPipeline Agent

Build `ReviewAndValidationPipeline.run(target, candidates)`.

Responsibilities:

- deterministic stream validation
- trusted vs untrusted artifact decision
- trusted `camera.geojson`
- untrusted `untrusted_camera_candidates.geojson`
- map writing
- review packaging
- output summaries

Rules:

- Trusted output requires verified target geometry and validation evidence.
- Review-only output may contain untrusted candidates with clear labels.
- Final artifact writing is centralized here.

## Multi-location requirement

Users may specify one or more places/locations in a single query. The application must not collapse multi-location queries into a single combined target. It must extract and process each requested target independently:

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive a stable `target_id`, target-specific target-resolution diagnostics, target-specific candidate discovery artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.
