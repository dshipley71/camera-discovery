# SOURCES.example.md

Allowed sources are optional user-approved discovery inputs. They are used only in `directory` and `both` discovery modes. Blocked sources are global deny rules applied to blind search, directory sources, direct seed URLs, fetched pages, extracted endpoints, extracted media URLs, and final candidate rows.

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
