from __future__ import annotations

from pathlib import Path
from typing import Any

from .box_utils import require_bool, require_string, validate_slide_indices
from .events import append_event
from .json_io import read_json, write_json
from .planning_assets import load_content
from .stage1_plan import load_stage1_slides
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage3_restore_targets import stable_json_hash
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .validation import ValidationError, require_matching_slide_indices, validate_content_asset, validate_stage1_plan


BACKGROUND_ACTIONS = {"remove_and_restore", "preserve_in_background"}
FORBIDDEN_SPLIT_SOURCE_FRAGMENTS = ("ocr", "detected_text", "recognized_text", "source_image_bbox", "confidence")


def text_unit_split_plan_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "text_unit_split_plan.json"


def load_text_unit_split_plan(run_dir: str | Path) -> dict[str, Any]:
    return validate_text_unit_split_plan(read_json(text_unit_split_plan_path(run_dir)))


def text_unit_split_plan_hash(run_dir: str | Path) -> str:
    path = text_unit_split_plan_path(run_dir)
    return stable_json_hash(read_json(path)) if path.exists() else ""


def record_text_unit_split_plan(run_dir: str | Path, split_plan_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("text unit split plan can only be recorded in stage3")
    source = Path(split_plan_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"text unit split plan not found: {source}")
    split_plan = apply_stage3_scope(validate_text_unit_split_plan(read_json(source)), state, "text_unit_split_plan", strict=True)
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    content = apply_stage3_scope(validate_content_asset(load_content(root)), state, "content")
    require_matching_slide_indices(("stage1_plan", stage1), ("text_unit_split_plan", split_plan))
    require_matching_slide_indices(("stage1_plan", stage1), ("content", content))
    require_split_plan_text_matches_content(split_plan, content)
    target = text_unit_split_plan_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, split_plan)
    state["status"] = "stage3_text_unit_split_plan_ready"
    state["required_actor"] = "main_controller"
    state["runtime_artifacts"]["stage3_text_unit_split_plan"] = "_state/阶段3/text_unit_split_plan.json"
    state["quality"]["stage3"] = "text_unit_split_plan_ready"
    state["next_required_action"] = "主控大模型基于 text_unit_split_plan 细化 text_ownership_map"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "text_unit_split_plan_recorded",
        "runtime",
        slides_count=len(split_plan["slides"]),
        stage3_scope=stage3_scope_summary(state),
    )
    return target


def create_text_unit_split_plan_draft(run_dir: str | Path, output_file: str | Path | None = None) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("text unit split plan draft can only be created in stage3")
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    content = apply_stage3_scope(validate_content_asset(load_content(root)), state, "content")
    require_matching_slide_indices(("stage1_plan", stage1), ("content", content))
    slides = []
    for content_slide in content["slides"]:
        slide_index = content_slide["slide_index"]
        units = []
        for index, text in enumerate(content_slide.get("final_visible_text", []), start=1):
            semantic_role = "page_title" if index == 1 else "body"
            units.append(
                {
                    "split_unit_id": f"s{slide_index:03d}_split_{index:03d}",
                    "text": text,
                    "content_source": "_state/阶段1/content.json#slides[].final_visible_text",
                    "semantic_role": semantic_role,
                    "style_role": semantic_role,
                    "visual_group_id": f"s{slide_index:03d}_group_{index:03d}",
                    "must_be_separate_shape": True,
                    "restore_as_editable": True,
                    "background_action": "remove_and_restore",
                    "notes": "draft generated from content.final_visible_text; controller must refine visual groups and style roles",
                }
            )
        slides.append({"slide_index": slide_index, "page_complexity": "draft", "units": units})
    draft = {
        "schema_version": "1.0",
        "basis": {
            "source": "stage1_content_final_visible_text",
            "status": "draft",
            "controller_review_required": True,
        },
        "slides": slides,
    }
    validate_text_unit_split_plan(draft)
    require_split_plan_text_matches_content(draft, content)
    target = Path(output_file) if output_file else root / "_state" / "阶段3" / "drafts" / "text_unit_split_plan.draft.json"
    write_json(target, draft)
    return target


def split_plan_slide(split_plan: dict[str, Any], slide_index: int) -> dict[str, Any]:
    for slide in split_plan.get("slides", []):
        if isinstance(slide, dict) and slide.get("slide_index") == slide_index:
            return slide
    raise ValidationError(f"text_unit_split_plan missing slide {slide_index}")


