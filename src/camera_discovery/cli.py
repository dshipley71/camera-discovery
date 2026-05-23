from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from camera_discovery.core.config import load_harvest_config, load_run_config
from camera_discovery.core.models import CandidateSet, RunConfig, RunState, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
from camera_discovery.services.harvest_handoff import harvest_records_to_candidates, load_harvest_handoff
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
from camera_discovery.sources import load_source_policy
from camera_discovery.utils.io import write_json
from camera_discovery.core.progress_events import emit_progress_event

app = typer.Typer(help="Simplified public camera discovery pipeline", no_args_is_help=True)
console = Console()
def _emit_progress_stream_event(event: str, payload: dict[str, Any] | None = None) -> None:
    emit_progress_event(event, payload)


def _make_progress(console: Console, *, enabled: bool) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
        disable=not enabled,
        refresh_per_second=2,
    )


def _resolve_progress_mode(console: Console, *, enabled: bool, style: str = "auto") -> str:
    """Return rich, plain, events, or off for progress rendering.

    Rich live progress bars are used only when stdout is attached to a real
    terminal. The events mode emits machine-readable progress records for any
    external UI adapter that wants to render stable progress without terminal
    control sequences.
    """
    if not enabled:
        return "off"
    normalized = (style or "auto").strip().casefold()
    if normalized not in {"auto", "rich", "plain", "events"}:
        raise typer.BadParameter("progress style must be one of: auto, rich, plain, events")
    if normalized == "auto":
        # Require both Rich terminal support and an actual TTY file descriptor for live bars.
        file_is_tty = bool(getattr(console.file, "isatty", lambda: False)())
        return "rich" if console.is_terminal and file_is_tty else "plain"
    return normalized


def _make_discovery_progress_callback(
    progress: Progress,
    task_id: int,
    state: dict[str, int],
    lock: threading.Lock,
):
    def callback(event: str, payload: dict[str, Any]) -> None:
        label = payload.get("target_label") or payload.get("target_id") or "target"
        with lock:
            if event == "source_rows_loading":
                progress.update(task_id, description=f"Loading source rows for {label}")
            elif event == "source_rows_selected":
                total = int(payload.get("primary_rows") or 0)
                state["total"] = max(state.get("total", 0), total)
                description = f"Fetching source rows for {label}: selected {payload.get('selected_rows', 0)}"
                progress.update(task_id, total=state["total"] or None, completed=state.get("completed", 0), description=description)
            elif event == "source_row_batch_started":
                rows = int(payload.get("rows") or 0)
                if payload.get("phase") != "primary":
                    state["total"] = state.get("total", 0) + rows
                elif not state.get("total"):
                    state["total"] = rows
                progress.update(task_id, total=state["total"] or None, completed=state.get("completed", 0))
            elif event == "source_row_processed":
                state["completed"] = state.get("completed", 0) + 1
                description = (
                    f"Discovering {label}: rows {state['completed']}/{state.get('total', 0)} "
                    f"| accepted {payload.get('accepted_total', 0)} "
                    f"| HLS {payload.get('hls_count', 0)} "
                    f"| images {payload.get('image_snapshot_count', 0)}"
                )
                progress.update(task_id, total=state.get("total") or None, completed=state["completed"], description=description)
            elif event == "coordinate_enrichment_started":
                total = int(payload.get("unique") or 0)
                state["coord_total"] = total
                state["coord_completed"] = 0
                state["total"] = total
                state["completed"] = 0
                progress.update(
                    task_id,
                    total=total or None,
                    completed=0,
                    description=f"Enriching coordinates for {label}: 0/{total} mapped {payload.get('already_coordinate_bearing', 0)}",
                )
            elif event == "coordinate_candidate_processed":
                completed = int(payload.get("processed") or 0)
                total = int(payload.get("total") or state.get("coord_total") or 0)
                state["coord_completed"] = completed
                state["completed"] = completed
                description = (
                    f"Enriching coordinates for {label}: {completed}/{total} "
                    f"mapped {payload.get('coordinate_bearing', 0)} "
                    f"| metadata {payload.get('metadata_enriched', 0)} "
                    f"| geocoded {payload.get('geocode_enriched', 0)} "
                    f"| LLM {payload.get('llm_location_enriched', 0)}"
                )
                progress.update(task_id, total=total or None, completed=completed, description=description)
            elif event == "coordinate_enrichment_complete":
                total = int(payload.get("total") or state.get("coord_total") or 0)
                progress.update(
                    task_id,
                    total=total or None,
                    completed=total,
                    description=(
                        f"Coordinates enriched for {label}: mapped {payload.get('coordinate_bearing', 0)}/{total} "
                        f"| metadata {payload.get('metadata_enriched', 0)} "
                        f"| geocoded {payload.get('geocode_enriched', 0)} "
                        f"| LLM {payload.get('llm_location_enriched', 0)}"
                    ),
                )
            elif event == "scope_review_started":
                total = int(payload.get("unique") or state.get("coord_total") or 0)
                state["total"] = total
                state["completed"] = 0
                progress.update(task_id, total=total or None, completed=0, description=f"Scoping and reviewing {label}")
            elif event == "discovery_complete":
                total = max(1, state.get("total", 0), state.get("completed", 0))
                state["total"] = total
                state["completed"] = total
                progress.update(
                    task_id,
                    total=total,
                    completed=total,
                    description=(
                        f"Discovered {label}: raw {payload.get('raw', 0)}, "
                        f"unique {payload.get('unique', 0)}, "
                        f"mapped {payload.get('coordinate_bearing', 0)}"
                    ),
                )
    return callback


