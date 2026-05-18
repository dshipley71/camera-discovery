from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from camera_discovery.core.config import load_run_config
from camera_discovery.core.models import CandidateSet, RunState, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
from camera_discovery.utils.io import write_json
import json

app = typer.Typer(help="Simplified public camera discovery pipeline", no_args_is_help=True)
console = Console()


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

    targets = TargetResolver(cfg).resolve_all()
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(runnable_targets))) as pool:
        futures = {}
        for target in runnable_targets:
            console.print(f"[bold]Discovering:[/bold] {target.target_label or target.canonical_target or target.target_id}")
            futures[pool.submit(CandidateDiscoveryEngine(cfg).discover, target)] = target
        for future in concurrent.futures.as_completed(futures):
            target = futures[future]
            per_target_sets[target.target_id] = future.result()
    state.candidate_sets_by_target = per_target_sets
    merged = CandidateSet.merge(list(per_target_sets.values()))
    state.candidates = merged
    console.print(
        f"[bold]Candidates:[/bold] raw={len(merged.raw)} unique={len(merged.unique)} "
        f"coordinate_bearing={len(merged.coordinate_bearing)} targets={len(per_target_sets)}"
    )

    validation, outputs = ReviewAndValidationPipeline(cfg).run(runnable_targets, merged)
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
