from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .editable_coordinate_plan import (
    load_editable_coordinate_plan,
    require_coordinate_plan_background_alignment,
)
from .events import append_event
from .json_io import write_json
from .officecli_utils import (
    SLIDE_HEIGHT_PT,
    SLIDE_WIDTH_PT,
    close_officecli_document,
    collect_officecli_slides_readback,
    file_sha256,
    iter_officecli_nodes,
    officecli_relative_box,
    officecli_version,
    pt,
    relative_box_to_pt,
    require_officecli,
    run_officecli,
)
from .stage1_plan import load_stage1_slides
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .time_utils import now_iso
from .validation import ValidationError, require_matching_slide_indices, validate_stage1_plan


OFFICECLI_DECK_REL_PATH = "阶段3_可编辑PPT/ppt/可编辑PPT.pptx"
OFFICECLI_MANIFEST_REL_PATH = "_state/阶段3/manifests/officecli_manifest.json"
OFFICECLI_COMMANDS_REL_PATH = "_state/阶段3/officecli/commands/build_deck.batch.json"
OFFICECLI_RESULT_REL_PATH = "_state/阶段3/officecli/commands/build_deck.result.json"
OFFICECLI_READBACK_REL_PATH = "_state/阶段3/officecli/readback/build_deck.readback.json"
OFFICECLI_WORK_PPTX_REL_PATH = "_state/阶段3/officecli/build/build_deck.pptx"


def build_officecli_coordinate_deck(
    run_dir: str | Path,
    *,
    output_file: str | Path | None = None,
    mode: str = "full_deck",
    probe_slide_index: int | None = None,
) -> Path:
    require_officecli()
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("OfficeCLI coordinate deck can only be built in stage3")
    if not state.get("confirmed", {}).get("stage3_coordinate_plan"):
        raise ValidationError("OfficeCLI coordinate deck requires user-confirmed stage3 coordinate plan")
    if mode not in {"full_deck", "native_style_probe"}:
        raise ValidationError("OfficeCLI coordinate deck mode must be full_deck or native_style_probe")
    if mode == "full_deck" and probe_slide_index is not None:
        raise ValidationError("probe_slide_index is only valid for native_style_probe mode")

    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    plan = apply_stage3_scope(load_editable_coordinate_plan(root), state, "editable_coordinate_plan", strict=True)
    require_matching_slide_indices(("stage1_plan", stage1), ("editable_coordinate_plan", plan))
    require_coordinate_plan_background_alignment(root, plan)

    selected_plan_slides = _selected_slides(plan["slides"], mode=mode, probe_slide_index=probe_slide_index)
    output_path = _output_path(root, output_file, mode=mode, probe_slide_index=probe_slide_index)
    work_pptx = root / OFFICECLI_WORK_PPTX_REL_PATH if mode == "full_deck" else root / "_state" / "阶段3" / "officecli" / "probe" / f"probe_slide_{probe_slide_index:03d}.pptx"
    commands, manifest_parts = _build_commands(root, selected_plan_slides)

    commands_path = root / (
        OFFICECLI_COMMANDS_REL_PATH
        if mode == "full_deck"
        else f"_state/阶段3/officecli/probe/probe_slide_{probe_slide_index:03d}.batch.json"
    )
    result_path = root / (
        OFFICECLI_RESULT_REL_PATH
        if mode == "full_deck"
        else f"_state/阶段3/officecli/probe/probe_slide_{probe_slide_index:03d}.result.json"
    )
    readback_path = root / (
        OFFICECLI_READBACK_REL_PATH
        if mode == "full_deck"
        else f"_state/阶段3/officecli/probe/probe_slide_{probe_slide_index:03d}.readback.json"
    )
    manifest_path = root / (
        OFFICECLI_MANIFEST_REL_PATH
        if mode == "full_deck"
        else "_state/阶段3/officecli/probe/native_style_probe.json"
    )

    write_json(commands_path, commands)
    _create_clean_pptx(work_pptx)
    batch_result = run_officecli(["batch", str(work_pptx), "--input", str(commands_path), "--stop-on-error", "--json"])
    write_json(result_path, _serializable_command_result(batch_result))
    close_officecli_document(work_pptx)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.resolve() != work_pptx.resolve():
        close_officecli_document(output_path)
        shutil.copy2(work_pptx, output_path)

    readback = collect_officecli_slides_readback(
        output_path,
        list(range(1, len(selected_plan_slides) + 1)),
    )
    _attach_readback_slide_indices(readback, selected_plan_slides)
    write_json(readback_path, readback)
    manifest = _build_manifest(
        root,
        mode=mode,
        output_path=output_path,
        commands_path=commands_path,
        result_path=result_path,
        readback_path=readback_path,
        readback=readback,
        plan=plan,
        selected_plan_slides=selected_plan_slides,
        manifest_parts=manifest_parts,
    )
    write_json(manifest_path, manifest)

    _update_state(root, state, mode=mode, output_path=output_path, manifest_path=manifest_path, readback_path=readback_path)
    append_event(
        root,
        "officecli_coordinate_deck_built",
        "runtime",
        mode=mode,
        slides_count=len(selected_plan_slides),
        deck_path=str(_relative_or_absolute(root, output_path)),
        manifest=str(_relative_or_absolute(root, manifest_path)),
        stage3_scope=stage3_scope_summary(state),
    )
    return output_path


