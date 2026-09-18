from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .control import build_next_action
from .doctor import check_project
from .json_io import read_json, write_json
from .paths import control_dir, project_state_path
from .stage1_plan import load_stage1_slides
from .state import read_state, stage3_lesson_plan_required
from .time_utils import now_iso
from .validation import validate_stage1_plan


READ_ONLY_ACTIONS = {"status", "doctor", "resume_brief", "next_action", "drift_check"}
DECISION_ACTIONS = {"record_decision", "execute_decision"}
FULL_DOCTOR_ACTIONS = {
    "doctor",
    "validate_stage1",
    "stage2_ready_for_user_review",
    "stage3_outputs_completed",
    "stage4_deliverables_organized",
}
BROAD_ACTION_RULES: dict[str, dict[str, Any]] = {
    "stage1_plan": {"stages": {"stage0", "stage1"}, "actor": "main_controller"},
    "stage2_image": {"stages": {"stage2"}, "actor": "main_controller", "requires_confirmed": "stage1_plan"},
    "stage3_script": {"stages": {"stage3"}, "actor": "main_controller", "requires_confirmed": "stage2_image_deck", "requires_locked_source": "stage3_locked_presentation_source"},
    "stage3_lesson_plan": {
        "stages": {"stage3"},
        "actor": "main_controller",
        "requires_confirmed": "stage2_image_deck",
        "requires_locked_source": "stage3_locked_presentation_source",
        "requires_k12_lesson_plan": True,
    },
    "stage4_organize": {"stages": {"stage4"}, "actor": "main_controller"},
    "canva_auxiliary": {"actor": "main_controller", "sidecar": True},
    "organize_deliverables": {"stages": {"stage4"}, "actor": "main_controller"},
}
ACTION_RULES: dict[str, dict[str, Any]] = {
    "dispatch_cover_options": {"stage": "stage2", "statuses": {"ready_for_stage2_cover_options"}, "actor": "main_controller"},
    "dispatch_stage2_cover_options": {"stage": "stage2", "statuses": {"ready_for_stage2_cover_options"}, "actor": "main_controller"},
    "run_image_api_batch": {"stage": "stage2", "statuses": {"waiting_for_cover_option_results", "waiting_for_stage2_trial_first5_results", "waiting_for_stage2_remaining_image_results"}, "actor": "main_controller"},
    "record_image_result": {
        "stage": "stage2",
        "statuses": {
            "waiting_for_cover_option_results",
            "cover_option_result_recorded",
            "waiting_for_stage2_trial_first5_results",
            "stage2_trial_first5_result_recorded",
            "waiting_for_stage2_remaining_image_results",
            "stage2_image_result_recorded",
        },
        "actor": "main_controller",
    },
    "promote_selected_cover_option": {"stage": "stage2", "statuses": {"ready_for_stage2_image_deck"}, "actor": "main_controller"},
    "dispatch_stage2_trial_first5": {"stage": "stage2", "statuses": {"ready_for_stage2_image_deck", "selected_cover_option_promoted", "trial_first5_revision_requested", "waiting_for_stage2_trial_first5_results", "stage2_trial_first5_result_recorded"}, "actor": "main_controller"},
    "authorize_stage2_trial_skip": {"stage": "stage2", "statuses": {"ready_for_stage2_image_deck", "selected_cover_option_promoted", "trial_first5_revision_requested"}, "actor": "main_controller"},
    "migrate_legacy_trial_first5": {"stage": "stage2", "statuses": {"ready_for_stage2_image_deck", "waiting_for_stage2_trial_first5_results", "stage2_trial_first5_result_recorded", "waiting_user_trial_first5_confirmation", "trial_first5_revision_requested", "ready_for_stage2_remaining_images"}, "actor": "main_controller"},
    "dispatch_stage2_remaining": {"stage": "stage2", "statuses": {"ready_for_stage2_remaining_images", "stage2_trial_first5_promoted", "waiting_for_stage2_remaining_image_results", "stage2_image_result_recorded"}, "actor": "main_controller"},
    "promote_stage2_trial_first5": {"stage": "stage2", "statuses": {"ready_for_stage2_remaining_images"}, "actor": "main_controller"},
    "build_image_deck": {"stage": "stage2", "statuses": {"stage2_results_complete", "ready_for_stage2_remaining_images", "stage2_image_result_recorded"}, "actor": "main_controller"},
    "build_speaker_script": {
        "stage": "stage3",
        "statuses": {"ready_for_stage3_script", "stage3_script_generated", "stage3_lesson_plan_generated", "stage3_lesson_plan_revision_requested"},
        "actor": "main_controller",
    },
    "build_lesson_plan": {
        "stage": "stage3",
        "statuses": {
            "ready_for_stage3_script",
            "stage3_script_generated",
            "stage3_lesson_plan_generated",
            "stage3_lesson_plan_revision_requested",
        },
        "actor": "main_controller",
        "requires_k12_lesson_plan": True,
    },
    "record_lesson_plan_qa": {
        "stage": "stage3",
        "statuses": {"stage3_lesson_plan_generated", "stage3_script_generated", "stage3_lesson_plan_revision_requested"},
        "actor": "main_controller",
        "requires_k12_lesson_plan": True,
    },
    "organize_deliverables": {"stage": "stage4", "statuses": {"ready_for_stage4_organize", "stage4_organize_revision_requested"}, "actor": "main_controller"},
}
CONFIRMATION_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "dispatch_cover_options": ("stage1_plan", "阶段1规划尚未确认，不能分发阶段2封面候选"),
    "dispatch_stage2_cover_options": ("stage1_plan", "阶段1规划尚未确认，不能分发阶段2封面候选"),
    "promote_selected_cover_option": ("stage2_cover_style", "阶段2封面风格尚未确认，不能转正封面"),
    "dispatch_stage2_trial_first5": ("stage2_cover_style", "阶段2封面风格尚未确认，不能分发阶段2试样"),
    "authorize_stage2_trial_skip": ("stage2_cover_style", "阶段2封面风格尚未确认，不能跳过阶段2试样"),
    "dispatch_stage2_remaining": ("stage2_trial_first5", "阶段2试样尚未确认，不能生成剩余页面"),
    "promote_stage2_trial_first5": ("stage2_trial_first5", "阶段2试样尚未确认，不能 promotion 试样"),
    "build_speaker_script": ("stage2_image_deck", "尚未确认阶段2图片版 PDF，不能生成阶段3逐字稿"),
    "build_lesson_plan": ("stage2_image_deck", "尚未确认阶段2图片版 PDF，不能生成阶段3教案"),
}


