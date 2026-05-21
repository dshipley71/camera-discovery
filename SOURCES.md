# SOURCES.md

This registry is intentionally empty by default. Add user-approved public source URLs here when you want directory-mode discovery.

Allowed sources are used only in `directory` and `both` discovery modes. Blocked sources are a global deny policy and are respected by `blind`, `directory`, `both`, and `direct` modes, including fetched pages, linked endpoints, extracted media URLs, and final candidate rows.

Allowed `type` values are `page`, `feed`, `direct_hls`, `site`, and `dynamic`.

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| OpenCCTV | http://www.opencctv.org | site | global | true | User-approved public CCTV directory source. |

## Blocked Sources

| pattern | reason |
|---|---|
| http://www.insecam.org | User-blocked source; do not crawl, fetch, extract, or emit candidates from this domain. |
