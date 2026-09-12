from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .deliverable_naming import (
    SEPARATOR,
    deliverable_topic,
    existing_stage2_image_pdf_rel,
    existing_stage3_lesson_plan_output_rel,
    existing_stage3_output_rel,
    sanitize_deliverable_topic,
)
from .json_io import write_json
from .pdf_page_images import PdfPageImageError, PdfPageImageUnavailable, render_pdf_pages_to_png
from .state import read_state
from .time_utils import now_iso
from .validation import ValidationError


def organize_deliverables(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    state = read_state(root)
    topic = _organized_topic(root, state)
    target_dir = root / "阶段4_文件整理交付" / topic
    if target_dir.exists() and not target_dir.is_dir():
        raise ValidationError(f"delivery target exists but is not a directory: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rendered: list[dict[str, Any]] = []
    _copy_stage1_clean_transcript(root, target_dir, copied, skipped)

    _copy_stage2_images(root, target_dir, copied, skipped)
    _copy_optional_rel(
        root,
        existing_stage2_image_pdf_rel(root, state),
        target_dir / f"{topic}{SEPARATOR}图片版PPT.pdf",
        "stage2_image_deck",
        copied,
        skipped,
    )

    _copy_optional_rel(
        root,
        existing_stage3_output_rel(root, "stage3_speaker_script_docx", state=state),
        target_dir / f"{topic}{SEPARATOR}逐字稿.docx",
        "stage3_speaker_script_docx",
        copied,
        skipped,
    )
    speaker_pdf = _copy_optional_rel(
        root,
        existing_stage3_output_rel(root, "stage3_speaker_script_pdf", state=state),
        target_dir / f"{topic}{SEPARATOR}逐字稿.pdf",
        "stage3_speaker_script_pdf",
        copied,
        skipped,
    )
    if speaker_pdf:
        _render_optional_pdf_images(
            root,
            speaker_pdf,
            target_dir / "逐字稿图片",
            "stage3_speaker_script_pdf_images",
            rendered,
            skipped,
        )

    _copy_optional_rel(
        root,
        existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_docx", state=state),
        target_dir / f"{topic}{SEPARATOR}教案设计.docx",
        "stage3_lesson_plan_docx",
        copied,
        skipped,
    )
    lesson_pdf = _copy_optional_rel(
        root,
        existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_pdf", state=state),
        target_dir / f"{topic}{SEPARATOR}教案设计.pdf",
        "stage3_lesson_plan_pdf",
        copied,
        skipped,
    )
    if lesson_pdf:
        _render_optional_pdf_images(
            root,
            lesson_pdf,
            target_dir / "教案设计图片",
            "stage3_lesson_plan_pdf_images",
            rendered,
            skipped,
        )

    result = {
        "schema_version": "1.0",
        "status": "organized",
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "topic": topic,
        "organized_dir": _relative(root, target_dir),
        "copied": copied,
        "rendered": rendered,
        "skipped": skipped,
        "created_at": now_iso(),
    }
    _write_stage4_summary(root, result)
    return result


def _organized_topic(root: Path, state: dict[str, Any]) -> str:
    stage3_topic = _topic_from_stage3_outputs(root, state)
    if stage3_topic:
        return stage3_topic
    return deliverable_topic(root, state=state)


def _topic_from_stage3_outputs(root: Path, state: dict[str, Any]) -> str:
    candidates = [
        existing_stage3_output_rel(root, "stage3_speaker_script_pdf", state=state),
        existing_stage3_output_rel(root, "stage3_speaker_script_docx", state=state),
        existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_pdf", state=state),
        existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_docx", state=state),
    ]
    for relpath in candidates:
        if not relpath:
            continue
        filename = Path(relpath).name
        if SEPARATOR not in filename:
            continue
        topic = sanitize_deliverable_topic(filename.split(SEPARATOR, 1)[0])
        if topic and not _is_overly_generic_topic(topic):
            return topic
    return ""


def _is_overly_generic_topic(topic: str) -> bool:
    compact = topic.replace(" ", "")
    if compact in {"八年级上册历史", "七年级上册历史", "九年级上册历史", "八上历史", "七上历史", "九上历史"}:
        return True
    if compact in {"第1课", "第2课", "第3课", "第4课", "第5课", "第6课", "第7课", "第8课"}:
        return True
    return compact.startswith(("第一单元", "第二单元", "第三单元", "第四单元"))


def _copy_stage1_clean_transcript(
    root: Path,
    target_dir: Path,
    copied: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    rel = "阶段1_规划确认/每页干净逐字稿.md"
    source = root / rel
    if not source.exists():
        skipped.append({"kind": "stage1_clean_transcript", "reason": "source_missing"})
        return
    _copy_file(root, source, target_dir / "每页干净逐字稿.md", "stage1_clean_transcript", copied)


def _copy_stage2_images(
    root: Path,
    target_dir: Path,
    copied: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    image_dir = root / "阶段2_图片版PPT" / "img"
    images = sorted(path for path in image_dir.glob("slide_*.png") if path.is_file())
    if not images:
        skipped.append({"kind": "stage2_images", "reason": "source_missing"})
        return
    target_image_dir = target_dir / "图片素材"
    for source in images:
        _copy_file(root, source, target_image_dir / source.name, "stage2_image", copied)


def _copy_optional_rel(
    root: Path,
    source_rel: str | None,
    target: Path,
    kind: str,
    copied: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> Path | None:
    if not source_rel:
        skipped.append({"kind": kind, "reason": "source_missing"})
        return None
    source_path = Path(source_rel)
    source = source_path if source_path.is_absolute() else root / source_path
    if not source.exists():
        skipped.append({"kind": kind, "reason": "source_missing", "source": source_rel})
        return None
    return _copy_file(root, source, target, kind, copied)


def _copy_file(root: Path, source: Path, target: Path, kind: str, copied: list[dict[str, Any]]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if _same_file(source, target):
        copied.append({"kind": kind, "source": _relative(root, source), "target": _relative(root, target), "status": "same_file"})
        return target
    shutil.copy2(source, target)
    copied.append({"kind": kind, "source": _relative(root, source), "target": _relative(root, target), "status": "copied"})
    return target


def _render_optional_pdf_images(
    root: Path,
    source_pdf: Path,
    target_dir: Path,
    kind: str,
    rendered: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    try:
        result = render_pdf_pages_to_png(source_pdf, target_dir)
    except PdfPageImageUnavailable as exc:
        skipped.append({"kind": kind, "reason": "pdftoppm_missing", "source": _relative(root, source_pdf), "error": str(exc)})
        return
    except PdfPageImageError as exc:
        skipped.append({"kind": kind, "reason": "pdf_render_failed", "source": _relative(root, source_pdf), "error": str(exc)})
        return
    except FileNotFoundError as exc:
        skipped.append({"kind": kind, "reason": "source_missing", "source": _relative(root, source_pdf), "error": str(exc)})
        return
    rendered.append(
        {
            "kind": kind,
            "source": _relative(root, source_pdf),
            "target_dir": _relative(root, target_dir),
            "render_dpi": result["render_dpi"],
            "render_scale": result["render_scale"],
            "tool": result["tool"],
            "tool_path": result["tool_path"],
            "pages": result["pages"],
            "images": [
                {
                    "page": image["page"],
                    "path": _relative(root, Path(image["path"])),
                    "width_px": image["width_px"],
                    "height_px": image["height_px"],
                    "sha256": image["sha256"],
                }
                for image in result["images"]
            ],
        }
    )


def _same_file(source: Path, target: Path) -> bool:
    if not target.exists():
        return False
    try:
        return source.samefile(target)
    except OSError:
        return False


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _write_stage4_summary(root: Path, result: dict[str, Any]) -> None:
    stage4_state = root / "_state" / "阶段4"
    stage4_state.mkdir(parents=True, exist_ok=True)
    write_json(stage4_state / "organize_summary.json", result)
    write_json(stage4_state / "deliverable_manifest.json", result)
