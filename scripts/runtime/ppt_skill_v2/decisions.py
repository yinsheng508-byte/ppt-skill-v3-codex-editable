from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .deliverable_naming import (
    LEGACY_STAGE2_IMAGE_PDF_REL,
    existing_stage2_image_pdf_rel,
    existing_stage4_lesson_plan_output_rel,
    existing_stage4_output_rel,
)
from .education_context import is_k12_lesson_plan_required, load_education_context
from .events import append_event
from .json_io import read_json, write_json
from .paths import decision_path, decisions_dir
from .stage3_artifact_hashes import require_no_stage3_stale_artifacts
from .state import read_state, set_stage4_lesson_plan_required, stage4_lesson_plan_required, write_state
from .coordinate_stage3_qa import validate_coordinate_stage3_qa_review
from .validation import (
    ValidationError,
    validate_controller_decision,
    validate_deck_style,
    validate_layout_intent,
    validate_lesson_plan_manifest,
    validate_lesson_plan_qa,
    validate_speaker_script_manifest,
)


def record_decision(run_dir: str | Path, decision: dict[str, Any]) -> Path:
    validated = validate_controller_decision(decision)
    state = read_state(run_dir)
    _require_decision_matches_state(validated, state)
    target = decision_path(run_dir, validated["decision_id"])
    if target.exists():
        raise FileExistsError(f"decision already exists: {target}")
    decisions_dir(run_dir).mkdir(parents=True, exist_ok=True)
    write_json(target, validated)
    append_event(
        run_dir,
        "decision_recorded",
        "main_controller",
        decision_id=validated["decision_id"],
        decision_type=validated["decision_type"],
    )
    return target


def load_decision(run_dir: str | Path, decision_id: str | None = None, decision_file: str | Path | None = None) -> dict[str, Any]:
    if decision_file:
        return validate_controller_decision(read_json(decision_file))
    if not decision_id:
        raise ValueError("decision_id or decision_file is required")
    return validate_controller_decision(read_json(decision_path(run_dir, decision_id)))


