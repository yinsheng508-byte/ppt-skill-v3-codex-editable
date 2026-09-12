from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .paths import decisions_dir, legacy_decisions_dir
from .validation import ValidationError


def migrate_decisions_layout(run_dir: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    root = Path(run_dir)
    legacy = legacy_decisions_dir(root)
    target = decisions_dir(root)
    moved: list[str] = []
    skipped: list[str] = []
    conflicts: list[str] = []

    if not legacy.exists():
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
        return {
            "status": "already_current",
            "run_dir": str(root),
            "legacy_dir": str(legacy),
            "decisions_dir": str(target),
            "moved": moved,
            "skipped": skipped,
            "conflicts": conflicts,
            "legacy_removed": not legacy.exists(),
            "dry_run": dry_run,
        }

    items = sorted(legacy.iterdir(), key=lambda path: path.name)
    for item in sorted(legacy.iterdir(), key=lambda path: path.name):
        destination = target / item.name
        if destination.exists():
            if item.is_file() and destination.is_file() and item.read_bytes() == destination.read_bytes():
                skipped.append(item.name)
                continue
            conflicts.append(item.name)
            continue
        moved.append(item.name)

    if conflicts:
        raise ValidationError("legacy _decisions contains conflicts: " + ", ".join(conflicts))

    legacy_removed = False
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        for item in items:
            destination = target / item.name
            if destination.exists() and item.is_file() and destination.is_file() and item.read_bytes() == destination.read_bytes():
                item.unlink()
                continue
            if not destination.exists():
                shutil.move(str(item), str(destination))
        try:
            legacy.rmdir()
            legacy_removed = True
        except OSError:
            legacy_removed = False

    return {
        "status": "migrated" if moved or skipped else "already_current",
        "run_dir": str(root),
        "legacy_dir": str(legacy),
        "decisions_dir": str(target),
        "moved": moved,
        "skipped": skipped,
        "conflicts": conflicts,
        "legacy_removed": legacy_removed,
        "dry_run": dry_run,
    }
