# Target Resolver Agent

Maintain `TargetResolver.resolve_all() -> list[TargetContext]` and the backward-compatible `resolve()` first-target helper.

## LLM advisory duties

1. Extract target intent as strict JSON.
2. Generate target/geocoder query variants.
3. Rank/referee geocoder candidates semantically.

## Deterministic authority

Only deterministic code may verify:

- bbox validity and coordinate ranges;
- bbox plausibility by scope type;
- admin/country match;
- scope/result-type compatibility;
- selected target geometry status;
- target trust policy.

LLM bbox/coordinate hints must be stored only as unverified review hints. They cannot set `bbox_verified=True`.

## Failure behavior

A failed target-intent LLM call can fall back to the deterministic target-clause parser so review-only `fast` runs can still proceed. This fallback preserves the real user query; it must not fabricate geography.

## Multi-location requirement

Do not collapse multiple requested locations into one target. Write top-level diagnostics and per-target diagnostics under `logs/targets/<target_id>/`.


## Strict target geometry artifact rule

Artifacts and map overlays that represent target geometry must be emitted only from explicit resolver geometry hierarchy fields: `primary_geometry_geojson`, `fallback_geometry_bbox`, or `last_fallback_geometry_bbox`. Do not synthesize artifact geometry from `bbox`, `effective_bbox`, `nominatim_bbox`, `polygon`, LLM hints, or geocoder point coordinates. Do not add unconfirmed fields or behavior when repository evidence is ambiguous; implement the narrow requested behavior and document limitations.
