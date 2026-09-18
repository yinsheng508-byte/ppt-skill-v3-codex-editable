from __future__ import annotations

import hashlib
import json
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
    draft_content = _draft_content(slide_count)
    content_digest = content_source_sha256(draft_content)
    draft["content_source_sha256"] = content_digest
    if not stage1_slides_path(root).exists():
        write_json(stage1_slides_path(root), draft)
    if not content_path(root).exists():
        save_content(root, draft_content)
    if not slide_prompt_briefs_path(root).exists():
        briefs = _draft_prompt_briefs(slide_count)
        briefs["content_source_sha256"] = content_digest
        save_slide_prompt_briefs(root, briefs)
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


def content_source_sha256(content: dict[str, Any]) -> str:
    """Digest the one controller-authored Stage 1 text source deterministically."""

    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def sync_stage1_derivatives(run_dir: str | Path) -> dict[str, Any]:
    """Regenerate Stage 1 text derivatives from the only editable source: content.json."""

    root = Path(run_dir)
    content = validate_content_asset(load_content(root))
    plan = load_stage1_slides(root)
    briefs = load_slide_prompt_briefs(root)
    _validate_derivative_shell(plan, "stage1_plan")
    _validate_derivative_shell(briefs, "slide_prompt_briefs")
    require_matching_slide_indices(("stage1_plan", plan), ("content", content), ("slide_prompt_briefs", briefs))
    content_by_index = {slide["slide_index"]: slide for slide in content["slides"]}
    for slide in plan["slides"]:
        source = content_by_index[slide["slide_index"]]
        slide["title"] = source["title"]
        slide["purpose"] = source["purpose"]
        slide["core_content"] = "\n".join(source["final_visible_text"])
    for brief in briefs["slides"]:
        source = content_by_index[brief["slide_index"]]
        brief["page_role"] = source.get("page_role") or source["page_type"]
        brief["message_goal"] = source["purpose"]
        brief["final_visible_text"] = list(source["final_visible_text"])
    digest = content_source_sha256(content)
    plan["content_source_sha256"] = digest
    briefs["content_source_sha256"] = digest
    plan = validate_stage1_plan(plan)
    briefs = validate_slide_prompt_briefs(briefs)
    save_stage1_slides(root, plan)
    save_slide_prompt_briefs(root, briefs)
    _render_stage1_text_docs(root, plan, content)
    return {
        "content_source": str(content_path(root).relative_to(root)),
        "content_source_sha256": digest,
        "slides_count": len(content["slides"]),
        "updated": [
            str(stage1_slides_path(root).relative_to(root)),
            str(slide_prompt_briefs_path(root).relative_to(root)),
            "阶段1_规划确认/页面规划.md",
            str(stage1_clean_transcript_path(root).relative_to(root)),
        ],
    }


def _validate_derivative_shell(value: Any, label: str) -> None:
    if not isinstance(value, dict) or value.get("schema_version") not in {"2.0", "2.3"}:
        raise ValidationError(f"{label} must be a supported Stage 1 object")
    slides = value.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError(f"{label}.slides must be a non-empty list")
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict) or not isinstance(slide.get("slide_index"), int):
            raise ValidationError(f"{label}.slides[{index}].slide_index must be an integer")


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
        _validate_stage1_derivative_source(content, plan, prompt_briefs)
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


def _validate_stage1_derivative_source(
    content: dict[str, Any],
    plan: dict[str, Any],
    prompt_briefs: dict[str, Any],
) -> None:
    """Keep legacy projects readable while requiring a fresh sync for new assets."""

    values = [plan.get("content_source_sha256"), prompt_briefs.get("content_source_sha256")]
    present = [value for value in values if isinstance(value, str) and value.strip()]
    if not present:
        return
    if len(present) != len(values):
        raise ValidationError("Stage 1 派生资料的 content_source_sha256 不完整，请执行 sync-stage1-derivatives")
    expected = content_source_sha256(content)
    if any(value != expected for value in present):
        raise ValidationError("content.json 已更新，页面规划或提示词 brief 未同步；请执行 sync-stage1-derivatives")