def run_drift_check(run_dir: str | Path, *, action: str | None = None, persist: bool = False) -> dict[str, Any]:
    root = Path(run_dir)
    normalized_action = _normalize_action(action)
    issues: list[str] = []
    warnings: list[str] = []
    if _looks_like_skill_root(root):
        issues.append("当前目录是 Skill 根目录或外层工作区，不是具体 PPT 项目目录；请先定位 PPT输出/<中文项目名>/。")
        result = _result(root, normalized_action, None, issues, warnings, [], None)
        return _persist(root, result, persist)
    if not project_state_path(root).exists():
        issues.append(f"缺少项目状态文件：{project_state_path(root)}")
        result = _result(root, normalized_action, None, issues, warnings, [], None)
        return _persist(root, result, persist)

    state = read_state(root)
    next_action = build_next_action(root, persist=False)
    allowed_next_actions = _allowed_next_actions(next_action)
    if normalized_action:
        _check_action(root, state, normalized_action, issues, warnings)
    _check_stage3_drift(root, state, normalized_action, issues, warnings)
    doctor = _run_action_checks(root, state, normalized_action, issues, warnings)
    result = _result(root, normalized_action, state, issues, warnings, allowed_next_actions, doctor)
    return _persist(root, result, persist)


def _check_action(root: Path, state: dict[str, Any], action: str, issues: list[str], warnings: list[str]) -> None:
    if action in READ_ONLY_ACTIONS:
        return
    if state.get("required_actor") == "user" and action not in DECISION_ACTIONS and action not in {"canva_auxiliary", "organize_deliverables"}:
        issues.append(f"当前 required_actor=user，必须等待用户确认或记录用户反馈 decision，不能执行 {action}")
    rule = ACTION_RULES.get(action)
    if rule is not None:
        _check_specific_action(root, state, action, rule, issues, warnings)
    else:
        broad_rule = BROAD_ACTION_RULES.get(action)
        if broad_rule is not None:
            _check_broad_action(state, action, broad_rule, issues, warnings)
            return
        warnings.append(f"未配置 action 状态矩阵：{action}；将回退完整项目检查")
    requirement = CONFIRMATION_REQUIREMENTS.get(action)
    if requirement:
        key, message = requirement
        confirmed = state.get("confirmed") if isinstance(state.get("confirmed"), dict) else {}
        if not confirmed.get(key):
            if action in {"build_speaker_script", "build_lesson_plan"} and _has_external_locked_stage3_source(state):
                return
            issues.append(message)
    if action in {"build_speaker_script", "build_lesson_plan"} and not state.get("stage3_locked_presentation_source"):
        target = "逐字稿" if action == "build_speaker_script" else "教案"
        issues.append(f"阶段3缺少 stage3_locked_presentation_source，不能生成{target}")
    if action in {"record_decision", "execute_decision"} and state.get("required_actor") == "user":
        warnings.append("当前等待用户确认；record/execute decision 前必须确认 decision.user_confirmed 与用户真实反馈一致")


