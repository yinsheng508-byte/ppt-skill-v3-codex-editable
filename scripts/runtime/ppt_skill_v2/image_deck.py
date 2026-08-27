from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .deliverable_naming import LEGACY_STAGE2_IMAGE_PDF_REL, project_deliverable_relpaths
from .dev_mode import require_dev_fixture_enabled
from .events import append_event
from .json_io import read_json, write_json
from .planning_assets import content_path, deck_style_path, layout_intent_path, slide_prompt_briefs_path
from .stage1_plan import load_stage1_slides
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .time_utils import now_iso
from .validation import ValidationError, validate_image_result, validate_stage1_plan


PDF_CANVAS_SIZE = (1600, 900)
PDF_RESOLUTION_DPI = 120
STAGE2_PDF_REL_PATH = LEGACY_STAGE2_IMAGE_PDF_REL


def build_image_deck(run_dir: str | Path, *, allow_dev_fixture: bool = False) -> Path:
    if allow_dev_fixture:
        require_dev_fixture_enabled()

    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage2":
        raise ValidationError("image deck can only be built in stage2")
    if not state["confirmed"].get("stage2_cover_style"):
        raise ValidationError("image deck requires approved cover style")

    plan = validate_stage1_plan(load_stage1_slides(root))
    results = [_load_stage2_result(root, slide["slide_index"], allow_dev_fixture) for slide in plan["slides"]]

    pages = [_pdf_page_from_image(root / result["image_path"]) for result in results]
    if not pages:
        raise ValidationError("image deck requires at least one stage2 image")

    relpaths = project_deliverable_relpaths(root, state=state)
    deck_rel = relpaths["stage2_image_deck"]
    deck_path = root / deck_rel
    deck_path.parent.mkdir(parents=True, exist_ok=True)
    first_page, *rest_pages = pages
    try:
        first_page.save(deck_path, "PDF", save_all=True, append_images=rest_pages, resolution=PDF_RESOLUTION_DPI)
    finally:
        for page in pages:
            page.close()

    manifest = {
        "schema_version": "2.0",
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "artifact_type": "stage2_image_pdf",
        "output_format": "pdf",
        "deck_path": deck_rel,
        "pdf_path": deck_rel,
        "legacy_pdf_path": STAGE2_PDF_REL_PATH,
        "slides_count": len(results),
        "page_size": {"width_px": PDF_CANVAS_SIZE[0], "height_px": PDF_CANVAS_SIZE[1], "resolution_dpi": PDF_RESOLUTION_DPI},
        "images": [result["image_path"] for result in results],
        "assets": {
            "content": str(content_path(root).relative_to(root)),
            "slide_prompt_briefs": str(slide_prompt_briefs_path(root).relative_to(root)),
            "deck_style": str(deck_style_path(root).relative_to(root)),
            "layout_intent": str(layout_intent_path(root).relative_to(root)),
            "final_prompts_dir": "_state/阶段2/final_prompts",
        },
        "dev_fixture_used": any(result["fixture"] for result in results),
        "created_at": now_iso(),
    }
    write_json(root / "_state" / "阶段2" / "manifests" / "image_deck.json", manifest)

    state["status"] = "waiting_user_confirmation"
    state["required_actor"] = "user"
    state.setdefault("user_artifacts", {})["stage2_image_deck"] = deck_rel
    state.setdefault("expected_user_paths", {})["stage2_image_deck"] = deck_rel
    state["quality"]["stage2"] = "pending_user_review"
    state["next_required_action"] = "等待用户确认阶段2图片版 PDF"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(root, "image_deck_built", "runtime", slides_count=len(results), allow_dev_fixture=allow_dev_fixture)
    return deck_path


def _pdf_page_from_image(image_path: Path) -> Image.Image:
    with Image.open(image_path) as original:
        image = ImageOps.exif_transpose(original)
        if image.mode == "RGBA" or "transparency" in image.info:
            rgba = image.convert("RGBA")
            source = Image.new("RGB", rgba.size, "white")
            source.paste(rgba, mask=rgba.getchannel("A"))
        else:
            source = image.convert("RGB")

        fitted = ImageOps.contain(source, PDF_CANVAS_SIZE, Image.Resampling.LANCZOS)
        page = Image.new("RGB", PDF_CANVAS_SIZE, "white")
        offset = ((PDF_CANVAS_SIZE[0] - fitted.width) // 2, (PDF_CANVAS_SIZE[1] - fitted.height) // 2)
        page.paste(fitted, offset)
        return page


def _load_stage2_result(root: Path, slide_index: int, allow_dev_fixture: bool) -> dict[str, Any]:
    result_path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
    if not result_path.exists():
        raise ValidationError(f"missing stage2 image result for slide {slide_index}")
    result = validate_image_result(read_json(result_path), production=not allow_dev_fixture)
    image_path = root / result["image_path"]
    if not image_path.exists():
        raise FileNotFoundError(f"registered image does not exist: {image_path}")
    if result["stage"] != "stage2":
        raise ValidationError("image deck can only use stage2 image results")
    if result.get("purpose") != "full_slide":
        raise ValidationError("image deck can only use full_slide image results")
    return result
