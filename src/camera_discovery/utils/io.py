from __future__ import annotations
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path): return str(obj)
    if isinstance(obj, Enum): return obj.value
    if is_dataclass(obj): return asdict(obj)
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")
def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
def write_jsonl(path: Path, rows: list[dict[str, Any]], *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row, sort_keys=True, default=_json_default) + "\n")
