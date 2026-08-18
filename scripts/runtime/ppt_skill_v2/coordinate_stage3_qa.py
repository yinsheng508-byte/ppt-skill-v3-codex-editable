from __future__ import annotations

from pathlib import Path
from typing import Any

from .editable_coordinate_plan import load_editable_coordinate_plan, validate_coordinate_execution_report
from .events import append_event
from .json_io import read_json, write_json
from .native_render_check import native_render_check_path, validate_native_render_check
from .officecli_utils import SLIDE_HEIGHT_PT, SLIDE_WIDTH_PT
from .stage1_plan import load_stage1_slides
from .stage3_artifact_hashes import current_stage3_input_hashes, refresh_stage3_stale_artifacts, require_no_stage3_stale_artifacts
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .validation import ValidationError, require_matching_slide_indices, validate_stage1_plan


COORDINATE_QA_CHECK_KEYS = {
    "coordinate_text_units_covered",
    "content_text_accuracy",
    "native_render_alignment",
    "no_obvious_overlap_or_overflow",
    "background_fidelity",
    "high_risk_pages_reviewed",
}
CORE_PASS_CHECK_KEYS = {
    "coordinate_text_units_covered",
    "content_text_accuracy",
    "no_obvious_overlap_or_overflow",
    "background_fidelity",
}
NATIVE_STYLE_PROBE_REVIEW_STATUSES = {"passed", "needs_rework", "not_applicable"}


def coordinate_stage3_qa_review_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "render_review" / "stage3_visual_qa_review.json"


def load_coordinate_stage3_qa_review(run_dir: str | Path) -> dict[str, Any]:
    return validate_coordinate_stage3_qa_review(read_json(coordinate_stage3_qa_review_path(run_dir)))


def record_coordinate_stage3_qa_review(run_dir: str | Path, review_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("coordinate stage3 QA can only be recorded in stage3")
    source = Path(review_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"coordinate stage3 QA review not found: {source}")
    review = validate_coordinate_stage3_qa_review(read_json(source))
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    coordinate_plan = apply_stage3_scope(load_editable_coordinate_plan(root), state, "editable_coordinate_plan", strict=True)
    require_matching_slide_indices(("stage1_plan", stage1), ("editable_coordinate_plan", coordinate_plan))
    _require_known_review_slides(review, {slide["slide_index"] for slide in stage1["slides"]})
    manifest = _require_editable_deck_manifest(root)
    require_no_stage3_stale_artifacts(root, state=state, ignore={"visual_qa"})
    _require_review_assets(root, review)
    _require_execution_report(root, manifest, coordinate_plan)
    officecli_manifest = _require_officecli_manifest(root, manifest, coordinate_plan)
    _require_background_placement(officecli_manifest, coordinate_plan)
    _require_officecli_text_shape_coverage(officecli_manifest, coordinate_plan)
    _require_native_render_if_present(root, review)
    if review["overall_status"] != "passed":
        raise ValidationError("coordinate stage3 QA review must pass before user confirmation")

    target = coordinate_stage3_qa_review_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    review["input_hashes"] = current_stage3_input_hashes(root)
    review["input_hashes"]["editable_deck_pptx_sha256"] = manifest["pptx_sha256"]
    write_json(target, review)

    state["status"] = "waiting_user_confirmation"
    state["required_actor"] = "user"
    state["runtime_artifacts"]["stage3_visual_qa_review"] = "_state/阶段3/render_review/stage3_visual_qa_review.json"
    state["quality"]["stage3"] = "pending_user_review"
    state["next_required_action"] = "等待用户确认阶段3可编辑 PPT；如用户反馈问题，由主控大模型组织阶段3坐标计划或可编辑 PPT 返工"
    refresh_stage3_stale_artifacts(root, state)
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "coordinate_stage3_qa_review_recorded",
        "runtime",
        slides_count=len(review["slides"]),
        stage3_scope=stage3_scope_summary(state),
    )
    return target


