from __future__ import annotations

import json

import typer
from rich.console import Console

from camera_discovery.cli_commands.progress import _make_harvest_progress_callback
from camera_discovery.core.models import HarvestConfig, HarvestResult
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine


def execute_harvest_run(cfg: HarvestConfig, *, console: Console, progress_mode: str) -> HarvestResult:
    """Run harvest mode for a prepared HarvestConfig."""
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    callback = _make_harvest_progress_callback(console, mode=progress_mode)
    try:
        engine = CameraUrlHarvestEngine(cfg, progress_callback=callback)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print("[bold]Harvest mode:[/bold] extraction-only raw camera/media URL harvesting")
    console.print("[bold]Bypasses:[/bold] target resolution, geocoding, validation, trust, scope, LLM review, GeoJSON, maps, cameras.md, review ZIP")
    console.print(f"[bold]Discovery mode:[/bold] {cfg.discovery_mode.value}")
    console.print(f"[bold]Sources file:[/bold] {cfg.sources_file}")
    console.print(f"[bold]Media filter:[/bold] {', '.join(cfg.media) if cfg.media else 'all'}")
    console.print(f"[bold]Intermediate records:[/bold] {'enabled' if cfg.write_intermediate_records else 'disabled'}")
    console.print(f"[bold]Image asset filter:[/bold] {cfg.image_asset_filter}")
    result = engine.harvest()
    summary_path = cfg.output_dir / "harvest_summary.json"
    console.print(f"[bold]Harvested URLs:[/bold] raw={result.raw_count} unique={result.unique_count} written={result.written_count}")
    console.print(f"[bold]camera_urls.txt:[/bold] {cfg.output_dir / 'camera_urls.txt'}")
    console.print(f"[bold]camera_urls.csv:[/bold] {cfg.output_dir / 'camera_urls.csv'}")
    console.print(f"[bold]camera_urls.jsonl:[/bold] {cfg.output_dir / 'camera_urls.jsonl'}")
    console.print(f"[bold]harvest_summary.json:[/bold] {summary_path}")
    for filename in ("camera_records.jsonl", "camera_media_assets.jsonl", "discovered_endpoints.jsonl", "harvest_camera_inventory.jsonl", "harvest_handoff.json"):
        console.print(f"[bold]{filename}:[/bold] {cfg.output_dir / filename}")
    if cfg.write_intermediate_records:
        for filename in ("raw_media_records.jsonl", "unique_media_records.jsonl", "media_filtered_records.jsonl", "image_filtered_records.jsonl"):
            console.print(f"[bold]{filename}:[/bold] {cfg.output_dir / filename}")
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            console.print(f"[bold]By media type:[/bold] {summary.get('by_media_type', {})}")
            source_summary = summary.get("source_rows") or {}
            if source_summary:
                console.print(f"[bold]Source rows by provider:[/bold] {source_summary.get('selected_by_provider', {})}")
                console.print(
                    "[bold]SOURCES.md used:[/bold] "
                    f"{source_summary.get('sources_file_used', False)} "
                    f"(file={source_summary.get('sources_file')}, exists={source_summary.get('sources_file_exists', False)}, "
                    f"enabled_directory_sources={source_summary.get('directory_sources_enabled', 0)})"
                )
        except Exception:
            pass
    return result
