from __future__ import annotations

from pathlib import Path
from typing import Any

from .deliverable_naming import project_deliverable_relpaths
from .json_io import read_json, write_json
from .paths import project_state_path
from .time_utils import now_iso
from .validation import validate_project_state


def make_initial_state(project_name: str, run_dir: str | Path) -> dict[str, Any]:
    run_dir_text = str(run_dir)
    deliverables = project_deliverable_relpaths(run_dir, state={"project_name": project_name})
    return {
        "schema_version": "2.0",
        "project_name": project_name,
        "run_dir": run_dir_text,
        "current_stage": "stage0",
        "status": "initialized",
        "required_actor": "main_controller",
        "last_decision_id": None,
        "stage3_locked_presentation_source": None,
        "stage3_outputs": {
            "speaker_script": {
                "required": True,
                "status": "not_started",
            },
            "lesson_plan": {
                "required": False,
                "required_reason": None,
                "status": "not_started",
                "skip_reason": None,
            },
        },
        "stage4_deliverables": {
            "required": True,
            "status": "not_started",
            "organized_dir": None,
            "summary": None,
        },
        "confirmed": {
            "stage1_plan": False,
            "stage2_cover_style": False,
            "stage2_trial_first5": False,
            "stage2_image_deck": False,
            "stage3_speaker_script": False,
            "stage3_lesson_plan": False,
            "stage4_deliverables": False,
        },
        "user_artifacts": {
            "stage1_page_plan": None,
            "stage1_clean_transcript": None,
            "stage1_ppt_consistency": None,
            "stage1_style_prompt_plan": None,
            "stage1_image_style": None,
            "stage2_image_prompts": None,
            "stage2_cover_options": None,
            "selected_cover_style": None,
            "stage2_trial_first5": None,
            "stage2_image_deck": None,
            "stage3_locked_presentation_source": None,
            "stage3_speaker_script": None,
            "stage3_speaker_script_docx": None,
            "stage3_speaker_script_pdf": None,
            "stage3_lesson_plan": None,
            "stage3_lesson_plan_docx": None,
            "stage3_lesson_plan_pdf": None,
            "stage4_organized_dir": None,
            "stage4_organize_summary": None,
        },
        "expected_user_paths": {
            "stage1_page_plan": "阶段1_规划确认/页面规划.md",
            "stage1_clean_transcript": "阶段1_规划确认/每页干净逐字稿.md",
            "stage1_ppt_consistency": "阶段1_规划确认/PPT一致性.md",
            "stage1_style_prompt_plan": "阶段1_规划确认/图片风格.md",
            "stage1_image_style": "阶段1_规划确认/图片风格.md",
            "stage2_image_prompts": "阶段2_图片版PPT/图片生成提示词.md",
            "stage2_cover_options": "阶段2_图片版PPT/封面风格候选/",
            "stage2_trial_first5": "阶段2_图片版PPT/img/",
            "stage2_image_deck": deliverables["stage2_image_deck"],
            "stage3_speaker_script": deliverables["stage3_speaker_script"],
            "stage3_speaker_script_docx": deliverables["stage3_speaker_script_docx"],
            "stage3_speaker_script_pdf": deliverables["stage3_speaker_script_pdf"],
            "stage3_lesson_plan": deliverables["stage3_lesson_plan"],
            "stage3_lesson_plan_docx": deliverables["stage3_lesson_plan_docx"],
            "stage3_lesson_plan_pdf": deliverables["stage3_lesson_plan_pdf"],
            "stage4_organized_dir": "阶段4_文件整理交付/<封面第一页主题>/",
        },
        "runtime_artifacts": {
            "materials_index": "_state/阶段0/materials_index.json",
            "stage1_slides_json": "_state/阶段1/slides.json",
            "content_json": "_state/阶段1/content.json",
            "design_contract_json": "_state/阶段1/design_contract.json",
            "layout_safety_contract": "_state/阶段1/layout_safety_contract.json",
            "slide_prompt_briefs_json": "_state/阶段1/slide_prompt_briefs.json",
            "stage2_cover_options_dir": "_state/阶段2/cover_options",
            "stage2_cover_style_cards_dir": "_state/阶段2/cover_options/style_cards",
            "stage2_cover_selection": "_state/阶段2/cover_options/selection/selection.json",
            "deck_style_json": "_state/阶段2/deck_style.json",
            "layout_intent_json": "_state/阶段2/layout_intent.json",
            "stage2_trial_first5_dir": "_state/阶段2/trial_first5",
            "stage2_visual_qa_review": "_state/阶段2/visual_qa/stage2_aesthetic_review.json",
            "stage2_results_dir": "_state/阶段2/results",
            "stage3_education_context": "_state/阶段3/education_context.json",
            "stage3_textbook_context": "_state/阶段3/textbook_context.json",
            "stage3_lesson_plan_context": "_state/阶段3/lesson_plan_context.json",
            "stage3_speaker_script_json": "_state/阶段3/speaker_script.json",
            "stage3_speaker_script_manifest": "_state/阶段3/speaker_script_manifest.json",
            "stage3_speaker_script_qa": "_state/阶段3/speaker_script_qa.json",
            "stage3_lesson_plan_json": "_state/阶段3/lesson_plan.json",
            "stage3_lesson_plan_manifest": "_state/阶段3/lesson_plan_manifest.json",
            "stage3_lesson_plan_qa": "_state/阶段3/lesson_plan_qa.json",
            "stage4_deliverable_manifest": "_state/阶段4/deliverable_manifest.json",
            "stage4_organize_summary": "_state/阶段4/organize_summary.json",
            "stage4_pdf_page_images_dir": "_state/阶段4/pdf_page_images",
            "decisions_dir": "_state/decisions",
        },
        "control_artifacts": {
            "resume_brief": "_state/control/resume_brief.json",
            "resume_brief_markdown": "_state/control/resume_brief.md",
            "next_action": "_state/control/next_action.json",
            "drift_check": "_state/control/drift_check.json",
            "active_work_packet": "_state/control/active_work_packet.json",
            "work_packets_dir": "_state/control/work_packets",
        },
        "quality": {
            "stage1": "not_started",
            "stage2": "not_started",
            "stage3": "not_started",
            "stage4": "not_started",
        },
        "next_required_action": "整理资料并由主控大模型撰写阶段1规划",
        "updated_at": now_iso(),
    }