def validate_coordinate_stage3_qa_review(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("coordinate stage3 QA review must be an object")
    for field in ("schema_version", "overall_status", "contact_sheet", "slides", "checks"):
        if field not in data:
            raise ValidationError(f"coordinate stage3 QA review missing required field: {field}")
    if data["schema_version"] != "2.0":
        raise ValidationError("coordinate stage3 QA review.schema_version must be 2.0")
    if data["overall_status"] not in {"passed", "needs_rework"}:
        raise ValidationError("coordinate stage3 QA review.overall_status must be passed or needs_rework")
    if not isinstance(data.get("contact_sheet"), str) or not data["contact_sheet"].strip():
        raise ValidationError("coordinate stage3 QA review.contact_sheet must be a non-empty string")
    checks = data.get("checks")
    if not isinstance(checks, dict):
        raise ValidationError("coordinate stage3 QA review.checks must be an object")
    missing = sorted(COORDINATE_QA_CHECK_KEYS - set(checks))
    if missing:
        raise ValidationError("coordinate stage3 QA review.checks missing key(s): " + ", ".join(missing))
    for key, value in checks.items():
        if key not in COORDINATE_QA_CHECK_KEYS:
            raise ValidationError(f"coordinate stage3 QA review.checks has unexpected key: {key}")
        if value not in {"passed", "failed", "needs_rework", "not_applicable"}:
            raise ValidationError(f"coordinate stage3 QA review.checks.{key} has invalid status")
    if data["overall_status"] == "passed" and any(value in {"failed", "needs_rework"} for value in checks.values()):
        raise ValidationError("coordinate stage3 QA review cannot pass while checks failed or need rework")
    if data["overall_status"] == "passed":
        not_passed_core = sorted(key for key in CORE_PASS_CHECK_KEYS if checks.get(key) != "passed")
        if not_passed_core:
            raise ValidationError("coordinate stage3 QA review core checks must pass: " + ", ".join(not_passed_core))
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError("coordinate stage3 QA review.slides must be a non-empty list")
    for index, slide in enumerate(slides, start=1):
        _validate_slide_review(slide, f"coordinate stage3 QA review.slides[{index}]")
        if data["overall_status"] == "passed" and slide["status"] != "passed":
            raise ValidationError("coordinate stage3 QA review cannot pass while reviewed slide needs rework")
    if "native_style_probe" in data:
        _validate_native_style_probe(data["native_style_probe"], "coordinate stage3 QA review.native_style_probe")
    if "font_probe" in data:
        _validate_native_style_probe(data["font_probe"], "coordinate stage3 QA review.font_probe")
    if "split_granularity_review" in data:
        _validate_split_granularity_review(data["split_granularity_review"], "coordinate stage3 QA review.split_granularity_review")
    if "ai_quality_profile" in data:
        _validate_non_empty_string(data["ai_quality_profile"], "coordinate stage3 QA review.ai_quality_profile")
    if "controller_review_plan" in data:
        _validate_non_empty_string(data["controller_review_plan"], "coordinate stage3 QA review.controller_review_plan")
    if "accepted_quality_tradeoffs" in data:
        _validate_accepted_quality_tradeoffs(
            data["accepted_quality_tradeoffs"],
            "coordinate stage3 QA review.accepted_quality_tradeoffs",
        )
    if "recommended_high_risk_coverage" in data:
        _validate_recommended_high_risk_coverage(
            data["recommended_high_risk_coverage"],
            "coordinate stage3 QA review.recommended_high_risk_coverage",
        )
    return data


def _validate_slide_review(slide: Any, label: str) -> None:
    if not isinstance(slide, dict):
        raise ValidationError(f"{label} must be an object")
    if isinstance(slide.get("slide_index"), bool) or not isinstance(slide.get("slide_index"), int):
        raise ValidationError(f"{label}.slide_index must be an integer")
    if slide.get("status") not in {"passed", "needs_rework"}:
        raise ValidationError(f"{label}.status must be passed or needs_rework")
    assets = slide.get("review_assets")
    if not isinstance(assets, dict):
        raise ValidationError(f"{label}.review_assets must be an object")
    for key in ("stage2_image", "stage3_background", "editable_render"):
        if not isinstance(assets.get(key), str) or not assets[key].strip():
            raise ValidationError(f"{label}.review_assets.{key} must be a non-empty string")
    if not isinstance(slide.get("checked_text_unit_ids"), list):
        raise ValidationError(f"{label}.checked_text_unit_ids must be a list")
    if not all(isinstance(item, str) and item.strip() for item in slide["checked_text_unit_ids"]):
        raise ValidationError(f"{label}.checked_text_unit_ids must contain non-empty strings")
    if "notes" in slide and not isinstance(slide["notes"], str):
        raise ValidationError(f"{label}.notes must be a string")


def _require_review_assets(root: Path, review: dict[str, Any]) -> None:
    contact_sheet = root / review["contact_sheet"]
    if not contact_sheet.exists() or not contact_sheet.is_file():
        raise FileNotFoundError(f"coordinate stage3 QA contact sheet missing: {review['contact_sheet']}")
    for slide in review["slides"]:
        for key in ("stage2_image", "stage3_background", "editable_render"):
            relpath = slide["review_assets"][key]
            path = root / relpath
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"coordinate stage3 QA asset missing: {relpath}")
    native_style_probe = review.get("native_style_probe")
    if not isinstance(native_style_probe, dict):
        native_style_probe = review.get("font_probe")
    if isinstance(native_style_probe, dict):
        for key in ("profile", "probe_compare", "probe_manifest", "probe_pptx"):
            relpath = native_style_probe.get(key)
            if isinstance(relpath, str) and relpath.strip() and not (root / relpath).is_file():
                raise FileNotFoundError(f"coordinate stage3 QA native style probe asset missing: {relpath}")
    for key in ("ai_quality_profile", "controller_review_plan"):
        relpath = review.get(key)
        if isinstance(relpath, str) and relpath.strip() and not (root / relpath).is_file():
            raise FileNotFoundError(f"coordinate stage3 QA optional evidence missing: {relpath}")


