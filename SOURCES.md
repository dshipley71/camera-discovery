# SOURCES.md

This registry is intentionally empty by default. Add user-approved public source URLs here when you want directory-mode discovery.
Allowed sources are used only in `directory` and `both` discovery modes. The `type` values are `page`, `feed`, `direct_hls`, `site`, and `dynamic`.
Blocked sources are a global deny policy and are respected by `blind`, `directory`, `both`, and `direct` modes, including fetched pages, linked endpoints, extracted media URLs, and final candidate rows.

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Capufe | https://www.gob.mx/capufe | site | global | true | official_road |
| Mexico | https://www.gob.mx/sict | site | global | true | official_transport |
| Mexico | https://www.gob.mx/sct | site | global | true | official_transport |
| Open CCTV | https://opencctv.org/cameras/mexico | site | global | true | camera_directory |
| Skyline | https://www.skylinewebcams.com/en/webcam/mexico.html | site | global | true | camera_directory |
| Webcamtxi | https://www.webcamtaxi.com/en/mexico.html | site | global | true | camera_directory |
| Mexico | https://www.gob.mx/sectur | site | global | true | official_tourism |


## Blocked Sources

| pattern | reason |
|---|---|
| insecam.org | User-blocked camera directory; do not crawl, fetch, extract, or emit candidates from this domain. |
| shodan.io | Internet-connected device search engine; not an approved public camera source. |
| censys.io | Internet infrastructure scanning/search platform; not an approved public camera source. |
| zoomeye.org | Cyberspace/internet asset search engine; not an approved public camera source. |
| zoomeye.ai | Cyberspace/internet asset search engine; not an approved public camera source. |
| fofa.info | Cyberspace/internet asset search engine; not an approved public camera source. |
