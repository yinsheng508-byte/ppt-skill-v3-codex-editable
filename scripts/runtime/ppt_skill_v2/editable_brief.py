from __future__ import annotations

from pathlib import Path
from typing import Any

from .dev_mode import require_dev_fixture_enabled
from .deliverable_naming import project_deliverable_relpaths
from .events import append_event
from .json_io import read_json
from .planning_assets import (
    content_path,
    deck_style_path,
    layout_intent_path,
    load_content,
    load_deck_style,
    load_layout_intent,
)
from .stage1_plan import load_stage1_slides
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .editable_coordinate_plan import (
    editable_coordinate_plan_path,
    load_editable_coordinate_plan,
    require_coordinate_plan_background_alignment,
    require_coordinate_plan_matches_ownership,
)
from .font_calibration_profile import font_calibration_profile_path, load_font_calibration_profile
from .text_ownership_map import load_text_ownership_map, restore_targets_for_slide, text_ownership_map_path
from .text_unit_split_plan import load_text_unit_split_plan, text_unit_split_plan_path
from .validation import (
    ValidationError,
    require_matching_slide_indices,
    validate_content_asset,
    validate_deck_style,
    validate_image_result,
    validate_layout_intent,
    validate_stage1_plan,
)


def build_editable_brief(run_dir: str | Path, *, allow_dev_fixture: bool = False) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("editable brief can only be built in stage3")
    if not state.get("confirmed", {}).get("stage3_coordinate_plan"):
        raise ValidationError("editable brief requires user-confirmed stage3 coordinate plan before text fill")
    if allow_dev_fixture:
        require_dev_fixture_enabled()

    plan = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    content = apply_stage3_scope(validate_content_asset(load_content(root)), state, "content")
    deck_style = validate_deck_style(load_deck_style(root))
    layout_intent = validate_layout_intent(load_layout_intent(root))
    ownership = apply_stage3_scope(load_text_ownership_map(root), state, "text_ownership_map", strict=True)
    coordinate_plan = apply_stage3_scope(load_editable_coordinate_plan(root), state, "editable_coordinate_plan", strict=True)
    split_plan = (
        apply_stage3_scope(load_text_unit_split_plan(root), state, "text_unit_split_plan", strict=True)
        if text_unit_split_plan_path(root).exists()
        else None
    )
    font_profile = load_font_calibration_profile(root) if font_calibration_profile_path(root).exists() else None
    require_matching_slide_indices(("stage1_plan", plan), ("text_ownership_map", ownership))
    require_matching_slide_indices(("stage1_plan", plan), ("editable_coordinate_plan", coordinate_plan))
    require_coordinate_plan_matches_ownership(coordinate_plan, ownership)
    require_coordinate_plan_background_alignment(root, coordinate_plan)
    slides: list[dict[str, Any]] = []
    for slide in plan["slides"]:
        slide_index = slide["slide_index"]
        stage2_result = _load_image_result(root, "阶段2", slide_index, allow_dev_fixture)
        stage3_result = _load_image_result(root, "阶段3", slide_index, allow_dev_fixture)
        slides.append(
            {
                "slide": slide,
                "stage2_image": stage2_result["image_path"],
                "stage3_background": stage3_result["image_path"],
                "stage2_result": stage2_result,
                "stage3_result": stage3_result,
            }
        )

    brief_path = root / "_state" / "阶段3" / "briefs" / "officecli_brief.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        _render_brief(state, slides, content, deck_style, layout_intent, ownership, coordinate_plan, split_plan, font_profile, root),
        encoding="utf-8",
    )

    state["status"] = "stage3_coordinate_builder_handoff_ready"
    state["required_actor"] = "main_controller"
    state["runtime_artifacts"]["stage3_officecli_brief"] = "_state/阶段3/briefs/officecli_brief.md"
    state["next_required_action"] = "主控大模型调用 OfficeCLI builder，严格基于 editable_coordinate_plan 填字并生成可编辑 PPTX"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "editable_brief_built",
        "runtime",
        slides_count=len(slides),
        allow_dev_fixture=allow_dev_fixture,
        stage3_scope=stage3_scope_summary(state),
    )
    return brief_path


def _load_image_result(root: Path, state_stage_dirname: str, slide_index: int, allow_dev_fixture: bool) -> dict[str, Any]:
    if state_stage_dirname == "阶段3":
        result_path = root / "_state" / state_stage_dirname / "no_text_background_results" / f"slide_{slide_index:03d}.json"
        if not result_path.exists():
            result_path = root / "_state" / state_stage_dirname / "results" / f"slide_{slide_index:03d}.json"
    else:
        result_path = root / "_state" / state_stage_dirname / "results" / f"slide_{slide_index:03d}.json"
    if not result_path.exists():
        raise ValidationError(f"missing {state_stage_dirname} image result for slide {slide_index}")
    result = validate_image_result(read_json(result_path), production=not allow_dev_fixture)
    image_path = root / result["image_path"]
    if not image_path.exists():
        raise FileNotFoundError(f"registered image does not exist: {image_path}")
    return result