def _require_known_review_slides(review: dict[str, Any], known: set[int]) -> None:
    seen: set[int] = set()
    unknown: list[int] = []
    duplicated: list[int] = []
    for slide in review["slides"]:
        slide_index = slide["slide_index"]
        if slide_index in seen:
            duplicated.append(slide_index)
        seen.add(slide_index)
        if slide_index not in known:
            unknown.append(slide_index)
    if duplicated:
        raise ValidationError("coordinate stage3 QA contains duplicated slide(s): " + ", ".join(str(item) for item in duplicated))
    if unknown:
        raise ValidationError("coordinate stage3 QA contains unknown slide(s): " + ", ".join(str(item) for item in unknown))


def _require_editable_deck_manifest(root: Path) -> dict[str, Any]:
    path = root / "_state" / "阶段3" / "manifests" / "editable_deck.json"
    if not path.exists():
        raise ValidationError("coordinate stage3 QA requires editable deck manifest")
    manifest = read_json(path)
    deck_rel = manifest.get("deck_path")
    if not isinstance(deck_rel, str) or not deck_rel.strip() or not (root / deck_rel).exists():
        raise ValidationError("editable deck manifest points to a missing PPTX before coordinate QA")
    pptx_sha256 = manifest.get("pptx_sha256")
    if not isinstance(pptx_sha256, str) or not pptx_sha256.startswith("sha256:"):
        raise ValidationError("editable deck manifest must include pptx_sha256 before coordinate QA")
    if manifest.get("provider") != "officecli":
        raise ValidationError("coordinate stage3 QA requires editable deck provider=officecli")
    return manifest


def _require_execution_report(root: Path, manifest: dict[str, Any], coordinate_plan: dict[str, Any]) -> None:
    evidence = manifest.get("runtime_evidence", {})
    report_rel = evidence.get("text_fill_execution_report") if isinstance(evidence, dict) else None
    if not isinstance(report_rel, str) or not report_rel.strip():
        raise ValidationError("coordinate stage3 QA requires coordinate execution report evidence")
    report_path = root / report_rel
    if not report_path.exists():
        raise FileNotFoundError(f"coordinate execution report not found: {report_rel}")
    report = validate_coordinate_execution_report(read_json(report_path), coordinate_plan, pptx_sha256=manifest["pptx_sha256"])
    if report.get("actual_source") != "pptx_ooxml":
        raise ValidationError("coordinate stage3 QA requires coordinate execution report actual_source=pptx_ooxml")
    for slide in report.get("slides", []):
        for unit in slide.get("coordinate_text_units", []):
            if isinstance(unit, dict) and unit.get("within_allowed_range") is False:
                raise ValidationError("coordinate stage3 QA cannot pass while coordinate execution report has unresolved deviations")


