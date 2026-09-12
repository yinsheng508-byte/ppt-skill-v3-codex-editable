from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .image_geometry import read_image_dimensions
from .time_utils import now_iso
from .validation import ValidationError


CANONICAL_POLICIES = {"preserve_api_raster", "normalize_at_stage2"}
CANONICAL_METHODS = {"fit_center_crop", "contain_pad"}


def parse_size(size: str) -> tuple[int, int]:
    parts = size.lower().split("x", 1)
    if len(parts) != 2:
        raise ValidationError("canonical image size must use WIDTHxHEIGHT format")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as exc:
        raise ValidationError("canonical image size must contain integer width and height") from exc
    if width <= 0 or height <= 0:
        raise ValidationError("canonical image size must be positive")
    return width, height


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonicalize_image(
    source: str | Path,
    target: str | Path,
    *,
    target_size: tuple[int, int],
    method: str,
    pad_color: str = "white",
) -> dict[str, Any]:
    if method not in CANONICAL_METHODS:
        raise ValidationError(f"unsupported canonical image method: {method}")
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_dimensions = read_image_dimensions(source_path)
    with Image.open(source_path) as image:
        rgb = image.convert("RGB")
        if method == "fit_center_crop":
            output = ImageOps.fit(rgb, target_size, method=Image.Resampling.LANCZOS)
            operation = "center_crop"
        else:
            contained = ImageOps.contain(rgb, target_size, method=Image.Resampling.LANCZOS)
            output = Image.new("RGB", target_size, pad_color)
            offset = ((target_size[0] - contained.width) // 2, (target_size[1] - contained.height) // 2)
            output.paste(contained, offset)
            operation = "contain_pad"
        output.save(target_path, format="PNG")
    output_dimensions = read_image_dimensions(target_path)
    return {
        "schema_version": "1.0",
        "type": "canonical_image_postprocess",
        "method": method,
        "operation": operation,
        "source": {
            "path": str(source_path),
            "sha256": sha256_file(source_path),
            **source_dimensions,
        },
        "output": {
            "path": str(target_path),
            "sha256": sha256_file(target_path),
            **output_dimensions,
        },
        "target_size": {"width_px": target_size[0], "height_px": target_size[1]},
        "created_at": now_iso(),
    }
