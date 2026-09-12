from __future__ import annotations

from pathlib import Path
from typing import Any

from .json_io import read_json, write_json
from .materials import load_materials
from .paths import state_dir
from .file_hashing import file_sha256
from .state import read_state
from .time_utils import now_iso
from .validation import ValidationError, validate_education_context
from .education_context import infer_education_context


SCHEMA_VERSION = "1.0"
TEXTBOOK_MATERIAL_ROLES = {
    "primary_textbook",
    "teacher_reference",
    "exercise_reference",
    "sample_lesson_plan",
}
TEXTBOOK_MATERIAL_KINDS = {
    "textbook",
    "textbook_pdf",
    "pdf_textbook",
    "textbook_extract",
    "teacher_reference",
    "exercise_reference",
    "sample_lesson_plan",
    "lesson_plan",
}
NON_TEXTBOOK_MATERIAL_KIND_TOKENS = {"ppt", "pptx", "presentation", "courseware", "slide_deck"}
EDUCATION_CONTEXT_FIELDS_FOR_CONFLICT = (
    "school_stage",
    "grade",
    "subject",
    "subject_group",
    "textbook_version",
    "unit",
    "lesson_title",
    "lesson_number",
    "period_count",
    "minutes_per_period",
)
K12_CORE_FIELDS = ("school_stage", "grade", "subject", "lesson_title", "period_count", "minutes_per_period")


def stage3_education_context_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段3" / "education_context.json"


def stage3_textbook_context_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段3" / "textbook_context.json"


def lesson_plan_context_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段3" / "lesson_plan_context.json"


def stage4_education_context_path(run_dir: str | Path) -> Path:
    # Legacy read alias for projects created before lesson-plan outputs moved to stage3.
    return stage3_education_context_path(run_dir)


def stage4_textbook_context_path(run_dir: str | Path) -> Path:
    # Legacy read alias for projects created before lesson-plan outputs moved to stage3.
    return stage3_textbook_context_path(run_dir)


def build_lesson_plan_context(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    state = read_state(root)
    content = _read_json_if_exists(root / "_state" / "阶段1" / "content.json")
    design_contract = _read_json_if_exists(root / "_state" / "阶段1" / "design_contract.json")
    materials_index = load_materials(root)

    education_context, source_conflicts = _resolve_education_context(
        root,
        state=state,
        content=content,
        design_contract=design_contract,
        materials_index=materials_index,
    )
    textbook_context = _build_textbook_context(root, materials_index)
    source_conflicts.extend(_missing_referenced_textbook_materials(education_context, textbook_context))
    # Legacy read fallback for old projects only; new state writes stage3_locked_presentation_source.
    legacy_locked_source = state.get("stage4_locked_presentation_source")

    context = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "education_context": education_context,
        "stage1_sources": _stage1_sources(root),
        "locked_presentation_source": state.get("stage3_locked_presentation_source") or legacy_locked_source,
        "textbook_context": textbook_context,
        "curriculum_sources": _curriculum_sources(education_context),
        "source_conflicts": source_conflicts,
        "missing_core_fields": _missing_core_fields(education_context, root, state),
        "teacher_confirmation_items": _teacher_confirmation_items(education_context, textbook_context),
    }
    write_json(stage3_education_context_path(root), education_context)
    write_json(stage3_textbook_context_path(root), {"schema_version": SCHEMA_VERSION, "materials": textbook_context})
    write_json(lesson_plan_context_path(root), context)
    return context


