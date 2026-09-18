from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .deliverable_naming import LEGACY_STAGE2_IMAGE_PDF_REL, existing_stage2_image_pdf_rel
from .json_io import read_json, write_json
from .state import read_state
from .time_utils import now_iso
from .validation import ValidationError


CANVA_TASKS_REL = Path("_state") / "工具任务" / "canva"
STAGE1_CONTENT_REL = Path("_state") / "阶段1" / "content.json"
STAGE1_TRANSCRIPT_REL = Path("阶段1_规划确认") / "每页干净逐字稿.md"
STAGE1_PLAN_REL = Path("阶段1_规划确认") / "页面规划.md"
STAGE2_PDF_REL = Path(LEGACY_STAGE2_IMAGE_PDF_REL)
STAGE2_IMAGES_REL = Path("阶段2_图片版PPT") / "img"
CANVA_PROVIDER = "canva_international"
CANVA_HOST_PROFILES = {"codex", "workbuddy", "unknown"}
CANVA_EXECUTORS = {"canva_mcp", "canva_plugin", "manual_handoff", "unresolved"}
CANVA_TASK_STATUSES = {
    "brief_ready",
    "waiting_manual_magic_layers",
    "ready_for_page_audit",
    "editing",
    "waiting_batch_confirmation",
    "completed",
    "cancelled",
    "blocked_connector",
}
CANVA_TRANSACTION_STATUSES = {"draft", "committed", "cancelled", "failed"}
CANVA_EVENT_TYPES = {"batch_edit"}
CANVA_PAGE_AUDIT_STATUSES = {"not_started", "in_progress", "completed", "blocked"}
CANVA_PREVIEW_STATUSES = {"not_requested", "pending", "ready", "reviewed_by_controller", "shown_to_user", "failed"}
CANVA_CONFIRMATION_STATUSES = {"not_requested", "pre_authorized", "confirmed", "declined", "cancelled"}
CANVA_AUTHORITY_SOURCES = {
    "stage1_content",
    "stage1_clean_transcript",
    "stage1_page_plan",
    "stage2_visual_reference",
}
CANVA_FINDING_CATEGORIES = {
    "typo",
    "garbled_text",
    "missing_text",
    "extra_text",
    "punctuation",
    "numbering",
    "unit",
    "hierarchy",
    "font_size",
    "font_weight",
    "color",
    "alignment",
    "line_height",
    "list_style",
    "overflow",
    "occlusion",
    "line_break",
}
CANVA_COPY_CHECK_STATUSES = {"pass", "needs_edit", "blocked"}
CANVA_VISUAL_CHECK_STATUSES = {"pass", "needs_edit", "not_applicable", "manual_todo", "blocked"}
CANVA_TEXT_ROLES = {"page", "title", "subtitle", "body", "bullet", "caption", "footer"}
CANVA_VISUAL_CHECK_ATTRIBUTES = {
    "hierarchy",
    "font_size",
    "font_weight",
    "color",
    "alignment",
    "line_height",
    "list_style",
    "position",
    "size",
    "overflow",
    "occlusion",
    "line_break",
}
CANVA_MANUAL_TODO_CATEGORIES = {
    "magic_layers",
    "font_family",
    "background",
    "complex_shape",
    "animation",
    "page_reorder",
    "add_or_delete_content",
    "image_or_fill",
    "unsupported_responsive_operation",
    "other",
}
CANVA_EXPORT_STATUSES = {"exported", "failed", "cancelled"}
CANVA_EXPORT_FORMATS = {"pdf", "pptx", "png", "jpg", "jpeg"}
_SENSITIVE_KEY_FRAGMENTS = {"token", "secret", "authorization", "signed_url", "thumbnail_url", "export_url", "local_path"}
_SENSITIVE_VALUE_FRAGMENTS = {"x-amz-signature", "authorization: bearer", "bearer "}


