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
        "stage4_locked_presentation_source": None,
        "confirmed": {
            "stage1_plan": False,
            "stage2_cover_style": False,
            "stage2_trial_first5": False,
            "stage2_image_deck": False,
            "stage3_coordinate_plan": False,
            "stage3_editable_deck": False,
            "stage4_speaker_script": False,
        },
        "user_artifacts": {
            "stage1_page_plan": None,
            "stage1_clean_transcript": None,
            "stage1_style_prompt_plan": None,
            "stage2_cover_options": None,
            "selected_cover_style": None,
            "stage2_trial_first5": None,
            "stage2_image_deck": None,
            "stage3_coordinate_preview": None,
            "stage3_editable_deck": None,
            "stage4_locked_presentation_source": None,
            "stage4_speaker_script": None,
            "stage4_speaker_script_docx": None,
            "stage4_speaker_script_pdf": None,
        },
        "expected_user_paths": {
            "stage1_page_plan": "阶段1_规划确认/页面规划.md",
            "stage1_clean_transcript": "阶段1_规划确认/每页干净逐字稿.md",
            "stage1_style_prompt_plan": "阶段1_规划确认/风格与提示词方案.md",
            "stage2_cover_options": "阶段2_图片版PPT/封面风格候选/封面风格选择说明.md",
            "stage2_trial_first5": "阶段2_图片版PPT/前5页试样/",
            "stage2_image_deck": deliverables["stage2_image_deck"],
            "stage3_coordinate_preview": "阶段3_可编辑PPT/坐标复刻预览/坐标复刻预览.md",
            "stage3_editable_deck": deliverables["stage3_editable_deck"],
            "stage4_speaker_script": deliverables["stage4_speaker_script"],
            "stage4_speaker_script_docx": deliverables["stage4_speaker_script_docx"],
            "stage4_speaker_script_pdf": deliverables["stage4_speaker_script_pdf"],
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
            "stage3_brief_dir": "_state/阶段3/briefs",
            "stage3_background_prompts_dir": "_state/阶段3/no_text_background_prompts",
            "stage3_background_results_dir": "_state/阶段3/no_text_background_results",
            "stage3_text_ownership_map": "_state/阶段3/text_ownership_map.json",
            "stage3_editable_coordinate_plan": "_state/阶段3/editable_coordinate_plan.json",
            "stage3_inspect_dir": "_state/阶段3/inspect",
            "stage3_officecli_manifest": "_state/阶段3/manifests/officecli_manifest.json",
            "stage3_officecli_readback": "_state/阶段3/officecli/readback/build_deck.readback.json",
            "stage3_native_style_probe": "_state/阶段3/officecli/probe/native_style_probe.json",
            "stage3_render_review_dir": "_state/阶段3/render_review",
            "stage3_native_render_check": "_state/阶段3/render_review/native_render_check.json",
            "stage3_visual_qa_review": "_state/阶段3/render_review/stage3_visual_qa_review.json",
            "stage3_editable_deck_manifest": "_state/阶段3/manifests/editable_deck.json",
            "stage3_ai_quality_profile": "_state/阶段3/ai_quality/stage3_quality_profile.json",
            "stage3_controller_review_plan_draft": "_state/阶段3/ai_quality/controller_review_plan.draft.json",
            "stage4_speaker_script_json": "_state/阶段4/speaker_script.json",
            "stage4_speaker_script_manifest": "_state/阶段4/speaker_script_manifest.json",
            "stage4_speaker_script_qa": "_state/阶段4/speaker_script_qa.json",
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
