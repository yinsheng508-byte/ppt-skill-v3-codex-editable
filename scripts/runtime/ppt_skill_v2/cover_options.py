from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .events import append_event
from .image_batches import create_image_generation_batch
from .image_packets import prompt_hash
from .image_routes import (
    DEFAULT_IMAGE_GENERATION_ROUTE,
    DEFAULT_PPT_IMAGE_SIZE_16_9,
    IMAGE_ROUTE_CODEX_IMAGE_GEN,
    IMAGE_ROUTE_OPENAI_IMAGE_API,
    OPENAI_IMAGE_API_TOOL,
    image_size_contract,
    normalize_image_generation_route,
    route_tool,
    route_tool_function,
)
from .json_io import read_json, write_json
from .planning_assets import (
    load_cover_selection,
    load_content,
    load_cover_option_style_card,
    load_design_contract,
    load_slide_prompt_briefs,
    save_cover_option_style_card,
)
from .state import read_state, write_state
from .time_utils import now_iso
from .validation import (
    ValidationError,
    require_matching_slide_indices,
    require_matching_visible_text,
    validate_content_asset,
    validate_cover_option_style_card,
    validate_design_contract,
    validate_image_result,
    validate_slide_prompt_briefs,
)


COVER_OPTION_IDS = ["A", "B", "C", "D"]
IMAGE_API_TOOL = OPENAI_IMAGE_API_TOOL
IMAGE_API_GENERATE_FUNCTION = "openai.images.generate"
DEFAULT_IMAGE_API_MODEL = "gpt-image-2-vip"
DEFAULT_IMAGE_API_SIZE = DEFAULT_PPT_IMAGE_SIZE_16_9
DEFAULT_IMAGE_API_QUALITY = "high"
DEFAULT_IMAGE_API_ENDPOINT = "/v1/draw/completions"

STYLE_DIRECTIONS = {
    "A": "专业现代：克制、高级、结构清楚，适合方案汇报或行业分析。",
    "B": "沉浸视觉：强场景、强主视觉、光影丰富，适合演讲和发布。",
    "C": "知识图解：清晰、理性、图解感强，适合课件、培训和专业内容。",
    "D": "极简观点：留白充足、标题突出、视觉干净，适合观点表达。",
}


def dispatch_cover_option_packets(
    run_dir: str | Path,
    *,
    route: str | None = None,
) -> list[Path]:
    root = Path(run_dir)
    generation_route = normalize_image_generation_route(route)
    state = read_state(root)
    _require_cover_options_open(state)
    content = validate_content_asset(load_content(root))
    briefs = validate_slide_prompt_briefs(load_slide_prompt_briefs(root))
    require_matching_slide_indices(("content", content), ("slide_prompt_briefs", briefs))
    require_matching_visible_text(content, briefs)
    design_contract = _load_design_contract_or_none(root)
    style_cards = _style_cards_from_design_contract(design_contract, content)

    cover_slide = _select_cover_slide(content, briefs)
    packet_root = root / "_state" / "阶段2" / "cover_options" / "packets"
    prompt_root = root / "_state" / "阶段2" / "cover_options" / "prompts"
    packet_paths: list[Path] = []
    total_packets = len(COVER_OPTION_IDS)
    execution_group = {
        "group_id": _cover_options_group_id(generation_route),
        "image_generation_route": generation_route,
        "required_tool": route_tool(generation_route),
        "tool_call": route_tool_function(generation_route),
        "mode": "parallel_required",
        "parallel_required": True,
        "total_packets": total_packets,
        "packet_index": 1,
        "max_parallel": min(6, total_packets),
    }
    for packet_index, option_id in enumerate(COVER_OPTION_IDS, start=1):
        style_card = validate_cover_option_style_card(style_cards[option_id])
        save_cover_option_style_card(root, option_id, style_card)
        prompt = _build_cover_prompt(content, cover_slide, option_id, design_contract, style_card)
        packet_execution_group = {**execution_group, "packet_index": packet_index}
        packet = {
            "schema_version": "2.3",
            "packet_id": f"stage2-cover-option-{option_id}",
            "stage": "stage2",
            "purpose": "cover_option",
            "option_id": option_id,
            "style_card_path": f"_state/阶段2/cover_options/style_cards/cover_option_{option_id}.json",
            "slide_index": cover_slide["slide_index"],
            "title": cover_slide["title"],
            "image_generation_route": generation_route,
            "execution_tool": route_tool(generation_route),
            "execution_tool_function": route_tool_function(generation_route),
            "execution_mode": "parallel_required",
            "execution_group": packet_execution_group,
            "prompt": prompt,
            "prompt_hash": prompt_hash(prompt),
            **image_size_contract(),
            "formal_mode": True,
            "created_at": now_iso(),
            "expected_output_relpath": f"阶段2_图片版PPT/封面风格候选/cover_option_{option_id}.png",
        }
        packet.update(_route_input(generation_route))
        packet_path = packet_root / f"cover_option_{option_id}.json"
        write_json(packet_path, packet)
        packet_paths.append(packet_path)
        prompt_path = prompt_root / f"cover_option_{option_id}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(
            f"# 封面候选 {option_id} 提示词\n\n{prompt}\n",
            encoding="utf-8",
        )

    create_image_generation_batch(root, execution_group, packet_paths, stage="stage2", purpose="cover_option", route=generation_route)

    state["status"] = "waiting_for_cover_option_results"
    state["required_actor"] = "main_controller"
    state["next_required_action"] = _next_action_for_route(generation_route, "四张封面候选")
    write_state(root, state)
    append_event(
        root,
        "cover_option_packets_dispatched",
        "runtime",
        packets_count=len(packet_paths),
        image_generation_route=generation_route,
        execution_tool=route_tool(generation_route),
        execution_mode="parallel_required",
    )
    return packet_paths