def create_canva_task_brief(
    run_dir: str | Path,
    *,
    task_id: str | None = None,
    trigger: str = "/canva",
    provider: str = CANVA_PROVIDER,
    host_profile: str = "unknown",
    executor: str = "unresolved",
) -> dict[str, Any]:
    """Create a stage-external Canva task brief without mutating project stage state."""

    root = Path(run_dir)
    provider = _normalize_provider(provider)
    host_profile = _normalize_host_profile(host_profile)
    executor = _normalize_executor(executor, host_profile=host_profile)
    state_before = read_state(root)
    content_path = root / STAGE1_CONTENT_REL
    stage2_pdf_rel = existing_stage2_image_pdf_rel(root, state_before)
    stage2_pdf = root / stage2_pdf_rel if stage2_pdf_rel else root / STAGE2_PDF_REL

    if not content_path.exists():
        raise ValidationError("stage1 content.json is required before creating a Canva task brief")
    if not stage2_pdf.exists():
        raise ValidationError("stage2 image PDF is required before creating a Canva task brief")

    content = read_json(content_path)
    slides = _reference_slides(root, content)
    if not slides:
        raise ValidationError("stage1 content.json must contain at least one slide")

    task_id = _normal_task_id(task_id) if task_id else _default_task_id()
    task_dir = root / CANVA_TASKS_REL / task_id
    if task_dir.exists():
        raise ValidationError(f"Canva task already exists: {task_id}")

    created_at = now_iso()
    warnings = []
    if not state_before.get("confirmed", {}).get("stage2_image_deck"):
        warnings.append("stage2_image_deck is not confirmed; use this Canva brief as draft support only")
    initial_status = "blocked_connector" if executor == "manual_handoff" else "brief_ready"
    if executor == "manual_handoff":
        warnings.append("selected executor is manual_handoff; no connector edit may be reported as completed")

    references = {
        "stage1_content": _posix(STAGE1_CONTENT_REL),
        "stage1_clean_transcript": _posix(STAGE1_TRANSCRIPT_REL),
        "stage1_page_plan": _posix(STAGE1_PLAN_REL),
        "stage2_image_deck_pdf": stage2_pdf_rel or _posix(STAGE2_PDF_REL),
        "stage2_images_dir": _posix(STAGE2_IMAGES_REL),
    }
    task = {
        "schema_version": "1.2",
        "task_id": task_id,
        "task_type": "canva_auxiliary_edit",
        "project_name": state_before["project_name"],
        "run_dir": state_before["run_dir"],
        "trigger": trigger,
        "status": initial_status,
        "created_at": created_at,
        "provider": provider,
        "host_profile": host_profile,
        "executor": executor,
        "selection_basis": {
            "selection_status": "fallback_selected" if executor == "manual_handoff" else ("selected" if executor in {"canva_mcp", "canva_plugin"} else "selection_required"),
            "required_tools_visible": None,
            "authorization_ready": None,
            "selected_at": created_at,
            "source": "explicit_cli_or_controller_input",
        },
        "stage_boundary": {
            "stage_external": True,
            "not_stage3": True,
            "does_not_change_project_stage": True,
            "must_not_write_stage3_decisions": True,
        },
        "commit_policy": {
            "mode": "direct_commit_after_controller_qa",
            "default_batch_page_count": 5,
            "user_batch_confirmation_required": False,
            "required_before_commit": [
                "Every edited page has an authority-matched copy_check with post_edit_text.",
                "Every edited page has a recorded stage2 visual check result.",
                "The returned preview has been reviewed by the controller.",
            ],
        },
        "references": references,
        "workflow": [
            "Resolve the current host executor with an explicit tool and authorization preflight before any Canva call.",
            "Acquire the Canva design through the selected executor when allowed, otherwise ask the user to upload it manually.",
            "Ask the user to run Magic Layers manually in Canva and return the edit link.",
            "Let the AI controller interpret each page role, authority copy, and stage2 visual intent before writing page-audit evidence.",
            "Audit every Canva page with the task page-audit contract before batch-fixing copy and supported text styling.",
            "Use five pages as the default editing batch, then commit directly after the AI controller review passes.",
            "Review every changed-page preview, then commit directly under the standing direct-edit policy; do not wait for another user batch confirmation.",
        ],
        "warnings": warnings,
    }
    reference_text = {
        "schema_version": "1.1",
        "task_id": task_id,
        "project_name": state_before["project_name"],
        "source": _posix(STAGE1_CONTENT_REL),
        "visual_reference": {
            "stage2_pdf": stage2_pdf_rel or _posix(STAGE2_PDF_REL),
            "stage2_images_dir": _posix(STAGE2_IMAGES_REL),
        },
        "slides": slides,
        "authority_contract": {
            "expected_text_field": "slides[].final_visible_text",
            "match_rule": "The page audit expected_text and a passed copy_check post_edit_text must exactly equal final_visible_text for the same slide_index.",
            "visual_reference": "stage2_image_deck_pdf and the same-index stage2 image when present",
        },
        "created_at": created_at,
    }
    import_attempt = {
        "schema_version": "1.1",
        "task_id": task_id,
        "status": "not_attempted",
        "notes": "Canva design acquisition is performed by the selected conversation executor, not by this local runtime command.",
        "created_at": created_at,
    }
    manual_todos = "\n".join(
        [
            "# Canva 人工待处理项",
            "",
            "此文件用于记录当前 Canva 执行器无法处理、需要用户在 Canva 手动修改的事项。格式：`- [open] 页：<页码或未指定> | 类型：<分类> | 原因：<说明> | 授权：<是/否>`。",
            "",
            "- [open] 页：未指定 | 类型：magic_layers | 原因：待用户手动执行 Magic Layers | 授权：否",
            "- [open] 页：未指定 | 类型：other | 原因：字体族、背景、复杂形状、加页删页重排等执行器不支持事项在执行中补充 | 授权：否",
            "",
        ]
    )

    write_json(task_dir / "task.json", task)
    write_json(task_dir / "reference_text_by_slide.json", reference_text)
    write_json(task_dir / "import_attempt.json", import_attempt)
    write_json(
        task_dir / "page_audit.json",
        {
            "schema_version": "1.1",
            "task_id": task_id,
            "protocol": "page_copy_and_visual_audit_v1",
            "status": "not_started",
            "pages": [],
            "created_at": created_at,
            "updated_at": created_at,
        },
    )
    (task_dir / "batch_edit_log.jsonl").write_text("", encoding="utf-8")
    (task_dir / "manual_todos.md").write_text(manual_todos, encoding="utf-8")

    state_after = read_state(root)
    if _stage_state_snapshot(state_after) != _stage_state_snapshot(state_before):
        raise ValidationError("create-canva-task-brief must not mutate project stage state")

    return {
        "status": "canva_task_brief_created",
        "task_id": task_id,
        "task_dir": _posix(CANVA_TASKS_REL / task_id),
        "task_json": _posix(CANVA_TASKS_REL / task_id / "task.json"),
        "reference_text_by_slide": _posix(CANVA_TASKS_REL / task_id / "reference_text_by_slide.json"),
        "page_audit": _posix(CANVA_TASKS_REL / task_id / "page_audit.json"),
        "provider": provider,
        "host_profile": host_profile,
        "executor": executor,
        "warnings": warnings,
    }


