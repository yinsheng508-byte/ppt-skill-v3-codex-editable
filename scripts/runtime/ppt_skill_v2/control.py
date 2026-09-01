from __future__ import annotations

from pathlib import Path
from typing import Any

from .deliverable_naming import existing_stage4_lesson_plan_output_rel, existing_stage4_output_rel
from .doctor import check_project
from .events import read_events
from .json_io import read_json, write_json
from .paths import control_dir, decision_path, decisions_dir
from .state import read_state, stage4_lesson_plan_required
from .time_utils import now_iso
from .validation import validate_lesson_plan_manifest, validate_lesson_plan_qa, validate_speaker_script_manifest


def build_next_action(run_dir: str | Path, *, persist: bool = True) -> dict[str, Any]:
    root = Path(run_dir)
    state = read_state(root)
    action = {
        "schema_version": "1.0",
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "current_stage": state["current_stage"],
        "status": state["status"],
        "required_actor": state["required_actor"],
        "action_kind": _action_kind(state),
        "summary": state.get("next_required_action") or "",
        "source": "project_state.next_required_action",
        "confirmation_required": state.get("required_actor") == "user",
        "candidate_decision_types": _candidate_decision_types(root, state),
        "suggested_command_groups": _suggested_command_groups(state),
        "created_at": now_iso(),
    }
    if persist:
        write_json(control_dir(root) / "next_action.json", action)
    return action


def build_resume_brief(run_dir: str | Path, *, persist: bool = True) -> dict[str, Any]:
    root = Path(run_dir)
    state = read_state(root)
    doctor = check_project(root)
    next_action = build_next_action(root, persist=persist)
    brief = {
        "schema_version": "1.0",
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "current_stage": state["current_stage"],
        "status": state["status"],
        "required_actor": state["required_actor"],
        "confirmed": state.get("confirmed", {}),
        "quality": state.get("quality", {}),
        "last_decision": _last_decision_summary(root, state),
        "recent_events": _recent_events(root),
        "active_work_packet": _active_work_packet(root),
        "next_action": next_action,
        "artifact_presence": {
            "expected_user_paths": _path_presence(root, state.get("expected_user_paths", {})),
            "current_stage_runtime_artifacts": _path_presence(
                root,
                _current_stage_runtime_artifacts(state.get("current_stage"), state.get("runtime_artifacts", {})),
            ),
        },
        "doctor": {
            "ok": doctor["ok"],
            "issues_count": len(doctor.get("issues", [])),
            "warnings_count": len(doctor.get("warnings", [])),
            "issues": doctor.get("issues", []),
            "warnings": doctor.get("warnings", []),
        },
        "control_artifacts": _control_artifacts(state),
        "created_at": now_iso(),
    }
    if persist:
        write_json(control_dir(root) / "resume_brief.json", brief)
        (control_dir(root) / "resume_brief.md").write_text(render_resume_brief_markdown(brief), encoding="utf-8")
    return brief


def render_resume_brief_markdown(brief: dict[str, Any]) -> str:
    next_action = brief.get("next_action") if isinstance(brief.get("next_action"), dict) else {}
    doctor = brief.get("doctor") if isinstance(brief.get("doctor"), dict) else {}
    last_decision = brief.get("last_decision") if isinstance(brief.get("last_decision"), dict) else None
    lines = [
        "# 恢复摘要",
        "",
        f"- 项目：{brief.get('project_name')}",
        f"- 目录：{brief.get('run_dir')}",
        f"- 当前阶段：{brief.get('current_stage')}",
        f"- 当前状态：{brief.get('status')}",
        f"- 当前责任方：{brief.get('required_actor')}",
        "",
        "## 下一步",
        "",
        f"- 动作类型：{next_action.get('action_kind')}",
        f"- 动作摘要：{next_action.get('summary')}",
        f"- 是否等待用户确认：{next_action.get('confirmation_required')}",
    ]
    decisions = next_action.get("candidate_decision_types")
    if decisions:
        lines.append(f"- 候选 decision：{', '.join(str(item) for item in decisions)}")
    command_groups = next_action.get("suggested_command_groups")
    if command_groups:
        lines.append(f"- 命令组提示：{', '.join(str(item) for item in command_groups)}")
    lines.extend(
        [
            "",
            "## 最近决策",
            "",
        ]
    )
    if last_decision:
        lines.extend(
            [
                f"- decision_id：{last_decision.get('decision_id')}",
                f"- decision_type：{last_decision.get('decision_type')}",
                f"- 路径：{last_decision.get('path')}",
            ]
        )
    else:
        lines.append("- 暂无")
    lines.extend(
        [
            "",
            "## Doctor",
            "",
            f"- ok：{doctor.get('ok')}",
            f"- issues：{doctor.get('issues_count')}",
            f"- warnings：{doctor.get('warnings_count')}",
        ]
    )
    issues = doctor.get("issues")
    if issues:
        lines.append("- issue 摘要：" + "；".join(str(item) for item in issues[:3]))
    warnings = doctor.get("warnings")
    if warnings:
        lines.append("- warning 摘要：" + "；".join(str(item) for item in warnings[:3]))
    lines.append("")
    return "\n".join(lines)


