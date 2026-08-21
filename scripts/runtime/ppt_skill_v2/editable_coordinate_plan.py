from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .box_utils import require_bool, require_number, require_string, validate_pixel_box, validate_relative_box, validate_slide_indices
from .events import append_event
from .font_calibration_profile import font_calibration_profile_path, load_font_calibration_profile, profile_ids
from .json_io import read_json, write_json
from .image_geometry import aspect_ratio_label, is_16_9, read_image_dimensions
from .stage1_plan import load_stage1_slides
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage3_artifact_hashes import file_sha256
from .stage3_restore_targets import stable_json_hash
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .text_ownership_map import load_text_ownership_map, text_ownership_map_path
from .text_unit_split_plan import load_text_unit_split_plan, text_unit_split_plan_path
from .validation import ValidationError, require_matching_slide_indices, validate_stage1_plan


COORDINATE_MODE = "approved_image_geometry"
GEOMETRY_SOURCE_TYPES = {"approved_image_detection", "manual_annotation", "vision_assisted_annotation", "controller_corrected"}
OVERFLOW_ACTIONS = {"flag_for_rework", "manual_adjust_required"}
WRAP_POLICY_MODES = {"manual_line_break", "single_line", "preserve_existing"}
NATIVE_ELEMENT_TYPES = {"rect", "round_rect", "ellipse", "line"}
NATIVE_ELEMENT_Z_ORDERS = {"under_text", "over_text"}
FORBIDDEN_TEXT_SOURCE_FRAGMENTS = ("ocr", "detected_text", "recognized_text")
FORBIDDEN_FONT_FAMILY_PATTERNS = ("pingfang", "苹方")


def editable_coordinate_plan_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "editable_coordinate_plan.json"


def coordinate_plan_warnings_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "coordinate_plan_warnings.json"


def load_editable_coordinate_plan(run_dir: str | Path) -> dict[str, Any]:
    return validate_editable_coordinate_plan(read_json(editable_coordinate_plan_path(run_dir)))


def editable_coordinate_plan_hash(run_dir: str | Path) -> str:
    path = editable_coordinate_plan_path(run_dir)
    return stable_json_hash(read_json(path)) if path.exists() else ""


def record_editable_coordinate_plan(run_dir: str | Path, plan_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("editable coordinate plan can only be recorded in stage3")
    if not text_ownership_map_path(root).exists():
        raise ValidationError("editable coordinate plan requires _state/阶段3/text_ownership_map.json")
    source = Path(plan_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"editable coordinate plan not found: {source}")

    plan = apply_stage3_scope(validate_editable_coordinate_plan(read_json(source)), state, "editable_coordinate_plan", strict=True)
    if isinstance(plan.get("basis"), dict) and plan["basis"].get("status") == "draft":
        raise ValidationError("editable coordinate plan draft must be controller-reviewed before formal record")
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    ownership = apply_stage3_scope(load_text_ownership_map(root), state, "text_ownership_map", strict=True)
    require_matching_slide_indices(("stage1_plan", stage1), ("editable_coordinate_plan", plan))
    require_matching_slide_indices(("stage1_plan", stage1), ("text_ownership_map", ownership))
    require_coordinate_plan_matches_ownership(plan, ownership)
    split_plan = None
    if text_unit_split_plan_path(root).exists():
        split_plan = apply_stage3_scope(load_text_unit_split_plan(root), state, "text_unit_split_plan", strict=True)
        require_matching_slide_indices(("text_unit_split_plan", split_plan), ("editable_coordinate_plan", plan))
        require_coordinate_plan_matches_split_plan(plan, split_plan)
    font_profile = None
    if font_calibration_profile_path(root).exists():
        font_profile = load_font_calibration_profile(root)
    require_coordinate_plan_source_images(root, plan)
    require_coordinate_plan_background_alignment(root, plan)
    warnings = build_coordinate_plan_warnings(plan, split_plan=split_plan, font_profile=font_profile)

    target = editable_coordinate_plan_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, plan)
    warning_target = coordinate_plan_warnings_path(root)
    write_json(warning_target, warnings)
    from .coordinate_preview import build_coordinate_preview

    preview = build_coordinate_preview(root)
    state["status"] = "waiting_user_coordinate_plan_confirmation"
    state["required_actor"] = "user"
    state.setdefault("confirmed", {})["stage3_coordinate_plan"] = False
    state.setdefault("user_artifacts", {})["stage3_coordinate_preview"] = preview["index"]
    state.setdefault("user_artifacts", {})["stage3_text_effect_preview"] = preview.get("text_effect_index")
    state["runtime_artifacts"]["stage3_editable_coordinate_plan"] = "_state/阶段3/editable_coordinate_plan.json"
    state["runtime_artifacts"]["stage3_coordinate_preview"] = preview.get("manifest", "_state/阶段3/coordinate_preview/manifest.json")
    state["runtime_artifacts"]["stage3_coordinate_plan_warnings"] = "_state/阶段3/coordinate_plan_warnings.json"
    state["quality"]["stage3"] = "coordinate_plan_pending_user_review"
    state["next_required_action"] = "等待用户确认阶段3文字坐标复刻；确认无误后主控大模型再构建可编辑 PPT handoff brief 并填字"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "editable_coordinate_plan_recorded",
        "runtime",
        slides_count=len(plan["slides"]),
        warnings_count=len(warnings["warnings"]),
        stage3_scope=stage3_scope_summary(state),
    )
    return target


