from __future__ import annotations

from pathlib import Path

from .doctor import check_project
from .json_io import write_json
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
