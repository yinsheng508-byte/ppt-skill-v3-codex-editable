from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import append_event
from .json_io import read_json, write_json
from .materials import load_materials
from .image_style import ensure_image_style_doc, load_image_style, style_document_path, style_rules, image_style_snapshot, STYLE_RELPATH
from .paths import state_dir
from .planning_assets import (
    content_path,
    design_contract_path,
    load_content,
    load_design_contract,
    load_slide_prompt_briefs,
    save_content,
    save_design_contract,
    save_slide_prompt_briefs,
    slide_prompt_briefs_path,
)
from .ppt_consistency import CONSISTENCY_RELPATH, ensure_ppt_consistency_doc, validate_ppt_consistency_doc
from .state import read_state, write_state
from .validation import (
    ValidationError,
    require_matching_visible_text,
    require_matching_slide_indices,
    validate_content_asset,
    validate_design_contract,
    validate_slide_prompt_briefs,
    validate_stage1_plan,
)


PLACEHOLDER_VALUES = {
    "待主控大模型填写",
    "由主控大模型填写",
    "TODO",
    "TBD",
    "第1页",
    "第2页",
}


def _write_new_doc(path: Path, content: str, *, encoding: str) -> None:
    if not path.exists():
        path.write_text(content, encoding=encoding)


def stage1_slides_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段1" / "slides.json"


def stage1_clean_transcript_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "阶段1_规划确认" / "每页干净逐字稿.md"


def stage1_style_prompt_plan_path(run_dir: str | Path) -> Path:
    return style_document_path(run_dir)


def stage1_ppt_consistency_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / CONSISTENCY_RELPATH


def create_stage1_draft(run_dir: str | Path, slide_count: int = 1) -> Path:
    if slide_count < 1:
        raise ValueError("slide_count must be >= 1")
    root = Path(run_dir)
    stage_dir = root / "阶段1_规划确认"
    stage_dir.mkdir(parents=True, exist_ok=True)
    ensure_image_style_doc(root)
    ensure_ppt_consistency_doc(root)
    _write_new_doc(stage1_clean_transcript_path(root),
        "# 每页干净逐字稿\n\n"
        "本文件用于逐页审阅最终可见文字。页面规划、结构化内容和后续图片提示词必须与本文件逐页一致。\n\n"
        "---\n\n"
        "## 第 01 页｜页面标题\n\n"
        "**页面角色**：待主控大模型填写\n"
        "**本页目的**：待主控大模型填写\n\n"
        "### 页面可见文字\n\n"
        "待主控大模型按标题、要点、表格或流程排版填写。第 01 页封面主标题会作为阶段2/3/4交付文件名前缀。\n",
        encoding="utf-8",
    )
    _write_new_doc(stage_dir / "页面规划.md",
        "# 页面规划\n\n"
        "待主控大模型整合阶段0资料后填写。\n\n"
        "| 页码 | 页面角色 | 页面标题 | 本页目的 | 页面具体文字 | 资料依据 | 视觉意图 | 事实保护点 | 内容调整边界 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    draft = {
        "schema_version": "2.0",
        "status": "draft",
        "slides": [
            {
                "slide_index": index,
                "title": "",
                "purpose": "",
                "core_content": "",
                "visual_intent": "",
            }
            for index in range(1, slide_count + 1)
        ],
    }
    if not stage1_slides_path(root).exists():
        write_json(stage1_slides_path(root), draft)
    if not content_path(root).exists():
        save_content(root, _draft_content(slide_count))
    if not slide_prompt_briefs_path(root).exists():
        save_slide_prompt_briefs(root, _draft_prompt_briefs(slide_count))
    if not design_contract_path(root).exists():
        save_design_contract(root, _draft_design_contract(slide_count))
    state = read_state(root)
    if state["current_stage"] == "stage0":
        state["current_stage"] = "stage1"
        state["status"] = "stage1_draft"
        state["next_required_action"] = "主控填写页面规划、每页干净逐字稿、PPT一致性和图片风格"
        write_state(root, state)
    return stage1_slides_path(root)


def load_stage1_slides(run_dir: str | Path) -> dict[str, Any]:
    return read_json(stage1_slides_path(run_dir))


def save_stage1_slides(run_dir: str | Path, plan: dict[str, Any]) -> None:
    write_json(stage1_slides_path(run_dir), plan)


