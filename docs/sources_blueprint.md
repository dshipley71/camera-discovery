# SOURCES.md Blueprint

`SOURCES.md` is the optional user-approved source registry for directory discovery. It starts empty by default.

Allowed sources are discovery inputs. They are not trusted camera evidence by themselves. Blocked sources are global deny rules.

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Example public page | https://public-agency.example/cameras | page | city | false | Replace with a real public camera page and enable it. |
| Example JSON feed | https://public-agency.example/api/cameras.json | feed | state | false | JSON/GeoJSON/ArcGIS-style feeds are walked generically. |
| Example direct HLS | https://public-agency.example/live/camera.m3u8 | direct_hls | city | false | Direct HLS URLs become candidates without browser capture. |
| Example dynamic site | https://public-agency.example/map | dynamic | state | false | Dynamic pages may be routed to browser capture when budgets allow. |
| Example site root | https://public-agency.example/ | site | state | false | Site roots can be explored and paginated generically. |

Allowed `type` values parsed by the current code are:

```text
page
feed
direct_hls
site
dynamic
```

Rows with any other `type` are treated as `page`.

## Blocked Sources

| pattern | reason |
|---|---|
| private.example | private or internal host pattern |
| login.example | requires login |
| *.tokenized.example | tokenized or restricted stream pattern |
| /admin/ | administrative path |

Blocked patterns are applied to:

- blind search result URLs;
- directory source URLs;
- direct seed URLs;
- fetched page/feed URLs;
- extracted HLS, image snapshot, JSON, or linked endpoint URLs;
- final candidate rows.

Pattern behavior:

- Full `http://` or `https://` patterns match normalized URLs and URL prefixes.
- Patterns containing `/` match URL substrings with glob support.
- `*.example.org` matches that host suffix.
- Bare domains match exact host, subdomains, or glob host patterns.

The application does not auto-edit `SOURCES.md`.
