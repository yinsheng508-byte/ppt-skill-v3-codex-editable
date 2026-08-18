from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .validation import ValidationError


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
    if width_px <= 0 or height_px <= 0:
        return False
    return abs((width_px / height_px) - (16 / 9)) <= 0.0015
