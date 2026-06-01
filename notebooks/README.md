# Google Colab Test Notebooks

These notebooks exercise the current public CLI workflows without moving notebook helpers into `src/`.

| Notebook | Purpose | Typical use |
|---|---|---|
| `camera_discovery_harvest_hls_only_test.ipynb` | Harvest `.m3u8` HLS URLs only. | Fastest way to test HLS extraction, source-row diagnostics, and harvest summaries. |
| `camera_discovery_harvest_hls_handoff_full_validation_test.ipynb` | Harvest HLS URLs and feed `harvest_handoff.json` into visible `camera-discovery run --profile balanced --http-timeout 10 --harvest-input-mode handoff-only`. | End-to-end HLS harvest-to-validation workflow. |
| `camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb` | Harvest all supported media types and feed the handoff into full pipeline validation with `--harvest-input-mode handoff-only`. | Inspect how broader media types are represented and handled downstream. |
| `camera_discovery_pipeline_only_profiles_test.ipynb` | Run `camera-discovery run` without harvest input for `fast`, `balanced`, and `full` profiles. | Compare normal pipeline behavior across profiles. |

Each notebook includes:

- Colab-friendly repository setup from the `dev` branch.
- Ollama Cloud / `OLLAMA_API_KEY` retrieval from Colab userdata without printing secrets.
- CLI/import smoke tests.
- Browser backend visibility and default browser-capture disabling for structured/HLS tests.
- Completion-aware run guards based on expected artifacts, not merely output-directory existence.
- Inspection cells for summaries, diagnostics, media distributions, scope counts, validation summaries, candidate tables, and GeoJSON counts.
- Optional artifact packaging/download cells.

Long-running validation cells are intentionally visible `!camera-discovery ...` shell commands so notebook output streams. Practical handoff validation uses `--http-timeout 10`; validation is parallel and bounded by worker count, not by candidate count. Do not treat a trusted artifact as expected unless the selected profile and validation/trust gates authorize it.

Handoff notebooks use `handoff-only` by default so native discovery is disabled and candidate counts remain bounded by the selected handoff records/assets. Use `--harvest-input-mode seed` only when intentionally combining harvest input with normal discovery.

## Target bbox visibility

Target-resolution diagnostics preserve both the accepted Nominatim bounding box and the effective bbox used by downstream scope checks. For very small precise targets such as buildings, monuments, or addresses, the effective bbox may be padded to the minimum practical extent while the original Nominatim bbox and padding reason remain in `logs/target_resolution*.json`.

Generated notebook maps overlay target bounding boxes as border-only rectangles and include geocoder target points alongside the camera coordinate markers from trusted/untrusted GeoJSON outputs. This makes it easier to audit whether discovered camera coordinates fall inside the Nominatim-derived target geometry.

## Nominatim target geometry overlays

The notebooks regenerate maps from the installed repository `camera_discovery` package and inspect target-resolution logs for the Nominatim geometry hierarchy:

1. Primary geometry: Nominatim polygon or multipolygon (`target_geometry_geojson` / `primary_geometry_source=nominatim_polygon`).
2. Fallback geometry: Nominatim rectangular bbox (`fallback_geometry_bbox` / `fallback_geometry_source=nominatim_bbox`).
3. Last fallback geometry: generic padded bbox only when no usable Nominatim polygon or bbox exists (`last_fallback_geometry_bbox`).

Map cells should show primary target borders with border-only GeoJSON overlays and show geocoder target points alongside camera coordinate points. Rectangular overlays are fallback-only, except dashed effective search extents for padded small locations.
