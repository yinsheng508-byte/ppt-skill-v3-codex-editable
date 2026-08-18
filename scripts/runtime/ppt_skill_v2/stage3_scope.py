from __future__ import annotations

from typing import Any

from .validation import ValidationError


SAMPLE_SCOPE_MODE = "sample_slide_indices"


def stage3_scope_slide_indices(state: dict[str, Any]) -> list[int] | None:
    scope = state.get("stage3_reopen_scope")
    if not isinstance(scope, dict):
        return None
    mode = scope.get("mode")
    if mode != SAMPLE_SCOPE_MODE:
        return None
    raw_indices = scope.get("slide_indices")
    if not isinstance(raw_indices, list) or not raw_indices:
        raise ValidationError("stage3_reopen_scope.slide_indices must be a non-empty list")
    indices: list[int] = []
    for position, item in enumerate(raw_indices, start=1):
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValidationError(f"stage3_reopen_scope.slide_indices[{position}] must be a positive integer")
        if item not in indices:
            indices.append(item)
    return indices


def apply_stage3_scope(
    asset: dict[str, Any],
    state: dict[str, Any],
    label: str,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    indices = stage3_scope_slide_indices(state)
    if indices is None:
        return asset
    slides = asset.get("slides")
    if not isinstance(slides, list):
        raise ValidationError(f"{label}.slides must be a list before applying stage3 sample scope")
    by_index: dict[int, dict[str, Any]] = {}
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_index = slide.get("slide_index")
        if isinstance(slide_index, int):
            by_index[slide_index] = slide
    missing = [slide_index for slide_index in indices if slide_index not in by_index]
    if missing:
        raise ValidationError(
            f"{label} missing stage3 scoped slide(s): " + ", ".join(str(slide_index) for slide_index in missing)
        )
    if strict:
        extras = sorted(slide_index for slide_index in by_index if slide_index not in set(indices))
        if extras:
            raise ValidationError(
                f"{label} contains slide(s) outside stage3 sample scope: "
                + ", ".join(str(slide_index) for slide_index in extras)
            )
    scoped = dict(asset)
    scoped["slides"] = [by_index[slide_index] for slide_index in indices]
    return scoped


def stage3_scope_summary(state: dict[str, Any]) -> dict[str, Any] | None:
    indices = stage3_scope_slide_indices(state)
    if indices is None:
        return None
    return {
        "mode": SAMPLE_SCOPE_MODE,
        "slide_indices": indices,
        "slides_count": len(indices),
    }
