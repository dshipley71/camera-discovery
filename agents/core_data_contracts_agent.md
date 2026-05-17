# 01 — Core Data Contracts Agent

Create canonical dataclasses:

- `RunConfig`
- `TargetIntent`
- `GeocoderCandidate`
- `TargetContext`
- `CameraCandidate`
- `CandidateSet`
- `ValidationSummary`
- `OutputSummary`
- `RunState`

`RunState` must be the single source of truth. All artifacts should be projections of `RunState`.

Add advisory LLM fields:

- geocoder candidate LLM rank/reason/recommendation
- camera candidate LLM semantic decision/reason/confidence

Do not allow these fields to imply verified geometry or trusted stream validation.

## Multi-location requirement

Users may specify one or more places/locations in a single query. The application must not collapse multi-location queries into a single combined target. It must extract and process each requested target independently:

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive a stable `target_id`, target-specific target-resolution diagnostics, target-specific candidate discovery artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.
