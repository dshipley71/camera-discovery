# AGENTS.md — Clean Camera Discovery Build Blueprint

Build a streamlined public-camera discovery application from scratch around three core services:

1. `TargetResolver`
2. `CandidateDiscoveryEngine`
3. `ReviewAndValidationPipeline`

Use one canonical `RunState`. Avoid scattered state and artifact synchronization problems.

## LLM Usage

Use LLMs as advisory evidence interpreters and rankers for:

1. Target intent extraction and geocoder-query expansion.
2. Geocoder candidate ranking/referee.
3. Candidate semantic review.

## Deterministic/Tool Authority

Use deterministic code/tools for:

1. Geometry verification.
2. Stream validation.
3. Trusted output authorization.
4. Final artifact writing.

## Provider Support

Implement a shared provider factory supporting:

- Ollama / Ollama Cloud `/api/chat`
- OpenAI-compatible `/v1/chat/completions`
- Bedrock Runtime Converse API

## Guardrails

- No LLM-only trusted geometry.
- No LLM-only trusted camera inventory.
- No fabricated streams, camera records, coordinates, validation results, or runtime camera inventories.
- No hard-coded real-world target/source behavior.
- No empty trusted output files.

## Multi-location requirement

Users may specify one or more places/locations in a single query. The application must not collapse multi-location queries into a single combined target. It must extract and process each requested target independently:

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive a stable `target_id`, target-specific target-resolution diagnostics, target-specific candidate discovery artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.


## Directory Source Provider and Global Block Policy

The application must include a `DirectorySourceProvider` inside `CandidateDiscoveryEngine`. It reads user-approved source URLs from `SOURCES.md`. It must be able to run by itself, in parallel with blind search, or not at all.

Allowed source rows are discovery inputs only and are used in `directory` and `both` modes. Blocked source rows are global deny rules and must be applied to blind search, directory sources, direct seed URLs, fetched pages, and extracted stream URLs.
