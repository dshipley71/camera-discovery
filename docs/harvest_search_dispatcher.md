# Harvest Search Dispatcher and Official Source Expansion

This repository now uses a multi-engine blind-search dispatcher for public camera source discovery.

## Engines

The dispatcher runs these engines for normal blind-search source discovery:

- DuckDuckGo HTML search
- Bing HTML search
- Optional SearXNG JSON search when a base URL is configured

SearXNG is disabled unless `CAMERA_DISCOVERY_SEARXNG_BASE_URL` or `CAMERA_DISCOVERY_HARVEST_SEARXNG_BASE_URL` is set. Search failures are logged per engine and do not abort other engines.

Relevant settings:

```text
CAMERA_DISCOVERY_SEARCH_ENGINES=ddg,bing,searxng
CAMERA_DISCOVERY_HARVEST_SEARCH_ENGINES=ddg,bing,searxng
CAMERA_DISCOVERY_SEARXNG_BASE_URL=
CAMERA_DISCOVERY_HARVEST_SEARXNG_BASE_URL=
CAMERA_DISCOVERY_SEARXNG_CATEGORIES=general
CAMERA_DISCOVERY_HARVEST_SEARXNG_CATEGORIES=general
CAMERA_DISCOVERY_DDG_DELAY_SECONDS=1.0
CAMERA_DISCOVERY_HARVEST_DDG_DELAY_SECONDS=1.0
```

## Official-source query expansion

Harvest and normal discovery add high-signal public/official source queries based on camera intent. Templates cover traffic, weather, airport, beach/coastal, harbor/port/marina, park/wildlife, mountain/ski, campus, construction, public safety, city, and tourism-style public cameras.

Normal discovery includes bounded Google-style public-source `site:` dorks by default. The feature can be disabled with `CAMERA_DISCOVERY_ENABLE_GOOGLE_DORKING=false`; when enabled, it remains bounded by `max_dork_queries` and source/block policy.

Harvest mode uses official-source query templates directly because harvest is source-discovery focused and does not perform trust, validation, geocoding, scope approval, or GeoJSON output.

## Endpoint extraction

Static HTML/page extraction now detects JSON/API/ArcGIS/GeoJSON endpoint references from:

- Quoted `.json`, `.geojson`, `/api/`, `/feed`, `/data`, `/layer`, `/query`, `MapServer`, and `FeatureServer` URLs
- `fetch(...)`
- `axios.get(...)`, `axios.post(...)`, `axios.request(...)`
- `$.getJSON(...)`, `$.get(...)`, `$.post(...)`
- `xhr.open("GET", ...)`
- jQuery-style `ajax({ url: ... })`
- JavaScript variables such as `serviceUrl`, `dataUrl`, `layerUrl`, or `queryUrl`

Discovered endpoints still pass through source block policy and URL safety handling before being fetched.

## Structured extraction

Linked JSON/API/ArcGIS/GeoJSON endpoints continue to feed the existing structured extraction path. That path extracts media assets, camera records, GeoJSON geometry, ArcGIS FeatureServer/MapServer query records, nested latitude/longitude fields, service status, timestamps, refresh metadata, and camera identity fields where present.

No trust or validation assumptions are made in harvest mode. Harvest artifacts remain source-provided and review-oriented.
