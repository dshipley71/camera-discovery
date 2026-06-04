# SOURCES.md

This registry is intentionally empty by default. Add user-approved public source URLs here when you want directory-mode discovery.
Allowed sources are used only in `directory` and `both` discovery modes. The `type` values are `page`, `feed`, `direct_hls`, `site`, and `dynamic`.
Blocked sources are a global deny policy and are respected by `blind`, `directory`, `both`, and `direct` modes, including fetched pages, linked endpoints, extracted media URLs, and final candidate rows.

## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| OpenCCTV | http://www.opencctv.org | site | global | true | User-approved public CCTV directory source. |
| Windy Webcams | https://www.windy.com/webcams | site | global | true |  |
| Skyline Webcams | https://www.skylinewebcams.com | site | global | true |  |
| EarthCam | https://www.earthcam.com | site | global | true |  |
| WorldViewStream | https://worldviewstream.com | site | global | true |  |
| WorldCams.tv | https://worldcams.tv | site | global | true |  |
| LiveBeaches | https://livebeaches.com | site | global | true |  |
| EarthTV | https://earthtv.com | site | global | true |  |
| GeoWebcams | https://www.geowebcams.com | site | global | true |  |
| CamStreamer | https://camstreamer.com/live | site | global | true |  |
| ipcamlive | https://ipcamlive.com | site | global | true |  |
| iplivecam | https://iplivecam.com | site | global | true |  |
| iplivecams | https://iplivecams.com | site | global | true |  |
| iwcpinc | https://iwcpinc.com | site | global | true |  |
| liveworldwebcams | https://liveworldwebcams.com | site | global | true |  |
| myearthcam | https://myearthcamcam.com | site | global | true |  |
| nizuc | https://nizuc.com | site | global | true |  |
| opentopia | https://opentopia.com | site | global | true |  |
| puentesfronterizos.gob.mx | https://puentesfronterizos.gob.mx | site | global | true |  |
| sammo.icmyl.unam.mx | https://sammo.icmyl.unam.mx | site | global | true |  |
| slshotels | https://slshotels.com | site | global | true |  |
| streamlock.net | https://streamlock.net | site | global | true |  |
| terminaltcp | https://terminaltcp.com | site | global | true |  |
| trafficland | https://trafficland.com | site | global | true |  |
| villapalmarcancun | https://villapalmarcancun.com | site | global | true |  |
| webcamhopper | https://webcamhopper.com | site | global | true |  |
| webcamsdemexico | https://webcamsdemexico.com | site | global | true |  |
| worldlivecamera | https://worldlivecamera.com | site | global | true |  |
| worldviewstream | https://worldviewstream.com | site | global | true |  |
| youtube | https://youtube.com | site | global | true |  |

## Blocked Sources

| pattern | reason |
|---|---|
| insecam.org | User-blocked camera directory; do not crawl, fetch, extract, or emit candidates from this domain. |
| shodan.io | Internet-connected device search engine; not an approved public camera source. |
| censys.io | Internet infrastructure scanning/search platform; not an approved public camera source. |
| zoomeye.org | Cyberspace/internet asset search engine; not an approved public camera source. |
| zoomeye.ai | Cyberspace/internet asset search engine; not an approved public camera source. |
| fofa.info | Cyberspace/internet asset search engine; not an approved public camera source. |
