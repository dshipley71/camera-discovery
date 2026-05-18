# CandidateDiscoveryEngine Agent

Search public pages, read optional user-approved directory sources, extract HLS `.m3u8` candidates, dedupe, and scope-score candidates.

## Discovery Inputs

`CandidateDiscoveryEngine` owns discovery input providers while keeping the simplified three-service architecture intact:

1. `BlindSearchSourceProvider` — query-driven public web search.
2. `DirectorySourceProvider` — user-approved URLs from `SOURCES.md`.
3. `DirectUrlSourceProvider` — command-line `--seed-url` inputs.

Supported modes:

```text
blind      = blind search only
directory  = SOURCES.md allowed sources only
both       = blind search + SOURCES.md allowed sources
direct     = seed URLs only
```

## SOURCES.md Policy

`SOURCES.md` has two separate meanings:

- Allowed sources are used only in `directory` and `both` modes.
- Blocked sources are global deny rules and must be respected by `blind`, `directory`, `both`, and `direct` modes.

Blocked sources apply to:

- blind search result URLs,
- directory source URLs,
- direct seed URLs,
- fetched page URLs,
- extracted stream URLs.

## LLM Advisory Duties

- Candidate semantic review based on title/source URL/location text/metadata.
- Mark likely `in_scope`, `out_of_scope`, `review`, or `unknown` semantically.

## Deterministic Duties

- Apply global source block policy.
- Fetch pages.
- Extract `.m3u8` URLs.
- Deduplicate URLs.
- Apply coordinate/bbox hard gates.

LLM semantic review does not validate stream liveness and does not authorize trusted output.


## Required Generic Extractors

The discovery engine must support blind search even when `SOURCES.md` has no allowed sources.  For every selected public URL, it should attempt generic extraction in this order:

- direct HLS `.m3u8` URLs;
- JSON endpoints;
- JavaScript configuration blobs containing camera records;
- map-layer/feed records, including GeoJSON features;
- image snapshot camera metadata;
- HLS URLs where available.

Camera-type terms such as `traffic cameras` are candidate intent, not target geography.
