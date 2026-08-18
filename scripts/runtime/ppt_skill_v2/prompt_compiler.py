from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def file_hash(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def compile_stage2_prompt(
    *,
    content_slide: dict[str, Any],
    prompt_brief: dict[str, Any],
    deck_style: dict[str, Any],
    layout_intent: dict[str, Any],
    route: str,
    design_contract: dict[str, Any] | None = None,
    layout_safety_slide: dict[str, Any] | None = None,
) -> str:
    visible_text = "；".join(prompt_brief.get("final_visible_text") or content_slide.get("final_visible_text") or [content_slide["title"]])
    negative = "；".join(prompt_brief.get("negative_constraints") or deck_style.get("forbidden_visuals") or ["不要英文占位", "不要伪文字"])
    acceptance = "；".join(prompt_brief.get("acceptance_criteria") or ["中文文字清晰", "信息层级明确"])
    visual_elements = "；".join(prompt_brief.get("main_visual_elements") or [])
    style_constraints = "；".join(prompt_brief.get("style_constraints") or [])
    source_policy = design_contract.get("source_policy", {}) if isinstance(design_contract, dict) else {}
    route_family = design_contract.get("route_family", "未提供") if isinstance(design_contract, dict) else "未提供"
    communication_path = design_contract.get("communication_path", "未提供") if isinstance(design_contract, dict) else "未提供"
    source_basis = _format_list_or_json(content_slide.get("source_basis") or [])
    text_contract = _format_list_or_json(content_slide.get("text_contract") or {})
    style_atoms = _format_list_or_json(deck_style.get("style_atoms") or {})
    color_contract = _format_list_or_json(deck_style.get("color_contract") or {})
    typography_contract = _format_list_or_json(deck_style.get("typography_contract") or {})
    image_language = _format_list_or_json(deck_style.get("image_language") or {})
    motif_system = _format_list_or_json(deck_style.get("motif_system") or {})
    composition_grammar = _format_list_or_json(layout_intent.get("composition_grammar") or {})
    slide_role_map = _slide_role_map_for_prompt(layout_intent.get("slide_role_map"), content_slide["slide_index"])
    layout_slot_contracts = _format_list_or_json(layout_intent.get("layout_slot_contracts") or {})
    variation_schedule = _format_list_or_json(layout_intent.get("variation_schedule") or {})
    layout_safety = _format_layout_safety(layout_safety_slide)
    return (
        "生成一张 16:9 中文 PPT 整页图片，作为阶段2B正式页面，后续会打包为图片版 PDF；优先目标 2K 画布 2048x1152，高清锐利，尽量避免低分辨率、模糊或压缩感图片。\n"
        f"PPT路线：{route}\n"
        f"设计合同路线：route_family={route_family}；communication_path={communication_path}\n"
        f"内容改写边界：{source_policy.get('content_mutation_level', content_slide.get('content_mutation_level', 'soft_polish'))}\n"
        f"资料依据：{source_basis}\n"
        f"文字合同：{text_contract}\n"
        f"页码：{content_slide['slide_index']}\n"
        f"pageType：{content_slide.get('page_type', 'content')}\n"
        f"页面角色：{prompt_brief.get('page_role', content_slide.get('page_role', ''))}\n"
        f"layout_family：{prompt_brief.get('layout_family', '')}\n"
        f"density_budget：{prompt_brief.get('density_budget', '')}\n"
        f"visual_anchor：{prompt_brief.get('visual_anchor', '')}\n"
        f"content_fidelity_policy：{prompt_brief.get('content_fidelity_policy', '')}\n"
        f"页面标题：{content_slide['title']}\n"
        f"页面目的：{content_slide['purpose']}\n"
        f"最终可见中文文字：{visible_text}\n"
        f"传播目标：{prompt_brief.get('message_goal', '')}\n"
        f"视觉构图：{prompt_brief.get('visual_composition', '')}\n"
        f"主视觉元素：{visual_elements}\n"
        f"整套视觉世界：{deck_style.get('visual_world', '')}\n"
        f"风格原子：{style_atoms}\n"
        f"配色合同：{color_contract}\n"
        f"字体合同：{typography_contract}\n"
        f"图片语言：{image_language}\n"
        f"视觉母题：{motif_system}\n"
        f"字体体系：{deck_style.get('typography', {})}\n"
        f"logo规则：{deck_style.get('logo_policy', {})}\n"
        f"页码规则：{deck_style.get('page_number_policy', {})}\n"
        f"标题区规则：{deck_style.get('header_policy', '')}\n"
        f"内容区规则：{deck_style.get('content_policy', '')}\n"
        f"版式意图：{layout_intent.get('global_layout', {})}\n"
        f"构图语法：{composition_grammar}\n"
        f"本页角色映射：{slide_role_map}\n"
        f"版式槽位合同：{layout_slot_contracts}\n"
        f"节奏变化计划：{variation_schedule}\n"
        f"信息密度策略：{layout_intent.get('density_policy', {})}\n"
        f"页面类型规则：{layout_intent.get('page_type_rules', {})}\n"
        f"可编辑重建安全区：{layout_safety}\n"
        f"额外风格约束：{style_constraints}\n"
        f"禁止项：{negative}；不要出现英文占位词、拼音、乱码、假字或 lorem ipsum。\n"
        "文字准确性：只能使用“最终可见中文文字”里列出的文字；不得改写、删减、增加、翻译或替换数字、单位、年份和专业术语；不得新增装饰性伪文字。\n"
        "清晰度要求：全页、文字边缘、图标、图表和细线优先按 2048x1152 高清画布绘制，尽量避免小图放大、模糊、锐化噪点、马赛克和明显压缩痕迹。\n"
        "可编辑重建约束：页面信息文字只能落在可编辑文字安全区；重要图像只能落在视觉区域；人物、设备、复杂纹理和装饰不得压入禁压区；"
        "未来要可编辑恢复的标题、正文、数据和来源注释必须保持清晰独立，不要嵌进复杂图像内部。\n"
        f"验收标准：{acceptance}。"
    )


def compile_stage3_background_prompt(
    *,
    content_slide: dict[str, Any],
    prompt_brief: dict[str, Any],
    deck_style: dict[str, Any],
    layout_intent: dict[str, Any],
    source_stage2: dict[str, Any],
    restore_targets: list[dict[str, Any]],
) -> str:
    remove_and_restore = _format_restore_targets(restore_targets, "remove_and_restore")
    preserve = _format_restore_targets(restore_targets, "preserve_in_background")
    remove_without_restore = _format_restore_targets(restore_targets, "remove_without_restore")
    return (
        "基于提供的阶段2整页参考图做图像编辑，生成一张 16:9 PPT 保真去字背景图，用于阶段3可编辑PPT重建；目标保留阶段2参考图原始清晰度，优先 2K 画布 2048x1152，尽量避免降采样、压缩或模糊图。\n"
        f"参考页码：{content_slide['slide_index']}\n"
        f"阶段2参考图：{source_stage2.get('image_path', '')}\n"
        f"阶段2参考图sha：{source_stage2.get('image_sha256', '')}\n"
        f"参考页面标题：{content_slide['title']}\n"
        f"必须移除且后续恢复为可编辑对象的文字/数字/标签：{remove_and_restore}\n"
        f"必须保留在背景中的可见文字/数字/符号：{preserve}\n"
        f"可以移除且不恢复的文字纹理：{remove_without_restore}\n"
        f"整套视觉世界：{deck_style.get('visual_world', '')}\n"
        f"logo规则：{deck_style.get('logo_policy', {})}\n"
        f"页码规则：{deck_style.get('page_number_policy', {})}\n"
        f"标题区规则：{deck_style.get('header_policy', '')}\n"
        f"版式意图：{layout_intent.get('global_layout', {})}\n"
        f"可编辑文本区域策略：{layout_intent.get('editable_text_policy', {})}\n"
        "编辑要求：不要重新设计页面，不要同风格重画，不要改变构图、人物、物体、图标、卡片、光影、纹理、色彩和复杂插画；"
        "只移除上方明确列入“必须移除且后续恢复”的目标，以及明确列入“可以移除且不恢复”的目标；"
        "尺寸和清晰度要求：尽量不要缩小参考图，不要把背景重新压缩成低分辨率；输出优先保持参考图同等或更高清晰度，文字移除区域边缘自然但不糊；"
        "目录序号、步骤编号、知识点编号、页码、卡片标签等如果属于 PPT 信息层，必须列入移除并恢复目标后再移除；"
        "插画、人物场景、设备、屏幕、小白板内部作为画面细节的文字和数字，应列入保留目标或默认保留；"
        "未列入目标清单的内容不要擅自清除；"
        "文字移除后的区域需要自然修补为原背景、卡片底或留白，保留后续可编辑文本可放置的视觉槽位。"
    )


def _format_restore_targets(restore_targets: list[dict[str, Any]], action: str) -> str:
    items = [
        f"{target.get('target_id', '')}={target.get('text', '')}"
        for target in restore_targets
        if target.get("action") == action
    ]
    return "；".join(items) if items else "无"


def _format_list_or_json(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(_format_scalar_or_json(item) for item in value) if value else "无"
    if isinstance(value, dict):
        return _format_scalar_or_json(value) if value else "无"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "无"


def _format_scalar_or_json(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _format_layout_safety(slide: dict[str, Any] | None) -> str:
    if not isinstance(slide, dict):
        return "未提供"
    payload = {
        "density_decision": slide.get("density_decision"),
        "editable_text_regions": slide.get("editable_text_regions", []),
        "visual_regions": slide.get("visual_regions", []),
        "exclusion_zones": slide.get("exclusion_zones", []),
        "text_ownership_policy": slide.get("text_ownership_policy", {}),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _slide_role_map_for_prompt(value: Any, slide_index: int) -> str:
    if not isinstance(value, list):
        return "无"
    matches = [item for item in value if isinstance(item, dict) and item.get("slide_index") == slide_index]
    return _format_list_or_json(matches[0]) if matches else "无"