def _action_kind(state: dict[str, Any]) -> str:
    status = state.get("status")
    actor = state.get("required_actor")
    if status == "completed" or actor == "none":
        return "complete"
    if actor == "user":
        return "wait_for_user"
    if isinstance(status, str) and ("revision" in status or "rework" in status):
        return "rework"
    if actor == "main_controller":
        return "execute"
    return "inspect"


def _candidate_decision_types(root: Path, state: dict[str, Any]) -> list[str]:
    stage = state.get("current_stage")
    status = state.get("status")
    if stage == "stage1" and status == "waiting_user_confirmation":
        return ["approve_stage1_start_stage2", "request_stage1_revision"]
    if stage == "stage2" and status == "waiting_user_cover_style_selection":
        return ["approve_stage2_cover_style_start_image_deck", "request_stage2_cover_style_revision"]
    if stage == "stage2" and status == "waiting_user_trial_first5_confirmation":
        return ["approve_stage2_trial_first5_continue_remaining", "request_stage2_trial_first5_revision"]
    if stage == "stage2" and status == "waiting_user_confirmation":
        return ["approve_stage2_start_stage3", "approve_stage2_skip_stage3_start_script_output", "request_stage2_revision"]
    if stage == "stage3" and status == "waiting_user_coordinate_plan_confirmation":
        return ["approve_stage3_coordinate_plan_start_text_fill", "request_stage3_coordinate_plan_revision"]
    if stage == "stage3" and status == "waiting_user_confirmation":
        return ["approve_stage3_start_script_output", "request_stage3_revision"]
    if stage == "stage4" and status in {"stage4_script_generated", "stage4_lesson_plan_generated"} and _stage4_required_outputs_generated(root, state):
        return ["stage4_script_completed"]
    if stage == "stage4" and status == "completed":
        return ["reopen_stage3_sample_after_stage4"]
    return []


def _suggested_command_groups(state: dict[str, Any]) -> list[str]:
    stage = state.get("current_stage")
    status = state.get("status")
    actor = state.get("required_actor")
    if actor == "user":
        return ["wait-for-user-response", "record-decision", "execute-decision"]
    if status == "completed" or actor == "none":
        return []
    if stage == "stage0":
        return ["add-material", "create-stage1-draft", "record-decision", "execute-decision"]
    if stage == "stage1":
        return ["create-stage1-draft", "validate-stage1", "record-decision", "execute-decision"]
    if stage == "stage2":
        if status == "ready_for_stage2_cover_options":
            return ["dispatch-cover-options", "record-image-result", "record-decision", "execute-decision"]
        if status == "ready_for_stage2_image_deck":
            return ["promote-selected-cover-option", "dispatch-stage2-trial-first5"]
        if status == "ready_for_stage2_remaining_images":
            return ["promote-stage2-trial-first5", "dispatch-stage2-remaining", "build-image-deck"]
        return ["dispatch-image-generation", "record-image-result", "record-stage2-visual-qa"]
    if stage == "stage3":
        if status == "stage3_coordinate_plan_confirmed":
            return ["build-editable-brief", "build-officecli-coordinate-deck", "record-editable-deck"]
        return [
            "record-text-unit-split-plan",
            "record-text-ownership-map",
            "dispatch-image-generation --stage stage3-background",
            "record-editable-coordinate-plan",
            "build-coordinate-preview",
        ]
    if stage == "stage4":
        commands = ["build-speaker-script"]
        if stage4_lesson_plan_required(state):
            commands.append("build-lesson-plan")
        commands.extend(["record-decision", "execute-decision"])
        return commands
    return []


def _stage4_required_outputs_generated(root: Path, state: dict[str, Any]) -> bool:
    if not _stage4_speaker_outputs_ready(root, state):
        return False
    if not stage4_lesson_plan_required(state):
        return True
    return _stage4_lesson_plan_outputs_ready(root, state)


def _stage4_speaker_outputs_ready(root: Path, state: dict[str, Any]) -> bool:
    manifest_path = root / "_state" / "阶段4" / "speaker_script_manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = validate_speaker_script_manifest(read_json(manifest_path))
    except Exception:
        return False
    if manifest.get("status") != "generated":
        return False
    return all(
        _existing_relpath_exists(root, existing_stage4_output_rel(root, key, state=state, manifest=manifest))
        for key in ("stage4_speaker_script", "stage4_speaker_script_docx", "stage4_speaker_script_pdf")
    )