def _render_stage1_text_docs(root: Path, plan: dict[str, Any], content: dict[str, Any]) -> None:
    content_by_index = {slide["slide_index"]: slide for slide in content["slides"]}
    plan_lines = [
        "# 页面规划",
        "",
        "本文件由 `_state/阶段1/content.json` 同步生成；文字修改请回到 content.json，再执行同步。",
        "",
        "| 页码 | 页面角色 | 页面标题 | 本页目的 | 页面具体文字 | 资料依据 | 内容保留边界 | 视觉意图 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    transcript_lines = [
        "# 每页干净逐字稿",
        "",
        "本文件由 `_state/阶段1/content.json` 同步生成；文字修改请回到 content.json，再执行同步。",
        "",
    ]
    for slide in plan["slides"]:
        source = content_by_index[slide["slide_index"]]
        role = source.get("page_role") or source["page_type"]
        title = _markdown_table_cell(source["title"])
        purpose = _markdown_table_cell(source["purpose"])
        visible = _markdown_table_cell("<br>".join(str(text) for text in source["final_visible_text"]))
        source_basis = _markdown_table_cell(_render_source_basis(source))
        content_boundary = _markdown_table_cell(_render_content_boundary(source))
        visual = _markdown_table_cell(str(slide.get("visual_intent", "")))
        plan_lines.append(
            f"| {slide['slide_index']:02d} | {role} | {title} | {purpose} | {visible} | {source_basis} | {content_boundary} | {visual} |"
        )
        transcript_lines.extend(
            [
                f"## 第 {slide['slide_index']:02d} 页｜{source['title']}",
                "",
                f"**页面角色**：{role}",
                f"**本页目的**：{source['purpose']}",
                "",
                "### 页面可见文字",
                "",
                *[f"- {text}" for text in source["final_visible_text"]],
                "",
            ]
        )
    (root / "阶段1_规划确认/页面规划.md").write_text("\n".join(plan_lines) + "\n", encoding="utf-8")
    stage1_clean_transcript_path(root).write_text("\n".join(transcript_lines), encoding="utf-8")


def _render_source_basis(slide: dict[str, Any]) -> str:
    basis_items = slide.get("source_basis")
    if not isinstance(basis_items, list):
        return ""
    rendered: list[str] = []
    for item in basis_items:
        if not isinstance(item, dict):
            continue
        material = item.get("material_id") or item.get("material") or item.get("source") or item.get("title")
        pieces = [str(material).strip()] if isinstance(material, str) and material.strip() else []
        locator = item.get("locator") or item.get("quote_locator")
        if isinstance(locator, str) and locator.strip():
            pieces.append(locator.strip())
        usage = item.get("usage") or item.get("reason")
        if isinstance(usage, str) and usage.strip():
            pieces.append(usage.strip())
        quote = item.get("quote")
        if isinstance(quote, str) and quote.strip():
            pieces.append(f"引用：{quote.strip()}")
        if pieces:
            rendered.append(" / ".join(pieces))
    return "；".join(rendered)


def _render_content_boundary(slide: dict[str, Any]) -> str:
    sections: list[str] = []
    text_contract = slide.get("text_contract")
    if isinstance(text_contract, dict):
        for label, field in (
            ("必须保留", "must_keep"),
            ("不得删除", "do_not_remove"),
            ("不得编造", "do_not_invent"),
            ("可软润色", "can_soft_polish"),
        ):
            values = text_contract.get(field)
            if isinstance(values, list):
                clean_values = [str(value).strip() for value in values if str(value).strip()]
                if clean_values:
                    sections.append(f"{label}：" + "、".join(clean_values))
            elif isinstance(values, str) and values.strip():
                sections.append(f"{label}：{values.strip()}")
    facts = slide.get("facts_to_preserve")
    if isinstance(facts, list):
        clean_facts = [str(value).strip() for value in facts if str(value).strip()]
        if clean_facts:
            sections.append("事实保留：" + "、".join(clean_facts))
    mutation_level = slide.get("content_mutation_level")
    if isinstance(mutation_level, str) and mutation_level.strip():
        sections.append(f"改写等级：{mutation_level.strip()}")
    return "；".join(sections)


def _markdown_table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


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
