from __future__ import annotations

import json
import sys
from typing import Any

PROGRESS_EVENT_PREFIX = "__CAMERA_DISCOVERY_PROGRESS__ "


def emit_progress_event(event: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a machine-readable CLI progress event.

    The event stream is part of the application CLI contract. Presentation of
    these events in terminals, logs, or other UIs is handled outside
    the core progress-event contract.
    """
    message = {"event": event, "payload": payload or {}}
    sys.stdout.write(PROGRESS_EVENT_PREFIX + json.dumps(message, default=str, sort_keys=True) + "\n")
    sys.stdout.flush()