def _run_action_checks(
    root: Path,
    state: dict[str, Any],
    action: str | None,
    issues: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Run full project inspection only when a formal project handoff needs it.

    Stage 2 cover/trial display and image-result recording keep their strict
    action/state checks above, but must not scan unrelated Stage 3/4 outputs.
    """

    if action in FULL_DOCTOR_ACTIONS or (action is not None and not _known_action(action)):
        return _run_full_doctor(root, action, issues, warnings)

    scope = _action_scope(action)
    try:
        _check_action_scope(root, state, scope, issues, warnings)
    except Exception as exc:
        warnings.append(f"{scope} 专项检查异常，已回退完整 doctor：{exc}")
        return _run_full_doctor(root, action, issues, warnings, fallback_reason="scoped_checker_exception")
    return {
        "mode": "scoped",
        "scope": scope,
        "ok": not issues,
        "issues": [],
        "warnings": [],
    }


def _run_full_doctor(
    root: Path,
    action: str | None,
    issues: list[str],
    warnings: list[str],
    *,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    doctor = check_project(root)
    if action == "canva_auxiliary":
        warnings.extend(f"doctor: {issue}" for issue in doctor.get("issues", []))
    else:
        issues.extend(f"doctor: {issue}" for issue in doctor.get("issues", []))
    warnings.extend(f"doctor: {warning}" for warning in doctor.get("warnings", []))
    result = {"mode": "full", **doctor}
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result


def _known_action(action: str) -> bool:
    return (
        action in READ_ONLY_ACTIONS
        or action in DECISION_ACTIONS
        or action in FULL_DOCTOR_ACTIONS
        or action in ACTION_RULES
        or action in BROAD_ACTION_RULES
    )


def _action_scope(action: str | None) -> str:
    if action in {
        "record_image_result",
        "run_image_api_batch",
        "dispatch_cover_options",
        "dispatch_stage2_cover_options",
        "dispatch_stage2_trial_first5",
        "dispatch_stage2_remaining",
        "promote_selected_cover_option",
        "promote_stage2_trial_first5",
    }:
        return "stage2_batch"
    if action == "stage2_image":
        return "stage2_current_images"
    if action == "build_image_deck":
        return "stage2_pdf_input"
    if action in {"build_speaker_script", "build_lesson_plan", "record_lesson_plan_qa"}:
        return "stage3_locked_source"
    if action == "organize_deliverables":
        return "stage4_delivery_input"
    return "state_only"


def _check_action_scope(
    root: Path,
    state: dict[str, Any],
    scope: str,
    issues: list[str],
    warnings: list[str],
) -> None:
    if scope == "stage2_batch":
        # State, confirmation and purpose-specific packet/result validation run
        # in the action implementation.  Do not add a project-wide document
        # scan here: legacy fixtures and valid in-flight batches may not yet
        # have future-stage artifacts.
        return
    elif scope == "stage2_current_images":
        # This is the narrow current-image guard used while Stage 2 is being
        # revised.  It deliberately does not inspect Stage 3/4 artifacts.
        from .doctor import _check_stage2_current_image_results

        _check_stage2_current_image_results(root, issues, warnings, require_complete=False)
    elif scope == "stage2_pdf_input":
        _check_build_image_deck_inputs(root, state, issues)
    elif scope == "stage3_locked_source":
        source = state.get("stage3_locked_presentation_source")
        if not isinstance(source, dict):
            issues.append("阶段3缺少 stage3_locked_presentation_source，不能生成阶段3产物")
            return
        mode = source.get("source_mode")
        allowed_modes = {"stage2_image_deck", "external_locked_deck"}
        if mode not in allowed_modes:
            issues.append(f"阶段3锁定稿 source_mode 无效：{mode}；只允许 stage2_image_deck 或 external_locked_deck")
        path = source.get("source_path")
        source_path = root / path if isinstance(path, str) and path.strip() else None
        if source_path is None or not source_path.exists():
            issues.append("阶段3锁定稿不存在，不能生成阶段3产物")
            return
        if mode == "stage2_image_deck":
            confirmed = state.get("confirmed") if isinstance(state.get("confirmed"), dict) else {}
            if not confirmed.get("stage2_image_deck"):
                issues.append("尚未确认阶段2图片版 PDF，不能生成阶段3产物")
        elif mode == "external_locked_deck":
            basis = source.get("confirmation_basis")
            if not isinstance(basis, str) or not basis.strip():
                issues.append("外部锁定稿缺少 confirmation_basis，不能生成阶段3产物")
            expected_sha = source.get("source_sha256")
            actual_sha = _sha256_file(source_path)
            if not isinstance(expected_sha, str) or not expected_sha.strip():
                issues.append("外部锁定稿缺少 source_sha256，不能生成阶段3产物")
            elif expected_sha != actual_sha:
                issues.append("外部锁定稿 source_sha256 与实际文件不一致，不能生成阶段3产物")
    elif scope == "stage4_delivery_input":
        # Stage 4 is intentionally passive: its own organizer records which
        # existing outputs were copied or skipped.  Missing optional source
        # files must not be converted into a global action blocker here.
        return


def _check_specific_action(
    root: Path,
    state: dict[str, Any],
    action: str,
    rule: dict[str, Any],
    issues: list[str],
    warnings: list[str],
) -> None:
    if state.get("current_stage") != rule["stage"]:
        issues.append(f"{action} 只能在 {rule['stage']} 执行，当前 current_stage={state.get('current_stage')}")
    if state.get("status") not in rule["statuses"]:
        allowed = ", ".join(sorted(rule["statuses"]))
        issues.append(f"{action} 需要状态为 {allowed}，当前 status={state.get('status')}")
    expected_actor = rule.get("actor")
    if expected_actor and state.get("required_actor") != expected_actor:
        if action == "organize_deliverables" and state.get("required_actor") == "user":
            warnings.append("当前项目仍在等待用户确认；阶段4整理动作可以复制识别到且实际存在的对应文件，并可导出 PDF 图片副本，但整理不代表用户确认或阶段完成")
        else:
            issues.append(f"{action} 需要 required_actor={expected_actor}，当前 required_actor={state.get('required_actor')}")
    if rule.get("requires_k12_lesson_plan") and not stage3_lesson_plan_required(state):
        issues.append(f"{action} 仅适用于 K12 教案必选项目，当前 stage3_outputs.lesson_plan.required 不是 true")
    if action == "build_image_deck":
        _check_build_image_deck_inputs(root, state, issues)


def _check_build_image_deck_inputs(root: Path, state: dict[str, Any], issues: list[str]) -> None:
    if state.get("current_stage") != "stage2":
        return
    try:
        stage1_plan = validate_stage1_plan(load_stage1_slides(root))
    except Exception as exc:
        issues.append(f"build_image_deck 无法读取阶段1页清单：{exc}")
        return
    for slide in stage1_plan["slides"]:
        slide_index = slide["slide_index"]
        result_rel = f"_state/阶段2/results/slide_{slide_index:03d}.json"
        if not (root / result_rel).exists():
            issues.append(f"build_image_deck 缺少阶段2正式图片结果：{result_rel}")


def _check_broad_action(
    state: dict[str, Any],
    action: str,
    rule: dict[str, Any],
    issues: list[str],
    warnings: list[str],
) -> None:
    stages = rule.get("stages")
    if isinstance(stages, set) and state.get("current_stage") not in stages:
        allowed = ", ".join(sorted(stages))
        issues.append(f"{action} 适用于 {allowed}，当前 current_stage={state.get('current_stage')}")
    expected_actor = rule.get("actor")
    if expected_actor and state.get("required_actor") != expected_actor:
        if action == "canva_auxiliary" and state.get("required_actor") == "user":
            warnings.append("当前项目正在等待用户确认；Canva 辅助任务可以继续作为阶段外任务，但不能推进阶段状态")
        elif action == "organize_deliverables" and state.get("required_actor") == "user":
            warnings.append("当前项目仍在等待用户确认；阶段4整理动作可以复制识别到且实际存在的对应文件，并可导出 PDF 图片副本，但整理不代表用户确认或阶段完成")
        else:
            issues.append(f"{action} 需要 required_actor={expected_actor}，当前 required_actor={state.get('required_actor')}")
    confirmed = state.get("confirmed") if isinstance(state.get("confirmed"), dict) else {}
    required_confirmation = rule.get("requires_confirmed")
    if isinstance(required_confirmation, str) and not confirmed.get(required_confirmation):
        source = state.get("stage3_locked_presentation_source")
        external_locked = (
            required_confirmation == "stage2_image_deck"
            and isinstance(source, dict)
            and source.get("source_mode") == "external_locked_deck"
        )
        if not external_locked:
            issues.append(f"{action} 缺少确认：{required_confirmation}")
    locked_source_key = rule.get("requires_locked_source")
    if isinstance(locked_source_key, str) and not state.get(locked_source_key):
        issues.append(f"缺少 {locked_source_key}，不能执行 {action}")
    if rule.get("requires_k12_lesson_plan") and not stage3_lesson_plan_required(state):
        issues.append(f"{action} 仅适用于 K12 教案必选项目，当前 stage3_outputs.lesson_plan.required 不是 true")
    if action == "canva_auxiliary":
        if not confirmed.get("stage1_plan"):
            warnings.append("Canva 辅助任务缺少已确认阶段1文案时，只能做有限错别字检查")
        if not confirmed.get("stage2_image_deck"):
            warnings.append("Canva 辅助任务缺少已确认阶段2图片版 PDF 时，只能参考已有视觉稿，不能视为正式锁稿")


def _has_external_locked_stage3_source(state: dict[str, Any]) -> bool:
    source = state.get("stage3_locked_presentation_source")
    return isinstance(source, dict) and source.get("source_mode") == "external_locked_deck"


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _check_stage3_drift(root: Path, state: dict[str, Any], action: str | None, issues: list[str], warnings: list[str]) -> None:
    for relpath in ("_state/阶段3/visual_slot_map.json", "_state/阶段3/text_fill_plan.json"):
        if (root / relpath).exists():
            warnings.append(f"存在 legacy 阶段3编辑产物，不得作为当前阶段3输出依据：{relpath}")


def _looks_like_skill_root(root: Path) -> bool:
    return (
        (root / "SKILL.md").exists() and (root / "references").is_dir() and (root / "scripts").is_dir()
    ) or (
        (root / ".skill" / "SKILL.md").exists()
        and (root / ".skill" / "references").is_dir()
        and (root / ".skill" / "scripts").is_dir()
    )


def _allowed_next_actions(next_action: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("suggested_command_groups", "candidate_decision_types"):
        items = next_action.get(key)
        if isinstance(items, list):
            values.extend(str(item) for item in items)
    return values


def _result(
    root: Path,
    action: str | None,
    state: dict[str, Any] | None,
    issues: list[str],
    warnings: list[str],
    allowed_next_actions: list[str],
    doctor: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "ok": not issues,
        "run_dir": str(root),
        "action": action,
        "current_stage": state.get("current_stage") if state else None,
        "status": state.get("status") if state else None,
        "required_actor": state.get("required_actor") if state else None,
        "issues": issues,
        "warnings": warnings,
        "allowed_next_actions": allowed_next_actions,
        "doctor": {
            "ok": doctor.get("ok"),
            "issues_count": len(doctor.get("issues", [])),
            "warnings_count": len(doctor.get("warnings", [])),
            "mode": doctor.get("mode", "full"),
            "scope": doctor.get("scope"),
        }
        if isinstance(doctor, dict)
        else None,
        "created_at": now_iso(),
    }


def _persist(root: Path, result: dict[str, Any], persist: bool) -> dict[str, Any]:
    if persist and not _looks_like_skill_root(root) and project_state_path(root).exists():
        write_json(control_dir(root) / "drift_check.json", result)
    return result


def _normalize_action(action: str | None) -> str | None:
    if not action:
        return None
    normalized = action.strip().replace("-", "_")
    aliases = {
        "dispatch_stage2_trial_first5_packets": "dispatch_stage2_trial_first5",
        "dispatch_stage2_remaining_packets": "dispatch_stage2_remaining",
        "record_image_generation_results": "record_image_result",
    }
    return aliases.get(normalized, normalized)
