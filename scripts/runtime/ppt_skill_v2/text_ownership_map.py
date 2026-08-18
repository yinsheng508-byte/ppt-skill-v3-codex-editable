from __future__ import annotations

from pathlib import Path
from typing import Any

from .box_utils import require_bool, require_string, validate_slide_indices
from .events import append_event
from .json_io import read_json, write_json
from .layout_safety_contract import layout_safety_contract_path, load_layout_safety_contract
from .planning_assets import load_content
from .stage1_plan import load_stage1_slides
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage3_restore_targets import stable_json_hash
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .text_unit_split_plan import load_text_unit_split_plan, text_unit_split_plan_path
from .validation import ValidationError, require_matching_slide_indices, validate_content_asset, validate_stage1_plan


def text_ownership_map_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "text_ownership_map.json"


def load_text_ownership_map(run_dir: str | Path) -> dict[str, Any]:
    return validate_text_ownership_map(read_json(text_ownership_map_path(run_dir)))


def text_ownership_map_hash(run_dir: str | Path) -> str:
    path = text_ownership_map_path(run_dir)
    return stable_json_hash(read_json(path)) if path.exists() else ""


def record_text_ownership_map(run_dir: str | Path, ownership_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("text ownership map can only be recorded in stage3")
    if not layout_safety_contract_path(root).exists():
        raise ValidationError("text ownership map requires _state/阶段1/layout_safety_contract.json")
    source = Path(ownership_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"text ownership map not found: {source}")
    ownership = apply_stage3_scope(validate_text_ownership_map(read_json(source)), state, "text_ownership_map", strict=True)
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    content = apply_stage3_scope(validate_content_asset(load_content(root)), state, "content")
    require_matching_slide_indices(("stage1_plan", stage1), ("text_ownership_map", ownership))
    require_matching_slide_indices(("stage1_plan", stage1), ("content", content))
    require_ownership_text_matches_content(ownership, content)
    if text_unit_split_plan_path(root).exists():
        split_plan = apply_stage3_scope(load_text_unit_split_plan(root), state, "text_unit_split_plan", strict=True)
        require_matching_slide_indices(("text_unit_split_plan", split_plan), ("text_ownership_map", ownership))
        require_ownership_matches_split_plan(ownership, split_plan)
    contract = load_layout_safety_contract(root)
    contract = apply_stage3_scope(contract, state, "layout_safety_contract")
    require_matching_slide_indices(("stage1_plan", stage1), ("layout_safety_contract", contract))
    target = text_ownership_map_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, ownership)
    state["status"] = "stage3_text_ownership_ready"
    state["required_actor"] = "main_controller"
    state["runtime_artifacts"]["stage3_text_ownership_map"] = "_state/阶段3/text_ownership_map.json"
    state["quality"]["stage3"] = "text_ownership_ready"
    state["next_required_action"] = "主控大模型基于 text_ownership_map 生成阶段3保真去字背景"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "text_ownership_map_recorded",
        "runtime",
        slides_count=len(ownership["slides"]),
        stage3_scope=stage3_scope_summary(state),
    )
    return target


def restore_targets_for_slide(ownership: dict[str, Any], slide_index: int) -> list[dict[str, Any]]:
    slide = ownership_slide(ownership, slide_index)
    targets: list[dict[str, Any]] = []
    for item in slide.get("editable_page_layer", []):
        action = "remove_and_restore" if item.get("remove_from_background") else "preserve_in_background"
        expected = "foreground_text" if item.get("restore_as_editable", True) else "background"
        target = {
            "target_id": item["ownership_id"],
            "action": action,
            "text": item["expected_text"],
            "semantic_role": item["semantic_role"],
            "source": _source_for_text_item(item),
            "expected_restore_as": expected,
            "notes": "text_ownership_map",
        }
        for optional_field in ("split_unit_id", "style_role", "visual_group_id"):
            if optional_field in item:
                target[optional_field] = item[optional_field]
        targets.append(target)
    for item in slide.get("raster_visual_layer", []):
        text = item.get("expected_text") or item.get("description") or item["ownership_id"]
        targets.append(
            {
                "target_id": item["ownership_id"],
                "action": "preserve_in_background",
                "text": text,
                "semantic_role": item.get("semantic_role", "raster_visual_text"),
                "source": {"content_json_path": "_state/阶段1/content.json", "source_field": item.get("source_field", "raster_visual_layer")},
                "expected_restore_as": "background",
                "notes": item.get("description", "raster_visual_layer"),
            }
        )
    return targets


def ownership_slide(ownership: dict[str, Any], slide_index: int) -> dict[str, Any]:
    for slide in ownership.get("slides", []):
        if isinstance(slide, dict) and slide.get("slide_index") == slide_index:
            return slide
    raise ValidationError(f"text_ownership_map missing slide {slide_index}")


def require_ownership_text_matches_content(ownership: dict[str, Any], content: dict[str, Any]) -> None:
    content_by_slide = {slide["slide_index"]: slide for slide in content.get("slides", []) if isinstance(slide, dict)}
    for slide in ownership.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_index = slide["slide_index"]
        content_slide = content_by_slide.get(slide_index)
        if not content_slide:
            raise ValidationError(f"text_ownership_map slide {slide_index} has no matching content slide")
        visible_blob = _normalized_visible_text_blob(content_slide)
        for index, item in enumerate(slide.get("editable_page_layer", []), start=1):
            expected = _normalize_text_for_match(item.get("expected_text", ""))
            if not expected or expected not in visible_blob:
                raise ValidationError(
                    f"text_ownership_map slide {slide_index} editable_page_layer[{index}].expected_text "
                    "must come from same-slide content.final_visible_text"
                )


