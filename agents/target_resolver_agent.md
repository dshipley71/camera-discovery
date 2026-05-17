# 03 — TargetResolver Agent

Build `TargetResolver.resolve() -> TargetContext`.

## LLM Advisory Stages

1. Target intent extraction.
2. Geocoder query expansion.
3. Geocoder candidate referee/ranking.

## Deterministic Authority

- bbox validity
- bbox plausibility
- admin/country match
- scope/result-type compatibility
- geometry trust policy

The LLM can rank geocoder candidates, but deterministic hard rejections remain final.

Never trust LLM bbox/coordinates. Store them only as review hints.

## Multi-location requirement

Users may specify one or more places/locations in a single query. The application must not collapse multi-location queries into a single combined target. It must extract and process each requested target independently:

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive a stable `target_id`, target-specific target-resolution diagnostics, target-specific candidate discovery artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.