def write_cover_options_review(run_dir: str | Path) -> Path:
    root = Path(run_dir)
    target = root / "阶段2_图片版PPT" / "封面风格候选" / "封面风格选择说明.md"
    lines = [
        "# 封面风格选择说明",
        "",
        "请从以下四种封面风格中选择一个，作为整套 PPT 的视觉方向：",
        "",
    ]
    for option_id in COVER_OPTION_IDS:
        card = _load_style_card_or_fallback(root, option_id)
        extension = card.get("layout_extension", {}) if isinstance(card.get("layout_extension"), dict) else {}
        lines.append(f"## 方案 {option_id}")
        lines.append("")
        lines.append(f"- 图片：`cover_option_{option_id}.png`")
        lines.append(f"- 风格定位：{card.get('style_positioning', STYLE_DIRECTIONS[option_id])}")
        lines.append(f"- 适合：{'、'.join(card.get('best_for') or ['待判断'])}")
        lines.append(f"- 内页延展：{extension.get('cover_to_inner_pages', '由主控大模型延展到内页视觉系统')}")
        risk_notes = card.get("risk_notes") or []
        lines.append(f"- 风险提醒：{'、'.join(risk_notes) if risk_notes else '暂无明显风险'}")
        lines.append("")
    lines.extend(
        [
            "用户选择后，主控大模型会把该方向沉淀为 `deck_style.json` 和 `layout_intent.json`。如果选中的封面本身无明显质量问题，会直接转正为正式封面页；阶段2B试样会跳过该封面，只生成需要验证的内页。",
            "",
        ]
    )
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def cover_option_results_complete(run_dir: str | Path) -> bool:
    root = Path(run_dir)
    return all(
        (root / "_state" / "阶段2" / "cover_options" / "results" / f"cover_option_{option_id}.json").exists()
        for option_id in COVER_OPTION_IDS
    )


