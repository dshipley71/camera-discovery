from __future__ import annotations

import concurrent.futures
import json
import threading
from collections import Counter
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
from camera_discovery.core.models import CameraCandidate, CandidateSet, HarvestInputMode, RunConfig, RunState, TargetContext, TrustPolicy
from camera_discovery.discovery.candidate_priority import priority_bucket_counts, prioritize_candidate_set
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_handoff import (
    describe_harvest_handoff,
    harvest_records_to_candidates,
    load_harvest_handoff_bundle,
)
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
from camera_discovery.sources import load_source_policy
from camera_discovery.utils.io import write_json


def execute_discovery_run(cfg: RunConfig, *, console: Console, progress_mode: str) -> RunState:
    """Run the full discovery workflow for a prepared RunConfig."""
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(config=cfg)
    sources_exists = bool(cfg.sources_file and cfg.sources_file.exists())
    console.print("[bold]Pipeline mode:[/bold] normal discovery pipeline")
    console.print(f"[bold]Query:[/bold] {cfg.query}")
    console.print(f"[bold]Output dir:[/bold] {cfg.output_dir}")
    console.print(f"[bold]Profile:[/bold] {cfg.profile.value}")
    console.print(f"[bold]Validation enabled:[/bold] {cfg.validation_enabled} (trusted outputs require validation)")
    console.print(f"[bold]LLM provider:[/bold] {cfg.llm_provider}")
    console.print(f"[bold]Target-intent model:[/bold] {cfg.target_intent_model}")
    console.print(f"[bold]Discovery mode:[/bold] {cfg.discovery_mode.value}")
    console.print(f"[bold]Sources file:[/bold] {cfg.sources_file} (exists={sources_exists})")
    console.print(f"[bold]Browser capture:[/bold] enabled={cfg.enable_browser_capture} backend={cfg.browser_backend}")
    if cfg.harvest_input:
        handoff_description = describe_harvest_handoff(cfg.harvest_input)
        console.print(f"[bold]Harvest input:[/bold] {cfg.harvest_input} (exists={handoff_description.get('exists')})")
        console.print(f"[bold]Harvest input mode:[/bold] {cfg.harvest_input_mode.value}")
        if handoff_description.get("media_filter"):
            console.print(
                f"[bold]Harvest handoff filter:[/bold] {handoff_description.get('media_filter')} "
                f"default={handoff_description.get('handoff_default_scope')} artifact={handoff_description.get('default_artifact')}"
            )
        console.print("[bold]Harvest input trust:[/bold] source-provided, unvalidated, untrusted seed data")

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
        native_discovery_enabled = not (cfg.harvest_input and cfg.harvest_input_mode == HarvestInputMode.HANDOFF_ONLY)
        if cfg.harvest_input:
            mode_message = (
                "enabled; harvest input will seed normal discovery"
                if native_discovery_enabled
                else "disabled by handoff-only harvest input mode"
            )
            console.print(f"[bold]Normal discovery:[/bold] {mode_message}")

        target_tasks: dict[str, int] = {}
        target_progress_state: dict[str, dict[str, int]] = {}
        if native_discovery_enabled:
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

            try:
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
                    try:
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
                    except KeyboardInterrupt:
                        for future in futures:
                            future.cancel()
                        completed = sum(1 for future in futures if future.done())
                        message = f"Run interrupted during native discovery after {completed}/{len(futures)} target task(s)."
                        console.print(f"[red]{message} Partial artifacts may be available under {cfg.output_dir}.[/red]")
                        state.warnings.append(message)
                        write_json(cfg.output_dir / "logs" / "run_summary.json", state.to_dict())
                        raise typer.Exit(code=130)
            except KeyboardInterrupt:
                message = "Run interrupted during native discovery."
                console.print(f"[red]{message} Partial artifacts may be available under {cfg.output_dir}.[/red]")
                state.warnings.append(message)
                write_json(cfg.output_dir / "logs" / "run_summary.json", state.to_dict())
                raise typer.Exit(code=130)
        elif progress_mode == "plain":
            console.print("Progress: native discovery disabled by handoff-only harvest input mode.")
        elif progress_mode == "events":
            _emit_progress_stream_event(
                "native_discovery_skipped",
                {"reason": "handoff-only harvest input mode", "harvest_input_mode": cfg.harvest_input_mode.value},
            )

        native_candidate_summary = _candidate_set_summary(CandidateSet.merge(list(per_target_sets.values())))
        native_candidate_summary["enabled"] = native_discovery_enabled
        harvest_input_summary: dict[str, object] = {
            "loaded": False,
            "mode": cfg.harvest_input_mode.value if cfg.harvest_input else None,
            "normal_discovery_enabled": native_discovery_enabled,
        }
        if cfg.harvest_input:
            if progress_mode == "plain":
                console.print("Progress: loading harvest input...")
            elif progress_mode == "events":
                _emit_progress_stream_event("harvest_input_loaded", {"path": str(cfg.harvest_input), "stage": "started"})
            try:
                handoff = load_harvest_handoff_bundle(cfg.harvest_input)
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            source_policy = load_source_policy(cfg.sources_file, cfg.block_patterns)
            total_handoff_candidates = 0
            harvest_media_counter: Counter[str] = Counter()
            harvest_scope_counter: Counter[str] = Counter()
            for target in runnable_targets:
                handoff_candidates = harvest_records_to_candidates(
                    handoff.records,
                    target_id=target.target_id,
                    target_index=target.target_index,
                    target_label=target.target_label or target.canonical_target,
                    source_policy=source_policy,
                )
                _scope_harvest_input_candidates(handoff_candidates, target)
                total_handoff_candidates += len(handoff_candidates)
                harvest_media_counter.update(str((c.source_metadata or {}).get("media_type") or "unknown") for c in handoff_candidates)
                harvest_scope_counter.update(c.scope_status for c in handoff_candidates)
                per_target_sets[f"{target.target_id}:harvest_input"] = _candidate_set_from_scoped_harvest(handoff_candidates)
            if cfg.harvest_input_mode == HarvestInputMode.HANDOFF_ONLY:
                _assert_handoff_only_bounds(
                    console,
                    record_count=len(handoff.records),
                    target_count=len(runnable_targets),
                    candidate_count=total_handoff_candidates,
                    loaded_artifact=handoff.loaded_artifact,
                    native_discovery_summary=native_candidate_summary,
                    output_dir=cfg.output_dir,
                )
            harvest_input_summary = {
                "loaded": True,
                "mode": cfg.harvest_input_mode.value,
                "source_path": str(cfg.harvest_input),
                "loaded_artifact": handoff.loaded_artifact,
                "source_file": str(handoff.source_file) if handoff.source_file else None,
                "schema_version": handoff.schema_version,
                "media_filter": handoff.media_filter,
                "handoff_default_scope": handoff.handoff_default_scope,
                "record_count": len(handoff.records),
                "candidate_count": total_handoff_candidates,
                "by_media_type": dict(sorted(harvest_media_counter.items())),
                "by_scope_status": dict(sorted(harvest_scope_counter.items())),
                "filtered_by_handoff_media_filter": handoff.filtered_by_handoff_media_filter,
                "normal_discovery_enabled": native_discovery_enabled,
            }
            processing_note = (
                "normal discovery is disabled by handoff-only mode"
                if cfg.harvest_input_mode == HarvestInputMode.HANDOFF_ONLY
                else "normal discovery is enabled because seed mode was requested"
            )
            state.warnings.append(
                f"Loaded {total_handoff_candidates} unvalidated/untrusted candidate(s) from harvest input; {processing_note}."
            )
            console.print(
                f"[bold]Harvest input candidates:[/bold] {total_handoff_candidates} "
                f"from {len(handoff.records)} record(s) in {handoff.loaded_artifact}; "
                f"media={dict(sorted(harvest_media_counter.items()))}; "
                f"scope={dict(sorted(harvest_scope_counter.items()))}"
            )
            if progress_mode == "events":
                _emit_progress_stream_event("harvest_input_loaded", {"path": str(cfg.harvest_input), "candidates": total_handoff_candidates, "stage": "complete"})

        state.candidate_sets_by_target = per_target_sets
        merged = prioritize_candidate_set(CandidateSet.merge(list(per_target_sets.values())))
        state.candidates = merged
        combined_summary = _candidate_set_summary(merged)
        _write_pipeline_candidate_summary(cfg, native_candidate_summary, harvest_input_summary, combined_summary)
        console.print(
            f"[bold]Candidates:[/bold] native_unique={native_candidate_summary['unique_candidates']} "
            f"harvest_input={harvest_input_summary.get('candidate_count', 0)} combined_unique={len(merged.unique)} "
            f"coordinate_bearing={len(merged.coordinate_bearing)} targets={len(per_target_sets)}"
        )

        if progress_mode == "rich":
            assert progress is not None
            validation_task = progress.add_task("Validating streams and writing outputs", total=1)
        elif progress_mode == "plain":
            console.print("Progress: validating streams and writing outputs...")
        elif progress_mode == "events":
            _emit_progress_stream_event("validation_started", {"completed": 0, "total": 1, "description": "Validating streams and writing outputs"})
        try:
            validation, outputs = ReviewAndValidationPipeline(cfg).run(runnable_targets, merged)
        except KeyboardInterrupt:
            message = "Run interrupted during validation/output writing."
            console.print(f"[red]{message} Partial artifacts may be available under {cfg.output_dir}.[/red]")
            state.warnings.append(message)
            write_json(cfg.output_dir / "logs" / "run_summary.json", state.to_dict())
            raise typer.Exit(code=130)
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


