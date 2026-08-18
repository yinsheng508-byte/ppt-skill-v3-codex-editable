from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .box_utils import require_bool, require_string, validate_slide_indices
from .editable_coordinate_plan import load_editable_coordinate_plan
from .events import append_event
from .json_io import read_json
from .stage1_plan import load_stage1_slides
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .validation import ValidationError, require_matching_slide_indices, validate_stage1_plan


CALIBRATION_REVIEW_STATUSES = {"draft", "passed", "needs_rework"}


def native_render_check_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "render_review" / "native_render_check.json"


def load_native_render_check(run_dir: str | Path) -> dict[str, Any]:
    return validate_native_render_check(read_json(native_render_check_path(run_dir)))


def record_native_render_check(run_dir: str | Path, check_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("native render check can only be recorded in stage3")
    source = Path(check_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"native render check not found: {source}")
    check = validate_native_render_check(read_json(source))
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    coordinate_plan = apply_stage3_scope(load_editable_coordinate_plan(root), state, "editable_coordinate_plan", strict=True)
    require_matching_slide_indices(("stage1_plan", stage1), ("editable_coordinate_plan", coordinate_plan))
    _require_known_checked_slides(check, {slide["slide_index"] for slide in stage1["slides"]})
    _require_check_assets(root, check)
    target = native_render_check_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    state["runtime_artifacts"]["stage3_native_render_check"] = "_state/阶段3/render_review/native_render_check.json"
    state["quality"]["stage3_native_render_check"] = check["overall_status"]
    state["next_required_action"] = "主控大模型基于 native_render_check 和 coordinate execution report 记录阶段3坐标 QA"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "native_render_check_recorded",
        "runtime",
        checked_slides=len(check["checked_slides"]),
        stage3_scope=stage3_scope_summary(state),
    )
    return target


def validate_native_render_check(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("native_render_check must be an object")
    for field in ("schema_version", "overall_status", "contact_sheet", "checked_slides", "high_risk_slides", "findings"):
        if field not in data:
            raise ValidationError(f"native_render_check missing required field: {field}")
    if data["schema_version"] != "1.0":
        raise ValidationError("native_render_check.schema_version must be 1.0")
    if data["overall_status"] not in {"passed", "needs_rework"}:
        raise ValidationError("native_render_check.overall_status must be passed or needs_rework")
    require_string(data, "contact_sheet", "native_render_check")
    checked = data.get("checked_slides")
    if not isinstance(checked, list) or not checked:
        raise ValidationError("native_render_check.checked_slides must be a non-empty list")
    for index, item in enumerate(checked, start=1):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValidationError(f"native_render_check.checked_slides[{index}] must be an integer")
    high_risk = data.get("high_risk_slides")
    if not isinstance(high_risk, list):
        raise ValidationError("native_render_check.high_risk_slides must be a list")
    for index, item in enumerate(high_risk, start=1):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValidationError(f"native_render_check.high_risk_slides[{index}] must be an integer")
    findings = data.get("findings")
    if not isinstance(findings, list):
        raise ValidationError("native_render_check.findings must be a list")
    for index, finding in enumerate(findings, start=1):
        _validate_finding(finding, f"native_render_check.findings[{index}]")
    calibration = data.get("calibration_results", [])
    if not isinstance(calibration, list):
        raise ValidationError("native_render_check.calibration_results must be a list")
    for index, item in enumerate(calibration, start=1):
        _validate_calibration_result(item, f"native_render_check.calibration_results[{index}]")
    return data


def _validate_finding(finding: Any, label: str) -> None:
    if not isinstance(finding, dict):
        raise ValidationError(f"{label} must be an object")
    if isinstance(finding.get("slide_index"), bool) or not isinstance(finding.get("slide_index"), int):
        raise ValidationError(f"{label}.slide_index must be an integer")
    severity = require_string(finding, "severity", label)
    if severity not in {"info", "warning", "blocking"}:
        raise ValidationError(f"{label}.severity is invalid: {severity}")
    require_string(finding, "description", label)
    require_bool(finding, "resolved", label)
    if severity == "blocking" and not finding["resolved"]:
        raise ValidationError(f"{label} blocking finding must be resolved before recording native render check")


def _require_known_checked_slides(check: dict[str, Any], known: set[int]) -> None:
    missing = sorted(set(check["checked_slides"]) - known)
    if missing:
        raise ValidationError("native_render_check contains unknown checked slide(s): " + ", ".join(str(item) for item in missing))
    missing_high_risk = sorted(set(check["high_risk_slides"]) - set(check["checked_slides"]))
    if missing_high_risk:
        raise ValidationError("native_render_check high_risk_slides must be included in checked_slides")


def _require_check_assets(root: Path, check: dict[str, Any]) -> None:
    sheet = root / check["contact_sheet"]
    if not sheet.exists() or not sheet.is_file():
        raise FileNotFoundError(f"native render contact sheet missing: {check['contact_sheet']}")
    for result in check.get("calibration_results", []):
        for key in ("font_calibration_profile", "probe_compare"):
            relpath = result.get(key)
            if isinstance(relpath, str) and relpath.strip() and not (root / relpath).is_file():
                raise FileNotFoundError(f"native render calibration asset missing: {relpath}")


def _validate_calibration_result(item: Any, label: str) -> None:
    if not isinstance(item, dict):
        raise ValidationError(f"{label} must be an object")
    probe_slide_index = item.get("probe_slide_index")
    if isinstance(probe_slide_index, bool) or not isinstance(probe_slide_index, int):
        raise ValidationError(f"{label}.probe_slide_index must be an integer")
    require_string(item, "font_calibration_profile", label)
    require_string(item, "probe_compare", label)
    status = require_string(item, "review_status", label)
    if status not in CALIBRATION_REVIEW_STATUSES:
        raise ValidationError(f"{label}.review_status is invalid: {status}")
    if "notes" in item and not isinstance(item["notes"], str):
        raise ValidationError(f"{label}.notes must be a string")
