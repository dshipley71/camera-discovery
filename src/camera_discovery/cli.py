from __future__ import annotations

import concurrent.futures
import os
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from camera_discovery.core.config import load_run_config
from camera_discovery.core.models import CandidateSet, RunState, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
from camera_discovery.utils.io import write_json
import json

app = typer.Typer(help="Simplified public camera discovery pipeline", no_args_is_help=True)
console = Console()
PROGRESS_EVENT_PREFIX = "__CAMERA_DISCOVERY_PROGRESS__ "


def _emit_notebook_progress_event(event: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a machine-readable progress event for notebook-native rendering."""
    message = {"event": event, "payload": payload or {}}
    sys.stdout.write(PROGRESS_EVENT_PREFIX + json.dumps(message, default=str, sort_keys=True) + "\n")
    sys.stdout.flush()


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
    """Return rich, plain, notebook, or off for progress rendering.

    Rich live progress bars are used when stdout is attached to a real terminal
    or pseudo-terminal. Notebooks should run the CLI through a pseudo-terminal
    when animated bars are desired; otherwise auto mode falls back to the
    low-noise plain renderer to avoid repeated live-render frames in captured logs.
    """
    if not enabled:
        return "off"
    normalized = (style or "auto").strip().casefold()
    if normalized not in {"auto", "rich", "plain", "notebook"}:
        raise typer.BadParameter("progress style must be one of: auto, rich, plain, notebook")
    if normalized == "auto":
        # FORCE_COLOR can make Rich consider a pipe terminal-like, which is
        # exactly what creates repeated live-render frames in notebooks. Require
        # both Rich terminal support and an actual TTY file descriptor for live bars.
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
    """Create a low-noise progress callback for notebooks, pipes, and logs."""

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


def _make_notebook_discovery_progress_callback(lock: threading.Lock):
    """Emit discovery progress events for a notebook-native renderer.

    This avoids Rich live-render escape sequences in notebook subprocess output.
    The notebook updates a single HTML progress panel in place instead of
    printing one line for every refresh frame.
    """

    def callback(event: str, payload: dict[str, Any]) -> None:
        with lock:
            _emit_notebook_progress_event(event, payload)

    return callback




def _make_rich_validation_progress_callback(progress: Progress, lock: threading.Lock):
    tasks: dict[str, int] = {}
    state: dict[str, Any] = {"counts": {}}

    def _counts(payload: dict[str, Any]) -> str:
        return (
            f"live {payload.get('live', 0)} | dead {payload.get('dead', 0)} | "
            f"restricted {payload.get('restricted', 0)} | decode {payload.get('decode_failed', 0)} | "
            f"static {payload.get('static_image_asset', 0)} | unknown {payload.get('unknown', 0)}"
        )

    def callback(event: str, payload: dict[str, Any]) -> None:
        with lock:
            if event == "validation_candidates_selected":
                state["selected"] = payload
            elif event == "hls_validation_started":
                total = int(payload.get("total") or 0)
                tasks["hls"] = progress.add_task(f"Validating HLS playlists — {_counts(payload)}", total=total or 1)
                if total == 0:
                    progress.update(tasks["hls"], completed=1)
            elif event == "hls_validation_processed":
                task = tasks.get("hls")
                if task is not None:
                    progress.update(task, completed=int(payload.get("processed") or 0), description=f"Validating HLS playlists — {_counts(payload)}")
            elif event == "hls_validation_complete":
                task = tasks.get("hls")
                if task is not None:
                    total = int(payload.get("total") or 0)
                    progress.update(task, completed=total or 1, description=f"HLS validation complete — {_counts(payload)}")
            elif event == "image_validation_started":
                total = int(payload.get("total") or 0)
                tasks["image"] = progress.add_task(f"Validating image snapshots — {_counts(payload)}", total=total or 1)
                if total == 0:
                    progress.update(tasks["image"], completed=1)
            elif event == "image_validation_processed":
                task = tasks.get("image")
                if task is not None:
                    progress.update(task, completed=int(payload.get("processed") or 0), description=f"Validating image snapshots — {_counts(payload)}")
            elif event == "image_validation_complete":
                task = tasks.get("image")
                if task is not None:
                    total = int(payload.get("total") or 0)
                    progress.update(task, completed=total or 1, description=f"Image validation complete — {_counts(payload)}")
            elif event == "output_writing_started":
                tasks["outputs"] = progress.add_task("Writing outputs", total=5)
            elif event == "output_writing_step":
                task = tasks.get("outputs")
                if task is not None:
                    completed = min(5, int(progress.tasks[task].completed) + 1)
                    progress.update(task, completed=completed, description=f"Writing outputs — {payload.get('step', 'step')}")
            elif event == "artifact_packaging_started":
                task = tasks.get("outputs")
                if task is not None:
                    progress.update(task, completed=4, description="Packaging review artifacts")
            elif event == "artifact_packaging_complete":
                task = tasks.get("outputs")
                if task is not None:
                    progress.update(task, completed=5, description="Outputs packaged")
    return callback


def _make_plain_validation_progress_callback(console: Console, lock: threading.Lock):
    state: dict[str, int] = {"hls_bucket": -1, "image_bucket": -1}

    def _bucket(done: int, total: int) -> int:
        return 10 if total <= 0 else min(10, int((done / total) * 10))

    def callback(event: str, payload: dict[str, Any]) -> None:
        with lock:
            if event == "hls_validation_started":
                console.print(f"Progress: validating HLS playlists ({payload.get('total', 0)} candidates)...")
            elif event == "hls_validation_processed":
                done = int(payload.get("processed") or 0); total = int(payload.get("total") or 0)
                b = _bucket(done, total)
                if b != state.get("hls_bucket"):
                    state["hls_bucket"] = b
                    console.print(f"Progress: HLS validation {done}/{total} · live {payload.get('live', 0)} · dead {payload.get('dead', 0)} · restricted {payload.get('restricted', 0)} · decode {payload.get('decode_failed', 0)}")
            elif event == "image_validation_started":
                console.print(f"Progress: validating image snapshots ({payload.get('total', 0)} candidates)...")
            elif event == "image_validation_processed":
                done = int(payload.get("processed") or 0); total = int(payload.get("total") or 0)
                b = _bucket(done, total)
                if b != state.get("image_bucket"):
                    state["image_bucket"] = b
                    console.print(f"Progress: image validation {done}/{total} · live {payload.get('live', 0)} · static {payload.get('static_image_asset', 0)} · unknown {payload.get('unknown', 0)}")
            elif event == "output_writing_started":
                console.print("Progress: writing outputs...")
            elif event == "artifact_packaging_started":
                console.print("Progress: packaging review artifacts...")
            elif event == "artifact_packaging_complete":
                console.print("Progress: review artifacts packaged.")
    return callback


def _make_notebook_validation_progress_callback(lock: threading.Lock):
    def callback(event: str, payload: dict[str, Any]) -> None:
        with lock:
            _emit_notebook_progress_event(event, payload)
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
    show_progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress while resolving, discovering, enriching coordinates, validating, and writing outputs."),
    progress_style: str = typer.Option("auto", "--progress-style", help="Progress renderer: auto, rich, plain, or notebook. Use notebook for stable in-place Jupyter/Colab progress bars."),
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
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(config=cfg)
    console.print(f"[bold]Profile:[/bold] {cfg.profile.value}")
    console.print(f"[bold]Validation enabled:[/bold] {cfg.validation_enabled}")
    console.print(f"[bold]LLM provider:[/bold] {cfg.llm_provider}")
    console.print(f"[bold]Target-intent model:[/bold] {cfg.target_intent_model}")
    console.print(f"[bold]Discovery mode:[/bold] {cfg.discovery_mode.value}")
    console.print(f"[bold]Sources file:[/bold] {cfg.sources_file}")

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
        elif progress_mode == "notebook":
            _emit_notebook_progress_event("target_resolution_started", {"completed": 0, "total": 1, "description": "Resolving targets"})

        targets = TargetResolver(cfg).resolve_all()

        if progress_mode == "rich":
            assert progress is not None
            progress.update(resolve_task, completed=1, description="Resolved targets")
        elif progress_mode == "plain":
            console.print(f"Progress: resolved {len(targets)} target(s).")
        elif progress_mode == "notebook":
            _emit_notebook_progress_event("target_resolution_complete", {"completed": len(targets), "total": max(1, len(targets)), "targets": len(targets)})

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
            elif progress_mode == "notebook":
                _emit_notebook_progress_event("target_discovery_started", {"target_id": target.target_id, "target_label": label})
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
                elif progress_mode == "notebook":
                    callback = _make_notebook_discovery_progress_callback(progress_lock)
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

        state.candidate_sets_by_target = per_target_sets
        merged = CandidateSet.merge(list(per_target_sets.values()))
        state.candidates = merged
        console.print(
            f"[bold]Candidates:[/bold] raw={len(merged.raw)} unique={len(merged.unique)} "
            f"coordinate_bearing={len(merged.coordinate_bearing)} targets={len(per_target_sets)}"
        )

        validation_callback = None
        if progress_mode == "rich":
            assert progress is not None
            validation_callback = _make_rich_validation_progress_callback(progress, progress_lock)
        elif progress_mode == "plain":
            validation_callback = _make_plain_validation_progress_callback(console, progress_lock)
        elif progress_mode == "notebook":
            validation_callback = _make_notebook_validation_progress_callback(progress_lock)
        validation, outputs = ReviewAndValidationPipeline(cfg, progress_callback=validation_callback).run(runnable_targets, merged)
    state.validation = validation
    state.outputs = outputs
    write_json(cfg.output_dir / "logs" / "run_summary.json", state.to_dict())
    write_json(cfg.output_dir / "logs" / "output_summary.json", state.outputs.__dict__)
    # Repackage once run-level diagnostics are written. Notebook-created logs are
    # also included when present in the output directory.
    try:
        outputs.review_artifacts_zip = str(ReviewAndValidationPipeline(cfg)._package_review_artifacts())
        state.outputs = outputs
        write_json(cfg.output_dir / "logs" / "output_summary.json", state.outputs.__dict__)
    except Exception as exc:
        state.warnings.append(f"review_artifacts_repackage_failed: {exc!r}")
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


if __name__ == "__main__":
    app()
