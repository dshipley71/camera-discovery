# CLI Agent

Maintain `src/camera_discovery/cli.py` as a thin Typer entry point. It should declare options, load config, resolve progress mode, and delegate to runners.

## Commands

```bash
camera-discovery run [OPTIONS] QUERY
camera-discovery harvest-urls [OPTIONS] QUERY
```

`run` delegates to `runners/discovery_run.py`. `harvest-urls` delegates to `runners/harvest_run.py`.

## `run` options

```text
--output-dir / -o
--profile
--seed-url
--sources-file
--discovery-mode
--block-pattern
--harvest-input
--browser-backend
--progress / --no-progress
--progress-style
```

## `harvest-urls` options

```text
--output-dir / -o
--max-urls
--discovery-mode
--seed-url
--seed-file
--sources-file
--block-pattern
--enable-browser-capture / --disable-browser-capture
--browser-backend
--max-search-queries
--max-search-results-per-query
--max-source-rows
--max-pages-per-source
--max-structured-endpoints-per-page
--max-browser-pages
--max-browser-pages-per-host
--media
--include-source-metadata / --no-source-metadata
--write-intermediate-records / --no-write-intermediate-records
--image-asset-filter
--progress / --no-progress
--progress-style
```

## Rules

- Keep command bodies thin; no business workflow logic in `cli.py`.
- Do not duplicate config parsing outside `core/config.py`.
- Do not add notebook helper code to `src/`.
- Preserve command names/options unless explicitly requested.
- Progress styles are `auto`, `rich`, `plain`, and `events`.
- `events` output is intended for external UIs and notebooks.
