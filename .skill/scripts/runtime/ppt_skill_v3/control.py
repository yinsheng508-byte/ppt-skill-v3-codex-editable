from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canva_task import CANVA_TASKS_REL
from .deliverable_naming import existing_stage3_lesson_plan_output_rel, existing_stage3_output_rel
from .doctor import check_project
from .image_style import result_is_current, style_document_path
from .events import read_events
from .json_io import read_json, write_json
from .paths import control_dir, existing_decision_path, iter_decision_paths
from .state import read_state, stage3_lesson_plan_required
from .time_utils import now_iso
from .validation import (
    validate_lesson_plan_manifest,
    validate_lesson_plan_qa,
    validate_project_state_relations,
    validate_speaker_script_manifest,
)
from .ppt_consistency import CONSISTENCY_RELPATH


def build_next_action(run_dir: str | Path, *, persist: bool = False) -> dict[str, Any]:
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


def build_resume_brief(run_dir: str | Path, *, persist: bool = False) -> dict[str, Any]:
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
        "image_style_status": _image_style_status(root, state),
        "canva_auxiliary_tasks": _canva_auxiliary_tasks(root),
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
    image_style = brief.get("image_style_status") if isinstance(brief.get("image_style_status"), dict) else {}
    canva_tasks = brief.get("canva_auxiliary_tasks") if isinstance(brief.get("canva_auxiliary_tasks"), list) else []
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
    if image_style:
        lines.extend(
            [
                "",
                "## 图片风格与生图",
                "",
                f"- PPT一致性文档：{image_style.get('ppt_consistency_document')}",
                f"- 风格文档：{image_style.get('style_document')}",
                f"- 受影响页：{', '.join(str(item) for item in image_style.get('affected_slides', [])) or '暂无'}",
                f"- 人工接纳旧图：{image_style.get('accepted_results_count', 0)}",
                f"- 当前试样页：{', '.join(str(item) for item in image_style.get('trial_selection', [])) or '暂无'}",
                f"- 提示词文档：{image_style.get('prompt_document')}",
            ]
        )
    lines.extend(
        [
            "",
            "## 阶段外 Canva 辅助任务",
            "",
        ]
    )
    if canva_tasks:
        for task in canva_tasks:
            if not isinstance(task, dict):
                continue
            last_batch = task.get("last_batch_transaction_status") or "暂无"
            lines.append(
                "- "
                + f"{task.get('task_id')}：{task.get('status')}；执行器={task.get('executor')}；"
                + f"最近批次={last_batch}；路径={task.get('path')}"
            )
    else:
        lines.append("- 暂无")
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
    if _is_completed_state(state):
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
        return ["approve_stage2_start_stage3", "request_stage2_revision"]
    if stage == "stage3" and status in {"stage3_script_generated", "stage3_lesson_plan_generated"} and _stage3_required_outputs_generated(root, state):
        candidates = ["stage3_outputs_completed"]
        if stage3_lesson_plan_required(state):
            candidates.append("request_stage3_lesson_plan_revision")
        return candidates
    if stage == "stage3" and status == "stage3_lesson_plan_revision_requested":
        return []
    if stage == "stage4" and status in {"ready_for_stage4_organize", "stage4_organize_revision_requested"}:
        return ["stage4_deliverables_organized", "request_stage4_organize_revision"]
    if stage == "stage4" and status == "completed":
        return []
    return []


def _suggested_command_groups(state: dict[str, Any]) -> list[str]:
    stage = state.get("current_stage")
    status = state.get("status")
    actor = state.get("required_actor")
    if actor == "user":
        return ["wait-for-user-response", "record-decision", "execute-decision"]
    if _is_completed_state(state):
        return []
    if actor == "none":
        return ["doctor", "resume-brief"]
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
        commands = ["build-speaker-script"]
        if stage3_lesson_plan_required(state):
            commands.append("build-lesson-plan")
        commands.extend(["record-decision", "execute-decision"])
        return commands
    if stage == "stage4":
        return ["organize-deliverables", "record-decision", "execute-decision"]
    return []


def _is_completed_state(state: dict[str, Any]) -> bool:
    try:
        validate_project_state_relations(state)
    except Exception:
        return False
    return state.get("status") == "completed" and state.get("required_actor") == "none" and state.get("current_stage") == "stage4"


def _stage3_required_outputs_generated(root: Path, state: dict[str, Any]) -> bool:
    if not _stage3_speaker_outputs_ready(root, state):
        return False
    if not stage3_lesson_plan_required(state):
        return True
    return _stage3_lesson_plan_outputs_ready(root, state)


def _stage3_speaker_outputs_ready(root: Path, state: dict[str, Any]) -> bool:
    manifest_path = root / "_state" / "阶段3" / "speaker_script_manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = validate_speaker_script_manifest(read_json(manifest_path))
    except Exception:
        return False
    if manifest.get("status") != "generated":
        return False
    return all(
        _existing_relpath_exists(root, existing_stage3_output_rel(root, key, state=state, manifest=manifest))
        for key in ("stage3_speaker_script", "stage3_speaker_script_docx", "stage3_speaker_script_pdf")
    )


