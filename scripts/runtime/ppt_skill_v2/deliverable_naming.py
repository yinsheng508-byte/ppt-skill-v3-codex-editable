from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SEPARATOR = "｜"
MAX_TOPIC_CHARS = 80

LEGACY_STAGE2_IMAGE_PDF_REL = "阶段2_图片版PPT/pdf/图片版PPT.pdf"
LEGACY_STAGE3_EDITABLE_PPTX_REL = "阶段3_可编辑PPT/ppt/可编辑PPT.pptx"
LEGACY_STAGE4_MARKDOWN_REL = "阶段4_演讲稿输出/演讲逐字稿.md"
LEGACY_STAGE4_DOCX_REL = "阶段4_演讲稿输出/docx/演讲逐字稿.docx"
LEGACY_STAGE4_PDF_REL = "阶段4_演讲稿输出/pdf/演讲逐字稿.pdf"

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WHITESPACE = re.compile(r"\s+")
_GENERIC_COVER_TITLES = {
    "cover",
    "title",
    "title page",
    "untitled",
    "封面",
    "首页",
    "标题页",
    "题目",
    "主题",
    "主标题",
    "未命名",
}


def project_deliverable_relpaths(
    run_dir: str | Path,
    *,
    state: dict[str, Any] | None = None,
    script: dict[str, Any] | None = None,
) -> dict[str, str]:
    topic = deliverable_topic(run_dir, state=state, script=script)
    return {
        "stage2_image_deck": f"阶段2_图片版PPT/pdf/{topic}{SEPARATOR}图片版PPT.pdf",
        "stage3_editable_deck": f"阶段3_可编辑PPT/ppt/{topic}{SEPARATOR}可编辑PPT.pptx",
        "stage4_speaker_script": f"阶段4_演讲稿输出/{topic}{SEPARATOR}逐字稿.md",
        "stage4_speaker_script_docx": f"阶段4_演讲稿输出/docx/{topic}{SEPARATOR}逐字稿.docx",
        "stage4_speaker_script_pdf": f"阶段4_演讲稿输出/pdf/{topic}{SEPARATOR}逐字稿.pdf",
    }


def deliverable_topic(
    run_dir: str | Path,
    *,
    state: dict[str, Any] | None = None,
    script: dict[str, Any] | None = None,
) -> str:
    root = Path(run_dir)
    candidates: list[Any] = []
    content = _read_json(root / "_state" / "阶段1" / "content.json")
    candidates.extend(_content_topic_candidates(content))
    stage1_slides = _read_json(root / "_state" / "阶段1" / "slides.json")
    candidates.extend(_stage1_slide_topic_candidates(stage1_slides))
    if isinstance(script, dict):
        talk = script.get("talk")
        if isinstance(talk, dict):
            candidates.append(talk.get("title"))
    if isinstance(state, dict):
        candidates.append(state.get("project_name"))
    candidates.append(root.name)

    for candidate in candidates:
        topic = sanitize_deliverable_topic(candidate)
        if topic and not _is_generic_topic(topic):
            return topic
    for candidate in candidates:
        topic = sanitize_deliverable_topic(candidate)
        if topic:
            return topic
    return "未命名主题"