def promote_selected_cover_option(run_dir: str | Path, *, force: bool = False) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage2" or not state["confirmed"].get("stage2_cover_style"):
        raise ValidationError("selected cover option promotion requires approved cover style")

    selection = load_cover_selection(root)
    option_id = _selected_option_id(selection)
    cover_result_path = root / "_state" / "阶段2" / "cover_options" / "results" / f"cover_option_{option_id}.json"
    if not cover_result_path.exists():
        raise ValidationError(f"selected cover option result is missing: cover_option_{option_id}")

    raw_result = read_json(cover_result_path)
    cover_result = validate_image_result(raw_result, production=not bool(raw_result.get("fixture")))
    if cover_result.get("stage") != "stage2" or cover_result.get("purpose") != "cover_option":
        raise ValidationError("selected cover option promotion can only use a stage2 cover_option result")
    if cover_result.get("option_id") != option_id:
        raise ValidationError("selected cover option result option_id does not match selection.json")

    slide_index = cover_result["slide_index"]
    cover_image_relpath = cover_result["image_path"]
    source_image = root / cover_image_relpath
    if not source_image.exists():
        raise FileNotFoundError(f"selected cover option image missing: {source_image}")

    formal_image_relpath = f"阶段2_图片版PPT/img/slide_{slide_index:03d}{source_image.suffix.lower()}"
    formal_result_path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
    if formal_result_path.exists() and not force:
        existing_raw = read_json(formal_result_path)
        existing = validate_image_result(existing_raw, production=not bool(existing_raw.get("fixture")))
        if existing.get("promoted_from_cover_option") and existing.get("selected_cover_option") == option_id:
            existing_image = root / existing["image_path"]
            if not existing_image.exists():
                raise FileNotFoundError(f"promoted cover image missing: {existing_image}")
            return formal_result_path
        raise ValidationError(f"formal stage2 result already exists for slide {slide_index}")

    dest_image = root / formal_image_relpath
    dest_image.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_image, dest_image)

    promoted = dict(cover_result)
    promoted.update(
        {
            "purpose": "full_slide",
            "image_path": formal_image_relpath,
            "promoted_from_cover_option": True,
            "cover_option_result_path": _relative_or_text(root, cover_result_path),
            "cover_option_image_path": cover_image_relpath,
            "selected_cover_option": option_id,
            "cover_option_id": option_id,
            "attempt_id": cover_result.get("attempt_id") or f"slide-{slide_index:03d}-from-cover-option-{option_id}",
            "version": cover_result.get("version") or 1,
            "result_path": _relative_or_text(root, formal_result_path),
            "created_at": now_iso(),
        }
    )
    validate_image_result(promoted, production=not bool(promoted.get("fixture")))
    write_json(formal_result_path, promoted)

    state["status"] = "selected_cover_option_promoted"
    state["required_actor"] = "main_controller"
    state["next_required_action"] = "已选封面候选已转正为阶段2正式封面页；继续分发阶段2B试样，试样应跳过该封面页"
    write_state(root, state)
    append_event(
        root,
        "selected_cover_option_promoted",
        "runtime",
        option_id=option_id,
        slide_index=slide_index,
        result_path=_relative_or_text(root, formal_result_path),
    )
    return formal_result_path


def _require_cover_options_open(state: dict[str, Any]) -> None:
    if state["current_stage"] != "stage2" or not state["confirmed"].get("stage1_plan"):
        raise ValidationError("cover option packets require approved stage1 plan")
    if state["confirmed"].get("stage2_cover_style"):
        raise ValidationError("cover style is already approved")


def _cover_options_group_id(route: str) -> str:
    if normalize_image_generation_route(route) == IMAGE_ROUTE_OPENAI_IMAGE_API:
        return "stage2-cover-options-image-api"
    return "stage2-cover-options-image-gen"


def _route_input(route: str) -> dict[str, Any]:
    normalized = normalize_image_generation_route(route)
    size_contract = image_size_contract()
    if normalized == IMAGE_ROUTE_OPENAI_IMAGE_API:
        return {
            "image_api_input": {
                "endpoint": DEFAULT_IMAGE_API_ENDPOINT,
                "model": DEFAULT_IMAGE_API_MODEL,
                "size": DEFAULT_IMAGE_API_SIZE,
                "aspectRatio": DEFAULT_IMAGE_API_SIZE,
                "quality": DEFAULT_IMAGE_API_QUALITY,
                "n": 1,
                "output_format": "png",
                **size_contract,
            }
        }
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return {
            "image_gen_input": {
                "mode": "generate",
                "tool": "image_gen.imagegen",
                "size": DEFAULT_IMAGE_API_SIZE,
                "quality": "auto",
                "output_format": "png",
                "project_bound": True,
                **size_contract,
                "expected_save_policy": "copy_generated_output_to_expected_output_relpath_then_record_result",
                "tool_argument_policy": "built_in_image_gen_size_is_a_target_not_a_guaranteed_raw_argument",
            }
        }
    raise ValidationError(f"unsupported image generation route: {route}")


