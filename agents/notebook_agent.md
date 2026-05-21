# 07 — Notebook Agent

Maintain `notebooks/camera_discovery_live_test.ipynb` as a live-test notebook for the real application.

Notebook-specific helper/display code belongs in the notebook, not in `src/`.

## Notebook must show

- query, profile, output directory, discovery mode, and source file;
- provider/model settings for all advisory LLM stages;
- target-resolution diagnostics;
- geocoder-referee diagnostics;
- candidate discovery summary;
- browser capture summary;
- coordinate enrichment diagnostics;
- candidate semantic-review diagnostics;
- trusted/untrusted output counts;
- artifact links;
- candidate table and embedded map.

Do not run `git pull`. Do not hard-code stale external source state. Do not add fake camera feeds, fake coordinates, or simulated validation results.

## GeoJSON selection

The notebook and map utilities should load camera features in this order or merge available files when appropriate:

```text
camera.geojson
untrusted_camera_candidates.geojson
untrusted_camera.geojson
```

If no GeoJSON exists, show a clear message and leave run diagnostics visible.

## Table display

Display camera rows with fields such as:

```text
name/title
target_label
location_text
location_display
camera_type
camera_id
media_type
stream_url
source_url
latitude
longitude
thumbnail_url
camera_refresh_rate
map_refresh_rate_seconds
trust_level
validation_status
scope_status
discovery_method
review_required
```

`camera_candidates_table.csv` is written by the application output pipeline and should be displayed when available.

## Map display

Render an embedded Leaflet map that works in Colab by embedding GeoJSON in the HTML. Popups should include GeoJSON metadata, thumbnail/snapshot images when present, source/media links, and a playback attempt button for HLS/native video. Image snapshot candidates should display snapshot refresh information when available.

Remote playback can fail because of browser/CORS restrictions; do not treat playback failure alone as proof that a stream is invalid.
