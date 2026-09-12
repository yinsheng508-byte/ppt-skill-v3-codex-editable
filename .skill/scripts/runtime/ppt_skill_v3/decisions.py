from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .deliverable_naming import (
    LEGACY_STAGE2_IMAGE_PDF_REL,
    existing_stage2_image_pdf_rel,
    existing_stage3_lesson_plan_output_rel,
    existing_stage3_output_rel,
)
from .education_context import is_k12_lesson_plan_required, load_education_context
from .events import append_event
from .cover_options import cover_option_results_complete
from .image_style import result_is_current
from .json_io import read_json, write_json
from .paths import decision_path, decisions_dir, existing_decision_path
from .stage2_trial import stage2_trial_first5_results_complete
from .state import read_state, set_stage3_lesson_plan_required, stage3_lesson_plan_required, write_state
from .validation import (
    ValidationError,
    validate_controller_decision,
    validate_deck_style,
    validate_layout_intent,
    validate_image_result,
    validate_lesson_plan_manifest,
    validate_lesson_plan_qa,
    validate_speaker_script_manifest,
    validate_stage4_organize_requirements,
    validate_stage4_organize_summary,
)


def record_decision(run_dir: str | Path, decision: dict[str, Any]) -> Path:
    validated = validate_controller_decision(decision)
    state = read_state(run_dir)
    _require_decision_matches_state(validated, state)
    target = decision_path(run_dir, validated["decision_id"])
    existing = existing_decision_path(run_dir, validated["decision_id"])
    if existing.exists():
        raise FileExistsError(f"decision already exists: {existing}")
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
    return validate_controller_decision(read_json(existing_decision_path(run_dir, decision_id)))


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
        state["next_required_action"] = "等待用户确认阶段1四份规划材料"
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
        state["next_required_action"] = "主控大模型修订阶段1页面规划、每页干净逐字稿、PPT一致性或图片风格"
    elif decision_type == "stage2_cover_options_ready_for_user_review":
        _require_cover_options_ready(run_dir)
        state["current_stage"] = "stage2"
        state["status"] = "waiting_user_cover_style_selection"
        state["required_actor"] = "user"
        state["user_artifacts"]["stage2_cover_options"] = "阶段2_图片版PPT/封面风格候选/"
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
        state["confirmed"]["stage2_cover_style"] = False
        state["confirmed"]["stage2_trial_first5"] = False
        state["confirmed"]["stage2_image_deck"] = False
        state["current_stage"] = "stage2"
        state["status"] = "cover_style_revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2_cover_options"] = "needs_revision"
        state["quality"]["stage2_trial_first5"] = "blocked_by_cover_revision"
        state["quality"]["stage2"] = "needs_revision"
        state["next_required_action"] = "主控大模型组织阶段2A封面风格候选返工"
    elif decision_type == "stage2_trial_first5_ready_for_user_review":
        if not state["confirmed"].get("stage2_cover_style"):
            raise ValidationError("stage2 cover style must be confirmed before trial first5 review")
        if not stage2_trial_first5_results_complete(run_dir):
            raise ValidationError("stage2 trial first5 selected images must be complete and current before user review")
        state["current_stage"] = "stage2"
        state["status"] = "waiting_user_trial_first5_confirmation"
        state["required_actor"] = "user"
        state["user_artifacts"]["stage2_trial_first5"] = "阶段2_图片版PPT/img/"
        state["quality"]["stage2_trial_first5"] = "pending_user_review"
        state["next_required_action"] = "等待用户确认阶段2B试样；有问题则返工阶段2设计规划和提示词"
    elif decision_type == "approve_stage2_trial_first5_continue_remaining":
        _require_state_status(state, "waiting_user_trial_first5_confirmation", decision_type)
        if not stage2_trial_first5_results_complete(run_dir):
            raise ValidationError("stage2 trial first5 selected images changed or are incomplete")
        state["confirmed"]["stage2_trial_first5"] = True
        state["current_stage"] = "stage2"
        state["status"] = "ready_for_stage2_remaining_images"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2_trial_first5"] = "confirmed"
        state["next_required_action"] = "由主控大模型复用已确认试样并生成剩余页面，然后打包图片版 PDF"
    elif decision_type == "request_stage2_trial_first5_revision":
        _require_state_status(state, "waiting_user_trial_first5_confirmation", decision_type)
        state["confirmed"]["stage2_trial_first5"] = False
        state["confirmed"]["stage2_image_deck"] = False
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
        locked_source = _stage3_locked_source_from_decision(run_dir, decision)
        state["confirmed"]["stage2_image_deck"] = True
        state.setdefault("user_artifacts", {})["stage2_image_deck"] = stage2_pdf
        state.setdefault("expected_user_paths", {})["stage2_image_deck"] = stage2_pdf
        state["current_stage"] = "stage3"
        state["status"] = "ready_for_stage3_script"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2"] = "confirmed"
        state["stage3_locked_presentation_source"] = locked_source
        state["user_artifacts"]["stage3_locked_presentation_source"] = locked_source["source_path"]
        lesson_required = _apply_stage3_lesson_plan_requirement(run_dir, state)
        state["next_required_action"] = _stage3_ready_next_action(lesson_required)
    elif decision_type == "request_stage2_revision":
        state["confirmed"]["stage2_image_deck"] = False
        state["current_stage"] = "stage2"
        state["status"] = "revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage2"] = "needs_revision"
        state["next_required_action"] = "主控大模型组织阶段2返工"
    elif decision_type == "stage3_outputs_completed":
        if not decision.get("controller_reviewed"):
            raise ValidationError("stage3_outputs_completed requires controller_reviewed=true")
        speaker_manifest_path = Path(run_dir) / "_state" / "阶段3" / "speaker_script_manifest.json"
        _require_file_exists(run_dir, "_state/阶段3/speaker_script_manifest.json", "speaker script manifest is required before completing stage3")
        speaker_manifest = validate_speaker_script_manifest(read_json(speaker_manifest_path))
        if speaker_manifest["status"] != "generated":
            raise ValidationError("speaker script manifest status must be generated before completing stage3")
        speaker_markdown = _require_stage3_output(run_dir, state, "stage3_speaker_script", "speaker script markdown is required before completing stage3", manifest=speaker_manifest)
        speaker_docx = _require_stage3_output(run_dir, state, "stage3_speaker_script_docx", "speaker script DOCX is required before completing stage3", manifest=speaker_manifest)
        speaker_pdf = _require_stage3_output(run_dir, state, "stage3_speaker_script_pdf", "speaker script PDF is required before completing stage3", manifest=speaker_manifest)
        state["confirmed"]["stage3_speaker_script"] = True
        state.setdefault("user_artifacts", {})["stage3_speaker_script"] = speaker_markdown
        state["user_artifacts"]["stage3_speaker_script_docx"] = speaker_docx
        state["user_artifacts"]["stage3_speaker_script_pdf"] = speaker_pdf
        state.setdefault("expected_user_paths", {})["stage3_speaker_script"] = speaker_markdown
        state["expected_user_paths"]["stage3_speaker_script_docx"] = speaker_docx
        state["expected_user_paths"]["stage3_speaker_script_pdf"] = speaker_pdf
        stage3_outputs = state.setdefault("stage3_outputs", {})
        speaker_output = stage3_outputs.setdefault("speaker_script", {})
        speaker_output["required"] = True
        speaker_output["status"] = "qa_passed"
        lesson_required = stage3_lesson_plan_required(state)
        if lesson_required:
            _require_file_exists(run_dir, "_state/阶段3/lesson_plan_manifest.json", "lesson plan manifest is required before completing K12 stage3")
            lesson_manifest = validate_lesson_plan_manifest(read_json(Path(run_dir) / "_state" / "阶段3" / "lesson_plan_manifest.json"))
            if lesson_manifest["status"] != "generated":
                raise ValidationError("lesson plan manifest status must be generated before completing K12 stage3")
            if lesson_manifest.get("summary", {}).get("pdf_text_probe") == "no_selectable_text_detected":
                raise ValidationError("lesson plan PDF selectable text is required before completing K12 stage3")
            lesson_markdown = _require_stage3_lesson_plan_output(run_dir, state, "stage3_lesson_plan", "lesson plan markdown is required before completing K12 stage3", manifest=lesson_manifest)
            lesson_docx = _require_stage3_lesson_plan_output(run_dir, state, "stage3_lesson_plan_docx", "lesson plan DOCX is required before completing K12 stage3", manifest=lesson_manifest)
            lesson_pdf = _require_stage3_lesson_plan_output(run_dir, state, "stage3_lesson_plan_pdf", "lesson plan PDF is required before completing K12 stage3", manifest=lesson_manifest)
            lesson_qa = _read_optional_lesson_plan_review(run_dir)
            state["confirmed"]["stage3_lesson_plan"] = True
            state["user_artifacts"]["stage3_lesson_plan"] = lesson_markdown
            state["user_artifacts"]["stage3_lesson_plan_docx"] = lesson_docx
            state["user_artifacts"]["stage3_lesson_plan_pdf"] = lesson_pdf
            state["expected_user_paths"]["stage3_lesson_plan"] = lesson_markdown
            state["expected_user_paths"]["stage3_lesson_plan_docx"] = lesson_docx
            state["expected_user_paths"]["stage3_lesson_plan_pdf"] = lesson_pdf
            lesson_output = stage3_outputs.setdefault("lesson_plan", {})
            lesson_output["required"] = True
            if lesson_qa and lesson_qa["status"] == "pass_with_warnings":
                lesson_output["status"] = "qa_passed_with_warnings"
            elif lesson_qa and lesson_qa["status"] == "pass":
                lesson_output["status"] = "qa_passed"
            else:
                lesson_output["status"] = "controller_reviewed"
        state["current_stage"] = "stage4"
        state["status"] = "ready_for_stage4_organize"
        state["required_actor"] = "main_controller"
        state["quality"]["stage3"] = "completed"
        state["next_required_action"] = "执行阶段4文件整理交付，复制已存在产物并按需渲染逐字稿/教案 PDF 图片副本"
    elif decision_type == "request_stage3_lesson_plan_revision":
        if not stage3_lesson_plan_required(state):
            raise ValidationError("stage3 lesson plan revision requires K12 stage3_outputs.lesson_plan.required=true")
        state["confirmed"]["stage3_lesson_plan"] = False
        stage3_outputs = state.setdefault("stage3_outputs", {})
        lesson_output = stage3_outputs.setdefault("lesson_plan", {})
        lesson_output["required"] = True
        lesson_output["status"] = "revision_requested"
        state["current_stage"] = "stage3"
        state["status"] = "stage3_lesson_plan_revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage3"] = "lesson_plan_needs_revision"
        state["next_required_action"] = "主控大模型重做阶段3 K12 教案设计并重新生成 Markdown、Word 和 PDF；逐字稿保持已完成事实"
    elif decision_type == "stage4_deliverables_organized":
        _require_stage4_organized(run_dir, state, decision)
        state["confirmed"]["stage4_deliverables"] = True
        stage4_deliverables = state.setdefault("stage4_deliverables", {})
        stage4_deliverables["required"] = True
        stage4_deliverables["status"] = "organized"
        stage4_deliverables["organized_dir"] = _stage4_organized_dir_from_decision(state, decision)
        stage4_deliverables["summary"] = _stage4_organize_summary_from_decision(decision)
        if stage4_deliverables["organized_dir"]:
            state.setdefault("user_artifacts", {})["stage4_organized_dir"] = stage4_deliverables["organized_dir"]
        if stage4_deliverables["summary"]:
            state["user_artifacts"]["stage4_organize_summary"] = stage4_deliverables["summary"]
        state["current_stage"] = "stage4"
        state["status"] = "completed"
        state["required_actor"] = "none"
        state["quality"]["stage4"] = "completed"
        state["next_required_action"] = "项目已完成，阶段4文件整理交付已收口"
    elif decision_type == "request_stage4_organize_revision":
        state["confirmed"]["stage4_deliverables"] = False
        stage4_deliverables = state.setdefault("stage4_deliverables", {})
        stage4_deliverables["required"] = True
        stage4_deliverables["status"] = "revision_requested"
        state["current_stage"] = "stage4"
        state["status"] = "stage4_organize_revision_requested"
        state["required_actor"] = "main_controller"
        state["quality"]["stage4"] = "organize_needs_revision"
        state["next_required_action"] = "重新执行阶段4文件整理交付；不得重新生成阶段3逐字稿或教案"
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
    _require_stage2_pdf_current(run_dir, relpath)
    return relpath