def execute_decision(run_dir: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    decision = validate_controller_decision(decision)
    decision_type = decision["decision_type"]
    state = read_state(run_dir)
    _require_decision_matches_state(decision, state)
    _require_state_stage(state, decision["from_stage"])

    if decision_type == "stage1_ready_for_user_review":
        state["current_stage"] = "stage1"
        state["status"] = "waiting_user_confirmation"
        state["required_actor"] = "user"
        state["quality"]["stage1"] = "pending_user_review"
        state["next_required_action"] = "等待用户确认阶段1规划"
    elif decision_type == "approve_stage1_start_stage2":
        _require_state_status(state, "waiting_user_confirmation", decision_type)
        _require_stage1_validated(run_dir)
        state["confirmed"]["stage1_plan"] = True
        state["current_stage"] = "stage2"
        state["status"] = "ready_for_stage2_cover_options"
        state["required_actor"] = "main_controller"
        state["quality"]["stage1"] = "confirmed"
        state["next_required_action"] = "由主控大模型显式分发阶段2A四封面风格候选任务"
    elif decision_type == "request_stage1_revision":
        state["current_stage"] = "stage1"
        state["status"] = "revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage1"] = "needs_revision"
        state["next_required_action"] = "主控大模型修订阶段1规划"
    elif decision_type == "stage2_cover_options_ready_for_user_review":
        state["current_stage"] = "stage2"
        state["status"] = "waiting_user_cover_style_selection"
        state["required_actor"] = "user"
        state["user_artifacts"]["stage2_cover_options"] = "阶段2_图片版PPT/封面风格候选/封面风格选择说明.md"
        state["quality"]["stage2_cover_options"] = "pending_user_review"
        state["next_required_action"] = "等待用户从四张封面候选中选择整套PPT风格"
    elif decision_type == "approve_stage2_cover_style_start_image_deck":
        _require_state_status(state, "waiting_user_cover_style_selection", decision_type)
        _require_cover_style_assets(run_dir)
        state["confirmed"]["stage2_cover_style"] = True
        state["current_stage"] = "stage2"
        state["status"] = "ready_for_stage2_image_deck"
        state["required_actor"] = "main_controller"
        state["user_artifacts"]["selected_cover_style"] = "_state/阶段2/cover_options/selection/selection.json"
        state["quality"]["stage2_cover_options"] = "confirmed"
        state["next_required_action"] = "由主控大模型先将无明显质量问题的已选封面候选转正为正式封面页，再分发阶段2B试样；试样确认后生成剩余页面并打包图片版 PDF"
    elif decision_type == "request_stage2_cover_style_revision":
        state["current_stage"] = "stage2"
        state["status"] = "cover_style_revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2_cover_options"] = "needs_revision"
        state["next_required_action"] = "主控大模型组织阶段2A封面风格候选返工"
    elif decision_type == "stage2_trial_first5_ready_for_user_review":
        if not state["confirmed"].get("stage2_cover_style"):
            raise ValidationError("stage2 cover style must be confirmed before trial first5 review")
        state["current_stage"] = "stage2"
        state["status"] = "waiting_user_trial_first5_confirmation"
        state["required_actor"] = "user"
        state["user_artifacts"]["stage2_trial_first5"] = "阶段2_图片版PPT/前5页试样/前5页试样说明.md"
        state["quality"]["stage2_trial_first5"] = "pending_user_review"
        state["next_required_action"] = "等待用户确认阶段2B试样；有问题则返工阶段2设计规划和提示词"
    elif decision_type == "approve_stage2_trial_first5_continue_remaining":
        _require_state_status(state, "waiting_user_trial_first5_confirmation", decision_type)
        _require_file_exists(
            run_dir,
            "阶段2_图片版PPT/前5页试样/前5页试样说明.md",
            "stage2 trial first5 summary is required before approving trial",
        )
        state["confirmed"]["stage2_trial_first5"] = True
        state["current_stage"] = "stage2"
        state["status"] = "ready_for_stage2_remaining_images"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2_trial_first5"] = "confirmed"
        state["next_required_action"] = "由主控大模型复用已确认试样并生成剩余页面，然后打包图片版 PDF"
    elif decision_type == "request_stage2_trial_first5_revision":
        _require_state_status(state, "waiting_user_trial_first5_confirmation", decision_type)
        state["confirmed"]["stage2_trial_first5"] = False
        state["current_stage"] = "stage2"
        state["status"] = "trial_first5_revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2_trial_first5"] = "needs_revision"
        state["next_required_action"] = "主控大模型返工阶段2设计规划、layout_intent 或提示词；除非用户明确改内容，不修改阶段1任务"
    elif decision_type == "stage2_ready_for_user_review":
        stage2_pdf = _require_stage2_image_pdf(run_dir, state, "stage2 image PDF is required before stage2 user review")
        state["current_stage"] = "stage2"
        state["status"] = "waiting_user_confirmation"
        state["required_actor"] = "user"
        state.setdefault("user_artifacts", {})["stage2_image_deck"] = stage2_pdf
        state.setdefault("expected_user_paths", {})["stage2_image_deck"] = stage2_pdf
        state["quality"]["stage2"] = "pending_user_review"
        state["next_required_action"] = "等待用户确认阶段2图片版 PDF"
    elif decision_type == "approve_stage2_start_stage3":
        _require_state_status(state, "waiting_user_confirmation", decision_type)
        stage2_pdf = _require_stage2_image_pdf(run_dir, state, "stage2 image PDF is required before approving stage2")
        state["confirmed"]["stage2_image_deck"] = True
        state.setdefault("user_artifacts", {})["stage2_image_deck"] = stage2_pdf
        state.setdefault("expected_user_paths", {})["stage2_image_deck"] = stage2_pdf
        state["current_stage"] = "stage3"
        state["status"] = "ready_for_stage3"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2"] = "confirmed"
        state["next_required_action"] = "由主控大模型显式分发阶段3无字背景任务"
    elif decision_type == "approve_stage2_skip_stage3_start_script_output":
        _require_state_status(state, "waiting_user_confirmation", decision_type)
        stage2_pdf = _require_stage2_image_pdf(run_dir, state, "stage2 image PDF is required before skipping stage3")
        locked_source = _stage4_locked_source_from_decision(run_dir, decision)
        state["confirmed"]["stage2_image_deck"] = True
        state.setdefault("user_artifacts", {})["stage2_image_deck"] = stage2_pdf
        state.setdefault("expected_user_paths", {})["stage2_image_deck"] = stage2_pdf
        state["confirmed"]["stage3_coordinate_plan"] = False
        state["confirmed"]["stage3_editable_deck"] = False
        state["current_stage"] = "stage4"
        state["status"] = "ready_for_stage4_script"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2"] = "confirmed"
        state["quality"]["stage3"] = "skipped"
        state["stage4_locked_presentation_source"] = locked_source
        state["user_artifacts"]["stage4_locked_presentation_source"] = locked_source["source_path"]
        lesson_required = _apply_stage4_lesson_plan_requirement(run_dir, state)
        state["next_required_action"] = _stage4_ready_next_action(lesson_required)
    elif decision_type == "request_stage2_revision":
        state["current_stage"] = "stage2"
        state["status"] = "revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2"] = "needs_revision"
        state["next_required_action"] = "主控大模型组织阶段2返工"
    elif decision_type == "reopen_stage3_sample_after_stage4":
        _require_state_status(state, "completed", decision_type)
        _require_stage2_image_pdf(run_dir, state, "stage2 image PDF is required before reopening stage3")
        scope = _stage3_sample_scope_from_decision(decision)
        state["confirmed"]["stage3_coordinate_plan"] = False
        state["confirmed"]["stage3_editable_deck"] = False
        state["current_stage"] = "stage3"
        state["status"] = "ready_for_stage3"
        state["required_actor"] = "main_controller"
        state["quality"]["stage3"] = "reopened_for_sample"
        state["user_artifacts"]["stage3_coordinate_preview"] = None
        state["user_artifacts"]["stage3_editable_deck"] = None
        state["stage3_reopen_scope"] = scope
        state["next_required_action"] = "主控大模型按 stage3_reopen_scope 重做阶段3样稿：拆字、归属、去字背景和坐标复刻预览"
    elif decision_type == "approve_stage3_coordinate_plan_start_text_fill":
        _require_state_status(state, "waiting_user_coordinate_plan_confirmation", decision_type)
        _require_file_exists(run_dir, "_state/阶段3/editable_coordinate_plan.json", "stage3 editable coordinate plan is required before text fill")
        state["confirmed"]["stage3_coordinate_plan"] = True
        state["current_stage"] = "stage3"
        state["status"] = "stage3_coordinate_plan_confirmed"
        state["required_actor"] = "main_controller"
        state["quality"]["stage3"] = "coordinate_plan_confirmed"
        state["next_required_action"] = "主控大模型构建 OfficeCLI 可编辑 PPT handoff brief，并按已确认 editable_coordinate_plan 运行 OfficeCLI builder 填字"
    elif decision_type == "request_stage3_coordinate_plan_revision":
        _require_state_status(state, "waiting_user_coordinate_plan_confirmation", decision_type)
        state["confirmed"]["stage3_coordinate_plan"] = False
        state["current_stage"] = "stage3"
        state["status"] = "coordinate_plan_revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage3"] = "coordinate_plan_needs_revision"
        state["next_required_action"] = "主控大模型基于用户反馈重新从阶段2确认图识别文字坐标，并更新 editable_coordinate_plan"
    elif decision_type == "stage3_ready_for_user_review":
        state["current_stage"] = "stage3"
        state["status"] = "waiting_user_confirmation"
        state["required_actor"] = "user"
        state["quality"]["stage3"] = "pending_user_review"
        state["next_required_action"] = "等待用户确认阶段3可编辑PPT"
    elif decision_type == "approve_stage3_start_script_output":
        _require_state_status(state, "waiting_user_confirmation", decision_type)
        require_no_stage3_stale_artifacts(run_dir, state=state)
        editable_manifest = _require_editable_deck_manifest(run_dir)
        _require_stage3_visual_qa_review(run_dir)
        state["confirmed"]["stage3_editable_deck"] = True
        state["current_stage"] = "stage4"
        state["status"] = "ready_for_stage4_script"
        state["required_actor"] = "main_controller"
        state["quality"]["stage3"] = "confirmed"
        state["stage4_locked_presentation_source"] = _stage3_locked_source(editable_manifest)
        state["user_artifacts"]["stage4_locked_presentation_source"] = state["stage4_locked_presentation_source"]["source_path"]
        lesson_required = _apply_stage4_lesson_plan_requirement(run_dir, state)
        state["next_required_action"] = _stage4_ready_next_action(lesson_required)
    elif decision_type == "request_stage3_revision":
        state["current_stage"] = "stage3"
        state["status"] = "revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage3"] = "needs_revision"
        state["next_required_action"] = "主控大模型组织阶段3返工"
    elif decision_type == "stage4_script_completed":
        if not decision.get("controller_reviewed"):
            raise ValidationError("stage4_script_completed requires controller_reviewed=true")
        speaker_manifest_path = Path(run_dir) / "_state" / "阶段4" / "speaker_script_manifest.json"
        _require_file_exists(run_dir, "_state/阶段4/speaker_script_manifest.json", "speaker script manifest is required before completing stage4")
        speaker_manifest = validate_speaker_script_manifest(read_json(speaker_manifest_path))
        if speaker_manifest["status"] != "generated":
            raise ValidationError("speaker script manifest status must be generated before completing stage4")
        stage4_markdown = _require_stage4_output(run_dir, state, "stage4_speaker_script", "speaker script markdown is required before completing stage4", manifest=speaker_manifest)
        stage4_docx = _require_stage4_output(run_dir, state, "stage4_speaker_script_docx", "speaker script DOCX is required before completing stage4", manifest=speaker_manifest)
        stage4_pdf = _require_stage4_output(run_dir, state, "stage4_speaker_script_pdf", "speaker script PDF is required before completing stage4", manifest=speaker_manifest)
        state["confirmed"]["stage4_speaker_script"] = True
        state.setdefault("user_artifacts", {})["stage4_speaker_script"] = stage4_markdown
        state["user_artifacts"]["stage4_speaker_script_docx"] = stage4_docx
        state["user_artifacts"]["stage4_speaker_script_pdf"] = stage4_pdf
        state.setdefault("expected_user_paths", {})["stage4_speaker_script"] = stage4_markdown
        state["expected_user_paths"]["stage4_speaker_script_docx"] = stage4_docx
        state["expected_user_paths"]["stage4_speaker_script_pdf"] = stage4_pdf
        stage4_outputs = state.setdefault("stage4_outputs", {})
        speaker_output = stage4_outputs.setdefault("speaker_script", {})
        speaker_output["required"] = True
        speaker_output["status"] = "qa_passed"
        lesson_required = stage4_lesson_plan_required(state)
        if lesson_required:
            _require_file_exists(run_dir, "_state/阶段4/lesson_plan_manifest.json", "lesson plan manifest is required before completing K12 stage4")
            lesson_manifest = validate_lesson_plan_manifest(read_json(Path(run_dir) / "_state" / "阶段4" / "lesson_plan_manifest.json"))
            if lesson_manifest["status"] != "generated":
                raise ValidationError("lesson plan manifest status must be generated before completing K12 stage4")
            if lesson_manifest.get("summary", {}).get("pdf_text_probe") == "no_selectable_text_detected":
                raise ValidationError("lesson plan PDF selectable text is required before completing K12 stage4")
            lesson_markdown = _require_stage4_lesson_plan_output(run_dir, state, "stage4_lesson_plan", "lesson plan markdown is required before completing K12 stage4", manifest=lesson_manifest)
            lesson_docx = _require_stage4_lesson_plan_output(run_dir, state, "stage4_lesson_plan_docx", "lesson plan DOCX is required before completing K12 stage4", manifest=lesson_manifest)
            lesson_pdf = _require_stage4_lesson_plan_output(run_dir, state, "stage4_lesson_plan_pdf", "lesson plan PDF is required before completing K12 stage4", manifest=lesson_manifest)
            lesson_qa = _read_optional_lesson_plan_review(run_dir)
            state["confirmed"]["stage4_lesson_plan"] = True
            state["user_artifacts"]["stage4_lesson_plan"] = lesson_markdown
            state["user_artifacts"]["stage4_lesson_plan_docx"] = lesson_docx
            state["user_artifacts"]["stage4_lesson_plan_pdf"] = lesson_pdf
            state["expected_user_paths"]["stage4_lesson_plan"] = lesson_markdown
            state["expected_user_paths"]["stage4_lesson_plan_docx"] = lesson_docx
            state["expected_user_paths"]["stage4_lesson_plan_pdf"] = lesson_pdf
            lesson_output = stage4_outputs.setdefault("lesson_plan", {})
            lesson_output["required"] = True
            if lesson_qa and lesson_qa["status"] == "pass_with_warnings":
                lesson_output["status"] = "qa_passed_with_warnings"
            elif lesson_qa and lesson_qa["status"] == "pass":
                lesson_output["status"] = "qa_passed"
            else:
                lesson_output["status"] = "controller_reviewed"
        state["current_stage"] = "stage4"
        state["status"] = "completed"
        state["required_actor"] = "none"
        state["quality"]["stage4"] = "completed"
        state["next_required_action"] = _stage4_completed_next_action(lesson_required)
    else:
        raise ValidationError(f"unsupported decision type: {decision_type}")

    state["last_decision_id"] = decision["decision_id"]
    write_state(run_dir, state)
    append_event(
        run_dir,
        "decision_executed",
        "runtime",
        decision_id=decision["decision_id"],
        decision_type=decision_type,
    )
    return state