def record_canva_task_event(
    run_dir: str | Path,
    task_id: str,
    *,
    event: dict[str, Any],
    status: str | None = None,
) -> dict[str, Any]:
    """Append one safe, stage-external Canva batch event and optionally update task status."""

    root = Path(run_dir)
    state_before = read_state(root)
    normalized_task_id = _normal_task_id(task_id)
    task_dir = root / CANVA_TASKS_REL / normalized_task_id
    task_path = task_dir / "task.json"
    if not task_path.exists():
        raise ValidationError(f"Canva task does not exist: {normalized_task_id}")
    task = read_json(task_path)
    if not isinstance(task, dict):
        raise ValidationError("Canva task.json must be an object")
    checked_event = _validate_canva_task_event(event)
    _validate_page_audits_against_reference(task_dir, checked_event["page_audits"])
    if status is not None and status not in CANVA_TASK_STATUSES:
        raise ValidationError(f"unsupported Canva task status: {status}")
    previous_event = _last_batch_event(task_dir, checked_event["batch_id"])
    task_schema_version = task.get("schema_version") if isinstance(task.get("schema_version"), str) else None
    _validate_batch_transition(previous_event, checked_event, task_schema_version=task_schema_version)
    _validate_task_status_for_event(status, checked_event, task_schema_version=task_schema_version)

    executor = task.get("executor")
    if not isinstance(executor, str) or not executor:
        executor = "legacy_plugin_inferred"
    record = {
        "schema_version": "1.0",
        "task_id": normalized_task_id,
        "executor": executor,
        "recorded_at": now_iso(),
        **checked_event,
    }
    log_path = task_dir / "batch_edit_log.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    _update_page_audit(task_dir, normalized_task_id, checked_event)
    _append_manual_todos(task_dir / "manual_todos.md", checked_event.get("page_audits", []))

    if status is not None:
        task["status"] = status
        task["updated_at"] = record["recorded_at"]
        write_json(task_path, task)

    state_after = read_state(root)
    if _stage_state_snapshot(state_after) != _stage_state_snapshot(state_before):
        raise ValidationError("record_canva_task_event must not mutate project stage state")
    return {
        "status": "canva_task_event_recorded",
        "task_id": normalized_task_id,
        "task_status": task.get("status"),
        "batch_edit_log": _posix(CANVA_TASKS_REL / normalized_task_id / "batch_edit_log.jsonl"),
        "page_audit": _posix(CANVA_TASKS_REL / normalized_task_id / "page_audit.json"),
        "record": record,
    }