def validate_stage1_project(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    report_path = state_dir(root) / "阶段1" / "validation_report.json"
    try:
        plan = validate_stage1_plan(load_stage1_slides(root))
        content = validate_content_asset(load_content(root))
        prompt_briefs = validate_slide_prompt_briefs(load_slide_prompt_briefs(root))
        _reject_placeholders(plan)
        _reject_placeholder_values(content, "content")
        _reject_placeholder_values(prompt_briefs, "slide_prompt_briefs")
        require_matching_slide_indices(
            ("stage1_plan", plan),
            ("content", content),
            ("slide_prompt_briefs", prompt_briefs),
        )
        require_matching_visible_text(content, prompt_briefs)
        clean_transcript_path = _validate_clean_transcript_doc(root, content)
        ppt_consistency_path = validate_ppt_consistency_doc(root, content)
        style_prompt_plan_path = _validate_style_prompt_plan_doc(root)
        load_image_style(root)
        if style_prompt_plan_path.name == "图片风格.md":
            rules = style_rules(root)
            for slide in content["slides"]:
                if not rules["pages"].get(str(slide["slide_index"])):
                    raise ValidationError(f"图片风格.md 缺少第{slide['slide_index']}页图片规划")
                image_style_snapshot(root, slide["slide_index"], slide.get("page_type", "content"))
        _validate_source_basis_material_ids(root, content)
        design_contract = validate_design_contract(load_design_contract(root))
        _reject_placeholder_values(design_contract, "design_contract")
    except Exception as exc:
        report = {
            "schema_version": "2.0",
            "ok": False,
            "error": str(exc),
        }
        write_json(report_path, report)
        return report

    state = read_state(root)
    state["current_stage"] = "stage1"
    state["status"] = "waiting_user_confirmation"
    state["required_actor"] = "user"
    state["user_artifacts"]["stage1_page_plan"] = "阶段1_规划确认/页面规划.md"
    state["user_artifacts"]["stage1_clean_transcript"] = str(clean_transcript_path.relative_to(root))
    state["user_artifacts"]["stage1_ppt_consistency"] = str(ppt_consistency_path.relative_to(root))
    state["user_artifacts"]["stage1_style_prompt_plan"] = str(style_prompt_plan_path.relative_to(root))
    state["user_artifacts"]["stage1_image_style"] = STYLE_RELPATH
    state.setdefault("expected_user_paths", {})["stage1_ppt_consistency"] = CONSISTENCY_RELPATH
    state["quality"]["stage1"] = "pending_user_review"
    state["next_required_action"] = "等待用户确认阶段1四份规划材料"
    write_state(root, state)
    report = {
        "schema_version": "2.0",
        "ok": True,
        "slides_count": len(plan["slides"]),
        "content_asset": str(content_path(root).relative_to(root)),
        "clean_transcript": str(clean_transcript_path.relative_to(root)),
        "ppt_consistency": str(ppt_consistency_path.relative_to(root)),
        "style_prompt_plan": str(style_prompt_plan_path.relative_to(root)),
        "prompt_briefs_asset": str(slide_prompt_briefs_path(root).relative_to(root)),
        "design_contract_asset": str(design_contract_path(root).relative_to(root)),
        "route_family": design_contract["route_family"],
        "next_required_action": "等待用户确认阶段1四份规划材料",
    }
    write_json(report_path, report)
    append_event(root, "stage1_validated", "runtime", slides_count=len(plan["slides"]))
    return report


def _reject_placeholders(plan: dict[str, Any]) -> None:
    for slide in plan["slides"]:
        for field in ("title", "purpose", "core_content", "visual_intent"):
            value = str(slide.get(field, "")).strip()
            if value in PLACEHOLDER_VALUES:
                raise ValidationError(f"slide {slide['slide_index']} contains placeholder field: {field}")


def _reject_placeholder_values(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_placeholder_values(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value, start=1):
            _reject_placeholder_values(child, f"{label}[{index}]")
    elif isinstance(value, str) and value.strip() in PLACEHOLDER_VALUES:
        raise ValidationError(f"{label} contains placeholder value")


def _validate_source_basis_material_ids(root: Path, content: dict[str, Any]) -> None:
    materials = load_materials(root).get("materials", [])
    known_ids = {item.get("id") for item in materials if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if not known_ids:
        return
    for slide in content.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_index = slide.get("slide_index")
        for basis_index, basis in enumerate(slide.get("source_basis", []), start=1):
            if not isinstance(basis, dict):
                continue
            material_id = basis.get("material_id")
            if isinstance(material_id, str) and material_id.strip() and material_id not in known_ids:
                raise ValidationError(
                    f"content slide {slide_index} source_basis[{basis_index}].material_id not found in materials_index: {material_id}"
                )


def _validate_clean_transcript_doc(root: Path, content: dict[str, Any]) -> Path:
    path = stage1_clean_transcript_path(root)
    if not path.exists():
        raise ValidationError("stage1 clean transcript is missing: 阶段1_规划确认/每页干净逐字稿.md")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValidationError("stage1 clean transcript is empty")
    if "待主控大模型" in text:
        raise ValidationError("stage1 clean transcript still contains controller placeholders")

    compact_text = "".join(text.split())
    for slide in content.get("slides", []):
        slide_index = slide.get("slide_index")
        title = str(slide.get("title", "")).strip()
        if isinstance(slide_index, int):
            page_markers = {f"第{slide_index}页", f"第{slide_index:02d}页"}
            if not any(marker in compact_text for marker in page_markers):
                raise ValidationError(f"stage1 clean transcript missing page marker for slide {slide_index}")
        if title and title not in text:
            raise ValidationError(f"stage1 clean transcript missing title for slide {slide_index}: {title}")
        for item_index, item in enumerate(slide.get("final_visible_text", []), start=1):
            visible = str(item).strip()
            if visible and "".join(visible.split()) not in compact_text:
                raise ValidationError(
                    f"stage1 clean transcript missing final_visible_text for slide {slide_index} item {item_index}: {visible}"
                )
    return path


def _validate_style_prompt_plan_doc(root: Path) -> Path:
    path = stage1_style_prompt_plan_path(root)
    if not path.exists():
        raise ValidationError("stage1 style and prompt plan is missing: 阶段1_规划确认/图片风格.md")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValidationError("stage1 style and prompt plan is empty")
    if "待主控大模型" in text:
        raise ValidationError("stage1 style and prompt plan still contains controller placeholders")
    required_sections = ("风格",) if path.name != "图片风格.md" else ("当前生效风格", "不同页面的应用", "逐页图片规划")
    missing = [section for section in required_sections if section not in text]
    if missing:
        raise ValidationError("stage1 style and prompt plan missing required coverage: " + ", ".join(missing))
    return path


def _draft_content(slide_count: int) -> dict[str, Any]:
    return {
        "schema_version": "2.3",
        "status": "draft",
        "deck_title": "",
        "audience": "",
        "route": "",
        "slides": [
            {
                "slide_index": index,
                "page_type": "",
                "page_role": "",
                "title": "",
                "purpose": "",
                "source_basis": [],
                "final_visible_text": [],
                "text_contract": {
                    "must_keep": [],
                    "can_soft_polish": [],
                    "do_not_remove": [],
                    "do_not_invent": [],
                },
                "content_mutation_level": "soft_polish",
                "facts_to_preserve": [],
                "content_blocks": [],
                "slide_text_required": True,
            }
            for index in range(1, slide_count + 1)
        ],
    }


def _draft_prompt_briefs(slide_count: int) -> dict[str, Any]:
    return {
        "schema_version": "2.3",
        "status": "draft",
        "slides": [
            {
                "slide_index": index,
                "page_role": "",
                "message_goal": "",
                "final_visible_text": [],
                "visual_composition": "",
                "layout_family": "",
                "density_budget": "",
                "visual_anchor": "",
                "content_fidelity_policy": "",
                "main_visual_elements": [],
                "style_constraints": [],
                "negative_constraints": [],
                "acceptance_criteria": [],
            }
            for index in range(1, slide_count + 1)
        ],
    }


def _draft_design_contract(slide_count: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "draft",
        "route_family": "professional_report",
        "communication_path": "report_decision_path",
        "source_policy": {
            "mode": "source_rewrite",
            "content_mutation_level": "soft_polish",
            "primary_materials": [],
            "supporting_materials": [],
            "rules": ["整合阶段0全部资料后再生成页面规划", "页面规划中的每页具体文字是阶段2提示词的文字合同"],
            "conflict_resolution": "待主控大模型根据用户最新资料填写",
        },
        "audience_profile": {
            "primary_audience": "待主控大模型填写",
            "reading_context": "",
        },
        "visual_system_intent": {
            "tone_keywords": ["专业", "清晰"],
            "avoid_keywords": ["英文伪文字", "模板感"],
        },
        "layout_grammar": {
            "page_role_taxonomy": ["cover", "content"],
            "density_rules": [f"规划 {slide_count} 页时逐页确定密度"],
        },
        "stage2_cover_option_strategy": {
            "option_briefs": [
                {"option_id": "A", "style_positioning": "专业现代"},
                {"option_id": "B", "style_positioning": "清爽教学"},
                {"option_id": "C", "style_positioning": "学术稳重"},
                {"option_id": "D", "style_positioning": "发布路演"},
            ]
        },
        "stage2_qa_focus": ["中文清晰", "内容文字一致", "视觉系统统一"],
    }
