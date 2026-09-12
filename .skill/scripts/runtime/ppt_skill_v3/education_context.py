from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .json_io import read_json
from .paths import state_dir
from .state import read_state
from .validation import EDUCATION_CONTEXT_SUBJECT_GROUPS, ValidationError, validate_education_context


K12_SUBJECT_PROFILE_REGISTRY_REL_PATH = Path("assets/templates/k12_subject_profiles/registry.json")
K12_SUBJECT_PROFILE_SCHEMA_VERSION = "1.0"

SUBJECT_ALIASES = {
    "语文": "语文",
    "中文": "语文",
    "数学": "数学",
    "英语": "英语",
    "英文": "英语",
    "外语": "英语",
    "物理": "物理",
    "化学": "化学",
    "生物": "生物",
    "科学": "科学",
    "历史": "历史",
    "地理": "地理",
    "政治": "政治/道德与法治",
    "道德与法治": "政治/道德与法治",
    "道法": "政治/道德与法治",
    "思想政治": "政治/道德与法治",
    "美术": "美术/艺术",
    "艺术": "美术/艺术",
    "音乐": "美术/艺术",
    "综合实践": "综合实践",
    "劳动": "劳动",
    "信息科技": "信息科技",
    "信息技术": "信息科技",
    "体育": "体育与健康",
    "体育与健康": "体育与健康",
}

SUBJECT_GROUP_BY_SUBJECT = {
    "语文": "language",
    "数学": "math",
    "英语": "foreign_language",
    "物理": "science",
    "化学": "science",
    "生物": "science",
    "科学": "science",
    "历史": "humanities",
    "地理": "humanities",
    "政治/道德与法治": "humanities",
    "美术/艺术": "arts",
    "综合实践": "integrated",
    "劳动": "integrated",
    "信息科技": "integrated",
    "体育与健康": "integrated",
}

COMPETENCY_LABELS = {
    "语文": ["文化自信", "语言运用", "思维能力", "审美创造"],
    "数学": ["数学眼光", "数学思维", "数学语言"],
    "英语": ["语言能力", "文化意识", "思维品质", "学习能力"],
    "物理": ["物理观念", "科学思维", "科学探究", "科学态度与责任"],
    "化学": ["化学观念", "科学思维", "科学探究与实践", "科学态度与责任"],
    "生物": ["生命观念", "科学思维", "探究实践", "态度责任"],
    "科学": ["科学观念", "科学思维", "探究实践", "态度责任"],
    "政治/道德与法治": ["政治认同", "道德修养", "法治观念", "健全人格", "责任意识"],
    "历史": ["唯物史观", "时空观念", "史料实证", "历史解释", "家国情怀"],
    "地理": ["人地协调观", "综合思维", "区域认知", "地理实践力"],
    "美术/艺术": ["审美感知", "艺术表现", "创意实践", "文化理解"],
    "信息科技": ["信息意识", "计算思维", "数字化学习与创新", "信息社会责任"],
    "劳动": ["劳动观念", "劳动能力", "劳动习惯和品质", "劳动精神"],
    "体育与健康": ["运动能力", "健康行为", "体育品德"],
}

SUBJECT_EXTENSION_FIELDS = {
    "数学": [
        "concept_path",
        "example_chain",
        "variant_training",
        "common_errors",
        "board_work_plan",
        "practice_ladder",
        "mathematical_methods",
        "reasoning_or_proof",
        "diagnostic_assessment",
    ],
    "英语": [
        "language_points",
        "language_function",
        "discourse_context",
        "input_tasks",
        "output_tasks",
        "interaction_patterns",
        "culture_notes",
        "scaffolding_sentences",
        "assessment_language",
    ],
    "政治/道德与法治": [
        "issue_context",
        "value_discussion",
        "law_or_rule_basis",
        "public_participation_task",
        "case_analysis",
        "behavior_transfer",
        "reflection_prompt",
    ],
    "地理": [
        "map_chart_tasks",
        "regional_case",
        "scale_and_location",
        "human_environment_question",
        "geography_practice",
        "data_interpretation",
        "transfer_practice",
    ],
    "美术/艺术": [
        "artwork_appreciation",
        "visual_language",
        "technique_demo",
        "creative_task",
        "materials_tools",
        "process_scaffold",
        "critique_rubric",
    ],
}

