from __future__ import annotations

from pathlib import Path
from typing import Any

from .control import build_next_action
from .doctor import check_project
from .json_io import read_json, write_json
from .paths import control_dir, project_state_path
from .stage3_artifact_hashes import stage3_artifacts_stale
from .state import read_state, stage4_lesson_plan_required
from .time_utils import now_iso


READ_ONLY_ACTIONS = {"status", "doctor", "resume_brief", "next_action", "drift_check"}
DECISION_ACTIONS = {"record_decision", "execute_decision"}
BROAD_ACTION_RULES: dict[str, dict[str, Any]] = {
    "stage1_plan": {"stages": {"stage0", "stage1"}, "actor": "main_controller"},
    "stage2_image": {"stages": {"stage2"}, "actor": "main_controller", "requires_confirmed": "stage1_plan"},
    "stage3_editable": {"stages": {"stage3"}, "actor": "main_controller", "requires_confirmed": "stage2_image_deck"},
    "stage4_script": {"stages": {"stage4"}, "actor": "main_controller", "requires_locked_source": True},
    "stage4_lesson_plan": {"stages": {"stage4"}, "actor": "main_controller", "requires_locked_source": True, "requires_k12_lesson_plan": True},
    "canva_auxiliary": {"actor": "main_controller", "sidecar": True},
    "organize_deliverables": {"sidecar": True},
}
STAGE3_ACTIONS = {
    "stage3_editable",
    "dispatch_stage3_background_packets",
    "record_text_unit_split_plan",
    "record_text_ownership_map",
    "record_editable_coordinate_plan",
    "build_coordinate_preview",
    "build_editable_brief",
    "build_officecli_coordinate_deck",
    "record_editable_deck",
    "record_coordinate_stage3_qa",
    "approve_stage3_start_script_output",
}
ACTION_RULES: dict[str, dict[str, Any]] = {
    "dispatch_cover_options": {"stage": "stage2", "statuses": {"ready_for_stage2_cover_options"}, "actor": "main_controller"},
    "dispatch_stage2_cover_options": {"stage": "stage2", "statuses": {"ready_for_stage2_cover_options"}, "actor": "main_controller"},
    "promote_selected_cover_option": {"stage": "stage2", "statuses": {"ready_for_stage2_image_deck"}, "actor": "main_controller"},
    "dispatch_stage2_trial_first5": {"stage": "stage2", "statuses": {"ready_for_stage2_image_deck"}, "actor": "main_controller"},
    "dispatch_stage2_remaining": {"stage": "stage2", "statuses": {"ready_for_stage2_remaining_images"}, "actor": "main_controller"},
    "promote_stage2_trial_first5": {"stage": "stage2", "statuses": {"ready_for_stage2_remaining_images"}, "actor": "main_controller"},
    "build_image_deck": {"stage": "stage2", "statuses": {"stage2_results_complete", "ready_for_stage2_remaining_images"}, "actor": "main_controller"},
    "dispatch_stage3_background_packets": {"stage": "stage3", "statuses": {"ready_for_stage3"}, "actor": "main_controller"},
    "record_text_unit_split_plan": {"stage": "stage3", "statuses": {"ready_for_stage3"}, "actor": "main_controller"},
    "record_text_ownership_map": {"stage": "stage3", "statuses": {"ready_for_stage3", "stage3_text_unit_split_plan_ready"}, "actor": "main_controller"},
    "record_editable_coordinate_plan": {
        "stage": "stage3",
        "statuses": {"stage3_text_ownership_ready", "stage3_background_results_ready", "ready_for_stage3"},
        "actor": "main_controller",
    },
    "build_coordinate_preview": {"stage": "stage3", "statuses": {"waiting_user_coordinate_plan_confirmation"}, "actor": "user"},
    "build_editable_brief": {"stage": "stage3", "statuses": {"stage3_coordinate_plan_confirmed"}, "actor": "main_controller"},
    "build_officecli_coordinate_deck": {"stage": "stage3", "statuses": {"stage3_coordinate_plan_confirmed", "stage3_coordinate_builder_handoff_ready"}, "actor": "main_controller"},
    "record_editable_deck": {
        "stage": "stage3",
        "statuses": {"stage3_officecli_deck_built", "stage3_native_style_probe_built", "stage3_coordinate_builder_handoff_ready"},
        "actor": "main_controller",
    },
    "record_coordinate_stage3_qa": {"stage": "stage3", "statuses": {"stage3_editable_qa_required", "stage3_officecli_deck_built"}, "actor": "main_controller"},
    "build_speaker_script": {"stage": "stage4", "statuses": {"ready_for_stage4_script", "stage4_script_generated", "stage4_lesson_plan_generated"}, "actor": "main_controller"},
    "build_lesson_plan": {
        "stage": "stage4",
        "statuses": {"ready_for_stage4_script", "stage4_script_generated", "stage4_lesson_plan_generated"},
        "actor": "main_controller",
        "requires_k12_lesson_plan": True,
    },
    "record_lesson_plan_qa": {
        "stage": "stage4",
        "statuses": {"stage4_lesson_plan_generated", "stage4_script_generated"},
        "actor": "main_controller",
        "requires_k12_lesson_plan": True,
    },
}
CONFIRMATION_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "dispatch_cover_options": ("stage1_plan", "阶段1规划尚未确认，不能分发阶段2封面候选"),
    "dispatch_stage2_cover_options": ("stage1_plan", "阶段1规划尚未确认，不能分发阶段2封面候选"),
    "promote_selected_cover_option": ("stage2_cover_style", "阶段2封面风格尚未确认，不能转正封面"),
    "dispatch_stage2_trial_first5": ("stage2_cover_style", "阶段2封面风格尚未确认，不能分发阶段2试样"),
    "dispatch_stage2_remaining": ("stage2_trial_first5", "阶段2试样尚未确认，不能生成剩余页面"),
    "promote_stage2_trial_first5": ("stage2_trial_first5", "阶段2试样尚未确认，不能 promotion 试样"),
    "dispatch_stage3_background_packets": ("stage2_image_deck", "阶段2图片版 PDF 尚未确认，不能进入阶段3背景生成"),
    "record_text_unit_split_plan": ("stage2_image_deck", "阶段2图片版 PDF 尚未确认，不能进入阶段3拆字"),
    "record_text_ownership_map": ("stage2_image_deck", "阶段2图片版 PDF 尚未确认，不能进入阶段3文字归属"),
    "record_editable_coordinate_plan": ("stage2_image_deck", "阶段2图片版 PDF 尚未确认，不能记录阶段3坐标计划"),
    "build_editable_brief": ("stage3_coordinate_plan", "阶段3文字坐标复刻尚未确认，不能构建可编辑 PPT handoff"),
    "build_officecli_coordinate_deck": ("stage3_coordinate_plan", "阶段3文字坐标复刻尚未确认，不能运行 OfficeCLI 坐标填字"),
    "build_speaker_script": ("stage2_image_deck", "尚未确认任何锁定稿，不能生成阶段4讲稿"),
    "build_lesson_plan": ("stage2_image_deck", "尚未确认任何锁定稿，不能生成阶段4教案"),
}


