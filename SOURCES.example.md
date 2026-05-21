# SOURCES.example.md

Allowed sources are used only in `directory` and `both` discovery modes. The `type` values are `page`, `feed`, `direct_hls`, `site`, and `dynamic`.

Blocked sources are a global deny policy and are respected by `blind`, `directory`, `both`, and `direct` modes, including fetched pages, linked endpoints, extracted media URLs, and final candidate rows.

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
| Public cameras page | https://public-agency.example/cameras | page | city | false | Replace with a real public camera page and enable it. |
| Public JSON camera feed | https://public-agency.example/api/cameras.json | feed | state | false | JSON, GeoJSON, ArcGIS-style records, and media metadata are extracted generically. |
| Direct public HLS stream | https://public-agency.example/live/camera.m3u8 | direct_hls | city | false | Direct HLS URLs become candidates without browser capture. |
| Dynamic public camera map | https://public-agency.example/camera-map | dynamic | state | false | Dynamic pages may be routed to Playwright/CloakBrowser capture when enabled and budgeted. |
| Public camera site root | https://public-agency.example/ | site | state | false | Site roots can produce pagination and linked feed rows. |

## Blocked Sources

| pattern | reason |
|---|---|
| private.example | private or internal host pattern |
| login.example | requires login |
| *.tokenized.example | tokenized or restricted stream pattern |
| /admin/ | administrative path |