def _require_stage2_pdf_current(run_dir: str | Path, relpath: str) -> None:
    root = Path(run_dir)
    pdf = root / relpath
    if not pdf.exists() or not pdf.is_file() or pdf.stat().st_size < 5:
        raise ValidationError("stage2 image PDF is missing or empty")
    if pdf.read_bytes()[:4] != b"%PDF":
        raise ValidationError("stage2 image PDF is not a valid PDF file")
    manifest_path = root / "_state" / "阶段2" / "manifests" / "image_deck.json"
    if not manifest_path.exists():
        raise ValidationError("阶段2图片版 PDF 缺少 image_deck manifest，不能确认当前风格有效性")
    manifest = read_json(manifest_path)
    if manifest.get("pdf_path") != relpath and manifest.get("deck_path") != relpath:
        raise ValidationError("stage2 image PDF path does not match image_deck manifest")
    expected_sha = manifest.get("pdf_sha256")
    if isinstance(expected_sha, str) and expected_sha.startswith("sha256:") and _file_sha256(pdf) != expected_sha:
        raise ValidationError("stage2 image PDF sha256 does not match image_deck manifest")
    from .stage1_plan import load_stage1_slides
    from .validation import validate_stage1_plan
    plan = validate_stage1_plan(load_stage1_slides(root))
    manifest_images = set(manifest.get("images") or [])
    for slide in plan["slides"]:
        slide_index = slide["slide_index"]
        result_path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
        if not result_path.exists():
            raise ValidationError(f"阶段2图片版 PDF 缺少第{slide_index}页正式结果记录")
        result = validate_image_result(read_json(result_path), production=not bool(read_json(result_path).get("fixture")))
        if result.get("purpose") != "full_slide" or not result_is_current(root, result):
            raise ValidationError(f"第{slide_index}页正式图片与当前风格依据不匹配")
        if result.get("image_path") not in manifest_images:
            raise ValidationError(f"image_deck manifest 未记录第{slide_index}页当前正式图片")


