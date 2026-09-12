from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .deliverable_naming import LEGACY_STAGE2_IMAGE_PDF_REL, existing_stage2_image_pdf_rel
from .json_io import read_json, write_json
from .state import read_state
from .time_utils import now_iso
from .validation import ValidationError


CANVA_TASKS_REL = Path("_state") / "工具任务" / "canva"
STAGE1_CONTENT_REL = Path("_state") / "阶段1" / "content.json"
STAGE1_TRANSCRIPT_REL = Path("阶段1_规划确认") / "每页干净逐字稿.md"
STAGE1_PLAN_REL = Path("阶段1_规划确认") / "页面规划.md"
STAGE2_PDF_REL = Path(LEGACY_STAGE2_IMAGE_PDF_REL)
STAGE2_IMAGES_REL = Path("阶段2_图片版PPT") / "img"


def create_canva_task_brief(
    run_dir: str | Path,
    *,
    task_id: str | None = None,
    trigger: str = "/canva",
) -> dict[str, Any]:
    """Create a stage-external Canva task brief without mutating project stage state."""

    root = Path(run_dir)
    state_before = read_state(root)
    content_path = root / STAGE1_CONTENT_REL
    stage2_pdf_rel = existing_stage2_image_pdf_rel(root, state_before)
    stage2_pdf = root / stage2_pdf_rel if stage2_pdf_rel else root / STAGE2_PDF_REL

    if not content_path.exists():
        raise ValidationError("stage1 content.json is required before creating a Canva task brief")
    if not stage2_pdf.exists():
        raise ValidationError("stage2 image PDF is required before creating a Canva task brief")

    content = read_json(content_path)
    slides = _reference_slides(root, content)
    if not slides:
        raise ValidationError("stage1 content.json must contain at least one slide")

    task_id = _normal_task_id(task_id) if task_id else _default_task_id()
    task_dir = root / CANVA_TASKS_REL / task_id
    if task_dir.exists():
        raise ValidationError(f"Canva task already exists: {task_id}")

    created_at = now_iso()
    warnings = []
    if not state_before.get("confirmed", {}).get("stage2_image_deck"):
        warnings.append("stage2_image_deck is not confirmed; use this Canva brief as draft support only")

    references = {
        "stage1_content": _posix(STAGE1_CONTENT_REL),
        "stage1_clean_transcript": _posix(STAGE1_TRANSCRIPT_REL),
        "stage1_page_plan": _posix(STAGE1_PLAN_REL),
        "stage2_image_deck_pdf": stage2_pdf_rel or _posix(STAGE2_PDF_REL),
        "stage2_images_dir": _posix(STAGE2_IMAGES_REL),
    }
    task = {
        "schema_version": "1.0",
        "task_id": task_id,
        "task_type": "canva_auxiliary_edit",
        "project_name": state_before["project_name"],
        "run_dir": state_before["run_dir"],
        "trigger": trigger,
        "status": "brief_ready",
        "created_at": created_at,
        "stage_boundary": {
            "stage_external": True,
            "not_stage3": True,
            "does_not_change_project_stage": True,
            "must_not_write_stage3_decisions": True,
        },
        "references": references,
        "workflow": [
            "Import the PPT/PDF into Canva with the Canva plugin when available, otherwise ask the user to upload it manually.",
            "Ask the user to run Magic Layers manually in Canva and return the edit link.",
            "Use the Canva plugin to batch-fix copy and supported text styling after the link is returned.",
        ],
        "warnings": warnings,
    }
    reference_text = {
        "schema_version": "1.0",
        "task_id": task_id,
        "project_name": state_before["project_name"],
        "source": _posix(STAGE1_CONTENT_REL),
        "visual_reference": {
            "stage2_pdf": stage2_pdf_rel or _posix(STAGE2_PDF_REL),
            "stage2_images_dir": _posix(STAGE2_IMAGES_REL),
        },
        "slides": slides,
        "created_at": created_at,
    }
    import_attempt = {
        "schema_version": "1.0",
        "task_id": task_id,
        "status": "not_attempted",
        "notes": "Canva import is performed by the Canva plugin in conversation, not by this local runtime command.",
        "created_at": created_at,
    }
    manual_todos = "\n".join(
        [
            "# Canva 人工待处理项",
            "",
            "此文件用于记录 Canva 插件无法处理、需要用户在 Canva 手动修改的事项。",
            "",
            "- 待用户手动执行 Magic Layers。",
            "- 字体族、背景、复杂形状、加页删页重排等插件不支持事项在执行中补充。",
            "",
        ]
    )

    write_json(task_dir / "task.json", task)
    write_json(task_dir / "reference_text_by_slide.json", reference_text)
    write_json(task_dir / "import_attempt.json", import_attempt)
    (task_dir / "batch_edit_log.jsonl").write_text("", encoding="utf-8")
    (task_dir / "manual_todos.md").write_text(manual_todos, encoding="utf-8")

    state_after = read_state(root)
    if _stage_state_snapshot(state_after) != _stage_state_snapshot(state_before):
        raise ValidationError("create-canva-task-brief must not mutate project stage state")

    return {
        "status": "canva_task_brief_created",
        "task_id": task_id,
        "task_dir": _posix(CANVA_TASKS_REL / task_id),
        "task_json": _posix(CANVA_TASKS_REL / task_id / "task.json"),
        "reference_text_by_slide": _posix(CANVA_TASKS_REL / task_id / "reference_text_by_slide.json"),
        "warnings": warnings,
    }


def _reference_slides(root: Path, content: dict[str, Any]) -> list[dict[str, Any]]:
    raw_slides = content.get("slides")
    if not isinstance(raw_slides, list):
        raise ValidationError("stage1 content.json slides must be a list")

    slides = []
    for position, slide in enumerate(raw_slides, start=1):
        if not isinstance(slide, dict):
            raise ValidationError(f"stage1 content slide {position} must be an object")
        slide_index = slide.get("slide_index")
        if not isinstance(slide_index, int) or slide_index <= 0:
            raise ValidationError(f"stage1 content slide {position} requires positive slide_index")
        final_visible_text = slide.get("final_visible_text")
        if not isinstance(final_visible_text, list) or not all(isinstance(item, str) for item in final_visible_text):
            raise ValidationError(f"stage1 content slide {slide_index} final_visible_text must be a string list")
        image_rel = STAGE2_IMAGES_REL / f"slide_{slide_index:03d}.png"
        record = {
            "slide_index": slide_index,
            "title": str(slide.get("title") or ""),
            "page_type": str(slide.get("page_type") or ""),
            "purpose": str(slide.get("purpose") or ""),
            "final_visible_text": final_visible_text,
            "stage2_image": _posix(image_rel) if (root / image_rel).exists() else None,
        }
        slides.append(record)
    return sorted(slides, key=lambda item: item["slide_index"])


def _normal_task_id(value: str) -> str:
    task_id = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", task_id):
        raise ValidationError("Canva task id may only contain letters, numbers, underscore, or hyphen")
    return task_id


def _default_task_id() -> str:
    return "canva_" + re.sub(r"[^0-9]", "", now_iso())[:14]


def _stage_state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_stage": state.get("current_stage"),
        "status": state.get("status"),
        "required_actor": state.get("required_actor"),
        "confirmed": state.get("confirmed"),
        "quality": state.get("quality"),
        "stage3_locked_presentation_source": state.get("stage3_locked_presentation_source"),
        "last_decision_id": state.get("last_decision_id"),
    }


def _posix(path: str | Path) -> str:
    return Path(path).as_posix()
