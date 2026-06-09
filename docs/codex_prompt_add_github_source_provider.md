# Codex Prompt: Add GitHub as a Camera-Discovery Source Provider

## Task

Update the existing `camera-discovery` repository to add **GitHub** as another passive source provider alongside the existing blind/web search providers such as **DDG**, **Bing**, and **SearXNG**.

The new GitHub provider must discover public source rows from GitHub-hosted public code, public datasets, public configuration files, public GeoJSON, public JSON, public ArcGIS references, and public media-feed references that may contain publicly available camera sources.

## Non-Negotiable Behavioral Rules

- Inspect the repository before changing code and adapt to actual names.
- Do not add stubs, fake search results, synthetic camera records, hard-coded success artifacts, or hard-coded real-world locations.
- Do not add unsafe discovery behavior such as Shodan/Censys/ZoomEye/FOFA-style exposed-device search, credential searching, default-login testing, RTSP brute forcing, ONVIF probing, direct-IP probing, admin-panel discovery, vulnerability-oriented behavior, or private-range scanning.
- Preserve `SOURCES.md` as the policy registry for reviewed allowed/blocked sources and keep search query libraries separate from source policy.
- Apply global blocked-source policy to GitHub result URLs, raw URLs, URLs found inside GitHub files, extracted media/endpoint URLs, harvest records, and final candidates.
- Make minimal, source-aligned changes and keep source/notebook logic separate.
- Remove cache/build/runtime clutter before packaging.

## Functional Goal

Add GitHub as a first-class passive source provider that can be used by blind/search discovery and harvest-first workflows. The provider should be selectable alongside existing engines, using the repository's actual provider-selection mechanism.

## Required Provider Behavior

- Provider identity should be `github`, `github_code`, or `github_code_search` according to repository style.
- The provider must search public GitHub content and return normalized source rows only; it must not validate cameras directly or bypass the harvest/discovery/validation/trust pipeline.
- Support GitHub-native code search when credentials/tooling are available.
- Support GitHub-targeted web dork templates through existing DDG/Bing/SearXNG providers.
- Support optional tokens from `CAMERA_DISCOVERY_GITHUB_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN`; never print or artifact tokens.
- Fail gracefully when GitHub credentials/tooling are missing and continue other providers where applicable.
- Normalize GitHub result URLs, including safe conversion of `github.com/{owner}/{repo}/blob/{ref}/{path}` to `raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}` when file metadata is known.
- Preserve owner/repo/ref/path, raw URL, HTML URL, query, rank, title/snippet/matched text, provider, and content-type hints in source-row metadata when available.
- Prioritize likely source files: `.json`, `.geojson`, `.csv`, `.tsv`, `.yaml`, `.yml`, `.xml`, `.kml`, `.md`, `.txt`, `.js`, `.ts`, `.html`.
- Deduplicate equivalent GitHub raw/blob URLs and source rows from other search engines.
- Include GitHub provider counts in existing provider summaries and run explanations.

## Required Query Libraries

GitHub query definitions must live outside `SOURCES.md`. Include GitHub-native code-search templates for public camera/media/source data, ArcGIS/FeatureServer/MapServer references, GeoJSON/FeatureCollection files, update-frequency fields, camera status/feed URL fields, path-based JSON/GeoJSON searches, OGC/KML/WMS references, and public camera coordinate metadata.

Include GitHub-targeted web-search dorks for `site:github.com` and `site:raw.githubusercontent.com` patterns covering `.m3u8`, `streamingVideoURL`, `currentImageURL`, `FeatureServer`, `MapServer`, `FeatureCollection`, `geojson`, update-frequency fields, camera status/feed URL fields, `.geojson`, `.json`, `.csv`, `.kml`, `.yml`/`.yaml`, ArcGIS REST directory references, and public/traffic camera source files.

Query expansion must remain location-aware and camera-type-aware without hard-coding any place, agency, or camera category.

## CLI and Configuration Requirements

Extend the existing provider-selection mechanism to include GitHub. Document final usage. Support optional GitHub authentication via `CAMERA_DISCOVERY_GITHUB_TOKEN`, `GITHUB_TOKEN`, and `GH_TOKEN` in that precedence. Respect existing source-row limits, provider-specific limits, timeouts, rate-limit handling, response caching, and deduplication.

## Extraction and Harvest Integration

GitHub provider output must feed the same source-row/extraction path as DDG/Bing/SearXNG results. Existing extraction should process GitHub raw files containing HLS URLs, image URLs, MJPEG/MJPG URLs, `streamingVideoURL`, `currentImageURL`, GeoJSON FeatureCollections, ArcGIS references, and camera metadata fields. Prefer generic extraction improvements over GitHub-only camera parsers.

## Documentation and Notebook Requirements

Update docs to explain the GitHub provider, provider selection, optional token configuration, query-library locations, the difference between `SOURCES.md` and query libraries, GitHub-native code search, GitHub-targeted web dorks, blocked-source enforcement, artifacts/provider summaries, and safety boundaries. Update notebooks as needed to expose GitHub provider examples without moving notebook-only helpers into `src/`.

## Validation Requirements

Validate provider registration/selection, disabled/missing-token behavior, GitHub URL normalization, raw/blob deduplication, blocked-source handling, query-library loading, location-aware and camera-type-aware construction without hard-coded places, harvest consumption, summary artifacts, and no token leakage. If live GitHub cannot be tested without credentials, validate pure normalization/query/config/registration/missing-auth/artifact paths without faking a live successful GitHub search.

## Acceptance Criteria

GitHub is selectable, existing providers continue to work, query templates are included outside `SOURCES.md`, GitHub results normalize into existing source rows, blob/raw normalization is safe, deduplication and blocked policy apply, no unsafe behavior or token leakage is added, missing credentials fail gracefully, summaries include GitHub, docs/notebooks are updated, this prompt is copied into docs, cache clutter is removed, and validation results are reported honestly.