def _require_officecli_manifest(root: Path, manifest: dict[str, Any], coordinate_plan: dict[str, Any]) -> dict[str, Any]:
    evidence = manifest.get("runtime_evidence", {})
    manifest_rel = evidence.get("officecli_manifest") if isinstance(evidence, dict) else None
    if not isinstance(manifest_rel, str) or not manifest_rel.strip():
        raise ValidationError("coordinate stage3 QA requires runtime_evidence.officecli_manifest")
    manifest_path = root / manifest_rel
    if not manifest_path.exists():
        raise FileNotFoundError(f"OfficeCLI manifest not found: {manifest_rel}")
    officecli_manifest = read_json(manifest_path)
    if not isinstance(officecli_manifest, dict):
        raise ValidationError("OfficeCLI manifest must be an object")
    if officecli_manifest.get("provider") != "officecli":
        raise ValidationError("OfficeCLI manifest provider must be officecli")
    if officecli_manifest.get("mode") != "full_deck":
        raise ValidationError("coordinate stage3 QA requires OfficeCLI manifest mode=full_deck")
    if officecli_manifest.get("pptx_sha256") != manifest.get("pptx_sha256"):
        raise ValidationError("OfficeCLI manifest pptx_sha256 must match editable_deck.json")
    slides_count = officecli_manifest.get("slides_count")
    if slides_count != len(coordinate_plan.get("slides", [])):
        raise ValidationError("OfficeCLI manifest slides_count must match editable_coordinate_plan")
    _require_officecli_manifest_evidence_paths(root, officecli_manifest, coordinate_plan)
    return officecli_manifest


def _require_officecli_manifest_evidence_paths(root: Path, officecli_manifest: dict[str, Any], coordinate_plan: dict[str, Any]) -> None:
    for field in ("commands", "command_results"):
        value = officecli_manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"OfficeCLI manifest requires {field} evidence path")
        if not _resolve_manifest_path(root, value).is_file():
            raise FileNotFoundError(f"OfficeCLI manifest {field} evidence not found: {value}")
    readback = officecli_manifest.get("readback")
    if not isinstance(readback, dict):
        raise ValidationError("OfficeCLI manifest requires readback evidence")
    readback_path = readback.get("path")
    if not isinstance(readback_path, str) or not readback_path.strip():
        raise ValidationError("OfficeCLI manifest readback.path must be a non-empty string")
    if not _resolve_manifest_path(root, readback_path).is_file():
        raise FileNotFoundError(f"OfficeCLI manifest readback evidence not found: {readback_path}")
    readback_count = readback.get("slides_count")
    if readback_count != len(coordinate_plan.get("slides", [])):
        raise ValidationError("OfficeCLI manifest readback.slides_count must match editable_coordinate_plan")


def _require_background_placement(officecli_manifest: dict[str, Any], coordinate_plan: dict[str, Any]) -> None:
    placements = _background_placements(officecli_manifest)
    if not placements:
        raise ValidationError("coordinate stage3 QA requires OfficeCLI background_placements")
    expected_by_slide = {
        slide["slide_index"]: slide
        for slide in coordinate_plan.get("slides", [])
        if isinstance(slide, dict) and isinstance(slide.get("slide_index"), int)
    }
    placements_by_slide: dict[int, dict[str, Any]] = {}
    duplicated: list[int] = []
    for placement in placements:
        slide_index = placement.get("slide_index")
        if not isinstance(slide_index, int):
            raise ValidationError("OfficeCLI background placement must include integer slide_index")
        if slide_index in placements_by_slide:
            duplicated.append(slide_index)
        placements_by_slide[slide_index] = placement
    if duplicated:
        raise ValidationError("OfficeCLI background_placements contains duplicated slide(s): " + ", ".join(str(item) for item in sorted(duplicated)))
    extra = sorted(set(placements_by_slide) - set(expected_by_slide))
    if extra:
        raise ValidationError("OfficeCLI background_placements contains unexpected slide(s): " + ", ".join(str(item) for item in extra))
    missing = sorted(set(expected_by_slide) - set(placements_by_slide))
    if missing:
        raise ValidationError("OfficeCLI background_placements missing slide(s): " + ", ".join(str(item) for item in missing))
    for slide_index, placement in placements_by_slide.items():
        mode = str(placement.get("fit") or placement.get("mode") or placement.get("placement_mode") or "").lower()
        crop = placement.get("crop") or placement.get("cropped") or placement.get("crop_applied")
        if mode == "cover" or crop is True:
            raise ValidationError("coordinate stage3 QA cannot pass while OfficeCLI manifest reports cover/cropped background placement")
        if mode != "exact_full_slide":
            raise ValidationError("coordinate stage3 QA requires OfficeCLI background placement_mode=exact_full_slide")
        expected_values = {
            "x": 0.0,
            "y": 0.0,
            "width": SLIDE_WIDTH_PT,
            "height": SLIDE_HEIGHT_PT,
        }
        for field, expected_value in expected_values.items():
            if not _number_close(placement.get(field), expected_value):
                raise ValidationError(
                    f"OfficeCLI background placement slide {slide_index} must use {field}={expected_value:g}pt"
                )
        background = expected_by_slide[slide_index].get("stage3_background_image")
        if not isinstance(background, dict):
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} missing stage3_background_image")
        if placement.get("image_path") != background.get("path"):
            raise ValidationError(f"OfficeCLI background placement slide {slide_index} image_path must match editable_coordinate_plan")
        if placement.get("image_sha256") != background.get("sha256"):
            raise ValidationError(f"OfficeCLI background placement slide {slide_index} image_sha256 must match editable_coordinate_plan")


