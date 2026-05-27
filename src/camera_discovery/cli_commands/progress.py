from __future__ import annotations

import threading
from typing import Any

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from camera_discovery.core.progress_events import emit_progress_event


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
                total = int(payload.get("unique") or 0)
                state["coord_total"] = total
                state["coord_completed"] = 0
                state["coord_last_bucket"] = -1
                console.print(f"Progress: {label} — enriching coordinates for {total} unique candidates...")
            elif event == "coordinate_candidate_processed":
                completed = int(payload.get("processed") or state.get("coord_completed", 0) + 1)
                total = int(payload.get("total") or state.get("coord_total") or 0)
                state["coord_completed"] = completed
                current_bucket = _bucket(completed, total)
                should_report = completed == total or current_bucket > int(state.get("coord_last_bucket", -1))
                if should_report:
                    state["coord_last_bucket"] = current_bucket
                    denominator = total if total else "?"
                    console.print(
                        f"Progress: {label} — enriching coordinates {completed}/{denominator}; "
                        f"mapped {payload.get('coordinate_bearing', 0)}; "
                        f"metadata {payload.get('metadata_enriched', 0)}; "
                        f"geocoded {payload.get('geocode_enriched', 0)}; "
                        f"LLM {payload.get('llm_location_enriched', 0)}."
                    )
            elif event == "coordinate_enrichment_complete":
                total = int(payload.get("total") or state.get("coord_total") or 0)
                state["coord_completed"] = total
                console.print(
                    f"Progress: {label} — coordinate enrichment complete: "
                    f"mapped {payload.get('coordinate_bearing', 0)}/{total}; "
                    f"metadata {payload.get('metadata_enriched', 0)}; "
                    f"geocoded {payload.get('geocode_enriched', 0)}; "
                    f"LLM {payload.get('llm_location_enriched', 0)}."
                )
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