def _require_cover_options_ready(run_dir: str | Path) -> None:
    if not cover_option_results_complete(run_dir):
        raise ValidationError("四张封面候选必须都有当前有效图片结果，才能交给用户选择")


def _require_stage3_output(
    run_dir: str | Path,
    state: dict[str, Any],
    artifact_key: str,
    message: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> str:
    relpath = existing_stage3_output_rel(run_dir, artifact_key, state=state, manifest=manifest)
    if not relpath:
        raise ValidationError(message)
    return relpath


def _require_stage3_lesson_plan_output(
    run_dir: str | Path,
    state: dict[str, Any],
    artifact_key: str,
    message: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> str:
    relpath = existing_stage3_lesson_plan_output_rel(run_dir, artifact_key, state=state, manifest=manifest)
    if not relpath:
        raise ValidationError(message)
    return relpath


def _read_optional_lesson_plan_review(run_dir: str | Path) -> dict[str, Any] | None:
    qa_path = Path(run_dir) / "_state" / "阶段3" / "lesson_plan_qa.json"
    if not qa_path.exists():
        return None
    qa = validate_lesson_plan_qa(read_json(qa_path))
    if qa["status"] == "fail" or qa.get("blockers"):
        raise ValidationError("lesson plan self-review records blockers before completing K12 stage3")
    return qa


def _apply_stage3_lesson_plan_requirement(run_dir: str | Path, state: dict[str, Any]) -> bool:
    try:
        context = load_education_context(run_dir, state=state)
    except ValidationError:
        context = {}
    if context:
        state["education_context"] = context
    required = stage3_lesson_plan_required(state) or is_k12_lesson_plan_required(context)
    if required:
        set_stage3_lesson_plan_required(state, required=True, reason=_lesson_plan_required_reason(context))
    else:
        set_stage3_lesson_plan_required(state, required=False, skip_reason="education_context 未识别为 K12 课件")
    return required


def _lesson_plan_required_reason(context: dict[str, Any]) -> str:
    parts = ["K12课件"]
    for field in ("grade", "subject", "lesson_title"):
        value = context.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "｜".join(parts)


def _stage3_ready_next_action(lesson_required: bool) -> str:
    if lesson_required:
        return "由主控大模型基于已确认锁定稿撰写阶段3演讲逐字稿，并基于 K12 教育上下文与教材资料撰写教案设计，分别生成 Word 与 PDF"
    return "由主控大模型基于已确认锁定稿撰写阶段3演讲逐字稿，并生成 Word 与 PDF"


def _stage3_locked_source_from_decision(run_dir: str | Path, decision: dict[str, Any]) -> dict[str, str]:
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
        confirmation_basis = str(basis.get("notes") or "用户确认阶段2图片版 PDF 可作为阶段3逐字稿/教案锁定稿。")
    if mode not in {"stage2_image_deck", "external_locked_deck"}:
        raise ValidationError("approve_stage2_start_stage3 supports stage2_image_deck or external_locked_deck only")
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValidationError("locked_presentation_source.source_path is required before entering stage3")
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


def _stage4_organized_dir_from_decision(state: dict[str, Any], decision: dict[str, Any]) -> str | None:
    basis = decision.get("basis") if isinstance(decision.get("basis"), dict) else {}
    value = basis.get("organized_dir") or state.get("user_artifacts", {}).get("stage4_organized_dir")
    if isinstance(value, str) and value.strip():
        return value
    summary_rel = _stage4_organize_summary_from_decision(decision)
    if summary_rel and isinstance(state.get("run_dir"), str):
        try:
            summary = _read_stage4_organize_summary(state["run_dir"], summary_rel)
        except Exception:
            return None
        return summary["organized_dir"]
    return None


def _stage4_organize_summary_from_decision(decision: dict[str, Any]) -> str | None:
    basis = decision.get("basis") if isinstance(decision.get("basis"), dict) else {}
    value = basis.get("organize_summary") or basis.get("deliverable_manifest")
    return value if isinstance(value, str) and value.strip() else None


def _require_stage4_organized(run_dir: str | Path, state: dict[str, Any], decision: dict[str, Any]) -> None:
    summary_rel = _stage4_organize_summary_from_decision(decision)
    organized_rel = _stage4_organized_dir_from_decision(state, decision)
    if not summary_rel:
        raise ValidationError("stage4_deliverables_organized requires basis.organize_summary or basis.deliverable_manifest")
    summary = _read_stage4_organize_summary(run_dir, summary_rel)
    if summary["project_name"] != state["project_name"]:
        raise ValidationError("stage4 organize summary project_name does not match project state")
    if summary["run_dir"] != state["run_dir"]:
        raise ValidationError("stage4 organize summary run_dir does not match project state")
    if organized_rel:
        if _resolved_path(run_dir, organized_rel) != _resolved_path(run_dir, summary["organized_dir"]):
            raise ValidationError("basis.organized_dir does not match stage4 organize summary organized_dir")
    else:
        organized_rel = summary["organized_dir"]
    validate_stage4_organize_requirements(summary, state)
    if not organized_rel:
        raise ValidationError("stage4_deliverables_organized requires organized_dir in stage4 organize summary")
    organized_path = _resolve_path(run_dir, organized_rel)
    if not organized_path.exists() or not organized_path.is_dir():
        raise ValidationError("stage4 organized directory is missing")


def _resolve_locked_source_path(run_dir: str | Path, source_path: str) -> Path:
    path = Path(source_path)
    return path if path.is_absolute() else Path(run_dir) / path


def _read_stage4_organize_summary(run_dir: str | Path, summary_rel: str) -> dict[str, Any]:
    path = _resolve_path(run_dir, summary_rel)
    if not path.exists():
        raise ValidationError("stage4 organize summary is missing")
    return validate_stage4_organize_summary(read_json(path))


def _resolve_path(run_dir: str | Path, relpath: str) -> Path:
    path = Path(relpath)
    return path if path.is_absolute() else Path(run_dir) / path


def _resolved_path(run_dir: str | Path, relpath: str) -> Path:
    return _resolve_path(run_dir, relpath).resolve(strict=False)


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


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
