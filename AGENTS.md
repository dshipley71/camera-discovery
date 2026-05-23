# AGENTS.md — Camera Discovery Source-Aligned Build Rules

The current application is a streamlined public-camera discovery pipeline built around three service modules:

1. `TargetResolver`
2. `CandidateDiscoveryEngine`
3. `ReviewAndValidationPipeline`

Use one canonical `RunState`. Avoid scattered state mutation, duplicated artifact writers, synthetic fallbacks, and source-specific hacks.

## Behavioral Guidelines

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

## LLM usage

LLMs are advisory evidence interpreters/rankers only. Current advisory stages are:

1. target intent extraction and geocoder-query expansion;
2. geocoder candidate referee/ranking;
3. candidate location-name inference for later real geocoding;
4. candidate semantic review.

The candidate location-name inference stage may return place names/query variants only. It must never return coordinates.

## Deterministic/tool authority

Deterministic code/tools remain authoritative for:

1. bbox and geometry verification;
2. candidate coordinate acceptance;
3. stream/image validation;
4. trusted output authorization;
5. final artifact writing.

## Provider support

Use the shared provider factory in `src/camera_discovery/llm/factory.py`. Supported providers are:

- `ollama` and `ollama-cloud` through Ollama-compatible `/api/chat`;
- `openai-compatible`, `openai`, or `openai_compatible` through `/v1/chat/completions`;
- `bedrock` through AWS Bedrock Runtime Converse API.

Stage-specific provider/model overrides must share the common factory path.

## Guardrails

- No LLM-only trusted geometry.
- No LLM-invented coordinates.
- No LLM-only trusted camera inventory.
- No fabricated streams, camera records, coordinates, validation results, or runtime camera inventories.
- No hard-coded real-world target/source/agency/domain behavior.
- Generic camera-type normalization constants are allowed.
- No empty trusted output files.
- Notebook-specific helper code belongs in the notebook, not in `src/`.

## Multi-location requirement

Users may specify one or more places/locations in a single query. Do not collapse multi-location queries into one combined target.

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive stable target metadata, target-specific diagnostics, target-specific candidate artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.

## Source providers and global block policy

`DirectorySourceProvider` is an input adapter inside `CandidateDiscoveryEngine`, not a separate orchestration layer. It reads enabled allowed source URLs from `SOURCES.md`.

Allowed source rows are used only in `directory` and `both` modes. Blocked rows are global deny rules and must be applied to blind search, directory rows, direct seed URLs, fetched pages/endpoints, extracted media URLs, and final candidates.

`both` mode should discover blind rows and directory rows in parallel, then normalize them into the same extraction path.

## Browser capture

Browser capture is optional and budgeted. Playwright is the default backend. CloakBrowser is an optional backend selected by `CAMERA_DISCOVERY_BROWSER_BACKEND=cloakbrowser`. Keep backend selection behind the current abstraction and preserve diagnostics.