def _scope_harvest_input_candidates(candidates: list[CameraCandidate], target: TargetContext) -> None:
    bbox = target.bbox if target.bbox_verified else None
    for candidate in candidates:
        if candidate.has_coordinates and bbox:
            assert candidate.lat is not None and candidate.lon is not None
            if bbox["min_lat"] <= candidate.lat <= bbox["max_lat"] and bbox["min_lon"] <= candidate.lon <= bbox["max_lon"]:
                candidate.scope_status = "in_scope"
                candidate.reasons.append("harvest_input_coordinate_inside_verified_bbox")
            else:
                candidate.scope_status = "out_of_scope"
                candidate.trust_level = "rejected"
                candidate.reasons.append("harvest_input_coordinate_outside_verified_bbox")
        elif candidate.has_coordinates:
            candidate.scope_status = "review"
            candidate.reasons.append("harvest_input_coordinate_available_but_target_bbox_untrusted_or_missing")
        else:
            candidate.scope_status = "unknown"
            candidate.reasons.append("harvest_input_missing_candidate_coordinates")


def _assert_handoff_only_bounds(
    console: Console,
    *,
    record_count: int,
    target_count: int,
    candidate_count: int,
    loaded_artifact: str | None,
    native_discovery_summary: dict[str, object],
    output_dir,
) -> None:
    native_unique = int(native_discovery_summary.get("unique_candidates") or 0)
    if native_unique:
        message = (
            f"Harvest handoff-only mode loaded {record_count} source record(s) but native discovery produced "
            f"{native_unique} candidate(s). Handoff-only mode must not run broad discovery or asset-host expansion. "
            "Use --harvest-input-mode seed to intentionally combine harvest input with normal discovery."
        )
        console.print(f"[red]{message}[/red]")
        write_json(output_dir / "logs" / "handoff_only_bounds_error.json", {"error": message})
        raise typer.Exit(code=2)

    url_level_artifacts = {"camera_urls_jsonl", "filtered_media_records"}
    if loaded_artifact in url_level_artifacts:
        expected_max = record_count * max(1, target_count)
        if candidate_count > expected_max:
            message = (
                f"Harvest handoff-only mode loaded {record_count} source record(s) but candidate preparation produced "
                f"{candidate_count} candidate(s). Handoff-only mode must not run broad discovery or asset-host expansion. "
                "Use --harvest-input-mode seed to intentionally combine harvest input with normal discovery."
            )
            console.print(f"[red]{message}[/red]")
            write_json(output_dir / "logs" / "handoff_only_bounds_error.json", {"error": message})
            raise typer.Exit(code=2)


