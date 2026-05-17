# AGENTS.md — Simplified Camera Discovery Build

Build the application around three core services:

1. `TargetResolver`
2. `CandidateDiscoveryEngine`
3. `ReviewAndValidationPipeline`

Use a single `RunState` as the source of truth. Avoid scattered state mutation across independent agents.

## LLM Role

LLMs are evidence interpreters/rankers only:

1. Target intent extraction and geocoder-query expansion.
2. Geocoder candidate ranking/referee.
3. Candidate semantic review.

## Deterministic Verification/Tool Role

Deterministic code and tools remain the authority for:

1. Geometry verification.
2. Stream validation.
3. Trusted output authorization.
4. Final artifact writing.

## Provider Support

Support:

- Ollama / Ollama Cloud `/api/chat`
- OpenAI-compatible `/v1/chat/completions`
- Bedrock Runtime Converse API

## Trust Rule

Never allow LLM output alone to create trusted `camera.geojson`.


## Directory Sources

The simplified app includes a `DirectorySourceProvider` inside `CandidateDiscoveryEngine`, not as a separate orchestration layer. Use `SOURCES.md` for user-approved pages, feeds, direct HLS URLs, and global blocked source patterns.

Allowed sources are optional discovery inputs used only in `directory` and `both` modes. Blocked source patterns are a global deny policy and must be applied to blind search, directory sources, direct seed URLs, fetched pages, and extracted stream URLs.
