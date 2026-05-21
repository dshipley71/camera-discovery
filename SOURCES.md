# SOURCES.md

This registry is intentionally empty by default. Add user-approved public source URLs here when you want directory-mode discovery.

Allowed sources are used only in `directory` and `both` discovery modes. Blocked sources are a global deny policy and are respected by `blind`, `directory`, `both`, and `direct` modes, including fetched pages, linked endpoints, extracted media URLs, and final candidate rows.

Allowed `type` values are `page`, `feed`, `direct_hls`, `site`, and `dynamic`.

| Pattern style          | Example                         | What it blocks                                                                                                      |
| ---------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Bare domain            | `insecam.org`                   | Exact host and subdomains, across `http` and `https`, such as `insecam.org`, `www.insecam.org`, `foo.insecam.org`   |
| Wildcard domain        | `*.insecam.org`                 | Subdomains matching the glob pattern, such as `www.insecam.org`; better when you intentionally only want subdomains |
| Full URL prefix        | `http://www.insecam.org`        | URLs beginning with that exact prefix; does **not** automatically block `https://www.insecam.org`                   |
| Full URL glob          | `https://example.com/private/*` | Matching normalized URLs using shell-style glob matching                                                            |
| Path/substring pattern | `/private/cameras`              | Any normalized URL containing that path-like substring, with glob support                                           |
| Host glob              | `*insecam*`                     | Hosts matching the glob pattern                                                                                     |

**Important notes:**
- Patterns are case-insensitive.
- Patterns are glob-style, not regular expressions.
- For blocking an entire site, use the bare domain form: insecam.org
- A full URL like http://www.insecam.org only blocks that protocol/host prefix. To block the whole domain regardless of protocol, use insecam.org instead.
- Blocked sources are global deny rules: they apply to blind search, directory search, direct URLs, fetched pages, extracted endpoints, media URLs, and final candidate rows.

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| OpenCCTV | http://www.opencctv.org | site | global | true | User-approved public CCTV directory source. |

## Blocked Sources

| pattern | reason |
|---|---|
| http://www.insecam.org | User-blocked source; do not crawl, fetch, extract, or emit candidates from this domain. |