def _stage4_lesson_plan_outputs_ready(root: Path, state: dict[str, Any]) -> bool:
    manifest_path = root / "_state" / "阶段4" / "lesson_plan_manifest.json"
    qa_path = root / "_state" / "阶段4" / "lesson_plan_qa.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = validate_lesson_plan_manifest(read_json(manifest_path))
    except Exception:
        return False
    if manifest.get("status") != "generated":
        return False
    if manifest.get("summary", {}).get("pdf_text_probe") == "no_selectable_text_detected":
        return False
    if not all(
        _existing_relpath_exists(root, existing_stage4_lesson_plan_output_rel(root, key, state=state, manifest=manifest))
        for key in ("stage4_lesson_plan", "stage4_lesson_plan_docx", "stage4_lesson_plan_pdf")
    ):
        return False
    if qa_path.exists():
        try:
            qa = validate_lesson_plan_qa(read_json(qa_path))
        except Exception:
            return False
        if qa.get("status") == "fail" or qa.get("blockers"):
            return False
    return True


def _existing_relpath_exists(root: Path, relpath: str | None) -> bool:
    return bool(relpath and (root / relpath).exists())


def _last_decision_summary(root: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    path: Path | None = None
    last_id = state.get("last_decision_id")
    if isinstance(last_id, str) and last_id.strip():
        path = decision_path(root, last_id)
    else:
        candidates = sorted(decisions_dir(root).glob("*.json"))
        if candidates:
            path = candidates[-1]
    if not path or not path.exists():
        return None
    try:
        decision = read_json(path)
    except Exception as exc:  # pragma: no cover - unreadable detail is enough for brief
        return {"path": _relative(root, path), "status": "unreadable", "error": str(exc)}
    return {
        "path": _relative(root, path),
        "decision_id": decision.get("decision_id"),
        "decision_type": decision.get("decision_type"),
        "from_stage": decision.get("from_stage"),
        "to_stage": decision.get("to_stage"),
        "user_confirmed": decision.get("user_confirmed"),
        "controller_reviewed": decision.get("controller_reviewed"),
        "created_at": decision.get("created_at"),
    }


def _recent_events(root: Path, limit: int = 5) -> list[dict[str, Any]]:
    events = read_events(root)[-limit:]
    return [
        {
            "event_type": event.get("event_type"),
            "actor": event.get("actor"),
            "created_at": event.get("created_at"),
            "decision_id": event.get("decision_id"),
            "decision_type": event.get("decision_type"),
        }
        for event in events
    ]


def _active_work_packet(root: Path) -> dict[str, Any] | None:
    path = control_dir(root) / "active_work_packet.json"
    if not path.exists():
        return None
    try:
        packet = read_json(path)
    except Exception as exc:  # pragma: no cover
        return {"path": _relative(root, path), "status": "unreadable", "error": str(exc)}
    if isinstance(packet, dict):
        return {"path": _relative(root, path), **packet}
    return {"path": _relative(root, path), "status": "invalid"}


def _path_presence(root: Path, mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    presence: dict[str, dict[str, Any]] = {}
    for key, value in sorted(mapping.items()):
        if not isinstance(value, str) or not value.strip():
            continue
        path = root / value
        presence[key] = {
            "path": value,
            "exists": path.exists(),
            "kind": "dir" if path.is_dir() else ("file" if path.is_file() else "missing"),
        }
    return presence


def _current_stage_runtime_artifacts(stage: Any, runtime_artifacts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(stage, str):
        return {}
    if stage == "stage0":
        prefixes = ("materials", "stage0")
    else:
        prefixes = (stage, "content_json", "design_contract_json", "layout_safety_contract", "slide_prompt_briefs_json")
    return {
        key: value
        for key, value in runtime_artifacts.items()
        if any(key.startswith(prefix) for prefix in prefixes)
    }


def _control_artifacts(state: dict[str, Any]) -> dict[str, str]:
    artifacts = state.get("control_artifacts")
    if isinstance(artifacts, dict):
        return {key: value for key, value in artifacts.items() if isinstance(value, str)}
    return {
        "resume_brief": "_state/control/resume_brief.json",
        "resume_brief_markdown": "_state/control/resume_brief.md",
        "next_action": "_state/control/next_action.json",
        "drift_check": "_state/control/drift_check.json",
        "active_work_packet": "_state/control/active_work_packet.json",
        "work_packets_dir": "_state/control/work_packets",
    }


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
