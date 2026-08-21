from __future__ import annotations

from pathlib import Path
from typing import Any

from .coordinate_stage3_qa import COORDINATE_QA_CHECK_KEYS, validate_coordinate_stage3_qa_review
from .doctor import check_project
from .editable_coordinate_plan import load_editable_coordinate_plan
from .json_io import read_json, write_json
from .state import read_state
from .validation import STAGE2_QA_CHECK_KEYS, ValidationError, validate_stage2_aesthetic_review


def create_stage2_visual_qa_draft(
    run_dir: str | Path,
    *,
    scope: str = "full_image_deck",
    output_file: str | Path | None = None,
) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage2":
        raise ValidationError("stage2 visual QA draft can only be created in stage2")
    doctor = check_project(root)
    findings = [{"issue": "draft_requires_controller_aesthetic_review"}]
    findings.extend({"issue": f"doctor: {issue}"} for issue in doctor.get("issues", []))
    findings.extend({"issue": f"doctor_warning: {warning}"} for warning in doctor.get("warnings", []))
    draft = {
        "schema_version": "1.0",
        "overall_status": "needs_rework",
        "review_scope": scope,
        "checks": {key: "needs_rework" for key in sorted(STAGE2_QA_CHECK_KEYS)},
        "slide_findings": findings,
        "rework_recommendation": {
            "target": "stage2_design_plan",
            "reason": "Runtime draft only lists required review items; controller must perform visual judgment before recording QA.",
        },
    }
    validate_stage2_aesthetic_review(draft)
    target = Path(output_file) if output_file else root / "_state" / "阶段2" / "visual_qa" / "stage2_aesthetic_review.draft.json"
    write_json(target, draft)
    return target


def create_stage3_qa_draft(run_dir: str | Path, *, output_file: str | Path | None = None) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("stage3 QA draft can only be created in stage3")
    plan = load_editable_coordinate_plan(root)
    doctor = check_project(root)
    slides = []
    for slide in plan["slides"]:
        slide_index = slide["slide_index"]
        slides.append(
            {
                "slide_index": slide_index,
                "status": "needs_rework",
                "review_assets": {
                    "stage2_image": slide["source_image"]["path"],
                    "stage3_background": slide.get("stage3_background_image", {}).get("path", f"阶段3_可编辑PPT/img/background_{slide_index:03d}.png"),
                    "editable_render": f"阶段3_可编辑PPT/render_review/slide_{slide_index:03d}.png",
                },
                "checked_text_unit_ids": [unit["text_unit_id"] for unit in slide.get("text_units", [])],
                "notes": "Draft requires controller visual review; do not record as passed without checking render assets.",
            }
        )
    draft: dict[str, Any] = {
        "schema_version": "2.0",
        "overall_status": "needs_rework",
        "contact_sheet": "阶段3_可编辑PPT/render_review/contact_sheet.png",
        "slides": slides,
        "checks": {key: "needs_rework" for key in sorted(COORDINATE_QA_CHECK_KEYS)},
        "accepted_quality_tradeoffs": [],
    }
    quality_profile = root / "_state" / "阶段3" / "ai_quality" / "stage3_quality_profile.json"
    if quality_profile.exists():
        draft["ai_quality_profile"] = str(quality_profile.relative_to(root))
        try:
            profile = read_json(quality_profile)
            recommended = profile.get("recommended_high_risk_slides")
            if isinstance(recommended, list):
                draft["recommended_high_risk_coverage"] = {
                    "recommended_slides": [item for item in recommended if isinstance(item, int)],
                    "reviewed_slides": [],
                    "not_reviewed_with_reason": ["draft_requires_controller_review"],
                }
        except Exception:
            pass
    if doctor.get("issues") or doctor.get("warnings"):
        draft["doctor_findings"] = {
            "issues": doctor.get("issues", []),
            "warnings": doctor.get("warnings", []),
        }
    validate_coordinate_stage3_qa_review(draft)
    target = Path(output_file) if output_file else root / "_state" / "阶段3" / "render_review" / "stage3_visual_qa_review.draft.json"
    write_json(target, draft)
    return target