GROUP_EXTENSION_FIELDS = {
    "language": [
        "text_focus",
        "key_language_points",
        "reading_methods",
        "question_chain",
        "recitation_or_reading_plan",
        "comparative_reading",
        "writing_transfer",
    ],
    "math": [
        "concept_path",
        "example_chain",
        "variant_training",
        "common_errors",
        "board_work_plan",
        "practice_ladder",
        "mathematical_methods",
    ],
    "foreign_language": [
        "language_points",
        "discourse_context",
        "input_tasks",
        "output_tasks",
        "interaction_patterns",
        "culture_notes",
        "assessment_language",
    ],
    "science": [
        "experiment_plan",
        "phenomena_and_conclusions",
        "model_building",
        "formula_or_equation_reasoning",
        "equipment_or_chemicals",
        "safety_and_waste",
    ],
    "humanities": [
        "issue_or_source_contexts",
        "map_or_material_tasks",
        "evidence_questions",
        "interpretation_or_value_tasks",
        "transfer_practice",
    ],
    "arts": [
        "artwork_appreciation",
        "technique_demo",
        "creative_task",
        "materials_tools",
        "critique_rubric",
    ],
    "integrated": [
        "real_world_task",
        "project_steps",
        "practice_record",
        "deliverable_rubric",
    ],
}

GROUP_QA_FOCUS = {
    "language": ["文本解读准确", "问题链由浅入深", "不大段复刻课文"],
    "math": ["概念路径清楚", "例题和变式有梯度", "符号与计算正确"],
    "foreign_language": ["输入输出平衡", "语篇语境一致", "交际目的真实"],
    "science": ["实验步骤可执行", "现象结论对应", "安全提示完整"],
    "humanities": ["材料或案例准确", "证据推理清楚", "价值辨析不过度口号化"],
    "arts": ["欣赏示范实践评价闭环", "材料工具可执行", "评价量规清楚"],
    "integrated": ["真实任务明确", "实践步骤可执行", "成果评价清楚"],
}

GRADE_NUMERAL_TO_INT = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
GRADE_INT_TO_CHINESE = {value: key for key, value in GRADE_NUMERAL_TO_INT.items()}
COMMON_TEXTBOOK_VERSIONS = ("统编版", "部编版", "人教版", "浙教版", "苏教版", "北师大版", "沪教版", "鲁教版", "湘教版", "粤教版")
K12_SIGNAL_TOKENS = ("小学", "初中", "高中", "年级", "上册", "下册", "教材", "课文", "课标", "课堂", "学习目标", "核心素养", "教学课件", "导学案")
COURSEWARE_SIGNAL_TOKENS = ("课件", "教学课件", "课堂", "学习目标", "教案", "导学案")
TEXTBOOK_MATERIAL_KIND_TOKENS = ("textbook", "textbook_pdf", "pdf_textbook", "teacher_reference", "exercise_reference")
NON_TEXTBOOK_MATERIAL_KIND_TOKENS = ("ppt", "pptx", "presentation", "courseware", "slide_deck")

SUBJECT_QA_FOCUS = {
    "数学": ["概念路径清楚", "例题链和变式训练有梯度", "易错点诊断与板演安排明确"],
    "英语": ["语言功能与语篇语境一致", "输入输出任务平衡", "评价语言能观察学生表达"],
    "政治/道德与法治": ["议题真实且价值辨析有边界", "案例与规则依据准确", "公共参与任务可执行"],
    "地理": ["地图图表任务清楚", "区域案例与尺度意识准确", "地理实践或迁移任务可执行"],
    "美术/艺术": ["欣赏示范实践评价闭环", "材料工具和技法步骤可执行", "评价量规清楚"],
}