def _stage3_lesson_plan_outputs_ready(root: Path, state: dict[str, Any]) -> bool:
    manifest_path = root / "_state" / "阶段3" / "lesson_plan_manifest.json"
    qa_path = root / "_state" / "阶段3" / "lesson_plan_qa.json"
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
        _existing_relpath_exists(root, existing_stage3_lesson_plan_output_rel(root, key, state=state, manifest=manifest))
        for key in ("stage3_lesson_plan", "stage3_lesson_plan_docx", "stage3_lesson_plan_pdf")
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
        path = existing_decision_path(root, last_id)
    else:
        candidates = iter_decision_paths(root)
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
    if isinstance(packet, dict) and isinstance(packet.get("packet_path"), str):
        return {"path": _relative(root, path), **packet}
    if isinstance(packet, dict):
        # Legacy full active packets remain readable without being rewritten.
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


def _image_style_status(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ppt_consistency_document": CONSISTENCY_RELPATH if (root / CONSISTENCY_RELPATH).exists() else None,
        "style_document": _relative(root, style_document_path(root)) if style_document_path(root).exists() else None,
        "prompt_document": "阶段2_图片版PPT/图片生成提示词.md" if (root / "阶段2_图片版PPT/图片生成提示词.md").exists() else None,
        "accepted_results_count": len(state.get("image_style_acceptances", {}) if isinstance(state.get("image_style_acceptances"), dict) else {}),
        "affected_slides": [],
        "trial_selection": [],
        "stale_results": [],
    }
    changes = state.get("image_style_changes") if isinstance(state.get("image_style_changes"), list) else []
    if changes and isinstance(changes[-1], dict):
        result["affected_slides"] = changes[-1].get("affected_slides") or []
        result["reusable_slides"] = changes[-1].get("reusable_slides") or []
        result["last_change_reason"] = changes[-1].get("reason")
    selection = root / "_state" / "阶段2" / "trial_first5" / "selection.json"
    if selection.exists():
        try:
            selected = read_json(selection).get("selected_slide_indices")
            if isinstance(selected, list):
                result["trial_selection"] = selected
        except Exception:
            result["trial_selection"] = ["unreadable"]
    for path in sorted((root / "_state" / "阶段2" / "results").glob("slide_*.json")):
        try:
            item = read_json(path)
            if not result_is_current(root, item, allow_legacy=False):
                result["stale_results"].append(_relative(root, path))
        except Exception:
            result["stale_results"].append(_relative(root, path))
    return result


def _canva_auxiliary_tasks(root: Path) -> list[dict[str, Any]]:
    """Summarize stage-external Canva sidecars without driving any project transition."""

    tasks_root = root / CANVA_TASKS_REL
    if not tasks_root.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for task_dir in sorted(path for path in tasks_root.iterdir() if path.is_dir()):
        task_path = task_dir / "task.json"
        summary: dict[str, Any] = {
            "task_id": task_dir.name,
            "path": _relative(root, task_dir),
            "status": "missing_task_json",
            "provider": "unknown",
            "host_profile": "unknown",
            "executor": "legacy_plugin_inferred",
            "last_batch_transaction_status": _last_canva_batch_transaction_status(task_dir),
            "manual_todo_count": _manual_todo_count(task_dir / "manual_todos.md"),
        }
        if not task_path.exists():
            summaries.append(summary)
            continue
        try:
            task = read_json(task_path)
        except Exception:
            summary["status"] = "unreadable_task_json"
            summaries.append(summary)
            continue
        if not isinstance(task, dict):
            summary["status"] = "invalid_task_json"
            summaries.append(summary)
            continue
        task_id = task.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            summary["task_id"] = task_id
        provider = task.get("provider")
        if isinstance(provider, str) and provider.strip():
            summary["provider"] = provider
        host_profile = task.get("host_profile")
        if isinstance(host_profile, str) and host_profile.strip():
            summary["host_profile"] = host_profile
        executor = task.get("executor")
        if isinstance(executor, str) and executor.strip():
            summary["executor"] = executor
        status = task.get("status")
        if isinstance(status, str) and status.strip():
            summary["status"] = status
        summaries.append(summary)
    return summaries


def _last_canva_batch_transaction_status(task_dir: Path) -> str | None:
    log_path = task_dir / "batch_edit_log.jsonl"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "unreadable"
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("event_type") != "batch_edit":
            continue
        transaction_status = record.get("transaction_status")
        if transaction_status in {"draft", "committed", "cancelled", "failed"}:
            return transaction_status
        return "invalid"
    return None


def _manual_todo_count(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.lstrip().startswith("- "))
    except OSError:
        return 0


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
