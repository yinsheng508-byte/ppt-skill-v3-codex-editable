from __future__ import annotations

from pathlib import Path


STATE_DIR = "_state"
DECISIONS_DIR = "decisions"
LEGACY_DECISIONS_DIR = "_decisions"
PROJECT_STATE_FILE = "project_state.json"
EVENTS_FILE = "events.jsonl"
CONTROL_DIR = "control"


def state_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / STATE_DIR


def decisions_dir(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / DECISIONS_DIR


def legacy_decisions_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / LEGACY_DECISIONS_DIR


def project_state_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / PROJECT_STATE_FILE


def events_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / EVENTS_FILE


def control_dir(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / CONTROL_DIR


def decision_path(run_dir: str | Path, decision_id: str) -> Path:
    return decisions_dir(run_dir) / f"{decision_id}.json"


def legacy_decision_path(run_dir: str | Path, decision_id: str) -> Path:
    return legacy_decisions_dir(run_dir) / f"{decision_id}.json"


def existing_decision_path(run_dir: str | Path, decision_id: str) -> Path:
    preferred = decision_path(run_dir, decision_id)
    if preferred.exists():
        return preferred
    legacy = legacy_decision_path(run_dir, decision_id)
    if legacy.exists():
        return legacy
    return preferred


def iter_decision_paths(run_dir: str | Path) -> list[Path]:
    paths_by_name: dict[str, Path] = {}
    for directory in (legacy_decisions_dir(run_dir), decisions_dir(run_dir)):
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            paths_by_name[path.name] = path
    return [paths_by_name[name] for name in sorted(paths_by_name)]