def create_editable_coordinate_plan_draft(run_dir: str | Path, output_file: str | Path | None = None) -> dict[str, Any]:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("editable coordinate plan draft can only be created in stage3")
    ownership = apply_stage3_scope(load_text_ownership_map(root), state, "text_ownership_map", strict=True)
    split_plan = apply_stage3_scope(load_text_unit_split_plan(root), state, "text_unit_split_plan", strict=True) if text_unit_split_plan_path(root).exists() else None
    slides = []
    for ownership_slide in ownership["slides"]:
        slide_index = ownership_slide["slide_index"]
        source = _draft_source_image(root, slide_index)
        background = _draft_background_image(root, slide_index, source)
        canvas = {
            "basis": "stage3_background_image",
            "width_px": background["width_px"],
            "height_px": background["height_px"],
            "scale_x_from_stage2": background["width_px"] / source["width_px"],
            "scale_y_from_stage2": background["height_px"] / source["height_px"],
        }
        slides.append(
            {
                "slide_index": slide_index,
                "source_image": source,
                "stage3_background_image": background,
                "coordinate_canvas": canvas,
                "text_units": _draft_text_units(ownership_slide, canvas),
                "native_elements": [],
            }
        )
    draft = {
        "schema_version": "1.0",
        "coordinate_mode": COORDINATE_MODE,
        "basis": {
            "source": "text_ownership_map_and_stage2_stage3_image_results",
            "status": "draft",
            "controller_review_required": True,
            "warning": "Draft uses grid placeholder geometry. Controller must replace with approved image geometry before formal record.",
        },
        "slides": slides,
    }
    validate_editable_coordinate_plan(draft)
    require_coordinate_plan_matches_ownership(draft, ownership)
    if split_plan is not None:
        require_coordinate_plan_matches_split_plan(draft, split_plan)
    warnings = build_coordinate_plan_warnings(draft, split_plan=split_plan)
    warnings["overall_status"] = "draft_requires_controller_review"
    warnings.setdefault("warnings", []).insert(
        0,
        _warning(0, "", "draft_placeholder_geometry", "坐标草稿使用网格占位框，主控必须替换为阶段2确认图上的真实文字坐标后才能正式入账"),
    )
    target = Path(output_file) if output_file else root / "_state" / "阶段3" / "drafts" / "editable_coordinate_plan.draft.json"
    write_json(target, draft)
    warning_target = target.with_suffix(".warnings.json")
    write_json(warning_target, warnings)
    from .coordinate_preview import build_coordinate_preview

    preview = build_coordinate_preview(root, plan_file=target)
    return {"plan_path": target, "warnings_path": warning_target, "preview": preview}


def validate_editable_coordinate_plan(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("editable_coordinate_plan must be an object")
    for field in ("schema_version", "coordinate_mode", "basis", "slides"):
        if field not in data:
            raise ValidationError(f"editable_coordinate_plan missing required field: {field}")
    if data["schema_version"] != "1.0":
        raise ValidationError("editable_coordinate_plan.schema_version must be 1.0")
    if data["coordinate_mode"] != COORDINATE_MODE:
        raise ValidationError("editable_coordinate_plan.coordinate_mode must be approved_image_geometry")
    if not isinstance(data.get("basis"), dict):
        raise ValidationError("editable_coordinate_plan.basis must be an object")
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError("editable_coordinate_plan.slides must be a non-empty list")
    validate_slide_indices(slides, "editable_coordinate_plan.slides")
    for position, slide in enumerate(slides, start=1):
        _validate_slide(slide, f"editable_coordinate_plan.slides[{position}]")
    return data


def require_coordinate_plan_matches_ownership(plan: dict[str, Any], ownership: dict[str, Any]) -> None:
    ownership_ids_by_slide: dict[int, set[str]] = {}
    editable_ids_by_slide: dict[int, set[str]] = {}
    expected_text_by_slide_and_id: dict[tuple[int, str], str] = {}
    for slide in ownership["slides"]:
        slide_index = slide["slide_index"]
        editable_ids = {item["ownership_id"] for item in slide.get("editable_page_layer", []) if item.get("restore_as_editable", True)}
        all_ids = set(editable_ids)
        for item in slide.get("editable_page_layer", []):
            expected_text_by_slide_and_id[(slide_index, item["ownership_id"])] = item["expected_text"]
        for item in slide.get("raster_visual_layer", []):
            all_ids.add(item["ownership_id"])
        ownership_ids_by_slide[slide_index] = all_ids
        editable_ids_by_slide[slide_index] = editable_ids
    for slide in plan["slides"]:
        slide_index = slide["slide_index"]
        seen_units = {unit["ownership_id"] for unit in slide.get("text_units", [])}
        unknown = sorted(seen_units - ownership_ids_by_slide.get(slide_index, set()))
        if unknown:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} uses unknown ownership_id(s): {', '.join(unknown)}")
        missing = sorted(editable_ids_by_slide.get(slide_index, set()) - seen_units)
        if missing:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} missing editable ownership_id(s): {', '.join(missing)}")
        for index, unit in enumerate(slide.get("text_units", []), start=1):
            ownership_id = unit["ownership_id"]
            expected_text = expected_text_by_slide_and_id.get((slide_index, ownership_id))
            if expected_text is not None and unit["text"].strip() != expected_text.strip():
                raise ValidationError(
                    f"editable_coordinate_plan slide {slide_index} text_units[{index}].text "
                    f"must match text_ownership_map expected_text for {ownership_id}"
                )


