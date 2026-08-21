from __future__ import annotations

from pathlib import Path


STATE_DIR = "_state"
DECISIONS_DIR = "_decisions"
PROJECT_STATE_FILE = "project_state.json"
EVENTS_FILE = "events.jsonl"
CONTROL_DIR = "control"


def state_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / STATE_DIR


def decisions_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / DECISIONS_DIR


def project_state_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / PROJECT_STATE_FILE


def events_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / EVENTS_FILE


def control_dir(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / CONTROL_DIR


def decision_path(run_dir: str | Path, decision_id: str) -> Path:
    return decisions_dir(run_dir) / f"{decision_id}.json"