def default_skill_root() -> Path:
    return Path(__file__).resolve().parents[3]


def subject_profile_registry_path(skill_root: str | Path | None = None) -> Path:
    root = Path(skill_root) if skill_root is not None else default_skill_root()
    return root / K12_SUBJECT_PROFILE_REGISTRY_REL_PATH


def load_subject_profile_registry(skill_root: str | Path | None = None) -> dict[str, Any]:
    return validate_subject_profile_registry(read_json(subject_profile_registry_path(skill_root)))


def validate_subject_profile_registry(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("k12_subject_profile_registry must be an object")
    if data.get("schema_version") != K12_SUBJECT_PROFILE_SCHEMA_VERSION:
        raise ValidationError(f"k12_subject_profile_registry.schema_version must be {K12_SUBJECT_PROFILE_SCHEMA_VERSION}")
    group_defaults = data.get("group_defaults")
    if not isinstance(group_defaults, dict):
        raise ValidationError("k12_subject_profile_registry.group_defaults must be an object")
    for group, profile in group_defaults.items():
        if group not in EDUCATION_CONTEXT_SUBJECT_GROUPS or group == "unknown":
            raise ValidationError(f"k12_subject_profile_registry.group_defaults has invalid subject_group: {group}")
        _validate_registry_profile(profile, f"k12_subject_profile_registry.group_defaults.{group}", require_subject=False)

    subjects = data.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise ValidationError("k12_subject_profile_registry.subjects must be a non-empty list")
    seen_subjects: set[str] = set()
    seen_aliases: dict[str, str] = {}
    for index, profile in enumerate(subjects, start=1):
        label = f"k12_subject_profile_registry.subjects[{index}]"
        subject = _validate_registry_profile(profile, label, require_subject=True)
        if subject in seen_subjects:
            raise ValidationError(f"{label}.subject is duplicated: {subject}")
        seen_subjects.add(subject)
        for alias in profile.get("aliases", []):
            previous = seen_aliases.get(alias)
            if previous is not None:
                raise ValidationError(f"{label}.aliases duplicates {alias} from {previous}")
            seen_aliases[alias] = subject
    return data


def subject_profile_registry_report(skill_root: str | Path | None = None) -> dict[str, Any]:
    try:
        registry = load_subject_profile_registry(skill_root)
        return {
            "schema_version": K12_SUBJECT_PROFILE_SCHEMA_VERSION,
            "ok": True,
            "registry": str(K12_SUBJECT_PROFILE_REGISTRY_REL_PATH),
            "subjects_count": len(registry["subjects"]),
            "groups_count": len(registry["group_defaults"]),
            "subjects": [profile["subject"] for profile in registry["subjects"]],
        }
    except Exception as exc:
        return {
            "schema_version": K12_SUBJECT_PROFILE_SCHEMA_VERSION,
            "ok": False,
            "registry": str(K12_SUBJECT_PROFILE_REGISTRY_REL_PATH),
            "error": str(exc),
        }


def load_education_context(run_dir: str | Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(run_dir)
    project_state = state or read_state(root)
    content = _read_json_if_object(root / "_state" / "阶段1" / "content.json")
    design_contract = _read_json_if_object(root / "_state" / "阶段1" / "design_contract.json")
    materials_index = _read_json_if_object(root / "_state" / "阶段0" / "materials_index.json")
    merged: dict[str, Any] = {}
    for candidate in (
        infer_education_context(
            root,
            state=project_state,
            content=content,
            design_contract=design_contract,
            materials_index=materials_index,
        ),
        _context_from_mapping(content),
        _context_from_mapping(design_contract),
        project_state.get("education_context"),
        _context_from_json(state_dir(root) / "阶段4" / "education_context.json", direct=True),
    ):
        if isinstance(candidate, dict):
            merged.update({key: value for key, value in candidate.items() if value not in (None, "", [])})
    return validate_education_context(merged) if merged else {}


def infer_education_context(
    run_dir: str | Path,
    *,
    state: dict[str, Any] | None = None,
    content: dict[str, Any] | None = None,
    design_contract: dict[str, Any] | None = None,
    materials_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(run_dir)
    project_state = state or _read_json_if_object(root / "_state" / "project_state.json") or {}
    content = content or _read_json_if_object(root / "_state" / "阶段1" / "content.json") or {}
    design_contract = design_contract or _read_json_if_object(root / "_state" / "阶段1" / "design_contract.json") or {}
    materials_index = materials_index or _read_json_if_object(root / "_state" / "阶段0" / "materials_index.json") or {}

    priority_text = "\n".join(_priority_inference_texts(project_state, content, design_contract, materials_index))
    all_text = "\n".join([priority_text, *_slide_inference_texts(content)])
    grade, school_stage = _infer_grade_and_school_stage(all_text)
    subject = _infer_subject(priority_text, all_text)
    lesson_number, lesson_title = _infer_lesson_info(priority_text, all_text, project_state, content)
    textbook_material_ids = _infer_textbook_material_ids(materials_index)
    route_teaching = _has_teaching_route(content, design_contract)
    has_k12_signal = any(token in all_text for token in K12_SIGNAL_TOKENS)
    has_lesson_signal = bool(lesson_number or textbook_material_ids or any(token in all_text for token in COURSEWARE_SIGNAL_TOKENS))

    if not (subject and grade and (route_teaching or has_k12_signal or has_lesson_signal)):
        return {}
    if not (has_k12_signal or textbook_material_ids or lesson_number):
        return {}

    profile = subject_profile_for({"subject": subject})
    confidence = "inferred_high" if textbook_material_ids or lesson_number else "inferred_medium"
    context: dict[str, Any] = {
        "is_k12": True,
        "confidence": confidence,
        "school_stage": school_stage or "unknown",
        "grade": grade,
        "subject": subject,
        "subject_group": profile["subject_group"],
        "lesson_scope": "single_lesson",
        "period_count": 1,
        "minutes_per_period": _default_minutes_for_stage(school_stage),
        "period_strategy": "single_period_default",
    }
    textbook_version = _infer_textbook_version(priority_text)
    if textbook_version:
        context["textbook_version"] = textbook_version
    unit = _infer_unit(priority_text)
    if unit:
        context["unit"] = unit
    if lesson_title:
        context["lesson_title"] = lesson_title
    if lesson_number:
        context["lesson_number"] = lesson_number
    if "任务型" in all_text:
        context["class_type"] = "任务型教学课件"
    elif "复习" in all_text:
        context["class_type"] = "复习课"
    else:
        context["class_type"] = "新授课"
    standard = _default_curriculum_standard(subject, school_stage)
    if standard:
        context["curriculum_standard"] = standard
    if textbook_material_ids:
        context["textbook_material_ids"] = textbook_material_ids
    return validate_education_context(context)


def is_k12_lesson_plan_required(context: dict[str, Any] | None, user_override: bool | None = None) -> bool:
    if user_override is not None:
        return bool(user_override)
    if not isinstance(context, dict) or context.get("is_k12") is not True:
        return False
    if _clean(context.get("subject")):
        return True
    return context.get("confidence") == "explicit_user_request"


def subject_profile_for(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}
    subject = _canonical_subject(context.get("subject"))
    explicit_group = _clean(context.get("subject_group"))
    registry_profile = _registry_profile_for(subject)
    group = (
        explicit_group
        if explicit_group and explicit_group != "unknown"
        else _profile_string(registry_profile, "subject_group") or SUBJECT_GROUP_BY_SUBJECT.get(subject, "unknown")
    )
    if group not in GROUP_EXTENSION_FIELDS:
        group = "unknown"
    group_profile = _registry_group_profile(group)
    return {
        "subject": subject or _clean(context.get("subject")) or "unknown",
        "subject_group": group,
        "competency_labels": _profile_string_list(registry_profile, "competency_labels")
        or _profile_string_list(group_profile, "competency_labels")
        or COMPETENCY_LABELS.get(subject, _default_competencies_for_group(group)),
        "suggested_focus_fields": _profile_focus_fields(registry_profile)
        or _profile_focus_fields(group_profile)
        or SUBJECT_EXTENSION_FIELDS.get(subject, GROUP_EXTENSION_FIELDS.get(group, [])),
        "qa_focus": _profile_string_list(registry_profile, "qa_focus")
        or _profile_string_list(group_profile, "qa_focus")
        or SUBJECT_QA_FOCUS.get(subject, GROUP_QA_FOCUS.get(group, ["学科未明确，需教师确认专项表"])),
        "warning": None if group != "unknown" else "unknown_subject_group",
    }


def _context_from_json(path: Path, *, direct: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    if direct:
        return data if isinstance(data, dict) else {}
    return _context_from_mapping(data)


def _context_from_mapping(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("education_context"), dict):
        return data["education_context"]
    return {}


def _read_json_if_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def _canonical_subject(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    if text in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[text]
    registry_subject = _registry_subject_for_alias(text)
    if registry_subject:
        return registry_subject
    for alias, subject in SUBJECT_ALIASES.items():
        if alias in text:
            return subject
    for alias, subject in _registry_aliases().items():
        if alias in text:
            return subject
    return text


def _priority_inference_texts(
    state: dict[str, Any],
    content: dict[str, Any],
    design_contract: dict[str, Any],
    materials_index: dict[str, Any],
) -> list[str]:
    texts: list[str] = []
    for source, fields in (
        (state, ("project_name", "run_dir", "next_required_action")),
        (content, ("deck_title", "audience", "route", "source_summary")),
        (design_contract, ("route_family", "communication_path", "topic", "audience")),
    ):
        for field in fields:
            _append_text(texts, source.get(field) if isinstance(source, dict) else None)
    audience = design_contract.get("audience_profile") if isinstance(design_contract, dict) else None
    if isinstance(audience, dict):
        _append_text(texts, audience.get("primary_audience"))
    for item in materials_index.get("materials", []) if isinstance(materials_index, dict) else []:
        if not isinstance(item, dict):
            continue
        for field in ("label", "original_name", "material_kind", "role_hint", "locator_hint", "quality_notes"):
            _append_text(texts, item.get(field))
        source = item.get("source")
        if isinstance(source, str):
            _append_text(texts, Path(source).name)
    return texts


def _slide_inference_texts(content: dict[str, Any]) -> list[str]:
    slides = content.get("slides") if isinstance(content, dict) else None
    if not isinstance(slides, list):
        return []
    texts: list[str] = []
    for slide in slides[:12]:
        if not isinstance(slide, dict):
            continue
        for field in ("title", "page_type", "page_role", "purpose"):
            _append_text(texts, slide.get(field))
        visible_text = slide.get("final_visible_text")
        if isinstance(visible_text, list):
            for item in visible_text[:8]:
                _append_text(texts, item)
    return texts


def _append_text(target: list[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        target.append(value.strip())


def _infer_grade_and_school_stage(text: str) -> tuple[str, str]:
    for pattern in (r"([一二三四五六七八九])年级", r"([1-9])年级"):
        match = re.search(pattern, text)
        if not match:
            continue
        token = match.group(1)
        grade_number = GRADE_NUMERAL_TO_INT.get(token, int(token) if token.isdigit() else 0)
        grade = f"{GRADE_INT_TO_CHINESE.get(grade_number, token)}年级"
        return grade, _school_stage_for_grade_number(grade_number)
    for token, number in (("初一", 7), ("初二", 8), ("初三", 9), ("七上", 7), ("八上", 8), ("九上", 9), ("七下", 7), ("八下", 8), ("九下", 9)):
        if token in text:
            return f"{GRADE_INT_TO_CHINESE[number]}年级", "junior_high"
    for token, grade in (("高一", "高一"), ("高二", "高二"), ("高三", "高三")):
        if token in text:
            return grade, "senior_high"
    return "", ""


def _school_stage_for_grade_number(grade_number: int) -> str:
    if 1 <= grade_number <= 6:
        return "primary"
    if 7 <= grade_number <= 9:
        return "junior_high"
    return "unknown"


def _infer_subject(priority_text: str, all_text: str) -> str:
    aliases = _registry_aliases()
    aliases.update(SUBJECT_ALIASES)
    scores: dict[str, int] = {}
    for alias, subject in aliases.items():
        count = _count_subject_alias(priority_text, alias) * 6 + _count_subject_alias(all_text, alias)
        if count:
            scores[subject] = scores.get(subject, 0) + count
    if not scores:
        return ""
    return max(scores.items(), key=lambda item: (item[1], len(item[0])))[0]


def _count_subject_alias(text: str, alias: str) -> int:
    if not alias:
        return 0
    if alias == "科学":
        return len(re.findall(r"(?<!自然)科学", text))
    return text.count(alias)


def _infer_lesson_info(
    priority_text: str,
    all_text: str,
    state: dict[str, Any],
    content: dict[str, Any],
) -> tuple[str, str]:
    lesson_number = ""
    lesson_title = _clean(content.get("deck_title"))
    pattern = re.compile(r"第\s*([0-9一二三四五六七八九十]+)\s*课\s*([^｜|（(\n，,。；;]+)")
    for corpus in (priority_text, all_text):
        match = pattern.search(corpus)
        if match:
            lesson_number = match.group(1).strip()
            if not lesson_title:
                lesson_title = _clean(_strip_non_title_suffix(match.group(2)))
            break
    if not lesson_title:
        project_name = _clean(state.get("project_name"))
        match = pattern.search(project_name)
        lesson_title = _clean(_strip_non_title_suffix(match.group(2))) if match else project_name
    return lesson_number, lesson_title


def _strip_non_title_suffix(value: str) -> str:
    title = re.sub(r"(PPT|课件|教学设计|教案|仿写|提取).*$", "", value, flags=re.IGNORECASE)
    return title.strip()


def _infer_textbook_version(text: str) -> str:
    for version in COMMON_TEXTBOOK_VERSIONS:
        if version in text:
            return version
    return ""


def _infer_unit(text: str) -> str:
    match = re.search(r"(第[一二三四五六七八九十0-9]+单元[^｜|\n，,。；;/\\]*)", text)
    return _strip_non_title_suffix(match.group(1)) if match else ""


def _infer_textbook_material_ids(materials_index: dict[str, Any]) -> list[str]:
    material_ids: list[str] = []
    for item in materials_index.get("materials", []) if isinstance(materials_index, dict) else []:
        if not isinstance(item, dict):
            continue
        kind = _clean(item.get("material_kind")).lower()
        if any(token in kind for token in NON_TEXTBOOK_MATERIAL_KIND_TOKENS):
            continue
        label_text = " ".join(
            _clean(item.get(field))
            for field in ("label", "original_name", "locator_hint", "quality_notes")
            if _clean(item.get(field))
        )
        if any(token in kind for token in TEXTBOOK_MATERIAL_KIND_TOKENS) or any(token in label_text for token in ("教材", "课文", "电子PDF")):
            material_id = _clean(item.get("id") or item.get("material_id"))
            if material_id:
                material_ids.append(material_id)
    return material_ids


def _has_teaching_route(content: dict[str, Any], design_contract: dict[str, Any]) -> bool:
    route = _clean(content.get("route")).lower()
    route_family = _clean(design_contract.get("route_family")).lower()
    return "teaching" in route or route_family == "teaching"


def _default_minutes_for_stage(school_stage: str) -> int:
    if school_stage == "primary":
        return 40
    return 45


def _default_curriculum_standard(subject: str, school_stage: str) -> str:
    if not subject:
        return ""
    if school_stage in {"primary", "junior_high"}:
        return f"义务教育{subject}课程标准（2022年版）"
    if school_stage == "senior_high":
        return f"普通高中{subject}课程标准"
    return ""


def _validate_registry_profile(profile: Any, label: str, *, require_subject: bool) -> str:
    if not isinstance(profile, dict):
        raise ValidationError(f"{label} must be an object")
    subject = ""
    if require_subject:
        subject = _require_non_empty_string(profile, "subject", label)
        _require_string_list(profile, "aliases", label, allow_empty=True)
        group = _require_non_empty_string(profile, "subject_group", label)
        if group not in EDUCATION_CONTEXT_SUBJECT_GROUPS or group == "unknown":
            raise ValidationError(f"{label}.subject_group is invalid: {group}")
    _require_string_list(profile, "competency_labels", label)
    _require_profile_focus_fields(profile, label)
    _require_string_list(profile, "qa_focus", label)
    return subject


def _registry_profile_for(subject: str) -> dict[str, Any] | None:
    if not subject:
        return None
    for profile in _registry_profiles():
        if profile.get("subject") == subject:
            return profile
    return None


def _registry_subject_for_alias(alias: str) -> str:
    return _registry_aliases().get(alias, "")


def _registry_group_profile(group: str) -> dict[str, Any] | None:
    try:
        registry = load_subject_profile_registry()
    except Exception:
        return None
    profile = registry.get("group_defaults", {}).get(group)
    return profile if isinstance(profile, dict) else None


def _registry_profiles() -> list[dict[str, Any]]:
    try:
        registry = load_subject_profile_registry()
    except Exception:
        return []
    return [profile for profile in registry.get("subjects", []) if isinstance(profile, dict)]


def _registry_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for profile in _registry_profiles():
        subject = profile.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            continue
        aliases[subject] = subject
        for alias in profile.get("aliases", []):
            if isinstance(alias, str) and alias.strip():
                aliases[alias.strip()] = subject
    return aliases


def _profile_string(profile: dict[str, Any] | None, field: str) -> str:
    if not isinstance(profile, dict):
        return ""
    return _clean(profile.get(field))


def _profile_string_list(profile: dict[str, Any] | None, field: str) -> list[str]:
    if not isinstance(profile, dict):
        return []
    value = profile.get(field)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _profile_focus_fields(profile: dict[str, Any] | None) -> list[str]:
    return _profile_string_list(profile, "suggested_focus_fields") or _profile_string_list(profile, "required_extension_fields")


def _require_profile_focus_fields(profile: dict[str, Any], label: str) -> list[str]:
    if "suggested_focus_fields" in profile:
        return _require_string_list(profile, "suggested_focus_fields", label)
    if "required_extension_fields" in profile:
        return _require_string_list(profile, "required_extension_fields", label)
    raise ValidationError(f"{label}.suggested_focus_fields must be a list of non-empty strings")


def _require_non_empty_string(profile: dict[str, Any], field: str, label: str) -> str:
    value = profile.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label}.{field} must be a non-empty string")
    return value.strip()


def _require_string_list(profile: dict[str, Any], field: str, label: str, *, allow_empty: bool = False) -> list[str]:
    value = profile.get(field)
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValidationError(f"{label}.{field} must be a list of non-empty strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValidationError(f"{label}.{field} must contain non-empty strings")
    return value


def _default_competencies_for_group(group: str) -> list[str]:
    if group == "science":
        return ["科学观念", "科学思维", "探究实践", "态度责任"]
    if group == "humanities":
        return ["证据意识", "综合思维", "价值判断", "实践参与"]
    if group == "integrated":
        return ["价值体认", "责任担当", "问题解决", "创意物化"]
    return []


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
