# Acceptance Criteria

The implementation is accepted when:

1. `TargetResolver` uses LLM target intent and geocoder referee as advisory signals only.
2. `CandidateDiscoveryEngine` uses LLM semantic review without stream validation authority.
3. `ReviewAndValidationPipeline` owns validation, trusted/untrusted output, map, and artifact packaging.
4. Geometry verification is deterministic.
5. Stream validation is deterministic/tool-based.
6. Trusted `camera.geojson` is never created from LLM-only evidence.
7. Fast mode writes review artifacts only.
8. Balanced/Full modes can write trusted output only after deterministic gates pass.
9. Ollama/Ollama Cloud, OpenAI-compatible, and Bedrock providers are supported. An LLM provider is required.
10. Compile, tests, and notebook validation pass.

## Multi-location requirement

Users may specify one or more places/locations in a single query. The application must not collapse multi-location queries into a single combined target. It must extract and process each requested target independently:

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive a stable `target_id`, target-specific target-resolution diagnostics, target-specific candidate discovery artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.

## Colab Table and Map Acceptance

The notebook is acceptable when it can:

- load `camera.geojson` or fall back to `untrusted_camera_candidates.geojson`,
- display a camera table with URL, target, location, latitude, longitude, trust, validation, and source fields,
- write `camera_candidates_table.csv`,
- render a Leaflet map with all GeoJSON camera locations,
- show marker popups with GeoJSON metadata,
- show a thumbnail image when a thumbnail/snapshot URL is present,
- provide a **Play video** button in each popup that attempts HLS playback through hls.js.

## Coordinate Enrichment Acceptance

- extract coordinates from JSON, GeoJSON, ArcGIS map-layer records, JavaScript config objects, URL query parameters, and source metadata;
- optionally geocode specific candidate location text with a real geocoder when coordinates are missing;
- never synthesize coordinates;
- write `camera_candidates_table.csv` even when no GeoJSON can be created;
- write GeoJSON only for candidates with real coordinates.