def run_drift_check(run_dir: str | Path, *, action: str | None = None, persist: bool = True) -> dict[str, Any]:
    root = Path(run_dir)
    normalized_action = _normalize_action(action)
    issues: list[str] = []
    warnings: list[str] = []
    if _looks_like_skill_root(root):
        issues.append("当前目录是 Skill 根目录，不是具体 PPT 项目目录；请先定位 outputs/projects/<中文项目名>/。")
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
    doctor = check_project(root)
    issues.extend(f"doctor: {issue}" for issue in doctor.get("issues", []))
    warnings.extend(f"doctor: {warning}" for warning in doctor.get("warnings", []))
    result = _result(root, normalized_action, state, issues, warnings, allowed_next_actions, doctor)
    return _persist(root, result, persist)


def _check_action(root: Path, state: dict[str, Any], action: str, issues: list[str], warnings: list[str]) -> None:
    if action in READ_ONLY_ACTIONS:
        return
    if state.get("required_actor") == "user" and action not in DECISION_ACTIONS and action not in {"canva_auxiliary", "organize_deliverables"}:
        issues.append(f"当前 required_actor=user，必须等待用户确认或记录用户反馈 decision，不能执行 {action}")
    broad_rule = BROAD_ACTION_RULES.get(action)
    if broad_rule is not None:
        _check_broad_action(state, action, broad_rule, issues, warnings)
        return
    rule = ACTION_RULES.get(action)
    if rule is None:
        warnings.append(f"未配置 action 状态矩阵：{action}；仅执行通用防漂移检查")
    else:
        if state.get("current_stage") != rule["stage"]:
            issues.append(f"{action} 只能在 {rule['stage']} 执行，当前 current_stage={state.get('current_stage')}")
        if state.get("status") not in rule["statuses"]:
            allowed = ", ".join(sorted(rule["statuses"]))
            issues.append(f"{action} 需要状态为 {allowed}，当前 status={state.get('status')}")
        expected_actor = rule.get("actor")
        if expected_actor and state.get("required_actor") != expected_actor:
            issues.append(f"{action} 需要 required_actor={expected_actor}，当前 required_actor={state.get('required_actor')}")
        if rule.get("requires_k12_lesson_plan") and not stage4_lesson_plan_required(state):
            issues.append(f"{action} 仅适用于 K12 教案必选项目，当前 stage4_outputs.lesson_plan.required 不是 true")
    requirement = CONFIRMATION_REQUIREMENTS.get(action)
    if requirement:
        key, message = requirement
        confirmed = state.get("confirmed") if isinstance(state.get("confirmed"), dict) else {}
        if not confirmed.get(key):
            if action in {"build_speaker_script", "build_lesson_plan"} and state.get("stage4_locked_presentation_source"):
                return
            issues.append(message)
    if action in {"build_speaker_script", "build_lesson_plan"} and not state.get("stage4_locked_presentation_source"):
        target = "讲稿" if action == "build_speaker_script" else "教案"
        issues.append(f"阶段4缺少 stage4_locked_presentation_source，不能生成{target}")
    if action in {"record_decision", "execute_decision"} and state.get("required_actor") == "user":
        warnings.append("当前等待用户确认；record/execute decision 前必须确认 decision.user_confirmed 与用户真实反馈一致")


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
        else:
            issues.append(f"{action} 需要 required_actor={expected_actor}，当前 required_actor={state.get('required_actor')}")
    confirmed = state.get("confirmed") if isinstance(state.get("confirmed"), dict) else {}
    required_confirmation = rule.get("requires_confirmed")
    if isinstance(required_confirmation, str) and not confirmed.get(required_confirmation):
        issues.append(f"{action} 缺少确认：{required_confirmation}")
    if rule.get("requires_locked_source") and not state.get("stage4_locked_presentation_source"):
        issues.append("阶段4缺少 stage4_locked_presentation_source，不能生成阶段4产物")
    if rule.get("requires_k12_lesson_plan") and not stage4_lesson_plan_required(state):
        issues.append(f"{action} 仅适用于 K12 教案必选项目，当前 stage4_outputs.lesson_plan.required 不是 true")
    if action == "canva_auxiliary":
        if not confirmed.get("stage1_plan"):
            warnings.append("Canva 辅助任务缺少已确认阶段1文案时，只能做有限错别字检查")
        if not confirmed.get("stage2_image_deck"):
            warnings.append("Canva 辅助任务缺少已确认阶段2图片版 PDF 时，只能参考已有视觉稿，不能视为正式锁稿")
    if action == "organize_deliverables" and state.get("required_actor") == "user":
        warnings.append("当前项目仍在等待用户确认；/文件整理 或 /整理 可以复制识别到且实际存在的对应文件，但整理不代表用户确认或阶段完成")


def _check_stage3_drift(root: Path, state: dict[str, Any], action: str | None, issues: list[str], warnings: list[str]) -> None:
    stale: dict[str, str] = {}
    state_stale = state.get("stage3_stale_artifacts")
    if isinstance(state_stale, dict):
        stale.update({str(key): str(value) for key, value in state_stale.items()})
    stale.update(stage3_artifacts_stale(root))
    if stale and (state.get("current_stage") in {"stage3", "stage4"} or action in STAGE3_ACTIONS):
        for key, reason in sorted(stale.items()):
            issues.append(f"阶段3存在过期产物：{key}={reason}")
    for relpath in ("_state/阶段3/visual_slot_map.json", "_state/阶段3/text_fill_plan.json"):
        if (root / relpath).exists():
            warnings.append(f"存在 legacy 阶段3产物，不得作为正式通过依据：{relpath}")


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
    return action.strip().replace("-", "_")


def _looks_like_skill_root(root: Path) -> bool:
    return (root / "SKILL.md").exists() and (root / "references").is_dir() and (root / "scripts").is_dir()