def _render_brief(
    state: dict[str, Any],
    slides: list[dict[str, Any]],
    content: dict[str, Any],
    deck_style: dict[str, Any],
    layout_intent: dict[str, Any],
    ownership: dict[str, Any],
    coordinate_plan: dict[str, Any],
    split_plan: dict[str, Any] | None,
    font_profile: dict[str, Any] | None,
    root: Path,
) -> str:
    coordinate_slides = coordinate_plan.get("slides", [])
    text_unit_count = sum(len(slide.get("text_units", [])) for slide in coordinate_slides if isinstance(slide, dict))
    native_element_count = sum(len(slide.get("native_elements", [])) for slide in coordinate_slides if isinstance(slide, dict))
    ownership_count = sum(len(slide.get("editable_page_layer", [])) for slide in ownership.get("slides", []) if isinstance(slide, dict))
    split_unit_count = _count_split_units(split_plan)
    editable_split_unit_count = _count_editable_split_units(split_plan)
    font_profile_count = len(font_profile.get("profiles", [])) if isinstance(font_profile, dict) else 0
    probe = font_profile.get("render_probe", {}) if isinstance(font_profile, dict) else {}
    probe_basis = font_profile.get("basis", {}) if isinstance(font_profile, dict) else {}
    native_style_probe = root / "_state" / "阶段3" / "officecli" / "probe" / "native_style_probe.json"
    editable_deck_rel = project_deliverable_relpaths(root, state=state)["stage3_editable_deck"]
    lines = [
        "# OfficeCLI 可编辑 PPT 生成 Brief",
        "",
        f"- 项目名称：{state['project_name']}",
        "- 目标：基于阶段2确认图几何和阶段3无字背景，生成真实可编辑 PPTX。",
        "- 目标：执行坐标复刻计划，不重新设计页面，不重新推理文本槽位，不自动重排。",
        "- 约束：不要把本 brief 当作 PPTX；不要把阶段2图片版 PDF 或整页图片改名为可编辑 PPT。",
        "- 约束：文字内容只能来自 `_state/阶段1/content.json` 和 `editable_coordinate_plan.text`；不得使用 OCR 或图片识别文字作为内容来源。",
        "- 约束：几何坐标必须来自 `_state/阶段3/editable_coordinate_plan.json`；不得临时猜坐标，不得按默认版式重排。",
        "- 约束：背景图铺底必须使用完整阶段3无字背景，placement_mode=exact_full_slide；不得使用会裁切画面的 `cover`，不得固定 1280x720 后裁切或偏移。",
        "- 约束：不要把所有文字合成一个整页大文本框；需要按页面层级建立 PPT 原生文本对象。",
        "- 约束：必须按 `editable_coordinate_plan.slides[].text_units[]` 挨着挨着逐个填字；一个 `text_unit_id` 对应一个 PPT 原生文本 shape。",
        "- 约束：每个 `text_unit_id` 必须成为同名或可追溯命名的 PPT 原生文本 shape，且只填入该 text unit 自己的文字，便于 PPTX inspect 逐个反查。",
        "- 约束：不得把多个 text unit、多个 bullet、多个卡片、多个流程节点或不同层级文字合并进同一个文本框。",
        "- 约束：字体、字号、颜色、行距、内边距、对齐、换行和 fit_policy 都以 editable_coordinate_plan 为准。",
        "- 约束：`fit_policy.auto_shrink=false` 时不得自动缩小文字；溢出必须写入执行报告并返工坐标或文案。",
        "- 约束：专业、医疗、宣教、商务风格默认使用 `Microsoft YaHei`；不要使用苹方/PingFang。",
        "- 约束：OfficeCLI builder 使用 PowerPoint pt 坐标画布，必须把 `relative_box` 换算到 960x540pt 并通过 OfficeCLI readback 校验。",
        "- 约束：如因技术限制发生偏差，必须写入 `within_allowed_range=false` 与 `deviation_reason`，不能假写通过。",
        "- 约束：坐标复刻预览和 PIL 文字效果预演只用于快速排查位置，不是字体校准证据；字体校准以 OfficeCLI native style probe 和 font_calibration_profile 为准。",
        "- 约束：只允许生成 coordinate plan 指定的少量 native_elements；复杂插画、人物、照片或复杂图表保留在背景图中。",
        "- 约束：执行顺序为 background image -> native_elements under_text -> coordinate text units -> native_elements over_text。",
        "- 约束：PPT 画布必须按每页 `coordinate_canvas` 或等比例 16:9 完整铺底计算；所有文本框使用同一画布基准换算。",
        f"- 输出：{editable_deck_rel}",
        "- 输出：_state/阶段3/text_fill_execution_report.json，schema_version=2.0，覆盖全部 coordinate text units，且 `actual_source=pptx_ooxml`。",
        "- 输出：_state/阶段3/officecli/readback/build_deck.readback.json",
        "- 输出：_state/阶段3/render_review/ 下的渲染图和 contact sheet",
        "- 输出：_state/阶段3/manifests/officecli_manifest.json，用于记录 OfficeCLI commands、results、readback 和 shape 映射。",
        f"- 内容资产：{content_path(root).relative_to(root)}",
        f"- 视觉系统：{deck_style_path(root).relative_to(root)}",
        f"- 版式意图：{layout_intent_path(root).relative_to(root)}",
        f"- 文字归属账本：{text_ownership_map_path(root).relative_to(root)}",
        f"- 拆字计划：{_optional_relpath(root, text_unit_split_plan_path(root))}",
        f"- 字体校准 profile：{_optional_relpath(root, font_calibration_profile_path(root))}",
        f"- native style probe：{_optional_relpath(root, native_style_probe)}",
        f"- 可编辑坐标计划：{editable_coordinate_plan_path(root).relative_to(root)}",
        "",
        "## 全局视觉系统",
        "",
        f"- 视觉世界：{deck_style.get('visual_world', '')}",
        f"- 字体体系：{deck_style.get('typography', {})}",
        f"- logo规则：{deck_style.get('logo_policy', {})}",
        f"- 页码规则：{deck_style.get('page_number_policy', {})}",
        f"- 标题区规则：{deck_style.get('header_policy', '')}",
        f"- 内容区规则：{deck_style.get('content_policy', '')}",
        "",
        "## 版式意图",
        "",
        f"- basis：{layout_intent.get('basis', {})}",
        f"- 全局布局：{layout_intent.get('global_layout', {})}",
        f"- 信息密度：{layout_intent.get('density_policy', {})}",
        f"- 可编辑文本策略：{layout_intent.get('editable_text_policy', {})}",
        "",
        "## 坐标复刻规划摘要",
        "",
        f"- 页面规划数量：{len(coordinate_slides)}",
        f"- 可编辑 ownership 数量：{ownership_count}",
        f"- split unit 数量：{split_unit_count}",
        f"- 可编辑 split unit 数量：{editable_split_unit_count}",
        f"- text unit 数量：{text_unit_count}",
        f"- native element 数量：{native_element_count}",
        f"- font profile 数量：{font_profile_count}",
        f"- native style probe slide：{probe_basis.get('probe_slide_index') if probe_basis else '暂无'}",
        f"- native style probe review_status：{probe.get('review_status') if probe else '暂无'}",
        "- OfficeCLI builder 不得用默认 title/body/footer 样式替代本规划；如因技术限制微调，必须写入 text_fill_execution_report.json。",
        "",
        "## 页面要求",
        "",
    ]
    content_by_index = {slide["slide_index"]: slide for slide in content["slides"]}
    coordinate_by_index = {slide["slide_index"]: slide for slide in coordinate_slides if isinstance(slide, dict)}
    for item in slides:
        slide = item["slide"]
        content_slide = content_by_index.get(slide["slide_index"], {})
        plan_slide = coordinate_by_index.get(slide["slide_index"], {})
        restore_targets = restore_targets_for_slide(ownership, slide["slide_index"])
        lines.extend(
            [
                f"### 第 {slide['slide_index']} 页：{slide['title']}",
                "",
                f"- 页面目的：{slide['purpose']}",
                f"- 核心内容：{slide['core_content']}",
                f"- 最终可编辑文字：{content_slide.get('final_visible_text', [])}",
                f"- 视觉意图：{slide['visual_intent']}",
                f"- 阶段2参考图：{item['stage2_image']}",
                f"- 阶段3无字背景：{item['stage3_background']}",
                f"- source image：{plan_slide.get('source_image', {})}",
                f"- stage3 background image：{plan_slide.get('stage3_background_image', {})}",
                f"- coordinate canvas：{plan_slide.get('coordinate_canvas', {})}",
                "- 背景铺底要求：使用完整阶段3无字背景 exact_full_slide 铺满同一坐标画布；不得 cover 裁切，不得产生 crop offset。",
                f"- restore targets：{_summarize_restore_targets(restore_targets)}",
                f"- coordinate text units：{_summarize_text_units(plan_slide.get('text_units', []))}",
                f"- native elements：{_summarize_native_elements(plan_slide.get('native_elements', []))}",
                "- 可编辑要求：标题、正文、关键标注需要使用 PPT 原生文本对象，背景使用无字背景图；文字来自内容资产，不来自图片识别。",
                "- 填字要求：按本页 coordinate text units 列表逐个创建文本对象、逐个填入、逐个设置字号和样式；所有文本对象按 `text_unit_id` 和 `relative_box` 放置；不得跨出坐标框、压住背景人物/图标/流程箭头/装饰元素。",
                "- 合并禁令：本页任何两个 text unit 都不得合并为同一个 PPT 文本框，即使它们看起来属于同一段或同一卡片。",
                "",
            ]
        )
    return "\n".join(lines)


