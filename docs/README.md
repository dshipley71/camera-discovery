# Documentation Index

This folder contains source-aligned project documentation for the current `camera-discovery` implementation.

- `project_structure.md` — module layout and responsibility boundaries.
- `runtime_configuration.md` — CLI options, provider settings, budgets, and runtime environment variables.
- `output_artifacts.md` — trusted/review outputs and diagnostic files.
- `acceptance.md` — behavior and validation criteria aligned with the implemented source code.
- CI/static hygiene is configured through `.github/workflows/tests.yml` and `pyproject.toml` (`ruff undefined-name lint`, permissive `mypy`, and pytest settings).
- `sources_blueprint.md` — `SOURCES.md` schema and source-policy behavior.
- `codex_prompt_*.md` — historical implementation prompts retained for traceability. They may mention earlier module locations or pre-refactor implementation preferences; they are references, not the primary runtime documentation.

The root `README.md` is the primary user/developer guide. The files under `agents/` are coding-agent instructions that should stay aligned with `src/camera_discovery/`.
