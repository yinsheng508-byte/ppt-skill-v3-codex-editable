from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import events_path
from .time_utils import now_iso


def append_event(run_dir: str | Path, event_type: str, actor: str, **payload: Any) -> dict[str, Any]:
    path = events_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event_type": event_type,
        "actor": actor,
        "created_at": now_iso(),
        **payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=False) + "\n")
    return event


def read_events(run_dir: str | Path) -> list[dict[str, Any]]:
    path = events_path(run_dir)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events