def _summarize_slots(slots: Any) -> list[str]:
    if not isinstance(slots, list):
        return []
    summary: list[str] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        summary.append(
            (
                f"{slot.get('slot_id', '')}"
                f"({slot.get('role', '')}, safe={slot.get('text_safe_box', {})}, "
                f"must_fill={slot.get('must_fill', False)})"
            )
        )
    return summary


def _summarize_fragments(fragments: Any) -> list[str]:
    if not isinstance(fragments, list):
        return []
    summary: list[str] = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        summary.append(
            (
                f"{fragment.get('fragment_id', '')}"
                f"({fragment.get('semantic_role', '')} -> {fragment.get('target_slot_id') or 'unused'}, "
                f"target={fragment.get('restore_target_id', '')})"
            )
        )
    return summary


def _summarize_restore_targets(targets: Any) -> list[str]:
    if not isinstance(targets, list):
        return []
    summary: list[str] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        summary.append(f"{target.get('target_id', '')}({target.get('action', '')}: {target.get('text', '')})")
    return summary


def _optional_relpath(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.exists() else "暂无"


def _count_split_units(split_plan: dict[str, Any] | None) -> int:
    if not isinstance(split_plan, dict):
        return 0
    return sum(len(slide.get("units", [])) for slide in split_plan.get("slides", []) if isinstance(slide, dict))


def _count_editable_split_units(split_plan: dict[str, Any] | None) -> int:
    if not isinstance(split_plan, dict):
        return 0
    return sum(
        1
        for slide in split_plan.get("slides", [])
        if isinstance(slide, dict)
        for unit in slide.get("units", [])
        if isinstance(unit, dict) and unit.get("restore_as_editable") and unit.get("background_action") == "remove_and_restore"
    )


def _summarize_text_objects(objects: Any) -> list[str]:
    if not isinstance(objects, list):
        return []
    summary: list[str] = []
    for text_object in objects:
        if not isinstance(text_object, dict):
            continue
        font = text_object.get("font", {}) if isinstance(text_object.get("font"), dict) else {}
        summary.append(
            (
                f"{text_object.get('object_id', '')}"
                f"(target={text_object.get('restore_target_id', '')}, box={text_object.get('relative_box', {})}, "
                f"font={font.get('resolved_family', '')}/{font.get('target_font_size_pt', '')}pt/{font.get('resolved_color', '')})"
            )
        )
    return summary


def _summarize_text_units(units: Any) -> list[str]:
    if not isinstance(units, list):
        return []
    summary: list[str] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        font = unit.get("font", {}) if isinstance(unit.get("font"), dict) else {}
        summary.append(
            (
                f"{unit.get('text_unit_id', '')}"
                f"(ownership={unit.get('ownership_id', '')}, text={unit.get('text', '')}, "
                f"display_text={unit.get('display_text', unit.get('text', ''))}, wrap_policy={unit.get('wrap_policy', {})}, "
                f"box_px={unit.get('box_px', {})}, relative_box={unit.get('relative_box', {})}, "
                f"font={font.get('resolved_family', '')}/{font.get('target_font_size_pt', '')}pt/{font.get('resolved_color', '')})"
            )
        )
    return summary


def _summarize_native_elements(elements: Any) -> list[str]:
    if not isinstance(elements, list):
        return []
    summary: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        summary.append(
            (
                f"{element.get('element_id', '')}"
                f"({element.get('type', '')}, z={element.get('z_order', '')}, "
                f"linked={element.get('linked_text_unit_id', '')}, "
                f"fill={element.get('fill', '')}, stroke={element.get('stroke', '')}, "
                f"box={element.get('relative_box') or element.get('box_px', {})})"
            )
        )
    return summary


def _summarize_foreground_elements(elements: Any) -> list[str]:
    if not isinstance(elements, list):
        return []
    summary: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        summary.append(
            f"{element.get('element_id', '')}({element.get('type', '')}, box={element.get('relative_box', {})})"
        )
    return summary


def _summarize_exclusion_zones(zones: Any) -> list[str]:
    if not isinstance(zones, list):
        return []
    summary: list[str] = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        summary.append(f"{zone.get('zone_id', '')}({zone.get('reason', '')}, box={zone.get('relative_box', {})})")
    return summary