def _candidate_set_from_scoped_harvest(candidates: list[CameraCandidate]) -> CandidateSet:
    return CandidateSet(
        raw=candidates,
        unique=candidates,
        coordinate_bearing=[c for c in candidates if c.has_coordinates],
        in_scope=[c for c in candidates if c.scope_status == "in_scope"],
        review=[c for c in candidates if c.scope_status in {"in_scope", "review", "unknown"}],
        rejected=[c for c in candidates if c.scope_status == "out_of_scope"],
    )


def _candidate_set_summary(candidates: CandidateSet) -> dict[str, object]:
    return {
        "raw_candidates": len(candidates.raw),
        "unique_candidates": len(candidates.unique),
        "coordinate_bearing_candidates": len(candidates.coordinate_bearing),
        "in_scope_candidates": len(candidates.in_scope),
        "review_candidates": len(candidates.review),
        "rejected_candidates": len(candidates.rejected),
        "by_media_type": dict(sorted(Counter(str((c.source_metadata or {}).get("media_type") or "unknown") for c in candidates.unique).items())),
        "by_scope_status": dict(sorted(Counter(c.scope_status for c in candidates.unique).items())),
        "by_discovery_method": dict(sorted(Counter(c.discovery_method for c in candidates.unique).items())),
        "by_priority_bucket": priority_bucket_counts(candidates.unique),
        "located_in_scope_candidates": sum(1 for c in candidates.unique if c.has_coordinates and c.scope_status == "in_scope"),
        "located_out_of_scope_candidates": sum(1 for c in candidates.unique if c.has_coordinates and c.scope_status == "out_of_scope"),
        "unlocated_candidates": sum(1 for c in candidates.unique if not c.has_coordinates),
    }


def _write_pipeline_candidate_summary(
    cfg: RunConfig,
    native_discovery: dict[str, object],
    harvest_input: dict[str, object],
    combined: dict[str, object],
) -> None:
    summary = {
        # Backward-compatible top-level counts now describe the combined set.
        "raw": combined["raw_candidates"],
        "unique": combined["unique_candidates"],
        "coordinate_bearing": combined["coordinate_bearing_candidates"],
        "in_scope": combined["in_scope_candidates"],
        "review": combined["review_candidates"],
        "rejected": combined["rejected_candidates"],
        "native_discovery": native_discovery,
        "harvest_input": harvest_input,
        "combined": {
            "candidate_count_before_scope": combined["unique_candidates"],
            "candidate_count_after_scope": combined["unique_candidates"],
            **combined,
        },
    }
    write_json(cfg.output_dir / "logs" / "candidate_discovery_summary.json", summary)
    write_json(cfg.output_dir / "logs" / "pipeline_candidate_summary.json", summary)