def _make_plain_discovery_progress_callback(
    console: Console,
    state: dict[str, int],
    lock: threading.Lock,
):
    """Create a low-noise progress callback for pipes and logs."""

    def _bucket(completed: int, total: int) -> int:
        if total <= 0:
            return completed
        return min(10, max(0, int((completed / total) * 10)))

    def callback(event: str, payload: dict[str, Any]) -> None:
        label = payload.get("target_label") or payload.get("target_id") or "target"
        with lock:
            if event == "source_rows_loading":
                if not state.get("loading_reported"):
                    console.print(f"Progress: {label} — loading source rows...")
                    state["loading_reported"] = 1
            elif event == "source_rows_selected":
                total = int(payload.get("primary_rows") or 0)
                state["total"] = max(state.get("total", 0), total)
                console.print(
                    f"Progress: {label} — scanning {total} source rows "
                    f"({payload.get('selected_rows', 0)} selected, {payload.get('discovered_rows', 0)} discovered)."
                )
            elif event == "source_row_batch_started":
                rows = int(payload.get("rows") or 0)
                if payload.get("phase") != "primary":
                    state["total"] = state.get("total", 0) + rows
                    console.print(f"Progress: {label} — checking promoted asset hosts ({rows} rows).")
                elif not state.get("total"):
                    state["total"] = rows
            elif event == "source_row_processed":
                completed = int(payload.get("processed_rows") or (state.get("completed", 0) + 1))
                if payload.get("phase") != "primary":
                    completed = state.get("completed", 0) + 1
                state["completed"] = completed
                total = int(state.get("total") or payload.get("rows") or 0)
                current_bucket = _bucket(completed, total)
                accepted = int(payload.get("accepted_total") or 0)
                last_accepted = int(state.get("last_accepted_report", 0))
                should_report = (
                    completed == total
                    or current_bucket > int(state.get("last_bucket", -1))
                    or accepted - last_accepted >= 50
                    or (bool(payload.get("budgets_full")) and not state.get("budgets_full_reported"))
                )
                if should_report:
                    state["last_bucket"] = current_bucket
                    state["last_accepted_report"] = accepted
                    if payload.get("budgets_full"):
                        state["budgets_full_reported"] = 1
                    denominator = total if total else "?"
                    console.print(
                        f"Progress: {label} — scanned {completed}/{denominator} rows; "
                        f"accepted {accepted} candidates "
                        f"(HLS {payload.get('hls_count', 0)}, images {payload.get('image_snapshot_count', 0)})."
                    )
            elif event == "coordinate_enrichment_started":
                console.print(f"Progress: {label} — enriching coordinates for {payload.get('unique', 0)} unique candidates...")
            elif event == "scope_review_started":
                console.print(f"Progress: {label} — checking target scope and review gates...")
            elif event == "discovery_complete":
                state["finished"] = 1
                console.print(
                    f"Progress: {label} — discovery complete: raw {payload.get('raw', 0)}, "
                    f"unique {payload.get('unique', 0)}, mapped {payload.get('coordinate_bearing', 0)}."
                )

    return callback


