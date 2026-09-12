from __future__ import annotations

from pathlib import Path
from typing import Any

from .decisions import record_decision
from .education_context import is_k12_lesson_plan_required, load_education_context
from .image_routes import DEFAULT_IMAGE_GENERATION_ROUTE, IMAGE_ROUTE_OPENAI_IMAGE_API, normalize_image_generation_route
from .paths import iter_decision_paths
from .state import read_state, stage3_lesson_plan_required
from .time_utils import now_iso
from .validation import (
    DECISION_ROUTES,
    DECISIONS_REQUIRING_USER_CONFIRMATION,
    ValidationError,
    validate_controller_decision,
)


DEFAULT_ALLOWED_ACTIONS: dict[str, list[str]] = {
    "stage1_ready_for_user_review": [],
    "approve_stage1_start_stage2": ["dispatch_stage2_cover_options", "record_image_result"],
    "request_stage1_revision": ["revise_stage1_plan", "validate_stage1"],
    "stage2_cover_options_ready_for_user_review": [],
    "approve_stage2_cover_style_start_image_deck": ["promote_selected_cover_option", "dispatch_stage2_trial_first5"],
    "request_stage2_cover_style_revision": ["revise_stage2_cover_options"],
    "stage2_trial_first5_ready_for_user_review": [],
    "approve_stage2_trial_first5_continue_remaining": ["promote_stage2_trial_first5", "dispatch_stage2_remaining"],
    "request_stage2_trial_first5_revision": ["revise_stage2_trial_first5"],
    "stage2_ready_for_user_review": [],
    "approve_stage2_start_stage3": ["build_speaker_script"],
    "request_stage2_revision": ["revise_stage2_image_deck"],
    "stage3_outputs_completed": ["organize_deliverables"],
    "request_stage3_lesson_plan_revision": [
        "build_lesson_plan_context",
        "build_lesson_plan",
        "record_lesson_plan_qa",
    ],
    "stage4_deliverables_organized": [],
    "request_stage4_organize_revision": ["organize_deliverables"],
}

STAGE2_IMAGE_ROUTE_DECISIONS = {
    "approve_stage1_start_stage2",
    "approve_stage2_cover_style_start_image_deck",
    "approve_stage2_trial_first5_continue_remaining",
}

STAGE2_IMAGE_DISPATCH_ACTIONS = {
    "dispatch_stage2_cover_options",
    "dispatch_stage2_trial_first5",
    "dispatch_stage2_remaining",
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
        image_generation_route = normalize_image_generation_route(image_generation_route)
    resolved_image_generation_route = _default_image_generation_route(decision_type, image_generation_route)
    if resolved_image_generation_route:
        basis["image_generation_route"] = resolved_image_generation_route
    execution: dict[str, Any] = {
        "allowed_actions": (
            allowed_actions
            if allowed_actions is not None
            else _default_allowed_actions(root, state, decision_type, image_generation_route=resolved_image_generation_route)
        ),
    }
    if slide_indices:
        execution["slide_indices"] = _normalize_slide_indices(slide_indices)
    if resolved_image_generation_route:
        execution["image_generation_route"] = resolved_image_generation_route
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
    for path in iter_decision_paths(root):
        prefix = path.stem.split("_", 1)[0]
        if prefix.isdigit():
            max_index = max(max_index, int(prefix))
    return f"{max_index + 1:04d}_{decision_type}"


def _default_allowed_actions(
    root: Path,
    state: dict[str, Any],
    decision_type: str,
    *,
    image_generation_route: str | None = None,
) -> list[str]:
    actions = list(DEFAULT_ALLOWED_ACTIONS.get(decision_type, []))
    if image_generation_route == IMAGE_ROUTE_OPENAI_IMAGE_API and any(action in STAGE2_IMAGE_DISPATCH_ACTIONS for action in actions):
        actions = _insert_after_last_dispatch(actions, "run_image_api_batch")
    if decision_type == "approve_stage2_start_stage3" and _requires_lesson_plan(root, state):
        for action in ("build_lesson_plan_context", "build_lesson_plan"):
            if action not in actions:
                actions.append(action)
    return actions


def _default_image_generation_route(decision_type: str, image_generation_route: str | None) -> str | None:
    if image_generation_route:
        return normalize_image_generation_route(image_generation_route)
    if decision_type in STAGE2_IMAGE_ROUTE_DECISIONS:
        return DEFAULT_IMAGE_GENERATION_ROUTE
    return None


def _insert_after_last_dispatch(actions: list[str], action: str) -> list[str]:
    if action in actions:
        return actions
    insert_at = max((index for index, value in enumerate(actions) if value in STAGE2_IMAGE_DISPATCH_ACTIONS), default=len(actions) - 1)
    return actions[: insert_at + 1] + [action] + actions[insert_at + 1 :]


def _requires_lesson_plan(root: Path, state: dict[str, Any]) -> bool:
    if stage3_lesson_plan_required(state):
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
