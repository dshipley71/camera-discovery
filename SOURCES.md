# SOURCES.md

This registry is intentionally empty by default. Add user-approved public source URLs here when you want directory-mode discovery.
Allowed sources are used only in `directory` and `both` discovery modes. The `type` values are `page`, `feed`, `direct_hls`, `site`, and `dynamic`.
Blocked sources are a global deny policy and are respected by `blind`, `directory`, `both`, and `direct` modes, including fetched pages, linked endpoints, extracted media URLs, and final candidate rows.

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| OpenCCTV | http://www.opencctv.org | site | global | true | User-approved public CCTV directory source. |

## Blocked Sources

| pattern | reason |
|---|---|
| insecam.org | User-blocked camera directory; do not crawl, fetch, extract, or emit candidates from this domain. |
| shodan.io | Internet-connected device search engine; not an approved public camera source. |
| censys.io | Internet infrastructure scanning/search platform; not an approved public camera source. |
| zoomeye.org | Cyberspace/internet asset search engine; not an approved public camera source. |
| zoomeye.ai | Cyberspace/internet asset search engine; not an approved public camera source. |
| fofa.info | Cyberspace/internet asset search engine; not an approved public camera source. |