def require_coordinate_plan_matches_split_plan(plan: dict[str, Any], split_plan: dict[str, Any]) -> None:
    split_units_by_slide: dict[int, dict[str, dict[str, Any]]] = {}
    required_ids_by_slide: dict[int, set[str]] = {}
    for slide in split_plan.get("slides", []):
        slide_index = slide["slide_index"]
        split_units_by_slide[slide_index] = {}
        required_ids_by_slide[slide_index] = set()
        for unit in slide.get("units", []):
            split_unit_id = unit["split_unit_id"]
            split_units_by_slide[slide_index][split_unit_id] = unit
            if unit.get("restore_as_editable") and unit.get("background_action") == "remove_and_restore":
                required_ids_by_slide[slide_index].add(split_unit_id)

    for slide in plan.get("slides", []):
        slide_index = slide["slide_index"]
        seen_split_ids: set[str] = set()
        for index, unit in enumerate(slide.get("text_units", []), start=1):
            item_label = f"editable_coordinate_plan slide {slide_index} text_units[{index}]"
            split_unit_id = unit.get("split_unit_id")
            if not isinstance(split_unit_id, str) or not split_unit_id.strip():
                raise ValidationError(f"{item_label}.split_unit_id is required when text_unit_split_plan exists")
            if split_unit_id in seen_split_ids:
                raise ValidationError(f"{item_label}.split_unit_id is duplicated on slide: {split_unit_id}")
            seen_split_ids.add(split_unit_id)
            split_unit = split_units_by_slide.get(slide_index, {}).get(split_unit_id)
            if not split_unit:
                raise ValidationError(f"{item_label}.split_unit_id does not exist on same slide: {split_unit_id}")
            if _normalize_display_text(unit.get("text", "")) != _normalize_display_text(split_unit.get("text", "")):
                raise ValidationError(f"{item_label}.text must match text_unit_split_plan unit text")
        missing = sorted(required_ids_by_slide.get(slide_index, set()) - seen_split_ids)
        if missing:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} missing split unit(s): {', '.join(missing)}")


def require_coordinate_plan_matches_font_profile(plan: dict[str, Any], font_profile: dict[str, Any]) -> None:
    """Compatibility hook: font profile drift is reported as warnings, not a hard gate."""
    _coordinate_plan_font_profile_warnings(plan, font_profile)
    return None


def _draft_source_image(root: Path, slide_index: int) -> dict[str, Any]:
    result = _load_stage2_result(root, slide_index)
    relpath = result.get("image_path") or f"阶段2_图片版PPT/img/slide_{slide_index:03d}.png"
    return _draft_image_info(root, relpath, result, sha_field="image_sha256")


def _draft_background_image(root: Path, slide_index: int, source: dict[str, Any]) -> dict[str, Any]:
    result = _load_stage3_background_result(root, slide_index)
    relpath = result.get("image_path") or f"阶段3_可编辑PPT/img/background_{slide_index:03d}.png"
    info = _draft_image_info(root, relpath, result, sha_field="image_sha256")
    info["aspect_ratio"] = aspect_ratio_label(info["width_px"], info["height_px"])
    info["source_stage2_sha256"] = source["sha256"]
    return info


def _draft_image_info(root: Path, relpath: Any, result: dict[str, Any], *, sha_field: str) -> dict[str, Any]:
    if not isinstance(relpath, str) or not relpath.strip():
        raise ValidationError("image result missing image_path")
    path = root / relpath
    if not path.exists():
        raise FileNotFoundError(f"image file missing for coordinate draft: {path}")
    dimensions = read_image_dimensions(path)
    width = result.get("width_px") if isinstance(result.get("width_px"), int) else dimensions["width_px"]
    height = result.get("height_px") if isinstance(result.get("height_px"), int) else dimensions["height_px"]
    sha = result.get(sha_field) if isinstance(result.get(sha_field), str) else file_sha256(path)
    return {
        "path": relpath,
        "width_px": width,
        "height_px": height,
        "sha256": sha,
    }


