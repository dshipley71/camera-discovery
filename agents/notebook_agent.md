# Notebook Agent

Maintain notebooks as live tests and analyst review helpers for the real CLI. Notebook-specific helper/display code belongs in notebooks, not in `src/`.

Current notebooks:

```text
notebooks/camera_discovery_live_test.ipynb
notebooks/camera_discovery_harvest_urls_test.ipynb
```

## Required notebook behavior

- Install/use the current package checkout, not stale remote code.
- Show query, profile, output directory, discovery mode, source file, browser backend, and media filter.
- Retrieve `OLLAMA_API_KEY` from Colab userdata when available and configure Ollama Cloud variables explicitly.
- Show target-resolution diagnostics, source-row summaries, browser preflight/capture diagnostics, harvest summaries, validation summaries, and artifact links.
- Display candidate tables and maps when artifacts exist.
- Do not use fake camera feeds, fake coordinates, or simulated validation results.

## GeoJSON selection

Load camera features in this order or merge available files when appropriate:

```text
camera.geojson
untrusted_camera_candidates.geojson
untrusted_camera.geojson
```

If no GeoJSON exists, show a clear message and leave diagnostics visible.

## Harvest notebooks

For HLS-focused testing, prefer no intermediate records unless debugging extraction size or dedupe:

```bash
camera-discovery harvest-urls "California traffic cameras" \
  --media .m3u8 \
  --max-urls 0 \
  --disable-browser-capture \
  --progress-style plain
```

For handoff tests, use `run --harvest-input harvest_handoff.json` and show the handoff media filter/default artifact.