def _resolve_education_context(
    root: Path,
    *,
    state: dict[str, Any],
    content: dict[str, Any] | None,
    design_contract: dict[str, Any] | None,
    materials_index: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inferred_context = infer_education_context(
        root,
        state=state,
        content=content,
        design_contract=design_contract,
        materials_index=materials_index,
    )
    content_context = _validated_context(content.get("education_context"), "content.education_context") if content else {}
    design_context = (
        _validated_context(design_contract.get("education_context"), "design_contract.education_context")
        if design_contract
        else {}
    )
    merged = dict(inferred_context)
    merged.update({key: value for key, value in content_context.items() if value not in (None, "", [])})
    merged.update({key: value for key, value in design_context.items() if value not in (None, "", [])})

    conflicts: list[dict[str, Any]] = []
    for field in EDUCATION_CONTEXT_FIELDS_FOR_CONFLICT:
        content_value = content_context.get(field)
        design_value = design_context.get(field)
        if content_value not in (None, "", []) and design_value not in (None, "", []) and content_value != design_value:
            conflicts.append(
                {
                    "field": field,
                    "content_value": content_value,
                    "design_contract_value": design_value,
                    "resolution": "use_design_contract_value_for_context; controller_should_review",
                }
            )
    return merged, conflicts


def _validated_context(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    return validate_education_context(value, label)


def _build_textbook_context(root: Path, materials_index: dict[str, Any]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for item in materials_index.get("materials", []):
        if not isinstance(item, dict):
            continue
        if not _is_textbook_material(item):
            continue
        contexts.append(
            {
                "material_id": item.get("id") or item.get("material_id"),
                "role": item.get("role_hint") or item.get("material_kind"),
                "authority_level": _material_authority_level(item),
                "title": item.get("label") or item.get("original_name") or item.get("source"),
                "edition": item.get("edition"),
                "school_stage": item.get("school_stage"),
                "grade": item.get("grade"),
                "subject": item.get("subject"),
                "unit": item.get("unit"),
                "lesson": item.get("lesson"),
                "locator": item.get("locator_hint") or item.get("locator"),
                "available_sections": item.get("available_sections") or [],
                "stored_path": item.get("stored_path"),
                "source": item.get("source"),
                "source_priority": item.get("source_priority"),
                "copyright_boundary": "教学提炼和短句定位，不复刻完整课文、教材或教辅内容",
                "exists": _material_exists(root, item),
            }
        )
    return contexts


def _is_textbook_material(item: dict[str, Any]) -> bool:
    role = _normalize(item.get("role_hint"))
    kind = _normalize(item.get("material_kind"))
    if any(token in kind for token in NON_TEXTBOOK_MATERIAL_KIND_TOKENS):
        return False
    label = _normalize(
        " ".join(
            str(value)
            for value in (
                item.get("label"),
                item.get("original_name"),
                item.get("locator_hint"),
                item.get("quality_notes"),
            )
            if value not in (None, "")
        )
    )
    if role in TEXTBOOK_MATERIAL_ROLES or kind in TEXTBOOK_MATERIAL_KINDS or "textbook" in kind:
        return True
    return any(token in label for token in ("教材", "课文", "教案", "教师用书", "练习"))


def _material_authority_level(item: dict[str, Any]) -> str:
    role = _normalize(item.get("role_hint"))
    kind = _normalize(item.get("material_kind"))
    label = _normalize(
        " ".join(
            str(value)
            for value in (
                item.get("label"),
                item.get("original_name"),
                item.get("locator_hint"),
            )
            if value not in (None, "")
        )
    )
    combined = " ".join(part for part in (role, kind, label) if part)
    if "sample_lesson_plan" in combined or "教案" in combined or "lesson_plan" in combined:
        return "teaching_sample_reference"
    if "teacher_reference" in combined or "教师用书" in combined:
        return "teacher_reference"
    if "exercise_reference" in combined or "练习" in combined:
        return "exercise_reference"
    if "primary_textbook" in combined or "textbook" in combined or "教材" in combined or "课文" in combined:
        return "primary_textbook"
    return "supplemental_reference"


def _material_exists(root: Path, item: dict[str, Any]) -> bool:
    stored_path = item.get("stored_path")
    if isinstance(stored_path, str) and stored_path.strip():
        return (root / stored_path).exists()
    if item.get("type") == "url":
        return True
    source = item.get("source")
    return bool(isinstance(source, str) and source.strip())


def _missing_referenced_textbook_materials(
    education_context: dict[str, Any],
    textbook_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requested = education_context.get("textbook_material_ids")
    if not isinstance(requested, list):
        return []
    available = {item.get("material_id") for item in textbook_context}
    missing = [material_id for material_id in requested if material_id not in available]
    return [
        {
            "field": "textbook_material_ids",
            "referenced_material_id": material_id,
            "resolution": "register_or_relink_textbook_material_before_final_lesson_plan",
        }
        for material_id in missing
    ]


def _stage1_sources(root: Path) -> list[dict[str, Any]]:
    paths = [
        root / "阶段1_规划确认" / "页面规划.md",
        root / "阶段1_规划确认" / "每页干净逐字稿.md",
        root / "_state" / "阶段1" / "content.json",
        root / "_state" / "阶段1" / "design_contract.json",
    ]
    return [_file_reference(root, path) for path in paths]


def _file_reference(root: Path, path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": _rel(root, path),
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        info["sha256"] = file_sha256(path)
    return info


def _curriculum_sources(education_context: dict[str, Any]) -> list[dict[str, str]]:
    standard = education_context.get("curriculum_standard")
    if not isinstance(standard, str) or not standard.strip():
        return []
    return [{"title": standard.strip(), "role": "curriculum_standard"}]


def _missing_core_fields(education_context: dict[str, Any], root: Path, state: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if education_context.get("is_k12") is True:
        for field in K12_CORE_FIELDS:
            if education_context.get(field) in (None, "", []):
                missing.append(f"education_context.{field}")
    for source in _stage1_sources(root):
        if not source["exists"]:
            missing.append(source["path"])
    # stage4_locked_presentation_source is a legacy read fallback only.
    if not (state.get("stage3_locked_presentation_source") or state.get("stage4_locked_presentation_source")):
        missing.append("stage3_locked_presentation_source")
    return missing


def _teacher_confirmation_items(
    education_context: dict[str, Any],
    textbook_context: list[dict[str, Any]],
) -> list[str]:
    items: list[str] = []
    if education_context.get("is_k12") is True and not textbook_context:
        items.append("缺少可追溯教材/课文材料，教案只能基于阶段1内容资产形成草案。")
    if education_context.get("period_strategy") in {"inferred_from_stage1", "inferred_from_textbook", "single_period_default"}:
        items.append("课时数或课时分配为推断结果，建议教师确认。")
    if education_context.get("subject_group") in {None, "", "unknown"} and education_context.get("is_k12") is True:
        items.append("学科组未明确，建议教师确认学科专项表。")
    return items


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValidationError(f"{_rel(path.parent, path)} must be an object")
    return data


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _normalize(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()
