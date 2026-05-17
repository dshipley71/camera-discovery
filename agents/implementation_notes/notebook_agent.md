# Notebook Agent

Provide a working live-test notebook.

Notebook must show:

- runtime profile
- provider/model settings for all advisory LLM hooks
- target-resolution diagnostics
- geocoder referee diagnostics
- candidate semantic-review diagnostics
- trusted/untrusted output counts
- artifact locations

Do not run `git pull`. Do not hard-code stale external source state.

## GeoJSON Review Table and Map

The Colab notebook must load `camera.geojson` first and fall back to `untrusted_camera_candidates.geojson` or `untrusted_camera.geojson`. It must display a table containing camera name/title, target label, location text, stream URL, source URL, latitude, longitude, trust level, validation status, scope status, discovery method, review flag, and thumbnail URL when available.

The notebook must also render an interactive Leaflet map with all GeoJSON camera locations. Marker popups must show GeoJSON metadata, an optional thumbnail image when a thumbnail/snapshot URL exists, and a **Play video** button that attempts to play the candidate stream URL using hls.js or native browser playback. The map must work in Colab by embedding the selected GeoJSON into the HTML rather than relying only on relative fetches.