def _draft_text_units(ownership_slide: dict[str, Any], canvas: dict[str, Any]) -> list[dict[str, Any]]:
    editable_items = [item for item in ownership_slide.get("editable_page_layer", []) if item.get("restore_as_editable", True)]
    units = []
    count = max(1, len(editable_items))
    for index, item in enumerate(editable_items, start=1):
        box = _draft_box(canvas["width_px"], canvas["height_px"], index, count)
        semantic_role = item.get("semantic_role", "body")
        target_size = 28 if semantic_role in {"page_title", "title", "headline"} else 20
        units.append(
            {
                "text_unit_id": f"{item['ownership_id']}_unit",
                "ownership_id": item["ownership_id"],
                **({"split_unit_id": item["split_unit_id"]} if isinstance(item.get("split_unit_id"), str) else {}),
                "visual_group_id": item.get("visual_group_id", f"{item['ownership_id']}_group"),
                "content_source": item["text_source"],
                "text": item["expected_text"],
                "semantic_role": semantic_role,
                "geometry_source": {
                    "type": "manual_annotation",
                    "method": "runtime_grid_placeholder_for_controller_refinement",
                    "human_reviewed": True,
                },
                "box_px": box,
                "relative_box": _relative_box(box, canvas),
                "font": {
                    "family_token": "default_cn",
                    "resolved_family": "Microsoft YaHei",
                    "target_font_size_pt": target_size,
                    "allowed_font_size_range_pt": [max(8, target_size - 4), target_size + 4],
                    "color_token": "body",
                    "resolved_color": "#111827",
                },
                "paragraph": {
                    "horizontal_align": "left",
                    "vertical_align": "top",
                    "text_box_insets_pt": [0, 0, 0, 0],
                },
                "fit_policy": {
                    "auto_shrink": False,
                    "overflow_action": "manual_adjust_required",
                },
            }
        )
    return units


def _draft_box(width: int, height: int, index: int, count: int) -> dict[str, int]:
    x = int(width * 0.12)
    w = int(width * 0.76)
    available_h = int(height * 0.72)
    gap = max(8, int(height * 0.012))
    h = max(32, min(int(height * 0.10), int((available_h - gap * max(0, count - 1)) / count)))
    y = int(height * 0.14) + (index - 1) * (h + gap)
    if y + h > height:
        y = max(0, height - h)
    return {"x": x, "y": y, "w": w, "h": h}


def _relative_box(box: dict[str, int], canvas: dict[str, Any]) -> dict[str, float]:
    return {
        "x": box["x"] / canvas["width_px"],
        "y": box["y"] / canvas["height_px"],
        "w": box["w"] / canvas["width_px"],
        "h": box["h"] / canvas["height_px"],
    }


def _coordinate_plan_font_profile_warnings(plan: dict[str, Any], font_profile: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    status = font_profile["render_probe"]["review_status"]
    if status != "passed":
        warnings.append(
            _warning(
                0,
                "",
                "font_profile_not_passed",
                f"font_calibration_profile.render_probe.review_status={status}，字号/行高/内边距策略仍需主控判断",
            )
        )
    basis = plan.get("basis", {})
    basis_status = basis.get("native_style_probe_status", basis.get("font_probe_status"))
    if basis_status is not None and basis_status != status:
        warnings.append(
            _warning(
                0,
                "",
                "native_style_probe_status_mismatch",
                "editable_coordinate_plan.basis.native_style_probe_status 与 font_calibration_profile.render_probe.review_status 不一致",
            )
        )
    available_profile_ids = profile_ids(font_profile)
    for slide in plan.get("slides", []):
        slide_index = slide["slide_index"]
        for unit in slide.get("text_units", []):
            text_unit_id = str(unit.get("text_unit_id", ""))
            style_profile_id = unit.get("style_profile_id")
            if not isinstance(style_profile_id, str) or not style_profile_id.strip():
                warnings.append(
                    _warning(
                        slide_index,
                        text_unit_id,
                        "missing_style_profile_id",
                        "font_calibration_profile 存在，但该 text unit 未绑定 style_profile_id",
                    )
                )
            elif style_profile_id not in available_profile_ids:
                warnings.append(
                    _warning(
                        slide_index,
                        text_unit_id,
                        "unknown_style_profile_id",
                        f"style_profile_id 未在 font_calibration_profile 中定义：{style_profile_id}",
                    )
                )
    return warnings


def build_coordinate_plan_warnings(
    plan: dict[str, Any],
    *,
    split_plan: dict[str, Any] | None = None,
    font_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    split_counts = _editable_split_counts(split_plan) if split_plan is not None else {}
    split_units_by_slide = _editable_split_units_by_slide(split_plan) if split_plan is not None else {}
    if font_profile is not None:
        warnings.extend(_coordinate_plan_font_profile_warnings(plan, font_profile))
    for slide in plan.get("slides", []):
        slide_index = slide["slide_index"]
        text_units = slide.get("text_units", [])
        required_count = split_counts.get(slide_index)
        if required_count is not None and len(text_units) < required_count:
            warnings.append(
                _warning(
                    slide_index,
                    "",
                    "text_unit_count_below_split_plan",
                    "坐标计划 text unit 数量低于拆字计划可编辑 unit 数量",
                )
            )
        for unit in text_units:
            split_unit_id = unit.get("split_unit_id")
            split_unit = split_units_by_slide.get(slide_index, {}).get(split_unit_id) if isinstance(split_unit_id, str) else None
            if split_unit is not None and unit.get("visual_group_id") != split_unit.get("visual_group_id"):
                warnings.append(
                    _warning(
                        slide_index,
                        str(unit.get("text_unit_id", "")),
                        "visual_group_id_differs_from_split_plan",
                        "coordinate plan visual_group_id 与拆字计划不一致，主控需确认是否只是标签漂移",
                    )
                )
            warnings.extend(_warnings_for_text_unit(slide_index, unit))
    return {
        "schema_version": "1.0",
        "overall_status": "warnings_present" if warnings else "no_warnings",
        "warnings": warnings,
    }


def require_coordinate_plan_source_images(root: Path, plan: dict[str, Any]) -> None:
    for slide in plan["slides"]:
        slide_index = slide["slide_index"]
        source = slide["source_image"]
        source_path = source["path"]
        if not source_path.startswith("阶段2_图片版PPT/img/"):
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} source image must be a confirmed stage2 image")
        image_path = root / source_path
        if not image_path.exists() or not image_path.is_file():
            raise FileNotFoundError(f"editable_coordinate_plan slide {slide_index} source image missing: {image_path}")
        actual_sha = file_sha256(image_path)
        if actual_sha != source["sha256"]:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} source image sha256 mismatch")


