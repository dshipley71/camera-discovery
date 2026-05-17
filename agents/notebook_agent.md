# 07 — Notebook Agent

Create `notebooks/camera_discovery_live_test.ipynb`.

Notebook must show:

- profile
- query
- provider/model settings
- target-intent diagnostics
- geocoder-referee diagnostics
- candidate semantic-review diagnostics
- trusted/untrusted output counts
- artifact locations

Do not run `git pull`. Do not hard-code stale external paths.

## Multi-location requirement

Users may specify one or more places/locations in a single query. The application must not collapse multi-location queries into a single combined target. It must extract and process each requested target independently:

```text
Get me all cameras from London, England and New York, New York
→ Target 1: London, England
→ Target 2: New York, New York
```

Each target must receive a stable `target_id`, target-specific target-resolution diagnostics, target-specific candidate discovery artifacts, and target metadata on every candidate and GeoJSON feature. Final trusted and untrusted outputs may be merged, but each feature must preserve `target_id`, `target_label`, and `target_index`.

## GeoJSON Camera Review Table and Interactive Map

The Colab notebook must include a post-run visualization section that works with both trusted and review-only outputs.

### GeoJSON selection

The notebook must load camera features in this order:

```text
camera.geojson
→ untrusted_camera_candidates.geojson
→ untrusted_camera.geojson
```

If no GeoJSON exists, the notebook must show a clear message and still leave the run diagnostics visible.

### Table display

The notebook must display a table of camera rows with, when available:

```text
name/title
target_label
location_text
stream_url
source_url
latitude
longitude
thumbnail_url
trust_level
validation_status
scope_status
discovery_method
review_required
```

It must also write a CSV review table to the run directory:

```text
camera_candidates_table.csv
```

### Map display

The notebook must render an interactive Leaflet map in Colab that embeds the selected GeoJSON directly in the HTML. Do not rely only on relative browser fetches, because that can fail in notebook display contexts.

Each marker popup must include:

- camera name/title,
- target label,
- location text,
- latitude/longitude,
- trust level,
- validation status,
- scope status,
- source URL link,
- stream URL link,
- thumbnail/snapshot image when a URL exists,
- a **Play video** button.

### Thumbnail support

The popup should look for thumbnails in GeoJSON properties or `source_metadata` using keys such as:

```text
thumbnail_url
snapshot_url
image_url
camera_image_url
preview_image_url
poster_url
```

If no thumbnail URL exists, show a clear placeholder such as `No thumbnail URL in GeoJSON`.

### Video playback

The **Play video** button must attempt to play the stream URL using hls.js for `.m3u8` streams and native browser playback otherwise. Playback may still fail if the remote stream blocks browser/CORS access; the notebook must not treat that as proof the stream is invalid.
