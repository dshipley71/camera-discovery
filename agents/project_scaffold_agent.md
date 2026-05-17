# 00 — Project Scaffold Agent

Create the Python package scaffold:

- `pyproject.toml` using setuptools build metadata
- `README.md`
- `.env.example`
- `Makefile`
- `src/camera_discovery/`
- `tests/`
- `notebooks/`
- `agents/`

Dependencies and build tooling:

- `httpx`
- `typer`
- `rich`
- `python-dotenv`
- `beautifulsoup4`
- optional `boto3`
- dev `pytest`, `nbformat`

Define the CLI entry point:

```toml
[project.scripts]
camera-discovery = "camera_discovery.cli:app"
```
