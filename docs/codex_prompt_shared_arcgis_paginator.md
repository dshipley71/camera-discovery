# Codex Prompt: Implement Shared ArcGIS Feature-Layer Pagination for Discovery and Harvest

This repository change was implemented from the Codex prompt titled “Implement Shared ArcGIS Feature-Layer Pagination for Discovery and Harvest.” The prompt required a shared, bounded ArcGIS paginator for normal discovery and `harvest-urls`, with metadata fetching, offset pagination, object-ID fallback, deduplication, response-cache integration, source-policy enforcement, diagnostics, documentation, tests, validation, cleanup, and packaging.

Key constraints from the prompt:

- Preserve separate normal discovery and harvest workflows.
- Use one shared paginator for both paths.
- Do not guess ArcGIS layer IDs or hard-code sources.
- Do not bypass blocked-source policy, scope, trust, validation, media extraction rules, or English-canonical output schemas.
- Use ArcGIS REST `resultOffset`, `resultRecordCount`, `orderByFields`, `returnIdsOnly=true`, and `objectIds=` semantics.
- Add bounded configuration through environment variables.
- Add tests with fake HTTP clients only; production code must not include fake responses.
- Clean generated caches before packaging and verify the final zip.
