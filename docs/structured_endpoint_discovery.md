# Structured Endpoint Discovery

Camera-discovery uses a shared structured-endpoint discovery path for normal target-aware runs and extraction-only `harvest-urls` runs. The path improves recall from public structured data while preserving source policy, workflow separation, and deterministic trust rules.

## Supported public evidence

The extractor follows only endpoints explicitly referenced by allowed public content or advertised by fetched public service metadata:

- JSON and GeoJSON URLs;
- API/feed/data links;
- ArcGIS REST `MapServer` and `FeatureServer` service roots, layers, and query URLs;
- OGC API Features collection and items links;
- WFS URLs when explicitly linked;
- endpoint literals in HTML and JavaScript state/config;
- endpoints found inside explicitly linked JavaScript bundles.

The implementation does not scan hosts, probe private networks, guess API paths, guess camera URLs, enumerate ports, submit forms, use credentials, or integrate Shodan/Censys/Zoomeye/FOFA/insecam-style asset indexes.

## ArcGIS expansion policy

ArcGIS service roots are expanded from public service metadata only. When a page references a `MapServer` or `FeatureServer` root, camera-discovery fetches the service metadata and creates layer query URLs only for advertised `layers` and `tables` IDs. It no longer guesses fixed layer IDs such as `0..7`.

Explicit layer URLs are normalized to bounded read-only query URLs using:

```text
where=1=1&outFields=*&returnGeometry=true&f=json
```

Those queries still pass source-policy checks, HTTP limits, extraction filters, scope handling, validation, and trust gates.

## Workflow boundaries

Normal `camera-discovery run` uses discovered structured endpoints as another candidate-extraction source. It still performs target resolution, scope handling, review, validation, and trusted/untrusted output filtering.

`camera-discovery harvest-urls` uses the same endpoint-discovery helper but remains extraction-only. It does not perform target resolution, geocoding, validation, trust classification, GeoJSON/map generation, or review ZIP creation.

## Diagnostics

Normal runs write structured endpoint diagnostics to:

```text
runs/.../logs/structured_endpoint_discovery.jsonl
```

Harvest mode writes diagnostics to:

```text
runs/.../logs/harvest_structured_endpoint_discovery.jsonl
```

Each record includes the page URL, endpoint URL, endpoint type, discovery reason, status/error, and candidate or record counts where available.