def require_ownership_matches_split_plan(ownership: dict[str, Any], split_plan: dict[str, Any]) -> None:
    split_units_by_slide: dict[int, dict[str, dict[str, Any]]] = {}
    required_split_ids_by_slide: dict[int, set[str]] = {}
    for slide in split_plan.get("slides", []):
        slide_index = slide["slide_index"]
        split_units_by_slide[slide_index] = {}
        required_split_ids_by_slide[slide_index] = set()
        for unit in slide.get("units", []):
            split_unit_id = unit["split_unit_id"]
            split_units_by_slide[slide_index][split_unit_id] = unit
            if unit.get("restore_as_editable") and unit.get("background_action") == "remove_and_restore":
                required_split_ids_by_slide[slide_index].add(split_unit_id)

    seen_split_ids: set[str] = set()
    for slide in ownership.get("slides", []):
        slide_index = slide["slide_index"]
        slide_split_units = split_units_by_slide.get(slide_index, {})
        for index, item in enumerate(slide.get("editable_page_layer", []), start=1):
            if item.get("restore_as_editable") is not True:
                continue
            item_label = f"text_ownership_map slide {slide_index} editable_page_layer[{index}]"
            split_unit_id = item.get("split_unit_id")
            if not isinstance(split_unit_id, str) or not split_unit_id.strip():
                raise ValidationError(f"{item_label}.split_unit_id is required when text_unit_split_plan exists")
            if split_unit_id in seen_split_ids:
                raise ValidationError(f"{item_label}.split_unit_id is duplicated: {split_unit_id}")
            seen_split_ids.add(split_unit_id)
            split_unit = slide_split_units.get(split_unit_id)
            if not split_unit:
                raise ValidationError(f"{item_label}.split_unit_id does not exist on same slide: {split_unit_id}")
            if _normalize_text_for_match(item.get("expected_text")) != _normalize_text_for_match(split_unit.get("text")):
                raise ValidationError(f"{item_label}.expected_text must match text_unit_split_plan unit text")
            expected_remove = split_unit.get("background_action") == "remove_and_restore"
            if item.get("remove_from_background") is not expected_remove:
                raise ValidationError(f"{item_label}.remove_from_background must match text_unit_split_plan background_action")

    missing: list[str] = []
    for slide_index, required_ids in required_split_ids_by_slide.items():
        for split_unit_id in sorted(required_ids):
            if split_unit_id not in seen_split_ids:
                missing.append(f"slide {slide_index}:{split_unit_id}")
    if missing:
        raise ValidationError("text_ownership_map missing editable split units: " + ", ".join(missing))


def validate_text_ownership_map(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("text_ownership_map must be an object")
    for field in ("schema_version", "basis", "slides"):
        if field not in data:
            raise ValidationError(f"text_ownership_map missing required field: {field}")
    if data["schema_version"] != "1.0":
        raise ValidationError("text_ownership_map.schema_version must be 1.0")
    if not isinstance(data.get("basis"), dict):
        raise ValidationError("text_ownership_map.basis must be an object")
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError("text_ownership_map.slides must be a non-empty list")
    validate_slide_indices(slides, "text_ownership_map.slides")
    ownership_ids: set[str] = set()
    for position, slide in enumerate(slides, start=1):
        label = f"text_ownership_map.slides[{position}]"
        _validate_layer(slide.get("editable_page_layer"), f"{label}.editable_page_layer", editable=True, seen=ownership_ids)
        _validate_layer(slide.get("raster_visual_layer", []), f"{label}.raster_visual_layer", editable=False, seen=ownership_ids)
        unresolved = slide.get("unresolved_items", [])
        if not isinstance(unresolved, list):
            raise ValidationError(f"{label}.unresolved_items must be a list")
        if unresolved:
            raise ValidationError(f"{label}.unresolved_items must be empty before formal stage3 background dispatch")
    return data


def _validate_layer(value: Any, label: str, *, editable: bool, seen: set[str]) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    if editable and not value:
        raise ValidationError(f"{label} must be non-empty")
    for index, item in enumerate(value, start=1):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{item_label} must be an object")
        ownership_id = require_string(item, "ownership_id", item_label)
        if ownership_id in seen:
            raise ValidationError(f"{item_label}.ownership_id is duplicated: {ownership_id}")
        seen.add(ownership_id)
        if editable:
            require_string(item, "text_source", item_label)
            require_string(item, "expected_text", item_label)
            require_string(item, "semantic_role", item_label)
            require_bool(item, "remove_from_background", item_label)
            require_bool(item, "restore_as_editable", item_label)
            for optional_field in ("split_unit_id", "style_role", "visual_group_id"):
                if optional_field in item:
                    require_string(item, optional_field, item_label)
        else:
            require_string(item, "description", item_label)
            require_bool(item, "preserve_in_background", item_label)


def _source_for_text_item(item: dict[str, Any]) -> dict[str, str]:
    source = item["text_source"]
    if "#" in source:
        path, field = source.split("#", 1)
    else:
        path, field = "_state/阶段1/content.json", source
    if path.endswith("slide_prompt_briefs.json"):
        return {"slide_prompt_briefs_path": path, "source_field": field}
    return {"content_json_path": path or "_state/阶段1/content.json", "source_field": field}


def _normalized_visible_text_blob(content_slide: dict[str, Any]) -> str:
    visible = content_slide.get("final_visible_text", [])
    pieces = []
    title = content_slide.get("title")
    if isinstance(title, str):
        pieces.append(title)
    pieces.extend(item for item in visible if isinstance(item, str))
    return _normalize_text_for_match(" ".join(pieces))


def _normalize_text_for_match(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(value.split())
