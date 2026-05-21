# 00 — Project Scaffold Agent

Maintain the existing Python package scaffold rather than recreating it from scratch.

Required top-level files/directories:

```text
pyproject.toml
README.md
REPOSITORY_LAYOUT.md
SOURCES.md
SOURCES.example.md
Makefile
src/camera_discovery/
tests/
notebooks/
docs/
agents/
```

`pyproject.toml` uses setuptools build metadata and exposes the CLI entry point:

```toml
[project.scripts]
camera-discovery = "camera_discovery.cli:app"
```

Runtime dependencies currently include:

```text
httpx
typer
rich
python-dotenv
beautifulsoup4
```

Optional extras currently include:

```text
bedrock      -> boto3
playwright   -> playwright
cloakbrowser -> cloakbrowser
dev          -> pytest, nbformat
notebook     -> jupyter, nbformat, pandas
```

Do not add scaffold-only files that are not present in the repo without a source-code need. Documentation should describe the implemented source tree, not an aspirational layout.
