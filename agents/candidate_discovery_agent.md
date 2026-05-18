# 04 — Candidate Discovery Engine Agent

## Role

Implement `CandidateDiscoveryEngine`, the single discovery service in the simplified architecture. Do not reintroduce many separate discovery agents. Keep discovery providers as input adapters inside this service.

## Discovery Providers

Implement three deterministic source providers:

```text
BlindSearchSourceProvider      query-driven public search
DirectorySourceProvider        user-approved SOURCES.md entries
DirectUrlSourceProvider        user-provided --seed-url values
```

The provider outputs are normalized into the same candidate extraction path.

## Discovery Modes

Support:

```text
blind       = blind search only
directory   = SOURCES.md allowed sources only
both        = blind search + SOURCES.md allowed sources
direct      = seed URLs only
```

CLI and config must expose:

```bash
--discovery-mode blind|directory|both|direct
--sources-file SOURCES.md
--seed-url <url>
--block-pattern <pattern>
```

Environment variables:

```bash
CAMERA_DISCOVERY_DISCOVERY_MODE=both
CAMERA_DISCOVERY_SOURCES_FILE=SOURCES.md
CAMERA_DISCOVERY_BLOCK_PATTERNS=
```

## SOURCES.md Format

Implement a human-editable Markdown registry:

```markdown
# SOURCES.md

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|

## Blocked Sources

| pattern | reason |
|---|---|
```

Allowed source `type` values:

```text
page
feed
direct_hls
site
```

## Source Policy Rule

Allowed sources are mode-specific. Blocked sources are global.

```text
Allowed Sources → used only by directory/both modes
Blocked Sources → applied to blind, directory, both, and direct modes
```

Blocked patterns must be applied to:

- blind search result URLs,
- directory source URLs,
- direct seed URLs,
- fetched page URLs,
- extracted stream URLs,
- final candidate rows.

## Candidate Extraction

For every accepted source row:

1. If it is a direct HLS URL, create a candidate directly.
2. If it is a page/feed/site URL, fetch it and extract `.m3u8` links.
3. Deduplicate stream URLs.
4. Preserve source provenance in each candidate.
5. Apply deterministic coordinate/bbox scope gates.
6. Use LLM semantic review only as an advisory ranker/reviewer.

## Candidate Metadata

Every candidate should carry:

```text
target_id
target_label
stream_url
source_url
discovery_method
source_provider
source_kind
source_name
source_scope_hint
source_notes
scope_status
trust_level
reasons
```

## Guardrails

- Do not let the directory provider become a separate orchestration layer.
- Do not let blind search read allowed sources from `SOURCES.md`.
- Do apply blocked patterns globally even when directory mode is disabled.
- Do not auto-edit `SOURCES.md`.
- Do not treat directory sources as trusted camera evidence; they are discovery inputs only.
- Do not bypass deterministic validation/trust gates.

## Required Artifacts

```text
logs/source_policy_summary.json
logs/blocked_source_rows.jsonl
logs/search_queries.json
logs/search_results.jsonl
candidates/<target_id>/agentic_candidates.jsonl
candidates/<target_id>/agentic_candidates_unique.jsonl
logs/targets/<target_id>/candidate_discovery_summary.json
```

## Acceptance Tests

Add tests proving:

- `SOURCES.md` allowed-source rows parse correctly.
- `SOURCES.md` blocked patterns parse correctly.
- `DirectorySourceProvider` emits enabled allowed rows.
- disabled allowed rows are skipped.
- blocked allowed rows are skipped.
- direct seed URLs respect global blocked patterns.
- blind search result selection respects global blocked patterns even when directory mode is not used.
- `both` mode merges blind and directory rows before candidate extraction.


## Required Generic Extractors

The discovery engine must support blind search even when `SOURCES.md` has no allowed sources.  For every selected public URL, it should attempt generic extraction in this order:

- direct HLS `.m3u8` URLs;
- JSON endpoints;
- JavaScript configuration blobs containing camera records;
- map-layer/feed records, including GeoJSON features;
- image snapshot camera metadata;
- HLS URLs where available.

Camera-type terms such as `traffic cameras` are candidate intent, not target geography.
