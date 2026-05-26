from __future__ import annotations

import concurrent.futures
import json
import threading
from contextlib import nullcontext

import typer
from rich.console import Console

from camera_discovery.cli_commands.output import friendly_llm_error
from camera_discovery.cli_commands.progress import (
    _emit_progress_stream_event,
    _make_discovery_progress_callback,
    _make_event_stream_discovery_progress_callback,
    _make_plain_discovery_progress_callback,
    _make_progress,
)
from camera_discovery.core.models import CandidateSet, RunConfig, RunState, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_handoff import harvest_records_to_candidates, load_harvest_handoff
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
from camera_discovery.sources import load_source_policy
from camera_discovery.utils.io import write_json


def execute_discovery_run(cfg: RunConfig, *, console: Console, progress_mode: str) -> RunState:
    """Run the full discovery workflow for a prepared RunConfig."""
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
            message = friendly_llm_error(exc, cfg)
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
                f"  - {target.target_id}: {target.canonical_target or target.target_label or cfg.query} | "
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
    return state