def _require_officecli_text_shape_coverage(officecli_manifest: dict[str, Any], coordinate_plan: dict[str, Any]) -> None:
    text_shapes = officecli_manifest.get("text_shapes")
    if not isinstance(text_shapes, list):
        raise ValidationError("OfficeCLI manifest text_shapes must be a list")
    expected: dict[int, dict[str, dict[str, Any]]] = {
        slide["slide_index"]: {
            unit["text_unit_id"]: unit
            for unit in slide.get("text_units", [])
            if isinstance(unit, dict) and isinstance(unit.get("text_unit_id"), str)
        }
        for slide in coordinate_plan.get("slides", [])
        if isinstance(slide, dict)
    }
    expected_count = sum(len(items) for items in expected.values())
    if len(text_shapes) != expected_count:
        raise ValidationError(f"OfficeCLI manifest text_shapes count mismatch: expected {expected_count}, got {len(text_shapes)}")
    actual: dict[int, set[str]] = {}
    duplicates: list[str] = []
    seen: set[tuple[int, str]] = set()
    seen_paths: set[str] = set()
    unexpected: list[str] = []
    for item in text_shapes:
        if not isinstance(item, dict):
            continue
        slide_index = item.get("slide_index")
        text_unit_id = item.get("text_unit_id")
        if not isinstance(slide_index, int) or not isinstance(text_unit_id, str) or not text_unit_id.strip():
            continue
        key = (slide_index, text_unit_id)
        if key in seen:
            duplicates.append(f"{slide_index}:{text_unit_id}")
        seen.add(key)
        planned = expected.get(slide_index, {}).get(text_unit_id)
        if planned is None:
            unexpected.append(f"{slide_index}:{text_unit_id}")
            continue
        if item.get("shape_name") != text_unit_id:
            raise ValidationError(f"OfficeCLI manifest text shape {slide_index}:{text_unit_id} shape_name must equal text_unit_id")
        shape_path = item.get("shape_path")
        if not isinstance(shape_path, str) or not shape_path.strip():
            raise ValidationError(f"OfficeCLI manifest text shape {slide_index}:{text_unit_id} missing OfficeCLI readback shape_path")
        if shape_path in seen_paths:
            raise ValidationError(f"OfficeCLI manifest text_shapes contains duplicate shape_path: {shape_path}")
        seen_paths.add(shape_path)
        if item.get("shape_id") in (None, ""):
            raise ValidationError(f"OfficeCLI manifest text shape {slide_index}:{text_unit_id} missing OfficeCLI readback shape_id")
        readback_box = item.get("readback_relative_box")
        if not isinstance(readback_box, dict) or not _relative_box_close(planned.get("relative_box", {}), readback_box):
            raise ValidationError(f"OfficeCLI manifest text shape {slide_index}:{text_unit_id} readback_relative_box differs from plan")
        actual.setdefault(slide_index, set()).add(text_unit_id)
    if duplicates:
        raise ValidationError("OfficeCLI manifest text_shapes contains duplicate text unit(s): " + ", ".join(sorted(duplicates)))
    if unexpected:
        raise ValidationError("OfficeCLI manifest text_shapes contains unexpected text unit(s): " + ", ".join(sorted(unexpected)))
    for slide_index, expected_units in expected.items():
        expected_ids = set(expected_units)
        missing = sorted(expected_ids - actual.get(slide_index, set()))
        if missing:
            raise ValidationError(f"OfficeCLI manifest slide {slide_index} missing text shape(s): {', '.join(missing)}")


def _resolve_manifest_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _number_close(value: Any, expected: float, tolerance: float = 0.01) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return abs(float(value) - expected) <= tolerance


