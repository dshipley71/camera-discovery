from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from camera_discovery.cli_commands.progress import (
    _emit_progress_stream_event,
    _make_discovery_progress_callback,
    _make_event_stream_discovery_progress_callback,
    _make_harvest_progress_callback,
    _make_plain_discovery_progress_callback,
    _make_progress,
    _resolve_progress_mode,
)
from camera_discovery.core.config import load_harvest_config, load_run_config
from camera_discovery.runners.discovery_run import execute_discovery_run
from camera_discovery.runners.harvest_run import execute_harvest_run
from camera_discovery.services.harvest_handoff import load_harvest_handoff_bundle

app = typer.Typer(help="Simplified public camera discovery pipeline", no_args_is_help=True, rich_markup_mode=None, pretty_exceptions_enable=False)
console = Console(width=120)


@app.callback()
def main() -> None:
    pass


@app.command()
def run(
    query: str = typer.Argument(...),
    output_dir: Path = typer.Option(Path("runs/latest"), "--output-dir", "-o"),
    profile: str = typer.Option("fast", "--profile"),
    seed_url: Optional[list[str]] = typer.Option(None, "--seed-url"),
    sources_file: Optional[Path] = typer.Option(None, "--sources-file"),
    discovery_mode: str = typer.Option("both", "--discovery-mode", help="blind, directory, both, or direct"),
    block_pattern: Optional[list[str]] = typer.Option(None, "--block-pattern"),
    harvest_input: Optional[Path] = typer.Option(None, "--harvest-input", help="Harvest handoff manifest or harvest_camera_inventory.jsonl to seed the normal run workflow."),
    harvest_input_mode: str = typer.Option("handoff-only", "--harvest-input-mode", help="How --harvest-input is used: handoff-only or seed."),
    harvest_first: bool = typer.Option(False, "--harvest-first", help="Run extraction-only harvest first, then feed its handoff into the normal run pipeline."),
    harvest_media: Optional[list[str]] = typer.Option(None, "--harvest-media", help="Harvest-first media filter; same values as harvest-urls --media."),
    harvest_max_source_rows: Optional[int] = typer.Option(None, "--harvest-max-source-rows", help="Harvest-first source-row cap; keeps harvest budget separate from run budgets."),
    browser_backend: Optional[str] = typer.Option(None, "--browser-backend", help="playwright or cloakbrowser; overrides CAMERA_DISCOVERY_BROWSER_BACKEND for this run."),
    http_timeout: Optional[float] = typer.Option(None, "--http-timeout", help="HTTP timeout in seconds for network discovery, enrichment, and validation requests; overrides CAMERA_DISCOVERY_HTTP_TIMEOUT."),
    show_progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress while resolving, discovering, enriching coordinates, validating, and writing outputs."),
    progress_style: str = typer.Option("auto", "--progress-style", help="Progress renderer: auto, rich, plain, or events. Use events for machine-readable progress records consumed by external UIs."),
) -> None:
    """Run public-camera discovery for one or more locations in QUERY."""
    if harvest_first and harvest_input:
        typer.echo("Error: --harvest-first builds its own harvest handoff; do not also pass --harvest-input")
        raise typer.Exit(2)
    if harvest_max_source_rows is not None and harvest_max_source_rows < 0:
        raise typer.BadParameter("--harvest-max-source-rows must be >= 0")
    progress_mode = _resolve_progress_mode(
        console,
        enabled=show_progress,
        style=os.environ.get("CAMERA_DISCOVERY_PROGRESS_STYLE", progress_style),
    )
    try:
        effective_output_dir = output_dir
        effective_harvest_input = harvest_input
        if harvest_first:
            harvest_dir = output_dir / "harvest"
            effective_output_dir = output_dir / "run"
            harvest_cfg = load_harvest_config(
                query,
                harvest_dir,
                seed_urls=seed_url or [],
                sources_file=sources_file,
                discovery_mode=discovery_mode,
                block_patterns=block_pattern or [],
                media=harvest_media or [],
                max_source_rows=harvest_max_source_rows,
                browser_backend=browser_backend,
            )
            console.print("[bold]Harvest-first:[/bold] running extraction-only harvest before normal run")
            execute_harvest_run(harvest_cfg, console=console, progress_mode=progress_mode)
            handoff_path = harvest_dir / "harvest_handoff.json"
            # Explicitly read the handoff now so combined mode fails before the
            # normal run if harvest did not produce a valid bridge manifest.
            load_harvest_handoff_bundle(handoff_path)
            effective_harvest_input = handoff_path
            console.print(f"[bold]Harvest-first handoff:[/bold] {handoff_path}")
            console.print(f"[bold]Harvest-first run artifacts:[/bold] {effective_output_dir}")
        cfg = load_run_config(
            query,
            effective_output_dir,
            profile=profile,
            seed_urls=seed_url or [],
            sources_file=sources_file,
            discovery_mode=discovery_mode,
            block_patterns=block_pattern or [],
            harvest_input=effective_harvest_input,
            harvest_input_mode=harvest_input_mode,
            browser_backend=browser_backend,
            http_timeout=http_timeout,
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(2) from exc
    execute_discovery_run(cfg, console=console, progress_mode=progress_mode)


@app.command(name="harvest-urls")
def harvest_urls(
    query: str = typer.Argument(...),
    output_dir: Path = typer.Option(Path("runs/harvest-latest"), "--output-dir", "-o"),
    max_urls: int = typer.Option(10000, "--max-urls", help="Final unique URL output cap after dedupe and media filtering. Use 0 for unlimited."),
    discovery_mode: str = typer.Option("both", "--discovery-mode", help="blind, directory, both, or direct"),
    seed_url: Optional[list[str]] = typer.Option(None, "--seed-url", help="Repeatable seed page or direct media URL."),
    seed_file: Optional[Path] = typer.Option(None, "--seed-file", help="Text file with one seed URL per line."),
    sources_file: Optional[Path] = typer.Option(None, "--sources-file"),
    block_pattern: Optional[list[str]] = typer.Option(None, "--block-pattern"),
    enable_browser_capture: bool = typer.Option(True, "--enable-browser-capture/--disable-browser-capture"),
    browser_backend: Optional[str] = typer.Option(None, "--browser-backend", help="playwright or cloakbrowser; defaults to env/config."),
    max_search_queries: Optional[int] = typer.Option(None, "--max-search-queries"),
    max_search_results_per_query: Optional[int] = typer.Option(None, "--max-search-results-per-query"),
    max_source_rows: Optional[int] = typer.Option(None, "--max-source-rows"),
    max_pages_per_source: Optional[int] = typer.Option(None, "--max-pages-per-source"),
    max_structured_endpoints_per_page: Optional[int] = typer.Option(None, "--max-structured-endpoints-per-page"),
    max_browser_pages: Optional[int] = typer.Option(None, "--max-browser-pages"),
    max_browser_pages_per_host: Optional[int] = typer.Option(None, "--max-browser-pages-per-host"),
    media: Optional[list[str]] = typer.Option(None, "--media", help="Comma-separated/repeatable extensions or categories: .m3u8, mp4, hls, rtsp, image, stream, video_file."),
    include_source_metadata: bool = typer.Option(True, "--include-source-metadata/--no-source-metadata"),
    write_intermediate_records: bool = typer.Option(False, "--write-intermediate-records/--no-write-intermediate-records", help="Write debug JSONL files for raw, unique, and media-filtered harvest records."),
    image_asset_filter: str = typer.Option("raw", "--image-asset-filter", help="Image filtering mode: raw, exclude-page-assets, or camera-evidence."),
    show_progress: bool = typer.Option(True, "--progress/--no-progress", help="Show harvest progress."),
    progress_style: str = typer.Option("auto", "--progress-style", help="Progress renderer: auto, rich, plain, or events."),
) -> None:
    """Harvest raw direct public camera/media URLs without inventory validation."""
    if max_urls < 0:
        raise typer.BadParameter("--max-urls must be >= 0; use 0 for unlimited")
    try:
        cfg = load_harvest_config(
            query,
            output_dir,
            seed_urls=seed_url or [],
            seed_file=seed_file,
            sources_file=sources_file,
            discovery_mode=discovery_mode,
            block_patterns=block_pattern or [],
            max_urls=max_urls,
            media=media or [],
            max_search_queries=max_search_queries,
            max_search_results_per_query=max_search_results_per_query,
            max_source_rows=max_source_rows,
            max_pages_per_source=max_pages_per_source,
            max_structured_endpoints_per_page=max_structured_endpoints_per_page,
            enable_browser_capture=enable_browser_capture,
            browser_backend=browser_backend,
            max_browser_pages=max_browser_pages,
            max_browser_pages_per_host=max_browser_pages_per_host,
            include_source_metadata=include_source_metadata,
            write_intermediate_records=write_intermediate_records,
            image_asset_filter=image_asset_filter,
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(2) from exc
    progress_mode = _resolve_progress_mode(
        console,
        enabled=show_progress,
        style=os.environ.get("CAMERA_DISCOVERY_PROGRESS_STYLE", progress_style),
    )
    execute_harvest_run(cfg, console=console, progress_mode=progress_mode)


if __name__ == "__main__":
    app()
