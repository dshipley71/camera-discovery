from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import BlockedSource, SourceEntry, SourcePolicy

_ALLOWED_SECTION_NAMES = {"allowed sources", "allow sources", "sources", "directory sources"}
_BLOCKED_SECTION_NAMES = {"blocked sources", "block sources", "deny sources", "blocked patterns"}


def load_source_policy(source_file: str | Path | None, extra_block_patterns: Iterable[str] | None = None) -> SourcePolicy:
    path = Path(source_file).expanduser() if source_file else None
    policy = SourcePolicy(source_file=path)
    if path and path.exists():
        parsed = parse_sources_markdown(path.read_text(encoding="utf-8"))
        policy.allowed_sources.extend(parsed.allowed_sources)
        policy.blocked_sources.extend(parsed.blocked_sources)
    for pattern in extra_block_patterns or []:
        if pattern and pattern.strip():
            policy.blocked_sources.append(BlockedSource(pattern=pattern.strip(), reason="cli_block_pattern"))
    return policy


def parse_sources_markdown(text: str) -> SourcePolicy:
    policy = SourcePolicy()
    section: str | None = None
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.startswith("#"):
            section = line.lstrip("#").strip().casefold()
            idx += 1
            continue
        if line.startswith("|") and idx + 1 < len(lines) and _is_separator(lines[idx + 1]):
            headers = [_normalize_header(cell) for cell in _split_table_row(line)]
            rows: list[dict[str, str]] = []
            idx += 2
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                values = _split_table_row(lines[idx])
                row = {headers[i]: values[i].strip() if i < len(values) else "" for i in range(len(headers))}
                rows.append(row)
                idx += 1
            _consume_rows(policy, section, headers, rows)
            continue
        idx += 1
    return policy


def _consume_rows(policy: SourcePolicy, section: str | None, headers: list[str], rows: list[dict[str, str]]) -> None:
    header_set = set(headers)
    if section in _BLOCKED_SECTION_NAMES or {"pattern"}.issubset(header_set) and not {"url"}.issubset(header_set):
        for row in rows:
            pattern = row.get("pattern", "").strip()
            if pattern:
                policy.blocked_sources.append(BlockedSource(pattern=pattern, reason=_none_if_blank(row.get("reason"))))
        return
    if section in _ALLOWED_SECTION_NAMES or "url" in header_set:
        for row in rows:
            url = row.get("url", "").strip()
            if not url:
                continue
            source_type = (row.get("type") or row.get("source_type") or "page").strip().casefold()
            if source_type not in {"page", "feed", "direct_hls", "site", "dynamic"}:
                source_type = "page"
            policy.allowed_sources.append(
                SourceEntry(
                    name=row.get("name", "").strip() or url,
                    url=url,
                    source_type=source_type,  # type: ignore[arg-type]
                    scope_hint=_none_if_blank(row.get("scope_hint")),
                    enabled=_truthy(row.get("enabled"), default=True),
                    notes=_none_if_blank(row.get("notes")),
                )
            )


def _split_table_row(line: str) -> list[str]:
    trimmed = line.strip().strip("|")
    return [cell.strip() for cell in trimmed.split("|")]


def _is_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(set(cell.replace(":", "").strip()) <= {"-"} and "-" in cell for cell in cells)


def _normalize_header(value: str) -> str:
    return value.strip().casefold().replace(" ", "_").replace("-", "_")


def _none_if_blank(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _truthy(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "y", "enabled"}
