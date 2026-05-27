# 01 — Core Data Contracts Agent

Maintain canonical dataclasses in `src/camera_discovery/core/models.py`:

- `RunConfig`
- `TargetIntent`
- `GeocoderCandidate`
- `TargetContext`
- `CameraCandidate`
- `CandidateSet`
- `ValidationSummary`
- `OutputSummary`
- `RunState`

`RunState` is the single run snapshot. Artifacts are projections of service state, not separate truth sources.

## Required contract fields

Target and candidate contracts must preserve:

```text
target_id
target_index
target_label
canonical_target
scope_type
bbox
bbox_verified
geometry_status
trust_policy
stream_url
source_url
discovery_method
source_metadata
lat/lon
coordinate_source
scope_status
validation_status
trust_level
reasons
```

LLM advisory fields must remain advisory:

```text
llm_rank
llm_relevance_score
llm_referee_recommendation
llm_referee_reason
llm_semantic_decision
llm_semantic_confidence
llm_semantic_reason
```

Do not let advisory fields imply verified geometry, accepted coordinates, validated streams, or trusted output.

## Multi-location requirement

Every candidate and GeoJSON feature must preserve `target_id`, `target_label`, and `target_index`. Merged outputs are allowed only when target provenance remains explicit.

## Candidate merge semantics

`CandidateSet.merge()` is a deterministic first-seen merge contract, not a quality-ranking strategy. It deduplicates unique candidates by `(stream_url without URL fragment, target_id)`. Keep `target_id` in the merge key so the same stream discovered under different targets remains represented once per target. When the same stream and same target collide, keep the first candidate and drop later duplicates without silently merging enrichment fields, coordinates, validation status, source metadata, reasons, or target provenance. If future behavior needs source-quality or enrichment-priority rules, implement that as an explicit merge strategy with tests rather than changing merge order accidentally.
