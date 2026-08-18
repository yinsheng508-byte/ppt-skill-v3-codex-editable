from __future__ import annotations

from pathlib import Path
from typing import Any

from .editable_coordinate_plan import validate_coordinate_execution_report, validate_editable_coordinate_plan
from .json_io import read_json, write_json
from .officecli_utils import (
    collect_officecli_slides_readback,
    file_sha256,
    iter_officecli_nodes,
    officecli_relative_box,
    parse_officecli_length_pt,
)


def build_officecli_coordinate_execution_report(
    pptx_file: str | Path,
    coordinate_plan_file: str | Path,
    output_file: str | Path | None = None,
    *,
    readback_file: str | Path | None = None,
) -> Path | dict[str, Any]:
    pptx_path = Path(pptx_file)
    plan = validate_editable_coordinate_plan(read_json(coordinate_plan_file))
    readback = (
        read_json(readback_file)
        if readback_file is not None
        else collect_officecli_slides_readback(pptx_path, [slide["slide_index"] for slide in plan["slides"]])
    )
    report = {
        "schema_version": "2.0",
        "actual_source": "pptx_ooxml",
        "pptx_sha256": file_sha256(pptx_path),
        "slides": [],
    }
    readback_by_slide = _readback_by_slide(readback)
    for plan_slide in plan["slides"]:
        slide_index = plan_slide["slide_index"]
        slide_readback = readback_by_slide.get(slide_index, {})
        nodes = iter_officecli_nodes(slide_readback.get("children"))
        used_paths: set[str] = set()
        unit_reports = []
        for text_unit in plan_slide["text_units"]:
            shape = _match_coordinate_text_shape(nodes, text_unit, used_paths)
            unit_reports.append(_inspect_coordinate_text_unit(shape, text_unit))
        merged_candidates = _possible_merged_text_shapes(nodes, plan_slide["text_units"])
        report["slides"].append(
            {
                "slide_index": slide_index,
                "coordinate_text_units": unit_reports,
                "summary": _coordinate_slide_summary(plan_slide, unit_reports, merged_candidates),
                "possible_merged_text_shapes": merged_candidates,
            }
        )
    validate_coordinate_execution_report(report, plan)
    if output_file is None:
        return report
    output_path = Path(output_file)
    write_json(output_path, report)
    return output_path