def _next_action_for_route(route: str, description: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == DEFAULT_IMAGE_GENERATION_ROUTE:
        return f"主控大模型必须调用 Codex 内置 image_gen 工具生成{description}，优先目标 2048x1152，尽量保留生成原始尺寸，把输出复制到项目目录，并逐张记录 image_gen evidence、尺寸和图片 sha"
    return f"主控大模型必须运行图片 API 批量执行器，按 6 并发生成{description}，优先目标 2048x1152，尽量保留生成原始尺寸，并逐张记录 API evidence、尺寸和图片 sha"


def _select_cover_slide(content: dict[str, Any], briefs: dict[str, Any]) -> dict[str, Any]:
    content_slides = content["slides"]
    cover = next((slide for slide in content_slides if slide.get("page_type") == "cover"), content_slides[0])
    brief_by_index = {slide["slide_index"]: slide for slide in briefs["slides"]}
    brief = brief_by_index.get(cover["slide_index"], {})
    return {
        "slide_index": cover["slide_index"],
        "title": cover["title"],
        "purpose": cover["purpose"],
        "final_visible_text": cover.get("final_visible_text", []),
        "visual_composition": brief.get("visual_composition", ""),
        "negative_constraints": brief.get("negative_constraints", []),
        "acceptance_criteria": brief.get("acceptance_criteria", []),
    }


def _load_design_contract_or_none(root: Path) -> dict[str, Any] | None:
    try:
        return validate_design_contract(load_design_contract(root))
    except FileNotFoundError:
        return None


def _style_cards_from_design_contract(
    design_contract: dict[str, Any] | None,
    content: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    option_briefs: dict[str, dict[str, Any]] = {}
    if design_contract:
        strategy = design_contract.get("stage2_cover_option_strategy", {})
        for item in strategy.get("option_briefs", []) if isinstance(strategy, dict) else []:
            if isinstance(item, dict) and item.get("option_id") in COVER_OPTION_IDS:
                option_briefs[item["option_id"]] = item

    cards: dict[str, dict[str, Any]] = {}
    audience = _string_from_path(design_contract, ("audience_profile", "primary_audience")) or content.get("audience", "目标受众")
    route_family = design_contract.get("route_family") if design_contract else content.get("route", "通用PPT")
    for option_id in COVER_OPTION_IDS:
        option = option_briefs.get(option_id, {})
        style_positioning = _field_or_default(option, "style_positioning", STYLE_DIRECTIONS[option_id])
        cards[option_id] = {
            "schema_version": "1.0",
            "option_id": option_id,
            "basis_design_contract": "_state/阶段1/design_contract.json" if design_contract else "fallback_style_directions",
            "style_positioning": style_positioning,
            "best_for": _list_or_default(option.get("best_for"), [str(route_family), str(audience)]),
            "composition": _field_or_default(
                option,
                "composition",
                f"围绕封面标题建立清晰主视觉；{style_positioning}",
            ),
            "visual_medium": _field_or_default(option, "visual_medium", "clean professional bitmap"),
            "palette_strategy": _field_or_default(option, "palette_strategy", _fallback_palette_strategy(option_id)),
            "typography_direction": _field_or_default(option, "typography_direction", "中文标题清晰可读，避免伪文字"),
            "layout_extension": _layout_extension(option, option_id),
            "risk_notes": _list_or_default(option.get("risk_notes"), ["避免英文占位、乱码、假字或不可读装饰文字"]),
            "prompt_constraints": _list_or_default(
                option.get("prompt_constraints"),
                ["只渲染 final_visible_text 中指定的中文", "四张候选必须在构图、色彩或图像语言上明显不同"],
            ),
            "selection_explanation": _field_or_default(
                option,
                "selection_explanation",
                f"方案 {option_id} 适合将 {content.get('deck_title', '本项目')} 做成{style_positioning}方向。",
            ),
        }
    return cards


def _load_style_card_or_fallback(root: Path, option_id: str) -> dict[str, Any]:
    try:
        return validate_cover_option_style_card(load_cover_option_style_card(root, option_id))
    except FileNotFoundError:
        return _style_cards_from_design_contract(None, {"deck_title": "本项目", "audience": "目标受众", "route": "通用PPT"})[option_id]


def _field_or_default(source: dict[str, Any], field: str, default: str) -> str:
    value = source.get(field)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _list_or_default(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return value
    return default


def _string_from_path(source: dict[str, Any] | None, path: tuple[str, ...]) -> str:
    value: Any = source
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _layout_extension(option: dict[str, Any], option_id: str) -> dict[str, Any]:
    extension = option.get("layout_extension")
    if isinstance(extension, dict):
        return {
            "cover_to_inner_pages": _field_or_default(
                extension,
                "cover_to_inner_pages",
                "把封面主色、图形母题和标题层级延展到内页",
            ),
            "suitable_page_roles": _list_or_default(extension.get("suitable_page_roles"), ["cover", "content"]),
            "risky_page_roles": _list_or_default(extension.get("risky_page_roles"), ["dense_table"]),
        }
    return {
        "cover_to_inner_pages": f"方案 {option_id} 的色彩、图形母题和标题层级延展到内页",
        "suitable_page_roles": ["cover", "content"],
        "risky_page_roles": ["dense_table"],
    }


def _fallback_palette_strategy(option_id: str) -> str:
    return {
        "A": "浅底、深色正文、蓝色强调，保证专业与通用性",
        "B": "深色背景、亮色聚焦，适合开场发布感",
        "C": "白底、图解色块、低饱和辅助色，适合知识说明",
        "D": "大留白、单一强调色、弱装饰，适合观点表达",
    }[option_id]


def _selected_option_id(selection: dict[str, Any]) -> str:
    option_id = selection.get("selected_cover_option") or selection.get("option_id")
    if not isinstance(option_id, str) or option_id not in COVER_OPTION_IDS:
        raise ValidationError("cover selection must include selected_cover_option A, B, C, or D")
    return option_id


def _relative_or_text(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _build_cover_prompt(
    content: dict[str, Any],
    cover_slide: dict[str, Any],
    option_id: str,
    design_contract: dict[str, Any] | None,
    style_card: dict[str, Any],
) -> str:
    visible_text = "；".join(cover_slide.get("final_visible_text") or [cover_slide["title"]])
    negative = "；".join(cover_slide.get("negative_constraints") or ["不要英文占位", "不要伪文字"])
    acceptance = "；".join(cover_slide.get("acceptance_criteria") or ["中文标题清晰可读", "适合扩展成整套PPT"])
    prompt_constraints = "；".join(style_card.get("prompt_constraints") or [])
    risk_notes = "；".join(style_card.get("risk_notes") or [])
    route_family = design_contract.get("route_family") if design_contract else "fallback"
    communication_path = design_contract.get("communication_path") if design_contract else "fallback"
    source_policy = design_contract.get("source_policy", {}) if design_contract else {}
    tone_keywords = _list_or_default(
        _value_from_contract(design_contract, ("visual_system_intent", "tone_keywords")),
        ["专业", "清晰", "通用"],
    )
    return (
        "生成一张 16:9 中文 PPT 封面图，作为四种风格候选之一；优先目标 2K 画布 2048x1152，高清锐利，尽量避免低分辨率或压缩感图片。\n"
        f"候选编号：{option_id}\n"
        f"整套PPT标题：{content['deck_title']}\n"
        f"受众：{content['audience']}\n"
        f"PPT路线：{content['route']}\n"
        f"设计合同路线：route_family={route_family}；communication_path={communication_path}\n"
        f"内容调整边界：{source_policy.get('content_mutation_level', 'soft_polish')}，不得脱离阶段1页面规划。\n"
        f"视觉关键词：{'、'.join(tone_keywords)}\n"
        f"页面目的：{cover_slide['purpose']}\n"
        f"最终可见中文文字：{visible_text}\n"
        f"本候选风格方向：{style_card['style_positioning']}\n"
        f"构图策略：{style_card['composition']}\n"
        f"图像媒介：{style_card['visual_medium']}\n"
        f"配色策略：{style_card['palette_strategy']}\n"
        f"中文字体方向：{style_card['typography_direction']}\n"
        f"内页延展：{style_card['layout_extension']['cover_to_inner_pages']}\n"
        f"基础构图提示：{cover_slide.get('visual_composition') or '完整封面构图，标题层级清晰'}\n"
        f"候选风险提醒：{risk_notes}\n"
        f"额外提示词约束：{prompt_constraints}\n"
        f"禁止项：{negative}；不要出现英文占位词、拼音、乱码、假字或 lorem ipsum；不要新增 final_visible_text 之外的装饰性文字。\n"
        f"验收标准：{acceptance}；四张候选必须明显不同，不只是换颜色。"
    )


def _value_from_contract(source: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
    value: Any = source
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value