def _require_decision_matches_state(decision: dict[str, Any], state: dict[str, Any]) -> None:
    if decision["run_dir"] != state["run_dir"]:
        raise ValidationError("decision.run_dir does not match project state")
    if decision["project_name"] != state["project_name"]:
        raise ValidationError("decision.project_name does not match project state")


def _require_state_stage(state: dict[str, Any], expected_stage: str) -> None:
    if state["current_stage"] != expected_stage:
        raise ValidationError(f"decision requires current_stage={expected_stage}, got {state['current_stage']}")


def _require_state_status(state: dict[str, Any], expected_status: str, decision_type: str) -> None:
    if state["status"] != expected_status:
        raise ValidationError(f"{decision_type} requires status={expected_status}, got {state['status']}")


def _require_stage1_validated(run_dir: str | Path) -> None:
    report_path = Path(run_dir) / "_state" / "阶段1" / "validation_report.json"
    if not report_path.exists():
        raise ValidationError("stage1 validation report is required before approving stage1")
    report = read_json(report_path)
    if not isinstance(report, dict) or not report.get("ok"):
        raise ValidationError("stage1 validation must pass before approving stage1")


def _require_file_exists(run_dir: str | Path, relpath: str, message: str) -> None:
    if not (Path(run_dir) / relpath).exists():
        raise ValidationError(message)