def record_canva_task_export(
    run_dir: str | Path,
    task_id: str,
    *,
    export: dict[str, Any],
) -> dict[str, Any]:
    """Record a sanitized actual Canva export attempt without storing an export URL or local file path."""

    root = Path(run_dir)
    state_before = read_state(root)
    normalized_task_id = _normal_task_id(task_id)
    task_dir = root / CANVA_TASKS_REL / normalized_task_id
    if not (task_dir / "task.json").exists():
        raise ValidationError(f"Canva task does not exist: {normalized_task_id}")
    record = _validate_canva_export(export)
    record["recorded_at"] = now_iso()
    record["task_id"] = normalized_task_id
    export_path = task_dir / "export_record.json"
    if export_path.exists():
        try:
            export_document = read_json(export_path)
        except Exception:
            export_document = {}
    else:
        export_document = {}
    exports = export_document.get("exports") if isinstance(export_document, dict) else None
    if not isinstance(exports, list):
        exports = []
    exports.append(record)
    write_json(
        export_path,
        {
            "schema_version": "1.0",
            "task_id": normalized_task_id,
            "exports": exports,
            "updated_at": record["recorded_at"],
        },
    )
    state_after = read_state(root)
    if _stage_state_snapshot(state_after) != _stage_state_snapshot(state_before):
        raise ValidationError("record_canva_task_export must not mutate project stage state")
    return {
        "status": "canva_task_export_recorded",
        "task_id": normalized_task_id,
        "export_record": _posix(CANVA_TASKS_REL / normalized_task_id / "export_record.json"),
        "record": record,
    }


def _normalize_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized != CANVA_PROVIDER:
        raise ValidationError(f"unsupported Canva provider: {value}")
    return normalized


