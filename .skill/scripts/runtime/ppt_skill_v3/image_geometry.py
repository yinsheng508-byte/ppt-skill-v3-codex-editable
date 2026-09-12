from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .validation import ValidationError


TARGET_PPT_ASPECT_RATIO = "16:9"
PPT_ASPECT_RATIO_TOLERANCE = 0.02
ASPECT_RATIO_RESULT_FIELDS = (
    "target_aspect_ratio",
    "aspect_ratio_error",
    "aspect_ratio_tolerance",
    "meets_target_aspect_ratio",
)


def read_image_dimensions(path: str | Path) -> dict[str, int | str]:
    image_path = Path(path)
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        raise ValidationError(f"cannot read image dimensions: {image_path}") from exc
    if width <= 0 or height <= 0:
        raise ValidationError(f"image dimensions must be positive: {image_path}")
    return {
        "width_px": int(width),
        "height_px": int(height),
        "aspect_ratio": aspect_ratio_label(int(width), int(height)),
    }


def aspect_ratio_label(width_px: int, height_px: int) -> str:
    divisor = math.gcd(width_px, height_px)
    return f"{width_px // divisor}:{height_px // divisor}"


def is_16_9(width_px: int, height_px: int) -> bool:
    if not _positive_dimension(width_px) or not _positive_dimension(height_px):
        return False
    return review_image_aspect_ratio(width_px, height_px)["meets_target_aspect_ratio"]


def review_image_aspect_ratio(width_px: int, height_px: int) -> dict[str, Any]:
    """Review real pixel dimensions; integer comparison includes the exact 2% boundary."""
    if not _positive_dimension(width_px) or not _positive_dimension(height_px):
        raise ValidationError("image aspect ratio requires positive integer pixel dimensions")
    difference = abs(9 * width_px - 16 * height_px)
    denominator = 16 * height_px
    return {
        "target_aspect_ratio": TARGET_PPT_ASPECT_RATIO,
        "aspect_ratio_error": difference / denominator,
        "aspect_ratio_tolerance": PPT_ASPECT_RATIO_TOLERANCE,
        "meets_target_aspect_ratio": difference * 50 <= denominator,
    }


def validate_image_aspect_ratio_fields(result: dict[str, Any]) -> None:
    """Keep legacy results readable while validating complete new ratio evidence."""
    if not any(field in result for field in ASPECT_RATIO_RESULT_FIELDS):
        return
    missing = [field for field in ASPECT_RATIO_RESULT_FIELDS if field not in result]
    if missing:
        raise ValidationError("image_result missing aspect ratio field(s): " + ", ".join(missing))
    expected = review_image_aspect_ratio(result.get("width_px"), result.get("height_px"))
    if result["target_aspect_ratio"] != expected["target_aspect_ratio"]:
        raise ValidationError("image_result.target_aspect_ratio must be 16:9")
    for field in ("aspect_ratio_error", "aspect_ratio_tolerance"):
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValidationError(f"image_result.{field} must be a finite non-negative number")
        if not math.isclose(value, expected[field], rel_tol=0, abs_tol=1e-12):
            raise ValidationError(f"image_result.{field} does not match the pixel dimensions and ratio policy")
    if not isinstance(result["meets_target_aspect_ratio"], bool):
        raise ValidationError("image_result.meets_target_aspect_ratio must be a boolean")
    if result["meets_target_aspect_ratio"] != expected["meets_target_aspect_ratio"]:
        raise ValidationError("image_result.meets_target_aspect_ratio does not match the pixel dimensions")


def _positive_dimension(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
