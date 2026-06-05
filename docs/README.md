# Documentation Index

Active source-aligned documentation:

| File | Purpose |
|---|---|
| `../README.md` | Main user/developer overview and common commands. |
| `../AGENTS.md` | Repository-wide coding-agent rules. |
| `../REPOSITORY_LAYOUT.md` | Implemented package/module layout. |
| `project_structure.md` | More detailed architecture and module responsibilities. |
| `runtime_configuration.md` | CLI options and environment variables. |
| `output_artifacts.md` | Normal-run and harvest artifact contracts. |
| `acceptance.md` | Verification commands and acceptance expectations. |
| `sources_blueprint.md` | `SOURCES.md` format and source-policy rules. |
| `../agents/*.md` | Role-specific coding-agent instructions. |
| `../notebooks/README.md` | Colab notebook scenarios and usage notes. |

Historical `docs/codex_prompt_*.md` files are implementation traceability records. They may mention older module locations; current source and the active docs above are authoritative.


## Current media-output additions

- `docs/output_artifacts.md` documents playlist/TXT exports, `logs/playlist_export_summary.json`, and the top-level `media_validation_dashboard.json` schema.
- `docs/runtime_configuration.md` documents RTSP media filters/validation, the external-player limitation for RTSP, and guarded Google dorking configuration.
- `docs/codex_prompt_media_playlists_rtsp_validation_dashboard.md` records the implementation prompt for media playlists, RTSP support, the validation dashboard, and guarded public-source Google dorking.


## Passive intelligence documentation

See `passive_intelligence.md` for the passive source/candidate evidence scoring, safe signature matching, HTTP metadata, protocol labeling, and review-artifact behavior. The corresponding implementation prompt is `codex_prompt_passive_camera_intelligence.md`.

- [Structured Endpoint Discovery](structured_endpoint_discovery.md)
