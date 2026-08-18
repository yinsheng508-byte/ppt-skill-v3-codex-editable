from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .editable_coordinate_plan import load_editable_coordinate_plan
from .events import append_event
from .json_io import write_json


PREVIEW_REL_DIR = "阶段3_可编辑PPT/坐标复刻预览"
TEXT_EFFECT_REL_DIR = "阶段3_可编辑PPT/文字效果预演"
MANIFEST_REL_DIR = "_state/阶段3/coordinate_preview"


def coordinate_preview_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / PREVIEW_REL_DIR


def build_coordinate_preview(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    plan = load_editable_coordinate_plan(root)
    output_dir = coordinate_preview_dir(root)
    text_effect_dir = root / TEXT_EFFECT_REL_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    text_effect_dir.mkdir(parents=True, exist_ok=True)
    preview_paths: list[str] = []
    text_effect_paths: list[str] = []
    for slide in plan["slides"]:
        preview_paths.append(_render_slide_preview(root, output_dir, slide))
        text_effect_paths.append(_render_text_effect_preview(root, text_effect_dir, slide))
    contact_sheet = _render_contact_sheet(root, output_dir, preview_paths)
    text_effect_contact_sheet = _render_contact_sheet(root, text_effect_dir, text_effect_paths)
    index_path = output_dir / "坐标复刻预览.md"
    _write_index(root, index_path, preview_paths, contact_sheet)
    text_effect_index_path = text_effect_dir / "文字效果预演.md"
    _write_text_effect_index(root, text_effect_index_path, text_effect_paths, text_effect_contact_sheet)
    manifest = {
        "schema_version": "1.0",
        "preview_dir": PREVIEW_REL_DIR,
        "contact_sheet": contact_sheet,
        "text_effect_preview_dir": TEXT_EFFECT_REL_DIR,
        "text_effect_contact_sheet": text_effect_contact_sheet,
        "slides": [{"slide_index": slide["slide_index"], "preview": path} for slide, path in zip(plan["slides"], preview_paths, strict=True)],
        "text_effect_slides": [
            {"slide_index": slide["slide_index"], "preview": path}
            for slide, path in zip(plan["slides"], text_effect_paths, strict=True)
        ],
        "index": str(index_path.relative_to(root)),
        "text_effect_index": str(text_effect_index_path.relative_to(root)),
    }
    manifest_path = root / MANIFEST_REL_DIR / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest["manifest"] = str(manifest_path.relative_to(root))
    write_json(manifest_path, manifest)
    append_event(root, "coordinate_preview_built", "runtime", slides_count=len(preview_paths))
    return manifest


def _render_slide_preview(root: Path, output_dir: Path, slide: dict[str, Any]) -> str:
    slide_index = slide["slide_index"]
    background = slide.get("stage3_background_image") or {}
    background_path = root / background.get("path", f"阶段3_可编辑PPT/img/background_{slide_index:03d}.png")
    with Image.open(background_path).convert("RGBA") as image:
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = ImageFont.load_default()
        for unit in slide.get("text_units", []):
            box = unit["box_px"]
            x0 = int(box["x"])
            y0 = int(box["y"])
            x1 = int(box["x"] + box["w"])
            y1 = int(box["y"] + box["h"])
            draw.rectangle([x0, y0, x1, y1], outline=(235, 64, 52, 230), width=max(2, image.width // 800))
            draw.rectangle([x0, y0, min(x1, x0 + 260), min(y1, y0 + 22)], fill=(235, 64, 52, 190))
            label = _unit_label(unit)
            draw.text((x0 + 4, y0 + 4), label, fill=(255, 255, 255, 255), font=font)
        combined = Image.alpha_composite(image, overlay).convert("RGB")
        output = output_dir / f"slide_{slide_index:03d}_coordinate_preview.png"
        combined.save(output)
    return str(output.relative_to(root))


def _render_text_effect_preview(root: Path, output_dir: Path, slide: dict[str, Any]) -> str:
    slide_index = slide["slide_index"]
    background = slide.get("stage3_background_image") or {}
    background_path = root / background.get("path", f"阶段3_可编辑PPT/img/background_{slide_index:03d}.png")
    with Image.open(background_path).convert("RGBA") as image:
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for element in slide.get("native_elements", []):
            if element.get("z_order") != "under_text":
                continue
            _draw_native_element(draw, element)
        for unit in slide.get("text_units", []):
            _draw_text_unit(draw, unit)
        for element in slide.get("native_elements", []):
            if element.get("z_order") != "over_text":
                continue
            _draw_native_element(draw, element)
        combined = Image.alpha_composite(image, overlay).convert("RGB")
        output = output_dir / f"slide_{slide_index:03d}_text_effect_preview.png"
        combined.save(output)
    return str(output.relative_to(root))


def _draw_native_element(draw: ImageDraw.ImageDraw, element: dict[str, Any]) -> None:
    box = element["box_px"]
    xy = [int(box["x"]), int(box["y"]), int(box["x"] + box["w"]), int(box["y"] + box["h"])]
    fill = _rgba(element.get("fill"), alpha=210)
    stroke = _rgba(element.get("stroke"), alpha=230)
    element_type = element.get("type")
    if element_type == "ellipse":
        draw.ellipse(xy, fill=fill, outline=stroke)
    elif element_type == "line":
        draw.line(xy, fill=stroke or fill or (20, 20, 20, 230), width=max(2, int(min(box["w"], box["h"]) or 2)))
    else:
        radius = max(4, min(int(box["h"] * 0.18), 18)) if element_type == "round_rect" else 0
        if radius:
            draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=stroke)
        else:
            draw.rectangle(xy, fill=fill, outline=stroke)


def _draw_text_unit(draw: ImageDraw.ImageDraw, unit: dict[str, Any]) -> None:
    box = unit["box_px"]
    font_info = unit.get("font", {})
    size_pt = float(font_info.get("target_font_size_pt", 12))
    font = _load_font(max(8, int(round(size_pt * 96 / 72))))
    color = _rgba(font_info.get("resolved_color"), alpha=255) or (20, 20, 20, 255)
    text = unit.get("display_text") or unit.get("text", "")
    paragraph = unit.get("paragraph", {})
    x = int(box["x"])
    y = int(box["y"])
    w = int(box["w"])
    h = int(box["h"])
    draw.rectangle([x, y, x + w, y + h], outline=(235, 64, 52, 90), width=1)
    align = _preview_align(paragraph.get("horizontal_align", "left"))
    spacing = max(2, int(size_pt * 0.25))
    draw.multiline_text((x, y), text, fill=color, font=font, spacing=spacing, align=align)


def _preview_align(value: Any) -> str:
    if value in {"left", "center", "right"}:
        return value
    return "left"


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Microsoft YaHei.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rgba(color: Any, *, alpha: int) -> tuple[int, int, int, int] | None:
    if not isinstance(color, str) or not color.startswith("#"):
        return None
    value = color[1:]
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        return None
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)
    except ValueError:
        return None


def _render_contact_sheet(root: Path, output_dir: Path, preview_paths: list[str]) -> str:
    images = [Image.open(root / path).convert("RGB") for path in preview_paths]
    try:
        thumb_width = 480
        thumbs = []
        for image in images:
            ratio = thumb_width / image.width
            thumb = image.resize((thumb_width, int(image.height * ratio)))
            thumbs.append(thumb)
        gap = 24
        sheet_width = thumb_width
        sheet_height = sum(thumb.height for thumb in thumbs) + gap * max(len(thumbs) - 1, 0)
        sheet = Image.new("RGB", (sheet_width, sheet_height), "white")
        y = 0
        for thumb in thumbs:
            sheet.paste(thumb, (0, y))
            y += thumb.height + gap
        output = output_dir / "contact_sheet.png"
        sheet.save(output)
        return str(output.relative_to(root))
    finally:
        for image in images:
            image.close()


def _write_index(root: Path, index_path: Path, preview_paths: list[str], contact_sheet: str) -> None:
    lines = [
        "# 阶段3文字坐标复刻预览",
        "",
        "请确认每个红框是否对应正确的文字对象、位置和大小；确认后才进入填字。",
        "",
        f"![contact_sheet]({contact_sheet})",
        "",
    ]
    for path in preview_paths:
        lines.extend([f"![{Path(path).stem}]({path})", ""])
    index_path.write_text("\n".join(lines), encoding="utf-8")


def _write_text_effect_index(root: Path, index_path: Path, preview_paths: list[str], contact_sheet: str) -> None:
    lines = [
        "# 阶段3文字效果预演",
        "",
        "请确认文字大小、换行、颜色和承载底形是否明显合理；这是填字前的轻量预演，不代表最终 PPT 渲染像素。",
        "",
        f"![contact_sheet]({contact_sheet})",
        "",
    ]
    for path in preview_paths:
        lines.extend([f"![{Path(path).stem}]({path})", ""])
    index_path.write_text("\n".join(lines), encoding="utf-8")


def _unit_label(unit: dict[str, Any]) -> str:
    font = unit.get("font", {}) if isinstance(unit.get("font"), dict) else {}
    size = font.get("target_font_size_pt", "")
    return f"{unit.get('text_unit_id', '')} {size}pt"