def editable_split_units(split_plan: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for slide in split_plan.get("slides", []):
        for unit in slide.get("units", []):
            if unit.get("restore_as_editable") is True:
                units.append(unit)
    return units


def split_units_by_id(split_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    units: dict[str, dict[str, Any]] = {}
    for slide in split_plan.get("slides", []):
        for unit in slide.get("units", []):
            split_unit_id = unit["split_unit_id"]
            if split_unit_id in units:
                raise ValidationError(f"text_unit_split_plan split_unit_id is duplicated: {split_unit_id}")
            units[split_unit_id] = unit
    return units


def require_split_plan_text_matches_content(split_plan: dict[str, Any], content: dict[str, Any]) -> None:
    content_by_slide = {slide["slide_index"]: slide for slide in content.get("slides", []) if isinstance(slide, dict)}
    for slide in split_plan.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_index = slide["slide_index"]
        content_slide = content_by_slide.get(slide_index)
        if not content_slide:
            raise ValidationError(f"text_unit_split_plan slide {slide_index} has no matching content slide")
        visible_blob = normalized_visible_text_blob(content_slide)
        for index, unit in enumerate(slide.get("units", []), start=1):
            text = normalize_text_for_match(unit.get("text", ""))
            if not text or text not in visible_blob:
                raise ValidationError(
                    f"text_unit_split_plan slide {slide_index} units[{index}].text "
                    "must come from same-slide content.final_visible_text"
                )


def validate_text_unit_split_plan(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("text_unit_split_plan must be an object")
    _reject_forbidden_fragments(data, "text_unit_split_plan")
    for field in ("schema_version", "basis", "slides"):
        if field not in data:
            raise ValidationError(f"text_unit_split_plan missing required field: {field}")
    if data["schema_version"] != "1.0":
        raise ValidationError("text_unit_split_plan.schema_version must be 1.0")
    if not isinstance(data.get("basis"), dict):
        raise ValidationError("text_unit_split_plan.basis must be an object")
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError("text_unit_split_plan.slides must be a non-empty list")
    validate_slide_indices(slides, "text_unit_split_plan.slides")
    seen_units: set[str] = set()
    for position, slide in enumerate(slides, start=1):
        label = f"text_unit_split_plan.slides[{position}]"
        units = slide.get("units")
        if not isinstance(units, list) or not units:
            raise ValidationError(f"{label}.units must be a non-empty list")
        for unit_index, unit in enumerate(units, start=1):
            _validate_split_unit(unit, f"{label}.units[{unit_index}]", seen_units)
    return data


def _validate_split_unit(unit: Any, label: str, seen_units: set[str]) -> None:
    if not isinstance(unit, dict):
        raise ValidationError(f"{label} must be an object")
    split_unit_id = require_string(unit, "split_unit_id", label)
    if split_unit_id in seen_units:
        raise ValidationError(f"{label}.split_unit_id is duplicated: {split_unit_id}")
    seen_units.add(split_unit_id)
    for field in ("text", "content_source", "semantic_role", "style_role", "visual_group_id", "background_action"):
        require_string(unit, field, label)
    require_bool(unit, "must_be_separate_shape", label)
    require_bool(unit, "restore_as_editable", label)
    if unit["background_action"] not in BACKGROUND_ACTIONS:
        raise ValidationError(f"{label}.background_action is invalid: {unit['background_action']}")
    if unit["restore_as_editable"] and unit["background_action"] != "remove_and_restore":
        raise ValidationError(f"{label}.restore_as_editable requires background_action=remove_and_restore")


def _reject_forbidden_fragments(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if any(fragment in normalized_key for fragment in FORBIDDEN_SPLIT_SOURCE_FRAGMENTS):
                raise ValidationError(f"{label}.{key}: OCR-derived field is forbidden")
            _reject_forbidden_fragments(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fragments(child, f"{label}[{index}]")
    elif isinstance(value, str):
        normalized_value = value.lower()
        if any(fragment in normalized_value for fragment in FORBIDDEN_SPLIT_SOURCE_FRAGMENTS):
            raise ValidationError(f"{label}: OCR-derived source is forbidden")


def normalized_visible_text_blob(content_slide: dict[str, Any]) -> str:
    visible = content_slide.get("final_visible_text", [])
    pieces = []
    title = content_slide.get("title")
    if isinstance(title, str):
        pieces.append(title)
    pieces.extend(item for item in visible if isinstance(item, str))
    return normalize_text_for_match(" ".join(pieces))


def normalize_text_for_match(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(value.split())