def sanitize_deliverable_topic(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace(SEPARATOR, " ")
    text = _ILLEGAL_FILENAME_CHARS.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip(" ._-")
    if text in {"", ".", ".."}:
        return ""
    if len(text) > MAX_TOPIC_CHARS:
        text = text[:MAX_TOPIC_CHARS].rstrip(" ._-")
    return text


def existing_stage2_image_pdf_rel(run_dir: str | Path, state: dict[str, Any] | None = None) -> str | None:
    root = Path(run_dir)
    return _first_existing_relpath(
        root,
        [
            _state_path(state, "user_artifacts", "stage2_image_deck"),
            _state_path(state, "expected_user_paths", "stage2_image_deck"),
            project_deliverable_relpaths(root, state=state)["stage2_image_deck"],
            LEGACY_STAGE2_IMAGE_PDF_REL,
            *[str(path.relative_to(root)) for path in sorted((root / "阶段2_图片版PPT" / "pdf").glob(f"*{SEPARATOR}图片版PPT.pdf"))],
        ],
    )


def existing_stage3_editable_deck_rel(run_dir: str | Path, state: dict[str, Any] | None = None) -> str | None:
    root = Path(run_dir)
    manifest = _read_json(root / "_state" / "阶段3" / "manifests" / "editable_deck.json")
    return _first_existing_relpath(
        root,
        [
            _mapping_value(manifest, "deck_path"),
            _state_path(state, "user_artifacts", "stage3_editable_deck"),
            _state_path(state, "expected_user_paths", "stage3_editable_deck"),
            project_deliverable_relpaths(root, state=state)["stage3_editable_deck"],
            LEGACY_STAGE3_EDITABLE_PPTX_REL,
            *[str(path.relative_to(root)) for path in sorted((root / "阶段3_可编辑PPT" / "ppt").glob(f"*{SEPARATOR}可编辑PPT.pptx"))],
        ],
    )


def existing_stage4_output_rel(
    run_dir: str | Path,
    artifact_key: str,
    *,
    state: dict[str, Any] | None = None,
    script: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> str | None:
    root = Path(run_dir)
    if artifact_key not in {"stage4_speaker_script", "stage4_speaker_script_docx", "stage4_speaker_script_pdf"}:
        raise ValueError(f"unsupported stage4 artifact key: {artifact_key}")
    if manifest is None:
        manifest = _read_json(root / "_state" / "阶段4" / "speaker_script_manifest.json")
    relpaths = project_deliverable_relpaths(root, state=state, script=script)
    legacy = {
        "stage4_speaker_script": LEGACY_STAGE4_MARKDOWN_REL,
        "stage4_speaker_script_docx": LEGACY_STAGE4_DOCX_REL,
        "stage4_speaker_script_pdf": LEGACY_STAGE4_PDF_REL,
    }
    globs = {
        "stage4_speaker_script": root / "阶段4_演讲稿输出",
        "stage4_speaker_script_docx": root / "阶段4_演讲稿输出" / "docx",
        "stage4_speaker_script_pdf": root / "阶段4_演讲稿输出" / "pdf",
    }
    suffixes = {
        "stage4_speaker_script": ".md",
        "stage4_speaker_script_docx": ".docx",
        "stage4_speaker_script_pdf": ".pdf",
    }
    return _first_existing_relpath(
        root,
        [
            _manifest_file_path(manifest, suffixes[artifact_key]),
            _state_path(state, "user_artifacts", artifact_key),
            _state_path(state, "expected_user_paths", artifact_key),
            relpaths[artifact_key],
            legacy[artifact_key],
            *[str(path.relative_to(root)) for path in sorted(globs[artifact_key].glob(f"*{SEPARATOR}逐字稿{suffixes[artifact_key]}"))],
        ],
    )


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _content_topic_candidates(content: Any) -> list[Any]:
    if not isinstance(content, dict):
        return []
    slides = content.get("slides")
    candidates: list[Any] = []
    first_slide = _first_slide(slides)
    if isinstance(first_slide, dict):
        visible_text = first_slide.get("final_visible_text")
        if isinstance(visible_text, list):
            candidates.extend(item for item in visible_text if isinstance(item, str) and item.strip())
        candidates.append(first_slide.get("title"))
    candidates.append(content.get("deck_title"))
    return candidates


def _stage1_slide_topic_candidates(slides_doc: Any) -> list[Any]:
    if not isinstance(slides_doc, dict):
        return []
    first_slide = _first_slide(slides_doc.get("slides"))
    if not isinstance(first_slide, dict):
        return []
    return [first_slide.get("title"), first_slide.get("core_content")]


def _first_slide(slides: Any) -> dict[str, Any] | None:
    if not isinstance(slides, list):
        return None
    valid = [slide for slide in slides if isinstance(slide, dict)]
    if not valid:
        return None
    return sorted(valid, key=lambda slide: slide.get("slide_index") if isinstance(slide.get("slide_index"), int) else 10**9)[0]


def _is_generic_topic(topic: str) -> bool:
    return topic.strip().lower() in _GENERIC_COVER_TITLES


def _mapping_value(mapping: Any, key: str) -> str | None:
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _state_path(state: dict[str, Any] | None, section: str, key: str) -> str | None:
    if not isinstance(state, dict):
        return None
    return _mapping_value(state.get(section), key)


def _manifest_file_path(manifest: Any, suffix: str) -> str | None:
    if not isinstance(manifest, dict):
        return None
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    for file_info in files:
        path = _mapping_value(file_info, "path")
        if path and path.endswith(suffix):
            return path
    return None


def _first_existing_relpath(root: Path, candidates: list[str | None]) -> str | None:
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip() or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        actual = path if path.is_absolute() else root / path
        if actual.exists():
            try:
                return str(actual.relative_to(root))
            except ValueError:
                return str(actual)
    return None
