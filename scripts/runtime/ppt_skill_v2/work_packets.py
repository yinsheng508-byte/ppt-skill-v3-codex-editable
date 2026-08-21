from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .drift_check import run_drift_check
from .events import append_event
from .json_io import read_json, write_json
from .paths import control_dir
from .state import read_state
from .time_utils import now_iso
from .validation import ValidationError


PACKET_STATUSES = {"active", "completed", "blocked", "failed"}
CLOSE_STATUSES = {"completed", "blocked", "failed"}
STAGES = {"stage0", "stage1", "stage2", "stage3", "stage4"}


def create_work_packet(
    run_dir: str | Path,
    *,
    stage: str,
    action: str,
    slide_indices: list[int] | None = None,
    allowed_commands: list[str] | None = None,
    input_artifacts: list[str] | None = None,
    expected_outputs: list[str] | None = None,
    stop_conditions: list[str] | None = None,
    requires_user_confirmation: bool = False,
    confirmation_decision_type: str | None = None,
) -> dict[str, Any]:
    root = Path(run_dir)
    if stage not in STAGES:
        raise ValidationError(f"unsupported work packet stage: {stage}")
    state = read_state(root)
    active = _read_active_packet(root)
    if active and active.get("status") == "active":
        raise ValidationError(f"active work packet already exists: {active.get('packet_id')}")
    drift = run_drift_check(root, action=action, persist=True)
    if not drift["ok"]:
        raise ValidationError(f"drift-check failed before creating work packet: {'; '.join(drift['issues'])}")
    packet = {
        "schema_version": "1.0",
        "packet_id": _next_packet_id(root, stage, action),
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "stage": stage,
        "action": action,
        "status": "active",
        "required_actor": state["required_actor"],
        "allowed_commands": allowed_commands or [action],
        "slide_scope": _slide_scope(slide_indices or []),
        "input_artifacts": input_artifacts or [],
        "input_hashes": {},
        "expected_outputs": expected_outputs or [],
        "stop_conditions": stop_conditions or _default_stop_conditions(requires_user_confirmation),
        "user_confirmation_boundary": {
            "required_after_completion": requires_user_confirmation,
            "decision_type": confirmation_decision_type,
        },
        "drift_guards": {
            "drift_check_path": "_state/control/drift_check.json",
            "issues": drift.get("issues", []),
            "warnings": drift.get("warnings", []),
        },
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    packet = validate_work_packet(packet)
    _write_packet(root, packet)
    write_json(control_dir(root) / "active_work_packet.json", packet)
    append_event(root, "work_packet_created", "runtime", packet_id=packet["packet_id"], action=action, stage=stage)
    return packet


def close_work_packet(run_dir: str | Path, packet_id: str, *, status: str, summary: str) -> dict[str, Any]:
    root = Path(run_dir)
    if status not in CLOSE_STATUSES:
        raise ValidationError(f"close status must be one of: {', '.join(sorted(CLOSE_STATUSES))}")
    if not summary.strip():
        raise ValidationError("completion summary is required when closing a work packet")
    packet = validate_work_packet(_load_packet(root, packet_id))
    if packet.get("status") != "active":
        raise ValidationError(f"work packet is not active: {packet_id}")
    packet["status"] = status
    packet["completion_summary"] = summary
    packet["closed_at"] = now_iso()
    packet["updated_at"] = now_iso()
    packet = validate_work_packet(packet)
    _write_packet(root, packet)
    write_json(control_dir(root) / "active_work_packet.json", packet)
    append_event(root, "work_packet_closed", "runtime", packet_id=packet["packet_id"], status=status)
    return packet


def validate_work_packet(packet: Any) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise ValidationError("work_packet must be an object")
    required = [
        "schema_version",
        "packet_id",
        "project_name",
        "run_dir",
        "stage",
        "action",
        "status",
        "required_actor",
        "allowed_commands",
        "slide_scope",
        "input_artifacts",
        "input_hashes",
        "expected_outputs",
        "stop_conditions",
        "user_confirmation_boundary",
        "drift_guards",
        "created_at",
        "updated_at",
    ]
    missing = [field for field in required if field not in packet]
    if missing:
        raise ValidationError(f"work_packet missing required fields: {', '.join(missing)}")
    if packet["schema_version"] != "1.0":
        raise ValidationError("work_packet.schema_version must be 1.0")
    for field in ("packet_id", "project_name", "run_dir", "stage", "action", "status", "required_actor", "created_at", "updated_at"):
        if not isinstance(packet.get(field), str) or not packet[field].strip():
            raise ValidationError(f"work_packet.{field} must be a non-empty string")
    if packet["stage"] not in STAGES:
        raise ValidationError("work_packet.stage is invalid")
    if packet["status"] not in PACKET_STATUSES:
        raise ValidationError("work_packet.status is invalid")
    for field in ("allowed_commands", "input_artifacts", "expected_outputs", "stop_conditions"):
        if not isinstance(packet.get(field), list):
            raise ValidationError(f"work_packet.{field} must be a list")
    for field in ("slide_scope", "input_hashes", "user_confirmation_boundary", "drift_guards"):
        if not isinstance(packet.get(field), dict):
            raise ValidationError(f"work_packet.{field} must be an object")
    boundary = packet["user_confirmation_boundary"]
    if not isinstance(boundary.get("required_after_completion"), bool):
        raise ValidationError("work_packet.user_confirmation_boundary.required_after_completion must be a boolean")
    if boundary.get("required_after_completion") and not isinstance(boundary.get("decision_type"), str):
        raise ValidationError("work_packet.user_confirmation_boundary.decision_type is required when confirmation is required")
    if packet["status"] in CLOSE_STATUSES and not isinstance(packet.get("completion_summary"), str):
        raise ValidationError("closed work_packet requires completion_summary")
    return packet


def _read_active_packet(root: Path) -> dict[str, Any] | None:
    path = control_dir(root) / "active_work_packet.json"
    if not path.exists():
        return None
    value = read_json(path)
    return value if isinstance(value, dict) else None


def _load_packet(root: Path, packet_id: str) -> dict[str, Any]:
    path = control_dir(root) / "work_packets" / f"{packet_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"work packet not found: {path}")
    return read_json(path)


def _write_packet(root: Path, packet: dict[str, Any]) -> Path:
    path = control_dir(root) / "work_packets" / f"{packet['packet_id']}.json"
    write_json(path, packet)
    return path


def _next_packet_id(root: Path, stage: str, action: str) -> str:
    base = f"{stage}_{_slug(action)}_{_timestamp_slug()}"
    candidate = base
    index = 1
    while (control_dir(root) / "work_packets" / f"{candidate}.json").exists():
        index += 1
        candidate = f"{base}_{index:02d}"
    return candidate


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value.replace("-", "_")).strip("_").lower()
    return slug or "action"


def _timestamp_slug() -> str:
    return re.sub(r"[^0-9]", "", now_iso())[:14]


def _slide_scope(slide_indices: list[int]) -> dict[str, Any]:
    if not slide_indices:
        return {"mode": "all_current_stage", "slide_indices": []}
    unique = sorted(set(slide_indices))
    if any(index < 1 for index in unique):
        raise ValidationError("slide indices must be positive integers")
    return {"mode": "slide_indices", "slide_indices": unique}


def _default_stop_conditions(requires_user_confirmation: bool) -> list[str]:
    conditions = [
        "stop_if_drift_check_fails",
        "stop_if_required_evidence_missing",
        "do_not_cross_stage_boundary_without_controller_decision",
    ]
    if requires_user_confirmation:
        conditions.append("stop_after_outputs_for_user_confirmation")
    return conditions