def require_coordinate_plan_background_alignment(root: Path, plan: dict[str, Any]) -> None:
    for slide in plan["slides"]:
        if "stage3_background_image" not in slide and "coordinate_canvas" not in slide:
            continue
        slide_index = slide["slide_index"]
        source = slide["source_image"]
        background = slide.get("stage3_background_image")
        if not isinstance(background, dict):
            raise ValidationError(f"editable_coordinate_plan slide {slide_index}.stage3_background_image must be an object")
        canvas = slide.get("coordinate_canvas")
        if not isinstance(canvas, dict):
            raise ValidationError(f"editable_coordinate_plan slide {slide_index}.coordinate_canvas must be an object")
        result = _load_stage3_background_result(root, slide_index)
        stage2_result = _load_stage2_result(root, slide_index)
        if stage2_result.get("image_sha256") != source["sha256"]:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} source image must match stage2 image result sha256")
        if result.get("image_path") != background["path"]:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} stage3 background path must match stage3 result")
        if result.get("image_sha256") != background["sha256"]:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} stage3 background sha256 mismatch")
        source_stage2 = result.get("source_stage2", {})
        if not isinstance(source_stage2, dict) or source_stage2.get("image_sha256") != source["sha256"]:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} stage3 background source_stage2 must match source image sha256")
        if background.get("source_stage2_sha256") != source["sha256"]:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} stage3 background source_stage2_sha256 must match source image sha256")
        if background["width_px"] != result.get("width_px") or background["height_px"] != result.get("height_px"):
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} stage3 background dimensions must match stage3 result")
        if not is_16_9(source["width_px"], source["height_px"]):
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} source image must be 16:9")
        if not is_16_9(background["width_px"], background["height_px"]):
            raise ValidationError(f"editable_coordinate_plan slide {slide_index} stage3 background must be 16:9")
        if canvas["basis"] != "stage3_background_image":
            raise ValidationError(f"editable_coordinate_plan slide {slide_index}.coordinate_canvas.basis must be stage3_background_image")
        if canvas["width_px"] != background["width_px"] or canvas["height_px"] != background["height_px"]:
            raise ValidationError(f"editable_coordinate_plan slide {slide_index}.coordinate_canvas must match stage3 background dimensions")
        _require_close(
            canvas.get("scale_x_from_stage2"),
            background["width_px"] / source["width_px"],
            f"editable_coordinate_plan slide {slide_index}.coordinate_canvas.scale_x_from_stage2",
        )
        _require_close(
            canvas.get("scale_y_from_stage2"),
            background["height_px"] / source["height_px"],
            f"editable_coordinate_plan slide {slide_index}.coordinate_canvas.scale_y_from_stage2",
        )
        for unit in slide.get("text_units", []):
            _require_box_relative_consistency(unit["box_px"], unit["relative_box"], canvas, slide_index, unit["text_unit_id"])


def coordinate_plan_text_unit_ids(plan: dict[str, Any]) -> dict[int, set[str]]:
    return {
        slide["slide_index"]: {unit["text_unit_id"] for unit in slide.get("text_units", [])}
        for slide in plan.get("slides", [])
        if isinstance(slide, dict)
    }


