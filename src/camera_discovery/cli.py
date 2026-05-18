from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from camera_discovery.core.config import load_run_config
from camera_discovery.core.models import CandidateSet, RunState, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
from camera_discovery.utils.io import write_json
import json

app = typer.Typer(help="Simplified public camera discovery pipeline", no_args_is_help=True)
console = Console()


def _make_progress(console: Console, *, enabled: bool) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        disable=not enabled,
    )


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
                progress.update(task_id, description=f"Enriching coordinates for {label}: {payload.get('unique', 0)} unique")
            elif event == "scope_review_started":
                progress.update(task_id, description=f"Scoping and reviewing {label}")
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
    show_progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress bars while resolving, discovering, and writing outputs."),
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

    progress = _make_progress(console, enabled=show_progress)
    with progress:
        resolve_task = progress.add_task("Resolving targets", total=1)
        targets = TargetResolver(cfg).resolve_all()
        progress.update(resolve_task, completed=1, description="Resolved targets")

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
            target_tasks[target.target_id] = progress.add_task(f"Discovering {label}", total=None)
            target_progress_state[target.target_id] = {"total": 0, "completed": 0}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(runnable_targets))) as pool:
            futures = {}
            for target in runnable_targets:
                callback = _make_discovery_progress_callback(progress, target_tasks[target.target_id], target_progress_state[target.target_id], progress_lock)
                engine = CandidateDiscoveryEngine(cfg, progress_callback=callback)
                futures[pool.submit(engine.discover, target)] = target
            for future in concurrent.futures.as_completed(futures):
                target = futures[future]
                try:
                    per_target_sets[target.target_id] = future.result()
                finally:
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

        validation_task = progress.add_task("Validating streams and writing outputs", total=1)
        validation, outputs = ReviewAndValidationPipeline(cfg).run(runnable_targets, merged)
        progress.update(validation_task, completed=1, description="Validation and outputs complete")
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


if __name__ == "__main__":
    app()
