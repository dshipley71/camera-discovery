# GitHub source provider

`camera-discovery` can use GitHub as a passive source provider alongside DDG, Bing, and SearXNG. The provider searches public GitHub code through the GitHub code-search API and returns normalized source rows for the existing harvest/discovery extraction pipeline. It does not validate cameras, infer trust, bypass target scope, or create camera records by itself.

## Provider selection

The current provider-selection mechanism is environment based:

```bash
CAMERA_DISCOVERY_HARVEST_SEARCH_ENGINES=github \
CAMERA_DISCOVERY_GITHUB_TOKEN=ghp_... \
camera-discovery harvest-urls "public traffic cameras" --media .m3u8,image
```

Combined public web and GitHub source discovery:

```bash
CAMERA_DISCOVERY_HARVEST_SEARCH_ENGINES=ddg,bing,searxng,github \
CAMERA_DISCOVERY_GITHUB_TOKEN=ghp_... \
camera-discovery harvest-urls "public traffic cameras" --media .m3u8,image --write-intermediate-records
```

The normal target-aware workflow uses the same `CAMERA_DISCOVERY_SEARCH_ENGINES` list:

```bash
CAMERA_DISCOVERY_SEARCH_ENGINES=ddg,bing,searxng,github \
CAMERA_DISCOVERY_GITHUB_TOKEN=ghp_... \
camera-discovery run "public traffic cameras near Example City"
```

## Authentication and limits

GitHub code search requires authentication. Tokens are read, in order, from:

1. `CAMERA_DISCOVERY_GITHUB_TOKEN`
2. `GITHUB_TOKEN`
3. `GH_TOKEN`

Tokens are not written to artifacts. If `github` is selected without a token, GitHub attempts are marked `not_configured` with `skip_reason = github_token_not_configured`, and other configured engines continue.

Optional limits:

- `CAMERA_DISCOVERY_GITHUB_MAX_RESULTS` / `CAMERA_DISCOVERY_HARVEST_GITHUB_MAX_RESULTS`
- `CAMERA_DISCOVERY_GITHUB_MAX_QUERIES` / `CAMERA_DISCOVERY_HARVEST_GITHUB_MAX_QUERIES`
- `CAMERA_DISCOVERY_GITHUB_WEB_DORK_MAX_QUERIES` / `CAMERA_DISCOVERY_HARVEST_GITHUB_WEB_DORK_MAX_QUERIES`

GitHub HTTP 401/403 responses are reported as authentication/rate-limit diagnostics; partial results from earlier successful requests are preserved by the calling workflow when available.

## Query libraries

GitHub query templates live outside `SOURCES.md` in `src/camera_discovery/search_queries/github.py`:

- `GITHUB_CODE_SEARCH_QUERIES` contains GitHub-native public-source code-search templates.
- `GITHUB_WEB_DORK_QUERIES` contains GitHub-targeted web-search dorks submitted to configured web engines such as DDG, Bing, and SearXNG when GitHub is in the selected engine list.

`SOURCES.md` remains the reviewed allow/block policy registry. Query libraries describe how to search; source rows and artifacts record what was discovered.

## URL normalization and artifacts

GitHub code-search results are normalized into the same source-row schema as other blind search results. Blob URLs such as:

```text
https://github.com/{owner}/{repo}/blob/{ref}/{path}
```

are converted to fetchable raw files when the file path is known:

```text
https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}
```

Source rows include GitHub metadata such as repository, owner, repo, ref, path, HTML URL, raw URL, result rank, and content-type hint when available. Deduplication treats equivalent blob/raw URLs as the same source row.

`harvest/logs/search_service_summary.json` includes a `github` backend entry with query, result, selected-row, blocked-row, duplicate, and error counts. `harvest/logs/search_engine_diagnostics.jsonl` records engine-aware query attempts.

## Safety boundaries

GitHub discovery is passive public-source discovery only. The provider is limited to public datasets, public configuration/source files, public GeoJSON/JSON/CSV/KML/YAML/XML/text/code references, ArcGIS references, and public media-feed references. It does not search for credentials, admin panels, exposed device UIs, private surveillance systems, default login paths, RTSP brute-force paths, or vulnerability-oriented material. Global blocked-source policy applies to GitHub result URLs, converted raw URLs, URLs extracted from GitHub files, harvested records, and final candidates.
