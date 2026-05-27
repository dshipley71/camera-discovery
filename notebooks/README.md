# Google Colab Test Notebooks

These notebooks exercise the current public CLI workflows without moving notebook helpers into `src/`.

| Notebook | Purpose | Typical use |
|---|---|---|
| `camera_discovery_harvest_hls_only_test.ipynb` | Harvest `.m3u8` HLS URLs only. | Fastest way to test HLS extraction, source-row diagnostics, and harvest summaries. |
| `camera_discovery_harvest_hls_handoff_full_validation_test.ipynb` | Harvest HLS URLs and feed `harvest_handoff.json` into `camera-discovery run --profile full`. | End-to-end HLS harvest-to-validation workflow. |
| `camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb` | Harvest all supported media types and feed the handoff into full pipeline validation. | Inspect how broader media types are represented and handled downstream. |
| `camera_discovery_pipeline_only_profiles_test.ipynb` | Run `camera-discovery run` without harvest input for `fast`, `balanced`, and `full` profiles. | Compare normal pipeline behavior across profiles. |

Each notebook includes:

- Colab-friendly repository setup from the `dev` branch.
- Ollama Cloud / `OLLAMA_API_KEY` retrieval from Colab userdata without printing secrets.
- CLI/import smoke tests.
- Browser backend visibility and default browser-capture disabling for structured/HLS tests.
- Completion-aware run guards based on expected artifacts, not merely output-directory existence.
- Inspection cells for summaries, diagnostics, media distributions, scope counts, validation summaries, candidate tables, and GeoJSON counts.
- Optional artifact packaging/download cells.

Long-running validation cells are intentionally visible and configurable. Do not treat a trusted artifact as expected unless the selected profile and validation/trust gates authorize it.