def validate_coordinate_execution_report(data: Any, plan: dict[str, Any], *, pptx_sha256: str | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("coordinate execution report must be an object")
    for field in ("schema_version", "actual_source", "pptx_sha256", "slides"):
        if field not in data:
            raise ValidationError(f"coordinate execution report missing required field: {field}")
    if data["schema_version"] != "2.0":
        raise ValidationError("coordinate execution report.schema_version must be 2.0")
    if data["actual_source"] not in {"pptx_inspect", "pptx_ooxml", "inspect"}:
        raise ValidationError("coordinate execution report.actual_source is invalid")
    if pptx_sha256 is not None and data["pptx_sha256"] != pptx_sha256:
        raise ValidationError("coordinate execution report pptx_sha256 does not match editable PPTX")
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError("coordinate execution report.slides must be a non-empty list")
    validate_slide_indices(slides, "coordinate_execution_report.slides")
    expected = coordinate_plan_text_unit_ids(plan)
    for slide in slides:
        slide_index = slide["slide_index"]
        units = slide.get("coordinate_text_units")
        if not isinstance(units, list):
            raise ValidationError(f"coordinate execution report slide {slide_index}.coordinate_text_units must be a list")
        reported = set()
        for index, unit in enumerate(units, start=1):
            label = f"coordinate execution report slide {slide_index}.coordinate_text_units[{index}]"
            if not isinstance(unit, dict):
                raise ValidationError(f"{label} must be an object")
            reported.add(require_string(unit, "text_unit_id", label))
            if "within_allowed_range" in unit:
                require_bool(unit, "within_allowed_range", label)
        missing = sorted(expected.get(slide_index, set()) - reported)
        if missing:
            raise ValidationError(f"coordinate execution report slide {slide_index} missing text unit(s): {', '.join(missing)}")
    return data


def _validate_slide(slide: dict[str, Any], label: str) -> None:
    if not isinstance(slide, dict):
        raise ValidationError(f"{label} must be an object")
    source = slide.get("source_image")
    if not isinstance(source, dict):
        raise ValidationError(f"{label}.source_image must be an object")
    require_string(source, "path", f"{label}.source_image")
    require_string(source, "sha256", f"{label}.source_image")
    if not source["sha256"].startswith("sha256:"):
        raise ValidationError(f"{label}.source_image.sha256 must start with sha256:")
    width = source.get("width_px")
    height = source.get("height_px")
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValidationError(f"{label}.source_image.width_px must be a positive integer")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValidationError(f"{label}.source_image.height_px must be a positive integer")
    if "stage3_background_image" in slide:
        _validate_stage3_background_image(slide["stage3_background_image"], f"{label}.stage3_background_image")
    if "coordinate_canvas" in slide:
        _validate_coordinate_canvas(slide["coordinate_canvas"], f"{label}.coordinate_canvas")
    canvas = slide.get("coordinate_canvas") if isinstance(slide.get("coordinate_canvas"), dict) else None
    box_width = canvas.get("width_px") if canvas else width
    box_height = canvas.get("height_px") if canvas else height
    text_units = slide.get("text_units")
    if not isinstance(text_units, list) or not text_units:
        raise ValidationError(f"{label}.text_units must be a non-empty list")
    seen: set[str] = set()
    for index, unit in enumerate(text_units, start=1):
        unit_label = f"{label}.text_units[{index}]"
        text_unit_id = _validate_text_unit(unit, unit_label, width_px=box_width, height_px=box_height)
        if text_unit_id in seen:
            raise ValidationError(f"{unit_label}.text_unit_id is duplicated: {text_unit_id}")
        seen.add(text_unit_id)
    native_elements = slide.get("native_elements", [])
    if not isinstance(native_elements, list):
        raise ValidationError(f"{label}.native_elements must be a list")
    seen_native: set[str] = set()
    text_unit_ids = seen
    for index, element in enumerate(native_elements, start=1):
        element_id = _validate_native_element(
            element,
            f"{label}.native_elements[{index}]",
            width_px=box_width,
            height_px=box_height,
            text_unit_ids=text_unit_ids,
        )
        if element_id in seen_native:
            raise ValidationError(f"{label}.native_elements[{index}].element_id is duplicated: {element_id}")
        seen_native.add(element_id)


def _validate_stage3_background_image(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("path", "sha256", "source_stage2_sha256"):
        require_string(value, field, label)
    if not value["sha256"].startswith("sha256:"):
        raise ValidationError(f"{label}.sha256 must start with sha256:")
    if not value["source_stage2_sha256"].startswith("sha256:"):
        raise ValidationError(f"{label}.source_stage2_sha256 must start with sha256:")
    _require_positive_int(value.get("width_px"), f"{label}.width_px")
    _require_positive_int(value.get("height_px"), f"{label}.height_px")
    expected_aspect = aspect_ratio_label(value["width_px"], value["height_px"])
    if value.get("aspect_ratio") not in {None, expected_aspect}:
        raise ValidationError(f"{label}.aspect_ratio must match width_px/height_px")


def _validate_coordinate_canvas(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    basis = require_string(value, "basis", label)
    if basis != "stage3_background_image":
        raise ValidationError(f"{label}.basis must be stage3_background_image")
    _require_positive_int(value.get("width_px"), f"{label}.width_px")
    _require_positive_int(value.get("height_px"), f"{label}.height_px")
    require_number(value.get("scale_x_from_stage2"), f"{label}.scale_x_from_stage2")
    require_number(value.get("scale_y_from_stage2"), f"{label}.scale_y_from_stage2")


def _validate_text_unit(unit: Any, label: str, *, width_px: int, height_px: int) -> str:
    if not isinstance(unit, dict):
        raise ValidationError(f"{label} must be an object")
    text_unit_id = require_string(unit, "text_unit_id", label)
    require_string(unit, "ownership_id", label)
    for optional_field in ("split_unit_id", "style_profile_id", "visual_group_id"):
        if optional_field in unit:
            require_string(unit, optional_field, label)
    if "calculation" in unit and not isinstance(unit["calculation"], dict):
        raise ValidationError(f"{label}.calculation must be an object")
    content_source = require_string(unit, "content_source", label)
    normalized_source = content_source.lower()
    if any(fragment in normalized_source for fragment in FORBIDDEN_TEXT_SOURCE_FRAGMENTS):
        raise ValidationError(f"{label}.content_source must not use OCR/detected text fields")
    require_string(unit, "text", label)
    if "display_text" in unit:
        display_text = require_string(unit, "display_text", label)
        if _normalize_display_text(display_text) != _normalize_display_text(unit["text"]):
            raise ValidationError(f"{label}.display_text must contain the same text content as text")
    if "wrap_policy" in unit:
        _validate_wrap_policy(unit["wrap_policy"], f"{label}.wrap_policy")
    require_string(unit, "semantic_role", label)
    _validate_geometry_source(unit.get("geometry_source"), f"{label}.geometry_source")
    validate_pixel_box(unit.get("box_px"), f"{label}.box_px", width_px=width_px, height_px=height_px)
    validate_relative_box(unit.get("relative_box"), f"{label}.relative_box")
    _validate_font(unit.get("font"), f"{label}.font")
    _validate_paragraph(unit.get("paragraph"), f"{label}.paragraph")
    _validate_fit_policy(unit.get("fit_policy"), f"{label}.fit_policy")
    return text_unit_id


def _validate_native_element(
    value: Any,
    label: str,
    *,
    width_px: int,
    height_px: int,
    text_unit_ids: set[str],
) -> str:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    element_id = require_string(value, "element_id", label)
    element_type = require_string(value, "type", label)
    if element_type not in NATIVE_ELEMENT_TYPES:
        raise ValidationError(f"{label}.type is invalid: {element_type}")
    box_px = validate_pixel_box(value.get("box_px"), f"{label}.box_px", width_px=width_px, height_px=height_px)
    relative_box = validate_relative_box(value.get("relative_box"), f"{label}.relative_box")
    canvas = {"width_px": width_px, "height_px": height_px}
    _require_box_relative_consistency(box_px, relative_box, canvas, 0, element_id, entity_label=label)
    z_order = require_string(value, "z_order", label)
    if z_order not in NATIVE_ELEMENT_Z_ORDERS:
        raise ValidationError(f"{label}.z_order is invalid: {z_order}")
    linked = value.get("linked_text_unit_id")
    if linked is not None:
        if not isinstance(linked, str) or not linked.strip():
            raise ValidationError(f"{label}.linked_text_unit_id must be a non-empty string")
        if linked not in text_unit_ids:
            raise ValidationError(f"{label}.linked_text_unit_id must reference a text_unit_id on the same slide")
    for color_field in ("fill", "stroke"):
        color = value.get(color_field)
        if color is not None and (not isinstance(color, str) or not color.startswith("#") or len(color) not in {4, 7}):
            raise ValidationError(f"{label}.{color_field} must be a hex color")
    return element_id


def _validate_wrap_policy(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    mode = require_string(value, "mode", label)
    if mode not in WRAP_POLICY_MODES:
        raise ValidationError(f"{label}.mode is invalid: {mode}")
    if "line_count" in value:
        line_count = value["line_count"]
        if isinstance(line_count, bool) or not isinstance(line_count, int) or line_count < 1:
            raise ValidationError(f"{label}.line_count must be a positive integer")
    if "preserve_manual_breaks" in value:
        require_bool(value, "preserve_manual_breaks", label)


def _normalize_display_text(value: str) -> str:
    removable = {" ", "\t", "\n", "\r"}
    return "".join(char for char in value if char not in removable)


def _require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{label} must be a positive integer")
    return value


def _load_stage2_result(root: Path, slide_index: int) -> dict[str, Any]:
    path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
    if not path.exists():
        raise ValidationError(f"editable_coordinate_plan slide {slide_index} requires stage2 image result")
    return read_json(path)


def _load_stage3_background_result(root: Path, slide_index: int) -> dict[str, Any]:
    path = root / "_state" / "阶段3" / "no_text_background_results" / f"slide_{slide_index:03d}.json"
    if not path.exists():
        path = root / "_state" / "阶段3" / "results" / f"slide_{slide_index:03d}.json"
    if not path.exists():
        raise ValidationError(f"editable_coordinate_plan slide {slide_index} requires stage3 background result")
    return read_json(path)


def _require_close(actual: Any, expected: float, label: str, tolerance: float = 0.0001) -> None:
    value = require_number(actual, label)
    if abs(float(value) - expected) > tolerance:
        raise ValidationError(f"{label} must match expected scale")


def _require_box_relative_consistency(
    box_px: dict[str, Any],
    relative_box: dict[str, Any],
    canvas: dict[str, Any],
    slide_index: int,
    text_unit_id: str,
    *,
    entity_label: str | None = None,
    tolerance: float = 0.0001,
) -> None:
    width = canvas["width_px"]
    height = canvas["height_px"]
    expected = {
        "x": box_px["x"] / width,
        "y": box_px["y"] / height,
        "w": box_px["w"] / width,
        "h": box_px["h"] / height,
    }
    for field, expected_value in expected.items():
        if abs(float(relative_box[field]) - expected_value) > tolerance:
            prefix = entity_label or f"editable_coordinate_plan slide {slide_index} text unit {text_unit_id}"
            raise ValidationError(
                f"{prefix}.relative_box.{field} "
                "must match box_px / coordinate_canvas"
            )


def _validate_geometry_source(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    source_type = require_string(value, "type", label)
    if source_type not in GEOMETRY_SOURCE_TYPES:
        raise ValidationError(f"{label}.type is invalid: {source_type}")
    require_string(value, "method", label)
    if not require_bool(value, "human_reviewed", label):
        raise ValidationError(f"{label}.human_reviewed must be true before user coordinate confirmation")


def _validate_font(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    require_string(value, "family_token", label)
    family = require_string(value, "resolved_family", label)
    if any(pattern in family.lower() for pattern in FORBIDDEN_FONT_FAMILY_PATTERNS):
        raise ValidationError(f"{label}.resolved_family contains forbidden PingFang/苹方")
    size = require_number(value.get("target_font_size_pt"), f"{label}.target_font_size_pt")
    if size <= 0:
        raise ValidationError(f"{label}.target_font_size_pt must be positive")
    allowed = value.get("allowed_font_size_range_pt")
    if not isinstance(allowed, list) or len(allowed) != 2:
        raise ValidationError(f"{label}.allowed_font_size_range_pt must contain two numbers")
    low = require_number(allowed[0], f"{label}.allowed_font_size_range_pt[0]")
    high = require_number(allowed[1], f"{label}.allowed_font_size_range_pt[1]")
    if low <= 0 or high < low or not (low <= size <= high):
        raise ValidationError(f"{label}.allowed_font_size_range_pt must contain target size")
    require_string(value, "color_token", label)
    color = require_string(value, "resolved_color", label)
    if not color.startswith("#") or len(color) not in {4, 7}:
        raise ValidationError(f"{label}.resolved_color must be a hex color")
    if "bold" in value:
        require_bool(value, "bold", label)


def _validate_paragraph(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    require_string(value, "horizontal_align", label)
    require_string(value, "vertical_align", label)
    if "line_spacing" in value:
        spacing = require_number(value.get("line_spacing"), f"{label}.line_spacing")
        if spacing <= 0:
            raise ValidationError(f"{label}.line_spacing must be positive")
    insets = value.get("text_box_insets_pt", [0, 0, 0, 0])
    if not isinstance(insets, list) or len(insets) != 4:
        raise ValidationError(f"{label}.text_box_insets_pt must contain four numbers")
    for index, item in enumerate(insets):
        require_number(item, f"{label}.text_box_insets_pt[{index}]")


def _validate_fit_policy(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    auto_shrink = value.get("auto_shrink", False)
    if auto_shrink is not False:
        raise ValidationError(f"{label}.auto_shrink must be false in the coordinate rebuild route")
    action = require_string(value, "overflow_action", label)
    if action not in OVERFLOW_ACTIONS:
        raise ValidationError(f"{label}.overflow_action is invalid: {action}")
    if "max_lines" in value:
        max_lines = value["max_lines"]
        if isinstance(max_lines, bool) or not isinstance(max_lines, int) or max_lines < 1:
            raise ValidationError(f"{label}.max_lines must be a positive integer")


def _editable_split_counts(split_plan: dict[str, Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for slide in split_plan.get("slides", []):
        counts[slide["slide_index"]] = sum(
            1
            for unit in slide.get("units", [])
            if unit.get("restore_as_editable") and unit.get("background_action") == "remove_and_restore"
        )
    return counts


def _editable_split_units_by_slide(split_plan: dict[str, Any]) -> dict[int, dict[str, dict[str, Any]]]:
    units_by_slide: dict[int, dict[str, dict[str, Any]]] = {}
    for slide in split_plan.get("slides", []):
        slide_index = slide["slide_index"]
        units_by_slide[slide_index] = {}
        for unit in slide.get("units", []):
            if unit.get("restore_as_editable") and unit.get("background_action") == "remove_and_restore":
                units_by_slide[slide_index][unit["split_unit_id"]] = unit
    return units_by_slide


def _warnings_for_text_unit(slide_index: int, unit: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    text = str(unit.get("text", ""))
    display_text = str(unit.get("display_text") or text)
    semantic_role = str(unit.get("semantic_role", ""))
    text_unit_id = str(unit.get("text_unit_id", ""))
    line_count = max(1, len(display_text.splitlines()))
    if line_count > 3 and semantic_role not in {"source_note", "citation", "footer", "footnote"}:
        warnings.append(
            _warning(
                slide_index,
                text_unit_id,
                "multi_line_dense_text_unit",
                "单个文本框行数超过 3 行，需确认是否应继续拆分",
            )
        )
    colon_count = text.count("：") + text.count(":")
    if colon_count >= 2 and semantic_role not in {"quote", "source_note"}:
        warnings.append(
            _warning(
                slide_index,
                text_unit_id,
                "possible_mixed_title_body",
                "多个冒号内容疑似混合了标题、标签和正文",
            )
        )
    if re.match(r"^\s*(\d+|[一二三四五六七八九十]+|[①-⑳])[\.\、:：]", text) and colon_count >= 1:
        warnings.append(
            _warning(
                slide_index,
                text_unit_id,
                "possible_step_number_title_body_merged",
                "编号、节点标题、正文疑似合并为一个文本框",
            )
        )
    return warnings


def _warning(slide_index: int, text_unit_id: str, warning_type: str, message: str) -> dict[str, Any]:
    return {
        "slide_index": slide_index,
        "text_unit_id": text_unit_id,
        "warning_type": warning_type,
        "message": message,
        "resolved": False,
    }
