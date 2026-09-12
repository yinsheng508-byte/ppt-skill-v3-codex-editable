from __future__ import annotations

from typing import Any

from .validation import ValidationError


def require_number(value: Any, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} must be a number")
    return value


def validate_relative_box(value: Any, label: str) -> dict[str, float | int]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    missing = [field for field in ("x", "y", "w", "h") if field not in value]
    if missing:
        raise ValidationError(f"{label} missing required fields: {', '.join(missing)}")
    box = {field: require_number(value[field], f"{label}.{field}") for field in ("x", "y", "w", "h")}
    if box["x"] < 0 or box["x"] > 1:
        raise ValidationError(f"{label}.x must be between 0 and 1")
    if box["y"] < 0 or box["y"] > 1:
        raise ValidationError(f"{label}.y must be between 0 and 1")
    if box["w"] <= 0 or box["w"] > 1:
        raise ValidationError(f"{label}.w must be greater than 0 and at most 1")
    if box["h"] <= 0 or box["h"] > 1:
        raise ValidationError(f"{label}.h must be greater than 0 and at most 1")
    if box["x"] + box["w"] > 1.000001:
        raise ValidationError(f"{label} must fit within slide width")
    if box["y"] + box["h"] > 1.000001:
        raise ValidationError(f"{label} must fit within slide height")
    return box


def validate_pixel_box(value: Any, label: str, *, width_px: int | None = None, height_px: int | None = None) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    missing = [field for field in ("x", "y", "w", "h") if field not in value]
    if missing:
        raise ValidationError(f"{label} missing required fields: {', '.join(missing)}")
    box: dict[str, int] = {}
    for field in ("x", "y", "w", "h"):
        raw = value[field]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValidationError(f"{label}.{field} must be an integer")
        box[field] = raw
    if box["x"] < 0 or box["y"] < 0 or box["w"] <= 0 or box["h"] <= 0:
        raise ValidationError(f"{label} must have non-negative x/y and positive w/h")
    if width_px is not None and box["x"] + box["w"] > width_px:
        raise ValidationError(f"{label} must fit within source image width")
    if height_px is not None and box["y"] + box["h"] > height_px:
        raise ValidationError(f"{label} must fit within source image height")
    return box


def box_contains(parent: dict[str, float | int], child: dict[str, float | int]) -> bool:
    epsilon = 0.000001
    return (
        child["x"] >= parent["x"] - epsilon
        and child["y"] >= parent["y"] - epsilon
        and child["x"] + child["w"] <= parent["x"] + parent["w"] + epsilon
        and child["y"] + child["h"] <= parent["y"] + parent["h"] + epsilon
    )


def require_string(data: dict[str, Any], field: str, label: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label}.{field} must be a non-empty string")
    return value


def require_bool(data: dict[str, Any], field: str, label: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ValidationError(f"{label}.{field} must be a boolean")
    return value


def validate_slide_indices(slides: list[Any], label: str) -> set[int]:
    seen: set[int] = set()
    for position, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise ValidationError(f"{label}[{position}] must be an object")
        if not isinstance(slide.get("slide_index"), int):
            raise ValidationError(f"{label}[{position}].slide_index must be an integer")
        slide_index = slide["slide_index"]
        if slide_index in seen:
            raise ValidationError(f"{label}[{position}].slide_index is duplicated: {slide_index}")
        seen.add(slide_index)
    return seen