def _readback_by_slide(readback: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(readback, dict):
        return {}
    slides = readback.get("slides")
    if not isinstance(slides, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for slide in slides:
        if isinstance(slide, dict) and isinstance(slide.get("slide_index"), int):
            result[slide["slide_index"]] = slide
    return result


def _match_coordinate_text_shape(
    nodes: list[dict[str, Any]],
    text_unit: dict[str, Any],
    used_paths: set[str],
) -> dict[str, Any] | None:
    expected_name = text_unit["text_unit_id"]
    for node in nodes:
        path = str(node.get("path", ""))
        if path in used_paths:
            continue
        fmt = _format(node)
        if fmt.get("name") == expected_name:
            used_paths.add(path)
            return node

    candidates = []
    for node in nodes:
        path = str(node.get("path", ""))
        if path in used_paths:
            continue
        text = _node_text(node).strip()
        if text and text == text_unit["text"].strip():
            relative_box = officecli_relative_box(_format(node))
            if relative_box is not None:
                candidates.append((node, _relative_box_distance(text_unit["relative_box"], relative_box)))
    if not candidates:
        return None
    best = min(candidates, key=lambda item: item[1])[0]
    used_paths.add(str(best.get("path", "")))
    return best


def _inspect_coordinate_text_unit(shape: dict[str, Any] | None, planned: dict[str, Any]) -> dict[str, Any]:
    planned_report = _planned_coordinate_text_report(planned)
    if shape is None:
        return {
            "text_unit_id": planned["text_unit_id"],
            "planned": planned_report,
            "actual": {},
            "within_allowed_range": False,
            "deviation_reason": "coordinate text unit not found in OfficeCLI readback",
        }
    fmt = _format(shape)
    actual = {
        "shape_path": shape.get("path"),
        "shape_name": fmt.get("name"),
        "shape_id": fmt.get("id"),
        "text": _node_text(shape),
        "relative_box": officecli_relative_box(fmt) or {},
        "font": _shape_font(fmt),
        "paragraph": _shape_paragraph(fmt),
        "text_frame": {
            "autoFit": _first_present(fmt, "autoFit", "autofit"),
        },
    }
    within, reason = _text_within_plan(planned, actual)
    report = {
        "text_unit_id": planned["text_unit_id"],
        "planned": planned_report,
        "actual": actual,
        "within_allowed_range": within,
    }
    if not within:
        report["deviation_reason"] = reason
    return report


def _planned_coordinate_text_report(planned: dict[str, Any]) -> dict[str, Any]:
    font = planned["font"]
    paragraph = planned.get("paragraph", {})
    return {
        "ownership_id": planned["ownership_id"],
        "split_unit_id": planned.get("split_unit_id"),
        "style_profile_id": planned.get("style_profile_id"),
        "visual_group_id": planned.get("visual_group_id"),
        "text": planned["text"],
        "display_text": planned.get("display_text", planned["text"]),
        "wrap_policy": planned.get("wrap_policy", {}),
        "relative_box": planned["relative_box"],
        "box_px": planned["box_px"],
        "font": {
            "resolved_family": font["resolved_family"],
            "target_font_size_pt": font["target_font_size_pt"],
            "allowed_font_size_range_pt": font.get("allowed_font_size_range_pt"),
            "resolved_color": font["resolved_color"],
            "bold": font.get("bold"),
        },
        "paragraph": {
            "horizontal_align": paragraph.get("horizontal_align"),
            "vertical_align": paragraph.get("vertical_align"),
            "line_spacing": paragraph.get("line_spacing"),
            "text_box_insets_pt": paragraph.get("text_box_insets_pt"),
        },
    }


def _coordinate_slide_summary(
    plan_slide: dict[str, Any],
    unit_reports: list[dict[str, Any]],
    merged_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    planned_units = plan_slide.get("text_units", [])
    style_profile_ids = {
        unit.get("style_profile_id")
        for unit in planned_units
        if isinstance(unit.get("style_profile_id"), str) and unit["style_profile_id"].strip()
    }
    return {
        "expected_text_units": len(planned_units),
        "expected_native_elements": len(plan_slide.get("native_elements", [])),
        "coordinate_text_units": len(unit_reports),
        "matched_text_shapes": sum(1 for item in unit_reports if item.get("actual")),
        "missing_text_units": sum(1 for item in unit_reports if not item.get("actual")),
        "possible_merged_text_shapes": len(merged_candidates),
        "deviations": sum(1 for item in unit_reports if not item["within_allowed_range"]),
        "style_profile_count": len(style_profile_ids),
        "units_with_split_unit_id": sum(1 for unit in planned_units if unit.get("split_unit_id")),
        "units_with_style_profile_id": sum(1 for unit in planned_units if unit.get("style_profile_id")),
    }


def _shape_font(fmt: dict[str, Any]) -> dict[str, Any]:
    size = parse_officecli_length_pt(_first_present(fmt, "size", "effective.size"))
    font_slots = {
        "font": _first_present(fmt, "font", "effective.font"),
        "font_ea": _first_present(fmt, "font.ea", "font.eastAsia", "effective.font.ea", "effective.font.eastAsia"),
        "font_latin": _first_present(fmt, "font.latin", "effective.font.latin"),
        "font_cs": _first_present(fmt, "font.cs", "effective.font.cs"),
    }
    family = font_slots["font_ea"] or font_slots["font"] or font_slots["font_latin"] or font_slots["font_cs"]
    result: dict[str, Any] = {"font_slots": font_slots}
    if isinstance(family, str) and family.strip():
        result["resolved_family"] = family.strip()
    if size is not None:
        result["target_font_size_pt"] = round(size, 2)
    color = _normalize_color(_first_present(fmt, "color", "font.color", "effective.color"))
    if color:
        result["resolved_color"] = color
    result["bold"] = _boolish(_first_present(fmt, "bold", "font.bold", "effective.bold"))
    return result


def _shape_paragraph(fmt: dict[str, Any]) -> dict[str, Any]:
    return {
        "horizontal_align": _normalize_horizontal_align(_first_present(fmt, "align", "effective.align")),
        "vertical_align": _normalize_vertical_align(_first_present(fmt, "valign")),
        "line_spacing": _line_spacing(_first_present(fmt, "lineSpacing", "effective.lineSpacing")),
        "text_box_insets_pt": _margin_values(_first_present(fmt, "margin")),
    }


def _text_within_plan(planned: dict[str, Any], actual: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(actual.get("shape_path"), str) or not actual["shape_path"].strip():
        return False, "OfficeCLI readback did not return shape_path"
    if not isinstance(actual.get("shape_name"), str) or not actual["shape_name"].strip():
        return False, "OfficeCLI readback did not return shape_name"
    if actual.get("shape_id") in (None, ""):
        return False, "OfficeCLI readback did not return shape_id"
    if _normalize_text(actual.get("text")) != _normalize_text(planned.get("display_text", planned["text"])):
        return False, "actual text differs from plan"
    actual_box = actual.get("relative_box", {})
    if not _relative_box_close(planned["relative_box"], actual_box):
        return False, "actual relative_box differs from plan"

    actual_font = actual.get("font", {})
    planned_font = planned["font"]
    required_font_fields = ("resolved_family", "target_font_size_pt", "resolved_color")
    missing = [field for field in required_font_fields if field not in actual_font]
    if missing:
        return False, "OfficeCLI readback could not read actual font fields: " + ", ".join(missing)
    allowed_range = planned_font["allowed_font_size_range_pt"]
    size = actual_font["target_font_size_pt"]
    if size < allowed_range[0] or size > allowed_range[1]:
        return False, "actual font size is outside allowed range"
    if not _font_family_matches(planned_font["resolved_family"], actual_font):
        return False, "actual resolved_family differs from plan"
    if _normalize_color(actual_font.get("resolved_color")) != _normalize_color(planned_font["resolved_color"]):
        return False, "actual resolved_color differs from plan"
    if actual_font.get("bold", False) != planned_font.get("bold", False):
        return False, "actual bold differs from plan"

    paragraph = planned.get("paragraph", {})
    actual_paragraph = actual.get("paragraph", {})
    if _normalize_horizontal_align(actual_paragraph.get("horizontal_align")) != _normalize_horizontal_align(paragraph.get("horizontal_align")):
        return False, "actual horizontal alignment differs from plan"
    if _normalize_vertical_align(actual_paragraph.get("vertical_align")) != _normalize_vertical_align(paragraph.get("vertical_align")):
        return False, "actual vertical alignment differs from plan"
    if "line_spacing" in paragraph:
        actual_spacing = actual_paragraph.get("line_spacing")
        if not isinstance(actual_spacing, (int, float)) or abs(float(actual_spacing) - float(paragraph["line_spacing"])) > 0.02:
            return False, "actual line spacing differs from plan"
    planned_margin = paragraph.get("text_box_insets_pt", [0, 0, 0, 0])
    actual_margin = actual_paragraph.get("text_box_insets_pt")
    if actual_margin is None:
        return False, "OfficeCLI readback could not read actual text box insets"
    if actual_margin is not None and not _margin_close(planned_margin, actual_margin):
        return False, "actual text box insets differ from plan"
    return True, ""


def _format(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("format")
    return value if isinstance(value, dict) else {}


def _node_text(node: dict[str, Any]) -> str:
    text = node.get("text")
    if isinstance(text, str):
        return text
    fmt = _format(node)
    value = fmt.get("text")
    return value if isinstance(value, str) else ""


def _possible_merged_text_shapes(nodes: list[dict[str, Any]], text_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    planned = [
        (unit["text_unit_id"], _normalize_text(unit["text"]))
        for unit in text_units
        if _normalize_text(unit.get("text"))
    ]
    planned_texts = {text for _, text in planned}
    findings: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("type") != "shape":
            continue
        text = _normalize_text(_node_text(node))
        if not text:
            continue
        if text in planned_texts:
            continue
        matched = [text_unit_id for text_unit_id, planned_text in planned if planned_text and planned_text in text]
        if len(matched) > 1:
            findings.append(
                {
                    "shape_path": node.get("path"),
                    "shape_name": _format(node).get("name"),
                    "matched_text_unit_ids": matched,
                    "reason": "one PPT text shape appears to contain multiple planned text units",
                }
            )
    return findings


def _font_family_matches(planned_family: str, actual_font: dict[str, Any]) -> bool:
    planned = _normalize_family(planned_family)
    candidates = [actual_font.get("resolved_family")]
    slots = actual_font.get("font_slots", {})
    if isinstance(slots, dict):
        candidates.extend(slots.values())
    return any(_normalize_family(candidate) == planned for candidate in candidates if isinstance(candidate, str))


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _line_spacing(value: Any) -> float | str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("x"):
        try:
            return float(text[:-1])
        except ValueError:
            return text
    return text or None


def _margin_values(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return [number, number, number, number]
    if not isinstance(value, str) or not value.strip():
        return None
    parts = [part.strip() for part in value.split(",")]
    if len(parts) == 1:
        number = parse_officecli_length_pt(parts[0])
        return [number, number, number, number] if number is not None else None
    if len(parts) != 4:
        return None
    values = [parse_officecli_length_pt(part) if part != "-" else None for part in parts]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values]


def _relative_box_close(planned: dict[str, Any], actual: dict[str, Any], tolerance: float = 0.01) -> bool:
    for field in ("x", "y", "w", "h"):
        planned_value = planned.get(field)
        actual_value = actual.get(field)
        if not isinstance(planned_value, (int, float)) or not isinstance(actual_value, (int, float)):
            return False
        if abs(planned_value - actual_value) > tolerance:
            return False
    return True


def _relative_box_distance(planned: dict[str, Any], actual: dict[str, Any]) -> float:
    total = 0.0
    for field in ("x", "y", "w", "h"):
        total += abs(float(planned[field]) - float(actual[field]))
    return total


def _margin_close(planned: Any, actual: Any, tolerance: float = 0.25) -> bool:
    if not isinstance(planned, list) or not isinstance(actual, list) or len(planned) != 4 or len(actual) != 4:
        return False
    for expected, observed in zip(planned, actual):
        if abs(float(expected) - float(observed)) > tolerance:
            return False
    return True


def _normalize_color(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if not text.startswith("#"):
        text = "#" + text
    if len(text) == 4:
        text = "#" + "".join(char * 2 for char in text[1:])
    if len(text) != 7:
        return text.upper()
    return text.upper()


def _normalize_family(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False


def _normalize_horizontal_align(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"center", "middle", "ctr", "c"}:
        return "center"
    if text in {"right", "r"}:
        return "right"
    if text in {"justify", "justified", "just"}:
        return "justify"
    if text in {"left", "l"}:
        return "left"
    return text


def _normalize_vertical_align(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"center", "middle", "ctr", "c"}:
        return "middle"
    if text in {"bottom", "b"}:
        return "bottom"
    if text in {"top", "t"}:
        return "top"
    return text
