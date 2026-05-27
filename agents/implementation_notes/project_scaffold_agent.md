# Project Scaffold Agent

Maintain the existing Python package scaffold rather than recreating it from scratch.

Required top-level files/directories:

```text
.github/workflows/tests.yml
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

`pyproject.toml` uses setuptools and exposes:

```toml
[project.scripts]
camera-discovery = "camera_discovery.cli:app"
```

Runtime dependencies are intentionally lean:

```text
httpx
typer
rich
python-dotenv
beautifulsoup4
```

Optional extras include browser/provider/dev/notebook dependencies. Keep optional browser/provider packages out of core runtime dependencies unless the source code truly requires them.

Do not add scaffold-only files that are not used by the current repo. Documentation should describe the implemented source tree, not an aspirational layout.
