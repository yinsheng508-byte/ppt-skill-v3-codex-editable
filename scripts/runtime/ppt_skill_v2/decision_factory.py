from __future__ import annotations

from pathlib import Path
from typing import Any

from .decisions import record_decision
from .education_context import is_k12_lesson_plan_required, load_education_context
from .paths import decisions_dir
from .state import read_state, stage4_lesson_plan_required
from .time_utils import now_iso
from .validation import (
    DECISION_ROUTES,
    DECISIONS_REQUIRING_USER_CONFIRMATION,
    ValidationError,
    validate_controller_decision,
)


DEFAULT_ALLOWED_ACTIONS: dict[str, list[str]] = {
    "stage1_ready_for_user_review": [],
    "approve_stage1_start_stage2": ["dispatch_stage2_cover_options", "record_image_generation_results"],
    "request_stage1_revision": ["revise_stage1_plan", "validate_stage1"],
    "stage2_cover_options_ready_for_user_review": [],
    "approve_stage2_cover_style_start_image_deck": ["promote_selected_cover_option", "dispatch_stage2_trial_first5_packets"],
    "request_stage2_cover_style_revision": ["revise_stage2_cover_options"],
    "stage2_trial_first5_ready_for_user_review": [],
    "approve_stage2_trial_first5_continue_remaining": ["promote_stage2_trial_first5", "dispatch_stage2_remaining_packets"],
    "request_stage2_trial_first5_revision": ["revise_stage2_trial_first5"],
    "stage2_ready_for_user_review": [],
    "approve_stage2_start_stage3": ["record_text_unit_split_plan", "record_text_ownership_map", "dispatch_stage3_background_packets"],
    "approve_stage2_skip_stage3_start_script_output": ["author_stage4_speaker_script", "render_stage4_script_docx_pdf"],
    "request_stage2_revision": ["revise_stage2_image_deck"],
    "reopen_stage3_sample_after_stage4": [
        "record_text_unit_split_plan",
        "record_text_ownership_map",
        "dispatch_stage3_background_packets",
        "record_image_generation_results",
        "record_editable_coordinate_plan",
    ],
    "approve_stage3_coordinate_plan_start_text_fill": ["build_editable_brief", "build_officecli_coordinate_deck"],
    "request_stage3_coordinate_plan_revision": ["revise_editable_coordinate_plan"],
    "stage3_ready_for_user_review": [],
    "approve_stage3_start_script_output": ["author_stage4_speaker_script", "render_stage4_script_docx_pdf"],
    "request_stage3_revision": ["revise_stage3_editable_deck"],
    "stage4_script_completed": [],
}


def make_decision(
    run_dir: str | Path,
    *,
    decision_type: str,
    notes: str,
    user_confirmed: bool = False,
    controller_reviewed: bool = True,
    confirmed_files: list[str] | None = None,
    allowed_actions: list[str] | None = None,
    slide_indices: list[int] | None = None,
    image_generation_route: str | None = None,
) -> dict[str, Any]:
    if decision_type not in DECISION_ROUTES:
        raise ValidationError(f"unsupported decision type: {decision_type}")
    if decision_type in DECISIONS_REQUIRING_USER_CONFIRMATION and not user_confirmed:
        raise ValidationError("user_confirmed is required for this decision type")
    if not notes.strip():
        raise ValidationError("decision notes are required")
    root = Path(run_dir)
    state = read_state(root)
    from_stage, to_stage = DECISION_ROUTES[decision_type]
    if state["current_stage"] != from_stage:
        raise ValidationError(f"{decision_type} requires current_stage={from_stage}, got {state['current_stage']}")
    basis: dict[str, Any] = {"notes": notes}
    if confirmed_files:
        basis["confirmed_files"] = confirmed_files
    if slide_indices:
        basis["slide_indices"] = _normalize_slide_indices(slide_indices)
    if image_generation_route:
        basis["image_generation_route"] = image_generation_route
    execution: dict[str, Any] = {
        "allowed_actions": allowed_actions if allowed_actions is not None else _default_allowed_actions(root, state, decision_type),
    }
    if slide_indices:
        execution["slide_indices"] = _normalize_slide_indices(slide_indices)
    if image_generation_route:
        execution["image_generation_route"] = image_generation_route
    decision = validate_controller_decision(
        {
            "schema_version": "2.0",
            "decision_id": _next_decision_id(root, decision_type),
            "project_name": state["project_name"],
            "run_dir": state["run_dir"],
            "decision_type": decision_type,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "actor": "main_controller",
            "user_confirmed": user_confirmed,
            "controller_reviewed": controller_reviewed,
            "basis": basis,
            "execution": execution,
            "created_at": now_iso(),
        }
    )
    path = record_decision(root, decision)
    return {
        "status": "decision_recorded",
        "path": str(path),
        "decision": decision,
    }


def _next_decision_id(root: Path, decision_type: str) -> str:
    max_index = 0
    for path in decisions_dir(root).glob("*.json"):
        prefix = path.stem.split("_", 1)[0]
        if prefix.isdigit():
            max_index = max(max_index, int(prefix))
    return f"{max_index + 1:04d}_{decision_type}"


def _default_allowed_actions(root: Path, state: dict[str, Any], decision_type: str) -> list[str]:
    actions = list(DEFAULT_ALLOWED_ACTIONS.get(decision_type, []))
    if decision_type in {"approve_stage2_skip_stage3_start_script_output", "approve_stage3_start_script_output"} and _requires_lesson_plan(root, state):
        for action in ("author_stage4_lesson_plan", "render_stage4_lesson_plan_docx_pdf"):
            if action not in actions:
                actions.append(action)
    return actions


def _requires_lesson_plan(root: Path, state: dict[str, Any]) -> bool:
    if stage4_lesson_plan_required(state):
        return True
    try:
        context = load_education_context(root, state=state)
    except ValidationError:
        return False
    return is_k12_lesson_plan_required(context)


def _normalize_slide_indices(slide_indices: list[int]) -> list[int]:
    normalized = sorted(set(slide_indices))
    if any(isinstance(index, bool) or not isinstance(index, int) or index < 1 for index in normalized):
        raise ValidationError("slide indices must contain positive integers")
    return normalized