def stage3_lesson_plan_required(state: dict[str, Any]) -> bool:
    outputs = state.get("stage3_outputs")
    if isinstance(outputs, dict):
        lesson_plan = outputs.get("lesson_plan")
        if isinstance(lesson_plan, dict) and isinstance(lesson_plan.get("required"), bool):
            return lesson_plan["required"]
    legacy_outputs = state.get("stage4_outputs")
    if isinstance(legacy_outputs, dict):
        lesson_plan = legacy_outputs.get("lesson_plan")
        if isinstance(lesson_plan, dict) and isinstance(lesson_plan.get("required"), bool):
            return lesson_plan["required"]
    return bool(state.get("stage4_lesson_plan_required"))


def set_stage3_lesson_plan_required(
    state: dict[str, Any],
    *,
    required: bool,
    reason: str | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    outputs = state.setdefault("stage3_outputs", {})
    lesson_plan = outputs.setdefault("lesson_plan", {})
    lesson_plan["required"] = bool(required)
    lesson_plan["required_reason"] = reason if required else None
    lesson_plan["skip_reason"] = None if required else skip_reason
    lesson_plan.setdefault("status", "not_started")
    # Legacy stage4_lesson_plan_required is read-only compatibility.
    # New writes must stay on stage3_outputs.lesson_plan.
    return state


def stage4_lesson_plan_required(state: dict[str, Any]) -> bool:
    return stage3_lesson_plan_required(state)


def set_stage4_lesson_plan_required(
    state: dict[str, Any],
    *,
    required: bool,
    reason: str | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    return set_stage3_lesson_plan_required(
        state,
        required=required,
        reason=reason,
        skip_reason=skip_reason,
    )


def read_state(run_dir: str | Path) -> dict[str, Any]:
    path = project_state_path(run_dir)
    if not path.exists():
        raise FileNotFoundError(f"project state not found: {path}")
    return validate_project_state(read_json(path))


def write_state(run_dir: str | Path, state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = now_iso()
    validate_project_state(state)
    write_json(project_state_path(run_dir), state)
    return state


def patch_state(run_dir: str | Path, **updates: Any) -> dict[str, Any]:
    state = read_state(run_dir)
    state.update(updates)
    return write_state(run_dir, state)
