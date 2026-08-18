from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .box_utils import require_string, validate_relative_box, validate_slide_indices
from .events import append_event
from .json_io import read_json
from .stage1_plan import load_stage1_slides
from .stage_docs import sync_stage_docs
from .stage3_artifact_hashes import file_sha256
from .state import read_state, write_state
from .validation import ValidationError, require_matching_slide_indices, validate_stage1_plan


DENSITY_DECISIONS = {"fits", "tight_but_acceptable", "too_dense_split_required"}


def layout_safety_contract_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段1" / "layout_safety_contract.json"


def load_layout_safety_contract(run_dir: str | Path) -> dict[str, Any]:
    return validate_layout_safety_contract(read_json(layout_safety_contract_path(run_dir)))


def layout_safety_contract_hash(run_dir: str | Path) -> str:
    path = layout_safety_contract_path(run_dir)
    return file_sha256(path) if path.exists() else ""


def record_layout_safety_contract(run_dir: str | Path, contract_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] not in {"stage1", "stage2"}:
        raise ValidationError("layout safety contract can only be recorded in stage1 or before stage2 image dispatch")
    source = Path(contract_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"layout safety contract not found: {source}")
    contract = validate_layout_safety_contract(read_json(source))
    stage1 = validate_stage1_plan(load_stage1_slides(root))
    require_matching_slide_indices(("stage1_plan", stage1), ("layout_safety_contract", contract))
    if any(slide.get("density_decision") == "too_dense_split_required" for slide in contract["slides"]):
        state["quality"]["stage1_layout_safety"] = "split_required"
    else:
        state["quality"]["stage1_layout_safety"] = "ready"
    target = layout_safety_contract_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    state["runtime_artifacts"]["layout_safety_contract"] = "_state/阶段1/layout_safety_contract.json"
    state["next_required_action"] = "主控大模型基于 layout_safety_contract 生成阶段2试样或正式图片"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(root, "layout_safety_contract_recorded", "runtime", slides_count=len(contract["slides"]))
    return target


def require_layout_safety_ready(run_dir: str | Path, slide_indices: list[int] | None = None) -> dict[str, Any]:
    contract = load_layout_safety_contract(run_dir)
    targets = set(slide_indices or [slide["slide_index"] for slide in contract["slides"]])
    by_index = {slide["slide_index"]: slide for slide in contract["slides"]}
    missing = sorted(targets - set(by_index))
    if missing:
        raise ValidationError("layout_safety_contract missing slide(s): " + ", ".join(str(item) for item in missing))
    too_dense = [
        slide_index
        for slide_index in sorted(targets)
        if by_index[slide_index].get("density_decision") == "too_dense_split_required"
    ]
    if too_dense:
        raise ValidationError(
            "layout_safety_contract requires stage1 split/rewrite before image dispatch for slide(s): "
            + ", ".join(str(item) for item in too_dense)
        )
    return contract


def safety_slide_for_prompt(contract: dict[str, Any] | None, slide_index: int) -> dict[str, Any] | None:
    if not isinstance(contract, dict):
        return None
    for slide in contract.get("slides", []):
        if isinstance(slide, dict) and slide.get("slide_index") == slide_index:
            return slide
    return None


def validate_layout_safety_contract(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("layout_safety_contract must be an object")
    for field in ("schema_version", "basis", "slides"):
        if field not in data:
            raise ValidationError(f"layout_safety_contract missing required field: {field}")
    if data["schema_version"] != "1.0":
        raise ValidationError("layout_safety_contract.schema_version must be 1.0")
    if not isinstance(data.get("basis"), dict):
        raise ValidationError("layout_safety_contract.basis must be an object")
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError("layout_safety_contract.slides must be a non-empty list")
    validate_slide_indices(slides, "layout_safety_contract.slides")
    for position, slide in enumerate(slides, start=1):
        label = f"layout_safety_contract.slides[{position}]"
        require_string(slide, "page_role", label)
        density = require_string(slide, "density_decision", label)
        if density not in DENSITY_DECISIONS:
            raise ValidationError(f"{label}.density_decision is invalid: {density}")
        _validate_regions(slide.get("editable_text_regions"), f"{label}.editable_text_regions", required=True)
        _validate_regions(slide.get("visual_regions"), f"{label}.visual_regions", required=False)
        _validate_zones(slide.get("exclusion_zones"), f"{label}.exclusion_zones")
        policy = slide.get("text_ownership_policy")
        if not isinstance(policy, dict):
            raise ValidationError(f"{label}.text_ownership_policy must be an object")
        for field in ("editable_page_layer", "raster_visual_layer"):
            value = policy.get(field)
            if not isinstance(value, list):
                raise ValidationError(f"{label}.text_ownership_policy.{field} must be a list")
            if not all(isinstance(item, str) and item.strip() for item in value):
                raise ValidationError(f"{label}.text_ownership_policy.{field} must contain non-empty strings")
    return data


def _validate_regions(value: Any, label: str, *, required: bool) -> None:
    if value is None and not required:
        return
    if not isinstance(value, list) or (required and not value):
        raise ValidationError(f"{label} must be a {'non-empty ' if required else ''}list")
    seen: set[str] = set()
    for index, region in enumerate(value, start=1):
        item_label = f"{label}[{index}]"
        if not isinstance(region, dict):
            raise ValidationError(f"{item_label} must be an object")
        region_id = require_string(region, "region_id", item_label)
        require_string(region, "role", item_label)
        if region_id in seen:
            raise ValidationError(f"{item_label}.region_id is duplicated: {region_id}")
        validate_relative_box(region.get("relative_box"), f"{item_label}.relative_box")
        roles = region.get("required_text_roles", [])
        if roles is not None and (not isinstance(roles, list) or not all(isinstance(item, str) and item.strip() for item in roles)):
            raise ValidationError(f"{item_label}.required_text_roles must contain non-empty strings")
        seen.add(region_id)


def _validate_zones(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    seen: set[str] = set()
    for index, zone in enumerate(value, start=1):
        item_label = f"{label}[{index}]"
        if not isinstance(zone, dict):
            raise ValidationError(f"{item_label} must be an object")
        zone_id = require_string(zone, "zone_id", item_label)
        require_string(zone, "reason", item_label)
        if zone_id in seen:
            raise ValidationError(f"{item_label}.zone_id is duplicated: {zone_id}")
        validate_relative_box(zone.get("relative_box"), f"{item_label}.relative_box")
        seen.add(zone_id)
