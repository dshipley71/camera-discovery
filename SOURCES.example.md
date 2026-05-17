# SOURCES.example.md

Allowed sources are optional user-approved discovery inputs. Blocked sources are global and are applied to blind search, directory sources, and direct seed URLs.

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| City public cameras page | https://public-agency.example/cameras | page | city | false | Replace with a real public camera page and enable it. |
| Direct public HLS stream | https://public-agency.example/live/camera.m3u8 | direct_hls | city | false | Replace with a real public HLS stream and enable it. |

## Blocked Sources

| pattern | reason |
|---|---|
| private.example | private or internal host pattern |
| login.example | requires login |
| *.tokenized.example | tokenized or restricted stream pattern |
