# Core Data Contracts Agent

Maintain `src/camera_discovery/core/models.py` and `core/config.py` as the canonical runtime contract modules.

## Key dataclasses/enums

```text
RuntimeProfile: fast, balanced, full
DiscoveryMode: blind, directory, both, direct
TrustPolicy: trusted_allowed, review_only, stop
RunConfig
HarvestConfig
TargetIntent
GeocoderCandidate
TargetContext
CameraCandidate
CandidateSet
RunState
HarvestResult
```

## Config rules

- `load_run_config()` loads the normal pipeline configuration.
- `load_harvest_config()` loads extraction-only harvest configuration.
- Helper functions such as `_bool_env` and `_split_csv_env` live above the config loader functions.
- `CAMERA_DISCOVERY_MAX_STREAMS` is deprecated but compatible. Explicit usage emits a `DeprecationWarning`.
- `SOURCES.md` defaults should resolve from the working directory or the editable repository root.

## CandidateSet.merge contract

`CandidateSet.merge()` dedupes unique candidates by `(stream_url_without_fragment, target_id)`.

- First-seen candidate wins for the same stream and target.
- Same stream under different target IDs is preserved once per target.
- Later duplicates do not overwrite enrichment, coordinates, source metadata, validation status, or target fields.
- Any future priority/quality merge behavior must be explicit, not hidden in merge order.

## Trust boundary

Coordinates, validation status, trust level, and final output authorization must be set by deterministic logic. LLMs cannot create trusted camera inventory.


## Passive intelligence fields

Candidate/source contracts should allow compact passive fields: `camera_evidence_score`, `camera_evidence_band`, `camera_evidence_reasons`, `protocol_label`, `media_family`, `protocol_confidence`, `protocol_reasons`, `signature_matches`, `http_status`, `content_type`, `final_url`, `source_evidence_score`, `source_evidence_band`, and `why_candidate_mattered`. Full metadata belongs in JSON/JSONL logs, not bloated GeoJSON properties.