def _relative_box_close(planned: dict[str, Any], actual: dict[str, Any], tolerance: float = 0.01) -> bool:
    for field in ("x", "y", "w", "h"):
        planned_value = planned.get(field)
        actual_value = actual.get(field)
        if isinstance(planned_value, bool) or isinstance(actual_value, bool):
            return False
        if not isinstance(planned_value, (int, float)) or not isinstance(actual_value, (int, float)):
            return False
        if abs(float(planned_value) - float(actual_value)) > tolerance:
            return False
    return True


def _background_placements(officecli_manifest: Any) -> list[dict[str, Any]]:
    if not isinstance(officecli_manifest, dict):
        return []
    placements = officecli_manifest.get("background_placements")
    if isinstance(placements, list):
        return [item for item in placements if isinstance(item, dict)]
    placement = officecli_manifest.get("background_placement")
    if isinstance(placement, dict):
        return [placement]
    slides = officecli_manifest.get("slides")
    if isinstance(slides, list):
        result = []
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            value = slide.get("background_placement")
            if isinstance(value, dict):
                result.append(value)
        return result
    return []


def _validate_native_style_probe(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("profile", "probe_compare", "review_status"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValidationError(f"{label}.{field} must be a non-empty string")
    if value["review_status"] not in NATIVE_STYLE_PROBE_REVIEW_STATUSES:
        raise ValidationError(f"{label}.review_status is invalid: {value['review_status']}")
    for field in ("probe_manifest", "probe_pptx"):
        if field in value and not isinstance(value[field], str):
            raise ValidationError(f"{label}.{field} must be a string")
    if "notes" in value and not isinstance(value["notes"], str):
        raise ValidationError(f"{label}.notes must be a string")


def _validate_split_granularity_review(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    if not isinstance(value.get("reviewed"), bool):
        raise ValidationError(f"{label}.reviewed must be a boolean")
    high_risk = value.get("high_risk_slides", [])
    if not isinstance(high_risk, list):
        raise ValidationError(f"{label}.high_risk_slides must be a list")
    for index, slide_index in enumerate(high_risk, start=1):
        if isinstance(slide_index, bool) or not isinstance(slide_index, int):
            raise ValidationError(f"{label}.high_risk_slides[{index}] must be an integer")
    if "notes" in value and not isinstance(value["notes"], str):
        raise ValidationError(f"{label}.notes must be a string")


def _validate_non_empty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")


def _validate_accepted_quality_tradeoffs(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            if not item.strip():
                raise ValidationError(f"{label}[{index}] must not be an empty string")
        elif not isinstance(item, dict):
            raise ValidationError(f"{label}[{index}] must be a string or object")


def _validate_recommended_high_risk_coverage(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("recommended_slides", "reviewed_slides", "not_reviewed_with_reason"):
        if field not in value:
            raise ValidationError(f"{label}.{field} is required when recommended_high_risk_coverage is present")
    for field in ("recommended_slides", "reviewed_slides"):
        _validate_integer_list(value[field], f"{label}.{field}")
    if not isinstance(value["not_reviewed_with_reason"], list):
        raise ValidationError(f"{label}.not_reviewed_with_reason must be a list")
    for index, item in enumerate(value["not_reviewed_with_reason"], start=1):
        item_label = f"{label}.not_reviewed_with_reason[{index}]"
        if isinstance(item, str):
            if not item.strip():
                raise ValidationError(f"{item_label} must not be an empty string")
            continue
        if not isinstance(item, dict):
            raise ValidationError(f"{item_label} must be a string or object")
        if "slide_index" in item and (isinstance(item["slide_index"], bool) or not isinstance(item["slide_index"], int)):
            raise ValidationError(f"{item_label}.slide_index must be an integer")
        if "reason" in item and (not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise ValidationError(f"{item_label}.reason must be a non-empty string")


def _validate_integer_list(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    for index, item in enumerate(value, start=1):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValidationError(f"{label}[{index}] must be an integer")


def _require_native_render_if_present(root: Path, review: dict[str, Any]) -> None:
    path = native_render_check_path(root)
    if not path.exists():
        return
    check = validate_native_render_check(read_json(path))
    if check["overall_status"] != "passed":
        raise ValidationError("coordinate stage3 QA cannot pass while native render check needs rework")
    if review["checks"].get("native_render_alignment") != "passed":
        raise ValidationError("coordinate stage3 QA must mark native_render_alignment passed when native render check exists")