def _selected_slides(
    slides: list[dict[str, Any]],
    *,
    mode: str,
    probe_slide_index: int | None,
) -> list[dict[str, Any]]:
    if mode == "full_deck":
        return slides
    if probe_slide_index is None:
        raise ValidationError("native_style_probe mode requires probe_slide_index")
    selected = [slide for slide in slides if slide["slide_index"] == probe_slide_index]
    if not selected:
        raise ValidationError(f"probe slide does not exist in editable coordinate plan: {probe_slide_index}")
    return selected


def _output_path(root: Path, output_file: str | Path | None, *, mode: str, probe_slide_index: int | None) -> Path:
    if output_file is not None:
        path = Path(output_file)
        return path if path.is_absolute() else root / path
    if mode == "full_deck":
        return root / OFFICECLI_DECK_REL_PATH
    return root / "阶段3_可编辑PPT" / "native_style_probe" / f"probe_slide_{probe_slide_index:03d}.pptx"


def _build_commands(root: Path, slides: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    commands: list[dict[str, Any]] = [
        {
            "command": "set",
            "path": "/",
            "props": {
                "slideWidth": pt(SLIDE_WIDTH_PT),
                "slideHeight": pt(SLIDE_HEIGHT_PT),
            },
        }
    ]
    background_placements: list[dict[str, Any]] = []
    native_shapes: list[dict[str, Any]] = []
    text_shapes: list[dict[str, Any]] = []

    for logical_index, slide in enumerate(slides, start=1):
        slide_index = slide["slide_index"]
        commands.append(
            {
                "command": "add",
                "parent": "/",
                "type": "slide",
                "props": {"layout": "Blank", "name": f"slide_{slide_index:03d}"},
            }
        )
        background = slide["stage3_background_image"]
        background_name = f"stage3_background_{slide_index:03d}"
        background_path = root / background["path"]
        if not background_path.exists():
            raise FileNotFoundError(f"stage3 background image missing: {background_path}")
        commands.append(
            {
                "command": "add",
                "parent": f"/slide[{logical_index}]",
                "type": "picture",
                "props": {
                    "src": str(background_path),
                    "x": "0pt",
                    "y": "0pt",
                    "width": pt(SLIDE_WIDTH_PT),
                    "height": pt(SLIDE_HEIGHT_PT),
                    "name": background_name,
                    "alt": f"stage3 no-text background for slide {slide_index}",
                },
            }
        )
        background_placements.append(
            {
                "slide_index": slide_index,
                "logical_slide_index": logical_index,
                "name": background_name,
                "image_path": background["path"],
                "image_sha256": background["sha256"],
                "x": 0,
                "y": 0,
                "width": SLIDE_WIDTH_PT,
                "height": SLIDE_HEIGHT_PT,
                "placement_mode": "exact_full_slide",
                "crop": False,
            }
        )

        for element in slide.get("native_elements", []):
            if element["z_order"] == "under_text":
                commands.append(_native_shape_command(logical_index, element))
                native_shapes.append(_native_shape_manifest(slide_index, logical_index, element))

        for unit in slide.get("text_units", []):
            commands.append(_text_shape_command(logical_index, unit))
            text_shapes.append(_text_shape_manifest(slide_index, logical_index, unit))

        for element in slide.get("native_elements", []):
            if element["z_order"] == "over_text":
                commands.append(_native_shape_command(logical_index, element))
                native_shapes.append(_native_shape_manifest(slide_index, logical_index, element))

    return commands, {
        "background_placements": background_placements,
        "native_shapes": native_shapes,
        "text_shapes": text_shapes,
    }


def _text_shape_command(logical_slide_index: int, unit: dict[str, Any]) -> dict[str, Any]:
    font = unit["font"]
    paragraph = unit["paragraph"]
    text = unit.get("display_text", unit["text"])
    family = font["resolved_family"]
    box = relative_box_to_pt(unit["relative_box"])
    props = {
        "name": unit["text_unit_id"],
        "text": text,
        "geometry": "rect",
        "fill": "none",
        "line": "none",
        "x": box["x"],
        "y": box["y"],
        "width": box["width"],
        "height": box["height"],
        "font": family,
        "font.ea": family,
        "font.latin": family,
        "font.cs": family,
        "size": pt(font["target_font_size_pt"]),
        "color": _normalize_color(font["resolved_color"]),
        "bold": "true" if font.get("bold") else "false",
        "align": _horizontal_align(paragraph["horizontal_align"]),
        "valign": _vertical_align(paragraph["vertical_align"]),
        "margin": _margin(paragraph.get("text_box_insets_pt", [0, 0, 0, 0])),
        "autoFit": "none",
    }
    if "line_spacing" in paragraph:
        props["lineSpacing"] = f"{float(paragraph['line_spacing']):.4g}x"
    return {
        "command": "add",
        "parent": f"/slide[{logical_slide_index}]",
        "type": "shape",
        "props": props,
    }


def _native_shape_command(logical_slide_index: int, element: dict[str, Any]) -> dict[str, Any]:
    box = relative_box_to_pt(element["relative_box"])
    props = {
        "name": element["element_id"],
        "geometry": _native_geometry(element["type"]),
        "x": box["x"],
        "y": box["y"],
        "width": box["width"],
        "height": box["height"],
        "fill": _normalize_color(element.get("fill")) if element.get("fill") else "none",
        "line": _native_line(element),
    }
    return {
        "command": "add",
        "parent": f"/slide[{logical_slide_index}]",
        "type": "shape",
        "props": props,
    }


def _text_shape_manifest(slide_index: int, logical_slide_index: int, unit: dict[str, Any]) -> dict[str, Any]:
    font = unit["font"]
    paragraph = unit["paragraph"]
    return {
        "slide_index": slide_index,
        "logical_slide_index": logical_slide_index,
        "text_unit_id": unit["text_unit_id"],
        "shape_name": unit["text_unit_id"],
        "shape_path": None,
        "shape_id": None,
        "ownership_id": unit["ownership_id"],
        "split_unit_id": unit.get("split_unit_id"),
        "style_profile_id": unit.get("style_profile_id"),
        "visual_group_id": unit.get("visual_group_id"),
        "relative_box": unit["relative_box"],
        "font_family": font["resolved_family"],
        "font_ea": font["resolved_family"],
        "font_latin": font["resolved_family"],
        "font_cs": font["resolved_family"],
        "font_size_pt": font["target_font_size_pt"],
        "bold": font.get("bold", False),
        "color": _normalize_color(font["resolved_color"]),
        "line_spacing": paragraph.get("line_spacing"),
        "margin": paragraph.get("text_box_insets_pt", [0, 0, 0, 0]),
        "valign": _vertical_align(paragraph["vertical_align"]),
        "align": _horizontal_align(paragraph["horizontal_align"]),
    }


def _native_shape_manifest(slide_index: int, logical_slide_index: int, element: dict[str, Any]) -> dict[str, Any]:
    return {
        "slide_index": slide_index,
        "logical_slide_index": logical_slide_index,
        "element_id": element["element_id"],
        "shape_name": element["element_id"],
        "type": element["type"],
        "z_order": element["z_order"],
        "relative_box": element["relative_box"],
        "fill": element.get("fill"),
        "stroke": element.get("stroke"),
        "linked_text_unit_id": element.get("linked_text_unit_id"),
    }


def _build_manifest(
    root: Path,
    *,
    mode: str,
    output_path: Path,
    commands_path: Path,
    result_path: Path,
    readback_path: Path,
    readback: dict[str, Any],
    plan: dict[str, Any],
    selected_plan_slides: list[dict[str, Any]],
    manifest_parts: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    _attach_readback_identity(manifest_parts["text_shapes"], readback)
    return {
        "schema_version": "1.0",
        "provider": "officecli",
        "officecli_version": officecli_version(),
        "mode": mode,
        "created_at": now_iso(),
        "coordinate_plan": "_state/阶段3/editable_coordinate_plan.json",
        "pptx_source": str(_relative_or_absolute(root, output_path)),
        "pptx_sha256": file_sha256(output_path),
        "slides_count": len(selected_plan_slides),
        "slides": [
            {
                "slide_index": slide["slide_index"],
                "logical_slide_index": position,
                "coordinate_canvas": slide.get("coordinate_canvas"),
            }
            for position, slide in enumerate(selected_plan_slides, start=1)
        ],
        "commands": str(_relative_or_absolute(root, commands_path)),
        "command_results": str(_relative_or_absolute(root, result_path)),
        "readback": {
            "path": str(_relative_or_absolute(root, readback_path)),
            "slides_count": len(readback.get("slides", [])),
            "source": "officecli get /slide[N] --depth 3 --json",
        },
        "probe": _probe_summary(root, mode, output_path, selected_plan_slides),
        "background_placements": manifest_parts["background_placements"],
        "native_shapes": manifest_parts["native_shapes"],
        "text_shapes": manifest_parts["text_shapes"],
        "source_plan_summary": {
            "source_slides_count": len(plan["slides"]),
            "selected_slide_indices": [slide["slide_index"] for slide in selected_plan_slides],
            "text_unit_count": sum(len(slide.get("text_units", [])) for slide in selected_plan_slides),
            "native_element_count": sum(len(slide.get("native_elements", [])) for slide in selected_plan_slides),
        },
        "warnings": [],
        "errors": [],
    }


def _probe_summary(root: Path, mode: str, output_path: Path, selected_plan_slides: list[dict[str, Any]]) -> dict[str, Any] | None:
    if mode != "native_style_probe":
        return None
    slide = selected_plan_slides[0]
    return {
        "slide_index": slide["slide_index"],
        "pptx": str(_relative_or_absolute(root, output_path)),
        "review_status": "draft",
        "compare_image": None,
        "notes": "Controller must compare OfficeCLI native render with stage2 reference before marking passed.",
    }


def _attach_readback_identity(text_shapes: list[dict[str, Any]], readback: dict[str, Any]) -> None:
    nodes_by_name: dict[tuple[int, str], dict[str, Any]] = {}
    for slide in readback.get("slides", []):
        logical_slide_index = slide.get("logical_slide_index", slide.get("slide_index"))
        for node in iter_officecli_nodes(slide.get("children")):
            fmt = node.get("format", {}) if isinstance(node.get("format"), dict) else {}
            name = fmt.get("name")
            if isinstance(logical_slide_index, int) and isinstance(name, str):
                nodes_by_name[(logical_slide_index, name)] = node
    for item in text_shapes:
        node = nodes_by_name.get((item["logical_slide_index"], item["shape_name"]))
        if not node:
            continue
        fmt = node.get("format", {}) if isinstance(node.get("format"), dict) else {}
        item["shape_path"] = node.get("path")
        item["shape_id"] = fmt.get("id")
        item["readback_relative_box"] = officecli_relative_box(fmt)


def _attach_readback_slide_indices(readback: dict[str, Any], selected_plan_slides: list[dict[str, Any]]) -> None:
    slides = readback.get("slides")
    if not isinstance(slides, list):
        return
    for logical_index, (readback_slide, plan_slide) in enumerate(zip(slides, selected_plan_slides), start=1):
        if not isinstance(readback_slide, dict):
            continue
        readback_slide["logical_slide_index"] = logical_index
        readback_slide["slide_index"] = plan_slide["slide_index"]


def _create_clean_pptx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    close_officecli_document(path)
    if path.exists():
        path.unlink()
    run_officecli(["create", str(path), "--type", "pptx", "--force", "--locale", "zh-CN", "--json"])


def _serializable_command_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "returncode": result["returncode"],
        "json": result["json"],
        "stderr": result["stderr"],
    }


def _update_state(
    root: Path,
    state: dict[str, Any],
    *,
    mode: str,
    output_path: Path,
    manifest_path: Path,
    readback_path: Path,
) -> None:
    state.setdefault("runtime_artifacts", {})["stage3_officecli_manifest"] = str(_relative_or_absolute(root, manifest_path))
    state["runtime_artifacts"]["stage3_officecli_readback"] = str(_relative_or_absolute(root, readback_path))
    if mode == "full_deck":
        state.setdefault("user_artifacts", {})["stage3_editable_deck_candidate"] = str(_relative_or_absolute(root, output_path))
        state["status"] = "stage3_officecli_deck_built"
        state["required_actor"] = "main_controller"
        state["next_required_action"] = "运行 OfficeCLI OOXML readback execution report、render review 和阶段3 QA 后再记录可编辑 PPT"
    else:
        state["status"] = "stage3_native_style_probe_built"
        state["required_actor"] = "main_controller"
        state["next_required_action"] = "主控复核 native style probe 后再决定是否调整字体 profile 或进入全量 OfficeCLI builder"
    write_state(root, state)
    sync_stage_docs(root)


def _native_geometry(element_type: str) -> str:
    mapping = {
        "rect": "rect",
        "round_rect": "roundRect",
        "ellipse": "ellipse",
        "line": "rect",
    }
    return mapping[element_type]


def _native_line(element: dict[str, Any]) -> str:
    stroke = element.get("stroke")
    if not stroke:
        return "none"
    width = element.get("stroke_width_pt", 1)
    return f"{_normalize_color(stroke)}:{float(width):.4g}:solid"


def _horizontal_align(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"center", "middle", "ctr", "c"}:
        return "center"
    if normalized in {"right", "r"}:
        return "right"
    if normalized in {"justify", "justified"}:
        return "justify"
    return "left"


def _vertical_align(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"center", "middle", "ctr", "c"}:
        return "middle"
    if normalized in {"bottom", "b"}:
        return "bottom"
    return "top"


def _margin(insets: Any) -> str:
    values = insets if isinstance(insets, list) and len(insets) == 4 else [0, 0, 0, 0]
    numeric = [float(value) for value in values]
    if len(set(numeric)) == 1:
        return pt(numeric[0])
    return ",".join(pt(value) for value in numeric)


def _normalize_color(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "#000000"
    text = value.strip()
    if not text.startswith("#"):
        text = "#" + text
    if len(text) == 4:
        text = "#" + "".join(char * 2 for char in text[1:])
    return text.upper()


def _relative_or_absolute(root: Path, path: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path