def _normalize_host_profile(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in CANVA_HOST_PROFILES:
        raise ValidationError(f"unsupported Canva host profile: {value}")
    return normalized


def _normalize_executor(value: str, *, host_profile: str) -> str:
    normalized = value.strip().lower()
    if normalized not in CANVA_EXECUTORS:
        raise ValidationError(f"unsupported Canva executor: {value}")
    if normalized == "canva_mcp" and host_profile != "workbuddy":
        raise ValidationError("canva_mcp executor requires host_profile=workbuddy")
    if normalized == "canva_plugin" and host_profile != "codex":
        raise ValidationError("canva_plugin executor requires host_profile=codex")
    return normalized


def _validate_canva_task_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValidationError("Canva task event must be an object")
    _assert_safe_task_value(event)
    event_type = event.get("event_type")
    if event_type not in CANVA_EVENT_TYPES:
        raise ValidationError("Canva task event_type must be batch_edit")
    batch_id = event.get("batch_id")
    if not isinstance(batch_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", batch_id):
        raise ValidationError("Canva task batch_id may only contain letters, numbers, underscore, or hyphen")
    slide_indices = event.get("slide_indices")
    if not isinstance(slide_indices, list) or not slide_indices or not all(isinstance(item, int) and item > 0 for item in slide_indices):
        raise ValidationError("Canva task event slide_indices must be a non-empty positive integer list")
    operation_types = event.get("operation_types")
    if not isinstance(operation_types, list) or not operation_types or not all(isinstance(item, str) and item.strip() for item in operation_types):
        raise ValidationError("Canva task event operation_types must be a non-empty string list")
    transaction_status = event.get("transaction_status")
    if transaction_status not in CANVA_TRANSACTION_STATUSES:
        raise ValidationError("unsupported Canva transaction_status")
    tool = event.get("tool")
    if tool is not None and (not isinstance(tool, str) or not tool.strip()):
        raise ValidationError("Canva task event tool must be a non-empty string when provided")
    preview_status = event.get("preview_status", "not_requested")
    if preview_status not in CANVA_PREVIEW_STATUSES:
        raise ValidationError("unsupported Canva preview_status")
    confirmation_status = event.get("confirmation_status", "not_requested")
    if confirmation_status not in CANVA_CONFIRMATION_STATUSES:
        raise ValidationError("unsupported Canva confirmation_status")
    raw_page_audits = event.get("page_audits", [])
    if not isinstance(raw_page_audits, list):
        raise ValidationError("Canva task event page_audits must be a list")
    page_audits = [_validate_page_audit(item) for item in raw_page_audits]
    audit_slide_indices = {item["slide_index"] for item in page_audits}
    if not audit_slide_indices.issubset(set(slide_indices)):
        raise ValidationError("Canva task page_audits must belong to the event slide_indices")
    return {
        "event_type": event_type,
        "batch_id": batch_id,
        "slide_indices": sorted(set(slide_indices)),
        "operation_types": [item.strip() for item in operation_types],
        "transaction_status": transaction_status,
        "preview_status": preview_status,
        "confirmation_status": confirmation_status,
        "page_audits": page_audits,
        **({"tool": tool.strip()} if isinstance(tool, str) else {}),
    }


def _validate_page_audit(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("each Canva page audit must be an object")
    slide_index = value.get("slide_index")
    if not isinstance(slide_index, int) or slide_index <= 0:
        raise ValidationError("Canva page audit slide_index must be a positive integer")
    canva_page_id = value.get("canva_page_id")
    if not isinstance(canva_page_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", canva_page_id):
        raise ValidationError("Canva page audit canva_page_id may only contain letters, numbers, underscore, or hyphen")
    for key in ("is_editable", "is_responsive"):
        if not isinstance(value.get(key), bool):
            raise ValidationError(f"Canva page audit {key} must be boolean")
    authority_sources = value.get("authority_sources")
    if not isinstance(authority_sources, list) or not authority_sources or not all(item in CANVA_AUTHORITY_SOURCES for item in authority_sources):
        raise ValidationError("Canva page audit authority_sources must use known authority source names")
    if "stage1_content" not in authority_sources:
        raise ValidationError("Canva page audit authority_sources must include stage1_content")
    expected_text = _normalize_text_list(value.get("expected_text"), field="expected_text")
    current_text = _normalize_text_list(value.get("current_text"), field="current_text")
    copy_check = _validate_copy_check(value.get("copy_check"), expected_text=expected_text)
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise ValidationError("Canva page audit findings must be a list")
    normalized_findings = [_validate_page_finding(item) for item in findings]
    proposed_operations = value.get("proposed_operations")
    if not isinstance(proposed_operations, list) or not all(isinstance(item, str) and item.strip() for item in proposed_operations):
        raise ValidationError("Canva page audit proposed_operations must be a string list")
    visual_checks = value.get("visual_checks")
    if not isinstance(visual_checks, list) or not visual_checks:
        raise ValidationError("Canva page audit visual_checks must be a non-empty list")
    manual_todos = value.get("manual_todos", [])
    if not isinstance(manual_todos, list):
        raise ValidationError("Canva page audit manual_todos must be a list")
    return {
        "slide_index": slide_index,
        "canva_page_id": canva_page_id,
        "is_editable": value["is_editable"],
        "is_responsive": value["is_responsive"],
        "authority_sources": list(dict.fromkeys(authority_sources)),
        "expected_text": expected_text,
        "current_text": current_text,
        "copy_check": copy_check,
        "findings": normalized_findings,
        "proposed_operations": [item.strip() for item in proposed_operations],
        "visual_checks": [_validate_visual_check(item) for item in visual_checks],
        "manual_todos": [_validate_manual_todo(item, slide_index=slide_index) for item in manual_todos],
    }


def _validate_copy_check(value: Any, *, expected_text: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("Canva page audit copy_check must be an object")
    status = value.get("status")
    if status not in CANVA_COPY_CHECK_STATUSES:
        raise ValidationError("unsupported Canva page audit copy_check status")
    post_edit_text = _normalize_text_list(value.get("post_edit_text"), field="copy_check.post_edit_text")
    if status == "pass" and post_edit_text != expected_text:
        raise ValidationError("a passed Canva copy_check post_edit_text must exactly match expected_text")
    return {"status": status, "post_edit_text": post_edit_text}


def _validate_visual_check(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationError("each Canva visual check must be an object")
    role = value.get("role")
    if role not in CANVA_TEXT_ROLES:
        raise ValidationError("unsupported Canva visual check role")
    attribute = value.get("attribute")
    if attribute not in CANVA_VISUAL_CHECK_ATTRIBUTES:
        raise ValidationError("unsupported Canva visual check attribute")
    status = value.get("status")
    if status not in CANVA_VISUAL_CHECK_STATUSES:
        raise ValidationError("unsupported Canva visual check status")
    before = _normalize_short_text(value.get("before", ""), field="visual_check.before", allow_empty=True)
    target = _normalize_short_text(value.get("target", ""), field="visual_check.target", allow_empty=True)
    after = _normalize_short_text(value.get("after", ""), field="visual_check.after", allow_empty=True)
    return {"role": role, "attribute": attribute, "status": status, "before": before, "target": target, "after": after}


def _validate_page_finding(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationError("each Canva page audit finding must be an object")
    category = value.get("category")
    if category not in CANVA_FINDING_CATEGORIES:
        raise ValidationError("unsupported Canva page audit finding category")
    current_text = _normalize_short_text(value.get("current_text", ""), field="finding.current_text", allow_empty=True)
    expected_text = _normalize_short_text(value.get("expected_text", ""), field="finding.expected_text", allow_empty=True)
    return {"category": category, "current_text": current_text, "expected_text": expected_text}


def _validate_manual_todo(value: Any, *, slide_index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("each Canva manual todo must be an object")
    category = value.get("category")
    if category not in CANVA_MANUAL_TODO_CATEGORIES:
        raise ValidationError("unsupported Canva manual todo category")
    reason = _normalize_short_text(value.get("reason"), field="manual_todo.reason")
    requires_authorization = value.get("requires_authorization", True)
    if not isinstance(requires_authorization, bool):
        raise ValidationError("Canva manual todo requires_authorization must be boolean")
    return {
        "slide_index": slide_index,
        "category": category,
        "reason": reason,
        "requires_authorization": requires_authorization,
    }


def _normalize_text_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError(f"Canva page audit {field} must be a string list")
    return [_normalize_short_text(item, field=field) for item in value]


def _normalize_short_text(value: Any, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"Canva {field} must be a string")
    normalized = value.strip()
    if (not normalized and not allow_empty) or len(normalized) > 500 or "\n" in normalized or "\r" in normalized:
        raise ValidationError(f"Canva {field} must be a single line of at most 500 characters")
    return normalized


def _last_batch_event(task_dir: Path, batch_id: str) -> dict[str, Any] | None:
    log_path = task_dir / "batch_edit_log.jsonl"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("event_type") == "batch_edit" and record.get("batch_id") == batch_id:
            return record
    return None


def _validate_batch_transition(
    previous_event: dict[str, Any] | None,
    event: dict[str, Any],
    *,
    task_schema_version: str | None,
) -> None:
    current_status = event["transaction_status"]
    if previous_event is None:
        if current_status != "draft":
            raise ValidationError("a Canva batch must be recorded as draft before it can be committed, cancelled, or failed")
        if not event["page_audits"]:
            raise ValidationError("the first Canva batch event must include a page audit for every edited page")
        audited = {item["slide_index"] for item in event["page_audits"]}
        if audited != set(event["slide_indices"]):
            raise ValidationError("the first Canva batch page audits must cover every edited slide")
        return
    previous_status = previous_event.get("transaction_status")
    if previous_status != "draft":
        raise ValidationError("a terminal Canva batch cannot receive another event")
    if current_status not in {"committed", "cancelled", "failed"}:
        raise ValidationError("a drafted Canva batch must end as committed, cancelled, or failed")
    if event["slide_indices"] != previous_event.get("slide_indices"):
        raise ValidationError("a Canva batch completion must keep the original slide_indices")
    if current_status == "committed":
        if event["preview_status"] not in {"reviewed_by_controller", "shown_to_user"}:
            raise ValidationError("a committed Canva batch requires a controller-reviewed preview")
        allowed_authorizations = {"pre_authorized"} if task_schema_version == "1.2" else {"pre_authorized", "confirmed"}
        if event["confirmation_status"] not in allowed_authorizations:
            if task_schema_version == "1.2":
                raise ValidationError("a schema v1.2 Canva batch requires pre_authorized direct commit authorization")
            raise ValidationError("a committed Canva batch requires pre_authorized or legacy confirmed commit authorization")
        _validate_committable_page_audits(previous_event.get("page_audits"))


def _validate_task_status_for_event(
    status: str | None,
    event: dict[str, Any],
    *,
    task_schema_version: str | None,
) -> None:
    if status == "completed" and event["transaction_status"] != "committed":
        raise ValidationError("completed Canva task status requires a committed batch")
    if status == "cancelled" and event["transaction_status"] != "cancelled":
        raise ValidationError("cancelled Canva task status requires a cancelled batch")
    if status == "waiting_batch_confirmation" and event["transaction_status"] != "draft":
        raise ValidationError("waiting_batch_confirmation requires a draft batch")
    if status == "waiting_batch_confirmation" and task_schema_version == "1.2":
        raise ValidationError("schema v1.2 Canva tasks use editing and direct commit, not waiting_batch_confirmation")


def _validate_committable_page_audits(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError("a committed Canva batch requires retained page audits")
    for audit in value:
        if not isinstance(audit, dict):
            raise ValidationError("a committed Canva batch has an invalid retained page audit")
        copy_check = audit.get("copy_check")
        if not isinstance(copy_check, dict) or copy_check.get("status") != "pass":
            raise ValidationError("a committed Canva batch requires every page copy_check to pass")
        visual_checks = audit.get("visual_checks")
        if not isinstance(visual_checks, list) or not visual_checks:
            raise ValidationError("a committed Canva batch requires every page visual_checks")
        unresolved = [
            check
            for check in visual_checks
            if isinstance(check, dict) and check.get("status") in {"needs_edit", "blocked"}
        ]
        if unresolved:
            raise ValidationError("a committed Canva batch cannot retain needs_edit or blocked visual checks")


def _validate_page_audits_against_reference(task_dir: Path, page_audits: list[dict[str, Any]]) -> None:
    if not page_audits:
        return
    reference_path = task_dir / "reference_text_by_slide.json"
    try:
        reference = read_json(reference_path)
    except Exception as exc:
        raise ValidationError("Canva task is missing readable reference_text_by_slide.json") from exc
    slides = reference.get("slides") if isinstance(reference, dict) else None
    if not isinstance(slides, list):
        raise ValidationError("Canva task reference_text_by_slide.json slides must be a list")
    expected_by_slide = {
        item.get("slide_index"): item.get("final_visible_text")
        for item in slides
        if isinstance(item, dict) and isinstance(item.get("slide_index"), int) and isinstance(item.get("final_visible_text"), list)
    }
    for audit in page_audits:
        expected = expected_by_slide.get(audit["slide_index"])
        if not isinstance(expected, list):
            raise ValidationError("Canva page audit slide_index is absent from the authority reference")
        if audit["expected_text"] != expected:
            raise ValidationError("Canva page audit expected_text must exactly match the stage1 authority reference")


def _update_page_audit(task_dir: Path, task_id: str, event: dict[str, Any]) -> None:
    path = task_dir / "page_audit.json"
    try:
        document = read_json(path) if path.exists() else {}
    except Exception:
        document = {}
    pages = document.get("pages") if isinstance(document, dict) else None
    if not isinstance(pages, list):
        pages = []
    by_slide = {item.get("slide_index"): item for item in pages if isinstance(item, dict) and isinstance(item.get("slide_index"), int)}
    recorded_at = now_iso()
    for audit in event["page_audits"]:
        by_slide[audit["slide_index"]] = {
            **audit,
            "last_batch_id": event["batch_id"],
            "last_transaction_status": event["transaction_status"],
            "last_preview_status": event["preview_status"],
            "last_commit_authorization": event["confirmation_status"],
            "updated_at": recorded_at,
        }
    for slide_index in event["slide_indices"]:
        existing = by_slide.get(slide_index)
        if not isinstance(existing, dict):
            continue
        by_slide[slide_index] = {
            **existing,
            "last_batch_id": event["batch_id"],
            "last_transaction_status": event["transaction_status"],
            "last_preview_status": event["preview_status"],
            "last_commit_authorization": event["confirmation_status"],
            "updated_at": recorded_at,
        }
    expected_slides = _reference_slide_indices(task_dir / "reference_text_by_slide.json")
    audited_slides = set(by_slide)
    status = "completed" if _page_audit_is_complete(expected_slides, by_slide) else "in_progress"
    write_json(
        path,
        {
            "schema_version": "1.1",
            "task_id": task_id,
            "status": status,
            "pages": [by_slide[index] for index in sorted(by_slide)],
            "created_at": document.get("created_at") if isinstance(document, dict) else recorded_at,
            "updated_at": recorded_at,
        },
    )


def _page_audit_is_complete(expected_slides: set[int], by_slide: dict[int, dict[str, Any]]) -> bool:
    if not expected_slides or not expected_slides.issubset(set(by_slide)):
        return False
    for slide_index in expected_slides:
        audit = by_slide[slide_index]
        if audit.get("last_transaction_status") != "committed":
            return False
        copy_check = audit.get("copy_check")
        if not isinstance(copy_check, dict) or copy_check.get("status") != "pass":
            return False
        checks = audit.get("visual_checks")
        if not isinstance(checks, list) or any(
            not isinstance(check, dict) or check.get("status") in {"needs_edit", "blocked"}
            for check in checks
        ):
            return False
        if audit.get("last_preview_status") not in {"reviewed_by_controller", "shown_to_user"}:
            return False
        if audit.get("last_commit_authorization") not in {"pre_authorized", "confirmed"}:
            return False
    return True


def _reference_slide_indices(path: Path) -> set[int]:
    try:
        reference = read_json(path)
    except Exception:
        return set()
    slides = reference.get("slides") if isinstance(reference, dict) else None
    if not isinstance(slides, list):
        return set()
    return {item["slide_index"] for item in slides if isinstance(item, dict) and isinstance(item.get("slide_index"), int)}


def _append_manual_todos(path: Path, page_audits: list[dict[str, Any]]) -> None:
    todo_lines: list[str] = []
    for audit in page_audits:
        for todo in audit.get("manual_todos", []):
            authorization = "是" if todo["requires_authorization"] else "否"
            todo_lines.append(
                f"- [open] 页：{todo['slide_index']} | 类型：{todo['category']} | 原因：{todo['reason']} | 授权：{authorization}"
            )
    if not todo_lines:
        return
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Canva 人工待处理项\n\n"
    missing = [line for line in todo_lines if line not in existing]
    if missing:
        path.write_text(existing.rstrip() + "\n" + "\n".join(missing) + "\n", encoding="utf-8")


def _validate_canva_export(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("Canva export record must be an object")
    _assert_safe_task_value(value)
    design_id = value.get("design_id")
    if not isinstance(design_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", design_id):
        raise ValidationError("Canva export design_id may only contain letters, numbers, underscore, or hyphen")
    export_format = value.get("format")
    if export_format not in CANVA_EXPORT_FORMATS:
        raise ValidationError("unsupported Canva export format")
    page_indices = value.get("page_indices")
    if not isinstance(page_indices, list) or not page_indices or not all(isinstance(item, int) and item > 0 for item in page_indices):
        raise ValidationError("Canva export page_indices must be a non-empty positive integer list")
    status = value.get("status")
    if status not in CANVA_EXPORT_STATUSES:
        raise ValidationError("unsupported Canva export status")
    return {
        "design_id": design_id,
        "format": export_format,
        "page_indices": sorted(set(page_indices)),
        "status": status,
    }


def _assert_safe_task_value(value: Any, *, key: str = "") -> None:
    lowered_key = key.lower()
    sensitive_key = lowered_key in _SENSITIVE_KEY_FRAGMENTS or any(
        lowered_key.endswith("_" + fragment)
        for fragment in _SENSITIVE_KEY_FRAGMENTS - {"authorization"}
    )
    if sensitive_key:
        raise ValidationError(f"Canva task events must not contain sensitive field: {key}")
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if not isinstance(child_key, str):
                raise ValidationError("Canva task event keys must be strings")
            _assert_safe_task_value(child_value, key=child_key)
        return
    if isinstance(value, list):
        for item in value:
            _assert_safe_task_value(item, key=key)
        return
    if not isinstance(value, str):
        return
    lowered_value = value.lower()
    if any(fragment in lowered_value for fragment in _SENSITIVE_VALUE_FRAGMENTS):
        raise ValidationError("Canva task events must not contain credentials or signed URLs")
    if "://" in value or re.search(r"(^|\\s)(/Users/|/home/|[A-Za-z]:\\\\)", value):
        raise ValidationError("Canva task events must not contain URLs or local paths")


def _reference_slides(root: Path, content: dict[str, Any]) -> list[dict[str, Any]]:
    raw_slides = content.get("slides")
    if not isinstance(raw_slides, list):
        raise ValidationError("stage1 content.json slides must be a list")

    slides = []
    for position, slide in enumerate(raw_slides, start=1):
        if not isinstance(slide, dict):
            raise ValidationError(f"stage1 content slide {position} must be an object")
        slide_index = slide.get("slide_index")
        if not isinstance(slide_index, int) or slide_index <= 0:
            raise ValidationError(f"stage1 content slide {position} requires positive slide_index")
        final_visible_text = slide.get("final_visible_text")
        if not isinstance(final_visible_text, list) or not all(isinstance(item, str) for item in final_visible_text):
            raise ValidationError(f"stage1 content slide {slide_index} final_visible_text must be a string list")
        image_rel = STAGE2_IMAGES_REL / f"slide_{slide_index:03d}.png"
        record = {
            "slide_index": slide_index,
            "title": str(slide.get("title") or ""),
            "page_type": str(slide.get("page_type") or ""),
            "purpose": str(slide.get("purpose") or ""),
            "final_visible_text": final_visible_text,
            "stage2_image": _posix(image_rel) if (root / image_rel).exists() else None,
        }
        slides.append(record)
    return sorted(slides, key=lambda item: item["slide_index"])


def _normal_task_id(value: str) -> str:
    task_id = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", task_id):
        raise ValidationError("Canva task id may only contain letters, numbers, underscore, or hyphen")
    return task_id


def _default_task_id() -> str:
    return "canva_" + re.sub(r"[^0-9]", "", now_iso())[:14]


def _stage_state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_stage": state.get("current_stage"),
        "status": state.get("status"),
        "required_actor": state.get("required_actor"),
        "confirmed": state.get("confirmed"),
        "quality": state.get("quality"),
        "stage3_locked_presentation_source": state.get("stage3_locked_presentation_source"),
        "last_decision_id": state.get("last_decision_id"),
    }


def _posix(path: str | Path) -> str:
    return Path(path).as_posix()