def _require_stage2_image_pdf(run_dir: str | Path, state: dict[str, Any], message: str) -> str:
    relpath = existing_stage2_image_pdf_rel(run_dir, state)
    if not relpath:
        raise ValidationError(message)
    return relpath


def _require_stage4_output(
    run_dir: str | Path,
    state: dict[str, Any],
    artifact_key: str,
    message: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> str:
    relpath = existing_stage4_output_rel(run_dir, artifact_key, state=state, manifest=manifest)
    if not relpath:
        raise ValidationError(message)
    return relpath


def _require_stage4_lesson_plan_output(
    run_dir: str | Path,
    state: dict[str, Any],
    artifact_key: str,
    message: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> str:
    relpath = existing_stage4_lesson_plan_output_rel(run_dir, artifact_key, state=state, manifest=manifest)
    if not relpath:
        raise ValidationError(message)
    return relpath


def _read_optional_lesson_plan_review(run_dir: str | Path) -> dict[str, Any] | None:
    qa_path = Path(run_dir) / "_state" / "阶段4" / "lesson_plan_qa.json"
    if not qa_path.exists():
        return None
    qa = validate_lesson_plan_qa(read_json(qa_path))
    if qa["status"] == "fail" or qa.get("blockers"):
        raise ValidationError("lesson plan self-review records blockers before completing K12 stage4")
    return qa


def _apply_stage4_lesson_plan_requirement(run_dir: str | Path, state: dict[str, Any]) -> bool:
    try:
        context = load_education_context(run_dir, state=state)
    except ValidationError:
        context = {}
    if context:
        state["education_context"] = context
    required = stage4_lesson_plan_required(state) or is_k12_lesson_plan_required(context)
    if required:
        set_stage4_lesson_plan_required(state, required=True, reason=_lesson_plan_required_reason(context))
    else:
        set_stage4_lesson_plan_required(state, required=False, skip_reason="education_context 未识别为 K12 课件")
    return required


def _lesson_plan_required_reason(context: dict[str, Any]) -> str:
    parts = ["K12课件"]
    for field in ("grade", "subject", "lesson_title"):
        value = context.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "｜".join(parts)


def _stage4_ready_next_action(lesson_required: bool) -> str:
    if lesson_required:
        return "由主控大模型基于已确认锁定稿撰写阶段4演讲逐字稿，并基于 K12 教育上下文与教材资料撰写教案设计，分别生成 Word 与 PDF"
    return "由主控大模型基于已确认锁定稿撰写阶段4演讲逐字稿，并生成 Word 与 PDF"


def _stage4_completed_next_action(lesson_required: bool) -> str:
    if lesson_required:
        return "项目已完成，阶段4演讲逐字稿和 K12 教案设计的 Markdown、Word、PDF 已输出"
    return "项目已完成，阶段4演讲逐字稿、Word 和 PDF 已输出"


def _stage3_sample_scope_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    basis = decision.get("basis", {})
    execution = decision.get("execution", {})
    slide_indices = None
    if isinstance(execution, dict):
        slide_indices = execution.get("slide_indices")
    if slide_indices is None and isinstance(basis, dict):
        slide_indices = basis.get("slide_indices")
    if not isinstance(slide_indices, list) or not slide_indices:
        raise ValidationError("reopen_stage3_sample_after_stage4 requires execution.slide_indices")
    normalized: list[int] = []
    for item in slide_indices:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValidationError("reopen_stage3_sample_after_stage4 slide_indices must contain positive integers")
        if item not in normalized:
            normalized.append(item)
    return {
        "mode": "sample_slide_indices",
        "slide_indices": normalized,
        "basis_decision_id": decision["decision_id"],
        "notes": str(basis.get("notes") or "") if isinstance(basis, dict) else "",
    }


def _require_editable_deck_manifest(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    manifest_path = root / "_state" / "阶段3" / "manifests" / "editable_deck.json"
    if not manifest_path.exists():
        raise ValidationError("stage3 editable deck runtime manifest is required before approving stage3")
    manifest = read_json(manifest_path)
    deck_rel = manifest.get("deck_path")
    if not isinstance(deck_rel, str) or not deck_rel.strip():
        raise ValidationError("editable deck manifest must include deck_path")
    deck_path = root / deck_rel
    if not deck_path.exists():
        raise ValidationError("editable deck manifest points to a missing PPTX")
    expected_sha = manifest.get("pptx_sha256")
    if not isinstance(expected_sha, str) or not expected_sha.startswith("sha256:"):
        raise ValidationError("editable deck manifest must include pptx_sha256")
    actual_sha = f"sha256:{hashlib.sha256(deck_path.read_bytes()).hexdigest()}"
    if actual_sha != expected_sha:
        raise ValidationError("editable deck manifest pptx_sha256 does not match PPTX")
    return manifest


def _stage3_locked_source(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "source_mode": "stage3_editable_deck",
        "source_path": manifest["deck_path"],
        "source_sha256": manifest["pptx_sha256"],
        "confirmation_basis": "用户确认阶段3可编辑 PPT，可作为阶段4讲稿锁定稿。",
    }


def _stage4_locked_source_from_decision(run_dir: str | Path, decision: dict[str, Any]) -> dict[str, str]:
    basis = decision.get("basis", {})
    state = read_state(run_dir)
    default_stage2_source = existing_stage2_image_pdf_rel(run_dir, state) or LEGACY_STAGE2_IMAGE_PDF_REL
    candidate = basis.get("locked_presentation_source") if isinstance(basis, dict) else None
    if isinstance(candidate, dict):
        mode = candidate.get("source_mode") or "stage2_image_deck"
        source_path = candidate.get("source_path") or default_stage2_source
        confirmation_basis = candidate.get("confirmation_basis") or str(basis.get("notes") or "")
    else:
        mode = "stage2_image_deck"
        source_path = default_stage2_source
        confirmation_basis = str(basis.get("notes") or "用户确认阶段2图片版 PDF 可作为阶段4讲稿锁定稿。")
    if mode not in {"stage2_image_deck", "external_editable_deck"}:
        raise ValidationError("approve_stage2_skip_stage3_start_script_output supports stage2_image_deck or external_editable_deck only")
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValidationError("locked_presentation_source.source_path is required before entering stage4")
    resolved = _resolve_locked_source_path(run_dir, source_path)
    if not resolved.exists():
        raise ValidationError("locked presentation source does not exist")
    locked_source = {
        "source_mode": mode,
        "source_path": source_path,
        "source_sha256": _file_sha256(resolved),
        "confirmation_basis": confirmation_basis,
    }
    known_stage2_source = existing_stage2_image_pdf_rel(run_dir, state)
    if mode == "stage2_image_deck" and known_stage2_source and source_path != known_stage2_source:
        raise ValidationError(f"stage2_image_deck locked source must be {known_stage2_source}")
    return locked_source


def _resolve_locked_source_path(run_dir: str | Path, source_path: str) -> Path:
    path = Path(source_path)
    return path if path.is_absolute() else Path(run_dir) / path


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _require_stage3_visual_qa_review(run_dir: str | Path) -> None:
    root = Path(run_dir)
    review_path = root / "_state" / "阶段3" / "render_review" / "stage3_visual_qa_review.json"
    if not review_path.exists():
        raise ValidationError("stage3 visual QA review is required before approving stage3")
    review = validate_coordinate_stage3_qa_review(read_json(review_path))
    if review.get("overall_status") != "passed":
        raise ValidationError("stage3 visual QA review must pass before approving stage3")


def _require_cover_style_assets(run_dir: str | Path) -> None:
    root = Path(run_dir)
    selection = root / "_state" / "阶段2" / "cover_options" / "selection" / "selection.json"
    style = root / "_state" / "阶段2" / "deck_style.json"
    intent = root / "_state" / "阶段2" / "layout_intent.json"
    for path, label in (
        (selection, "cover style selection"),
        (style, "deck_style.json"),
        (intent, "layout_intent.json"),
    ):
        if not path.exists():
            raise ValidationError(f"{label} is required before approving cover style")
    validate_deck_style(read_json(style))
    validate_layout_intent(read_json(intent))
