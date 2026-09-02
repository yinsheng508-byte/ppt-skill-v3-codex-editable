from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .deliverable_naming import (
    SEPARATOR,
    deliverable_topic,
    existing_stage2_image_pdf_rel,
    existing_stage3_editable_deck_rel,
    existing_stage4_lesson_plan_output_rel,
    existing_stage4_output_rel,
)
from .state import read_state
from .time_utils import now_iso
from .validation import ValidationError


def organize_deliverables(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    state = read_state(root)
    topic = deliverable_topic(root, state=state)
    target_dir = root / topic
    if target_dir.exists() and not target_dir.is_dir():
        raise ValidationError(f"delivery target exists but is not a directory: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
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
        existing_stage3_editable_deck_rel(root, state),
        target_dir / f"{topic}{SEPARATOR}可编辑PPT.pptx",
        "stage3_editable_deck",
        copied,
        skipped,
    )

    _copy_optional_rel(
        root,
        existing_stage4_output_rel(root, "stage4_speaker_script_docx", state=state),
        target_dir / f"{topic}{SEPARATOR}逐字稿.docx",
        "stage4_speaker_script_docx",
        copied,
        skipped,
    )
    _copy_optional_rel(
        root,
        existing_stage4_output_rel(root, "stage4_speaker_script_pdf", state=state),
        target_dir / f"{topic}{SEPARATOR}逐字稿.pdf",
        "stage4_speaker_script_pdf",
        copied,
        skipped,
    )

    _copy_optional_rel(
        root,
        existing_stage4_lesson_plan_output_rel(root, "stage4_lesson_plan_docx", state=state),
        target_dir / f"{topic}{SEPARATOR}教案设计.docx",
        "stage4_lesson_plan_docx",
        copied,
        skipped,
    )
    _copy_optional_rel(
        root,
        existing_stage4_lesson_plan_output_rel(root, "stage4_lesson_plan_pdf", state=state),
        target_dir / f"{topic}{SEPARATOR}教案设计.pdf",
        "stage4_lesson_plan_pdf",
        copied,
        skipped,
    )

    return {
        "schema_version": "1.0",
        "status": "organized",
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "topic": topic,
        "organized_dir": _relative(root, target_dir),
        "copied": copied,
        "skipped": skipped,
        "created_at": now_iso(),
    }


def _copy_stage1_clean_transcript(
    root: Path,
    target_dir: Path,
    copied: list[dict[str, str]],
    skipped: list[dict[str, str]],
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
    copied: list[dict[str, str]],
    skipped: list[dict[str, str]],
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
    copied: list[dict[str, str]],
    skipped: list[dict[str, str]],
) -> None:
    if not source_rel:
        skipped.append({"kind": kind, "reason": "source_missing"})
        return
    source_path = Path(source_rel)
    source = source_path if source_path.is_absolute() else root / source_path
    if not source.exists():
        skipped.append({"kind": kind, "reason": "source_missing", "source": source_rel})
        return
    _copy_file(root, source, target, kind, copied)


def _copy_file(root: Path, source: Path, target: Path, kind: str, copied: list[dict[str, str]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if _same_file(source, target):
        copied.append({"kind": kind, "source": _relative(root, source), "target": _relative(root, target), "status": "same_file"})
        return
    shutil.copy2(source, target)
    copied.append({"kind": kind, "source": _relative(root, source), "target": _relative(root, target), "status": "copied"})


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