def _make_event_stream_discovery_progress_callback(lock: threading.Lock):
    """Emit discovery progress events for external progress renderers."""

    def callback(event: str, payload: dict[str, Any]) -> None:
        with lock:
            _emit_progress_stream_event(event, payload)

    return callback



def _make_harvest_progress_callback(console: Console, *, mode: str):
    state = {"last_row_report": 0}

    def callback(event: str, payload: dict[str, Any]) -> None:
        if mode == "events":
            _emit_progress_stream_event(event, payload)
            return
        if mode == "off":
            return
        if event == "harvest_started":
            console.print(f"Progress: harvest started — discovery_mode={payload.get('discovery_mode')}")
        elif event == "harvest_source_rows_ready":
            summary = payload.get("source_rows_summary") or {}
            by_provider = summary.get("selected_by_provider") or {}
            sources_file = summary.get("sources_file")
            sources_used = summary.get("sources_file_used")
            directory_rows = by_provider.get("directory", 0)
            blind_rows = by_provider.get("blind", 0)
            direct_rows = by_provider.get("direct", 0)
            console.print(
                f"Progress: harvest source rows ready — {payload.get('rows', 0)} rows "
                f"(directory/SOURCES.md={directory_rows}, blind={blind_rows}, direct={direct_rows}; "
                f"sources_file_used={sources_used}; sources_file={sources_file})."
            )
        elif event == "harvest_source_row_processed":
            processed = int(payload.get("processed_rows") or 0)
            rows = int(payload.get("rows") or 0)
            raw_records = int(payload.get("raw_records") or 0)
            report_every = max(1, rows // 10) if rows else 1
            if processed == rows or processed - int(state.get("last_row_report", 0)) >= report_every or raw_records >= int(state.get("last_records_report", 0)) + 100:
                state["last_row_report"] = processed
                state["last_records_report"] = raw_records
                console.print(f"Progress: harvest rows {processed}/{rows}; raw records={raw_records}.")
        elif event == "harvest_dedupe_complete":
            console.print(
                "Progress: dedupe/media filtering complete — "
                f"raw={payload.get('raw_records', 0)} unique={payload.get('unique_urls', 0)} "
                f"media_filtered={payload.get('media_filtered_urls', 0)}."
            )
        elif event == "harvest_outputs_written":
            console.print(f"Progress: harvest outputs written — URLs={payload.get('written_urls', 0)}.")
        elif event == "harvest_complete":
            console.print(f"Progress: harvest complete — written={payload.get('written_urls', 0)}.")

    return callback


@app.callback()
def main() -> None:
    """Camera discovery command group."""


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
    show_progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress while resolving, discovering, enriching coordinates, validating, and writing outputs."),
    progress_style: str = typer.Option("auto", "--progress-style", help="Progress renderer: auto, rich, plain, or events. Use events for machine-readable progress records consumed by external UIs."),
) -> None:
    """Run public-camera discovery for one or more locations in QUERY."""
    cfg = load_run_config(
        query,
        output_dir,
        profile=profile,
        seed_urls=seed_url or [],
        sources_file=sources_file,
        discovery_mode=discovery_mode,
        block_patterns=block_pattern or [],
        harvest_input=harvest_input,
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(config=cfg)
    console.print(f"[bold]Profile:[/bold] {cfg.profile.value}")
    console.print(f"[bold]Validation enabled:[/bold] {cfg.validation_enabled}")
    console.print(f"[bold]LLM provider:[/bold] {cfg.llm_provider}")
    console.print(f"[bold]Target-intent model:[/bold] {cfg.target_intent_model}")
    console.print(f"[bold]Discovery mode:[/bold] {cfg.discovery_mode.value}")
    console.print(f"[bold]Sources file:[/bold] {cfg.sources_file}")
    if cfg.harvest_input:
        console.print(f"[bold]Harvest input:[/bold] {cfg.harvest_input} (source-provided, unvalidated, untrusted seed data)")

    progress_mode = _resolve_progress_mode(
        console,
        enabled=show_progress,
        style=os.environ.get("CAMERA_DISCOVERY_PROGRESS_STYLE", progress_style),
    )
    progress = _make_progress(console, enabled=True) if progress_mode == "rich" else None

    with progress if progress is not None else nullcontext():
        if progress_mode == "rich":
            assert progress is not None
            resolve_task = progress.add_task("Resolving targets", total=1)
        elif progress_mode == "plain":
            console.print("Progress: resolving targets...")
        elif progress_mode == "events":
            _emit_progress_stream_event("target_resolution_started", {"completed": 0, "total": 1, "description": "Resolving targets"})

        try:
            targets = TargetResolver(cfg).resolve_all()
        except Exception as exc:
            message = _friendly_llm_error(exc, cfg)
            if message:
                console.print(f"[red]{message}[/red]")
                raise typer.Exit(code=2) from exc
            raise

        if progress_mode == "rich":
            assert progress is not None
            progress.update(resolve_task, completed=1, description="Resolved targets")
        elif progress_mode == "plain":
            console.print(f"Progress: resolved {len(targets)} target(s).")
        elif progress_mode == "events":
            _emit_progress_stream_event("target_resolution_complete", {"completed": len(targets), "total": max(1, len(targets)), "targets": len(targets)})

        state.targets = targets
        state.target = targets[0] if targets else None
        console.print(f"[bold]Targets resolved:[/bold] {len(targets)}")
        for target in targets:
            console.print(
                f"  - {target.target_id}: {target.canonical_target or target.target_label or query} | "
                f"geometry={target.geometry_status}; verified={target.bbox_verified}; policy={target.trust_policy.value}"
            )

        runnable_targets = [target for target in targets if target.trust_policy != TrustPolicy.STOP]
        if not runnable_targets:
            state.warnings.extend(target.stop_reason or f"Target {target.target_id} stopped" for target in targets)
            write_json(cfg.output_dir / "logs" / "run_summary.json", state.to_dict())
            raise typer.Exit(code=2)

        per_target_sets: dict[str, CandidateSet] = {}
        progress_lock = threading.Lock()
        target_tasks: dict[str, int] = {}
        target_progress_state: dict[str, dict[str, int]] = {}
        for target in runnable_targets:
            label = target.target_label or target.canonical_target or target.target_id
            if progress_mode == "rich":
                assert progress is not None
                target_tasks[target.target_id] = progress.add_task(f"Discovering {label}", total=None)
            elif progress_mode == "plain":
                console.print(f"Progress: discovering {label}...")
            elif progress_mode == "events":
                _emit_progress_stream_event("target_discovery_started", {"target_id": target.target_id, "target_label": label})
            target_progress_state[target.target_id] = {"total": 0, "completed": 0}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(runnable_targets))) as pool:
            futures = {}
            for target in runnable_targets:
                callback = None
                if progress_mode == "rich":
                    assert progress is not None
                    callback = _make_discovery_progress_callback(
                        progress,
                        target_tasks[target.target_id],
                        target_progress_state[target.target_id],
                        progress_lock,
                    )
                elif progress_mode == "plain":
                    callback = _make_plain_discovery_progress_callback(
                        console,
                        target_progress_state[target.target_id],
                        progress_lock,
                    )
                elif progress_mode == "events":
                    callback = _make_event_stream_discovery_progress_callback(progress_lock)
                engine = CandidateDiscoveryEngine(cfg, progress_callback=callback)
                futures[pool.submit(engine.discover, target)] = target
            for future in concurrent.futures.as_completed(futures):
                target = futures[future]
                try:
                    per_target_sets[target.target_id] = future.result()
                finally:
                    if progress_mode == "rich":
                        assert progress is not None
                        task_id = target_tasks[target.target_id]
                        state_for_target = target_progress_state[target.target_id]
                        total = max(1, state_for_target.get("total", 0), state_for_target.get("completed", 0))
                        progress.update(task_id, total=total, completed=total, description=f"Discovered {target.target_label or target.canonical_target or target.target_id}")

        if cfg.harvest_input:
            if progress_mode == "plain":
                console.print("Progress: loading harvest input...")
            elif progress_mode == "events":
                _emit_progress_stream_event("harvest_input_loaded", {"path": str(cfg.harvest_input), "stage": "started"})
            try:
                handoff_records = load_harvest_handoff(cfg.harvest_input)
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            source_policy = load_source_policy(cfg.sources_file, cfg.block_patterns)
            total_handoff_candidates = 0
            for target in runnable_targets:
                handoff_candidates = harvest_records_to_candidates(
                    handoff_records,
                    target_id=target.target_id,
                    target_index=target.target_index,
                    target_label=target.target_label or target.canonical_target,
                    source_policy=source_policy,
                )
                total_handoff_candidates += len(handoff_candidates)
                per_target_sets[f"{target.target_id}:harvest_input"] = CandidateSet(
                    raw=handoff_candidates,
                    unique=handoff_candidates,
                    coordinate_bearing=[c for c in handoff_candidates if c.has_coordinates],
                    in_scope=[],
                    review=handoff_candidates,
                    rejected=[],
                )
            state.warnings.append(
                f"Loaded {total_handoff_candidates} unvalidated/untrusted candidate(s) from harvest input; normal run processing still applies."
            )
            console.print(f"[bold]Harvest input candidates:[/bold] {total_handoff_candidates}")
            if progress_mode == "events":
                _emit_progress_stream_event("harvest_input_loaded", {"path": str(cfg.harvest_input), "candidates": total_handoff_candidates, "stage": "complete"})

        state.candidate_sets_by_target = per_target_sets
        merged = CandidateSet.merge(list(per_target_sets.values()))
        state.candidates = merged
        console.print(
            f"[bold]Candidates:[/bold] raw={len(merged.raw)} unique={len(merged.unique)} "
            f"coordinate_bearing={len(merged.coordinate_bearing)} targets={len(per_target_sets)}"
        )

        if progress_mode == "rich":
            assert progress is not None
            validation_task = progress.add_task("Validating streams and writing outputs", total=1)
        elif progress_mode == "plain":
            console.print("Progress: validating streams and writing outputs...")
        elif progress_mode == "events":
            _emit_progress_stream_event("validation_started", {"completed": 0, "total": 1, "description": "Validating streams and writing outputs"})
        validation, outputs = ReviewAndValidationPipeline(cfg).run(runnable_targets, merged)
        if progress_mode == "rich":
            assert progress is not None
            progress.update(validation_task, completed=1, description="Validation and outputs complete")
        elif progress_mode == "plain":
            console.print("Progress: validation and outputs complete.")
        elif progress_mode == "events":
            _emit_progress_stream_event("validation_complete", {"completed": 1, "total": 1, "description": "Validation and outputs complete"})
    state.validation = validation
    state.outputs = outputs
    write_json(cfg.output_dir / "logs" / "run_summary.json", state.to_dict())
    console.print(
        f"[bold]Trusted GeoJSON:[/bold] {outputs.trusted_geojson_created} "
        f"features={outputs.trusted_geojson_features_written}"
    )
    console.print(
        f"[bold]Untrusted GeoJSON:[/bold] {outputs.untrusted_geojson_created} "
        f"features={outputs.untrusted_geojson_features_written}"
    )
    console.print(f"[bold]Review package:[/bold] {outputs.review_artifacts_zip}")
    explanation_path = cfg.output_dir / "logs" / "run_explanation.json"
    if explanation_path.exists():
        try:
            explanation = json.loads(explanation_path.read_text(encoding="utf-8"))
            console.print("[bold]Run explanation:[/bold]")
            for item in explanation.get("plain_language_summary", []):
                console.print(f"  - {item}")
        except Exception:
            console.print(f"[bold]Run explanation:[/bold] {cfg.output_dir / 'RUN_EXPLANATION.md'}")


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
    media: Optional[list[str]] = typer.Option(None, "--media", help="Comma-separated/repeatable extensions or categories: .m3u8, mp4, hls, image, stream, video_file."),
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
        raise typer.BadParameter(str(exc)) from exc
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    progress_mode = _resolve_progress_mode(
        console,
        enabled=show_progress,
        style=os.environ.get("CAMERA_DISCOVERY_PROGRESS_STYLE", progress_style),
    )
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


def _friendly_llm_error(exc: Exception, cfg: RunConfig) -> str | None:
    text = repr(exc)
    lowered = text.casefold()
    if "401" not in lowered and "unauthorized" not in lowered and "api_key" not in lowered and "authentication" not in lowered:
        return None
    provider = (cfg.llm_provider or "unknown").strip().lower()
    model = cfg.target_intent_model or cfg.geocoder_referee_model or cfg.llm_model or "unknown"
    key_hint = "OLLAMA_API_KEY" if provider in {"ollama", "ollama-cloud"} else "OPENAI_COMPATIBLE_API_KEY" if provider in {"openai", "openai-compatible", "openai_compatible"} else "AWS credentials" if provider == "bedrock" else "provider credentials"
    return (
        "LLM provider authentication/configuration failed while resolving the target query. "
        f"Provider: {provider}; model: {model}. "
        f"Set/verify {key_hint} or select a provider with valid credentials."
    )


if __name__ == "__main__":
    app()
