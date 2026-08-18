from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .events import append_event
from .image_batches import create_image_generation_batch
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
from .json_io import write_json
from .json_io import read_json
from .planning_assets import (
    content_path,
    deck_style_path,
    design_contract_path,
    layout_intent_path,
    load_content,
    load_deck_style,
    load_design_contract,
    load_layout_intent,
    load_slide_prompt_briefs,
    slide_prompt_briefs_path,
)
from .prompt_compiler import compile_stage2_prompt, compile_stage3_background_prompt, file_hash
from .layout_safety_contract import (
    layout_safety_contract_hash,
    layout_safety_contract_path,
    require_layout_safety_ready,
    safety_slide_for_prompt,
)
from .stage1_plan import load_stage1_slides
from .stage3_restore_targets import restore_targets_hash
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .state import read_state, write_state
from .text_ownership_map import load_text_ownership_map, restore_targets_for_slide, text_ownership_map_hash, text_ownership_map_path
from .time_utils import now_iso
from .validation import (
    ValidationError,
    require_matching_slide_indices,
    require_matching_visible_text,
    validate_content_asset,
    validate_deck_style,
    validate_design_contract,
    validate_layout_intent,
    validate_slide_prompt_briefs,
    validate_stage1_plan,
)
from .validation import STAGE3_BACKGROUND_PURPOSE, STAGE3_BACKGROUND_ROUTE, validate_image_result


IMAGE_API_TOOL = OPENAI_IMAGE_API_TOOL
IMAGE_API_GENERATE_FUNCTION = "openai.images.generate"
IMAGE_API_EDIT_FUNCTION = "openai.images.edit"
DEFAULT_IMAGE_API_MODEL = "gpt-image-2-vip"
DEFAULT_IMAGE_API_SIZE = DEFAULT_PPT_IMAGE_SIZE_16_9
DEFAULT_IMAGE_API_QUALITY = "high"
DEFAULT_IMAGE_API_PARALLELISM = 6
DEFAULT_IMAGE_API_GENERATION_ENDPOINT = "/v1/draw/completions"
DEFAULT_IMAGE_GEN_SIZE = DEFAULT_PPT_IMAGE_SIZE_16_9
DEFAULT_IMAGE_GEN_QUALITY = "auto"


def prompt_hash(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def dispatch_image_generation_packets(
    run_dir: str | Path,
    stage: str,
    *,
    route: str | None = None,
) -> list[Path]:
    root = Path(run_dir)
    generation_route = normalize_image_generation_route(route)
    normalized_stage = _normalize_stage(stage)
    state = read_state(root)
    plan = validate_stage1_plan(load_stage1_slides(root))

    if normalized_stage == "stage2":
        _require_stage2_open(state)
        packet_root = root / "_state" / "阶段2" / "packets"
        prompt_root = root / "_state" / "阶段2" / "final_prompts"
        purpose = "full_slide"
    else:
        _require_stage3_open(state)
        packet_root = root / "_state" / "阶段3" / "packets"
        prompt_root = root / "_state" / "阶段3" / "no_text_background_prompts"
        purpose = STAGE3_BACKGROUND_PURPOSE

    content = briefs = deck_style = layout_intent = design_contract = None
    content_by_index: dict[int, dict[str, Any]] = {}
    brief_by_index: dict[int, dict[str, Any]] = {}
    asset_hashes: dict[str, str] = {}
    if normalized_stage in {"stage2", "stage3-background"}:
        content = validate_content_asset(load_content(root))
        briefs = validate_slide_prompt_briefs(load_slide_prompt_briefs(root))
        deck_style = validate_deck_style(load_deck_style(root))
        layout_intent = validate_layout_intent(load_layout_intent(root))
        require_matching_slide_indices(("stage1_plan", plan), ("content", content), ("slide_prompt_briefs", briefs))
        require_matching_visible_text(content, briefs)
        if normalized_stage == "stage3-background":
            plan = apply_stage3_scope(plan, state, "stage1_plan")
            content = apply_stage3_scope(content, state, "content")
            briefs = apply_stage3_scope(briefs, state, "slide_prompt_briefs")
        if design_contract_path(root).exists():
            design_contract = validate_design_contract(load_design_contract(root))
        elif normalized_stage == "stage2":
            raise ValidationError("stage2 prompt compilation requires _state/阶段1/design_contract.json")
        content_by_index = {slide["slide_index"]: slide for slide in content["slides"]}
        brief_by_index = {slide["slide_index"]: slide for slide in briefs["slides"]}
        asset_hashes = {
            "content": file_hash(content_path(root)),
            "slide_prompt_briefs": file_hash(slide_prompt_briefs_path(root)),
            "deck_style": file_hash(deck_style_path(root)),
            "layout_intent": file_hash(layout_intent_path(root)),
        }
        if design_contract is not None:
            asset_hashes["design_contract"] = file_hash(design_contract_path(root))
        layout_safety = require_layout_safety_ready(root) if normalized_stage == "stage2" else None
        if normalized_stage == "stage2":
            asset_hashes["layout_safety_contract"] = layout_safety_contract_hash(root)
        else:
            ownership = apply_stage3_scope(load_text_ownership_map(root), state, "text_ownership_map", strict=True)
            require_matching_slide_indices(("stage1_plan", plan), ("text_ownership_map", ownership))
            asset_hashes["text_ownership_map"] = text_ownership_map_hash(root)
            if text_ownership_map_path(root).exists():
                asset_hashes["text_ownership_map_file"] = file_hash(text_ownership_map_path(root))
            layout_safety = None
            ownership_map = ownership
    else:
        layout_safety = None
        ownership_map = None

    slides = plan["slides"]
    total_packets = len(slides)
    packet_paths: list[Path] = []
    batch_group: dict[str, Any] | None = None
    batch_stage = "stage2" if normalized_stage == "stage2" else "stage3"
    for packet_index, slide in enumerate(slides, start=1):
        slide_index = slide["slide_index"]
        if normalized_stage == "stage2":
            if content is None or briefs is None or deck_style is None or layout_intent is None:
                raise ValidationError("stage2 prompt assets are required")
            prompt = compile_stage2_prompt(
                content_slide=content_by_index[slide_index],
                prompt_brief=brief_by_index[slide_index],
                deck_style=deck_style,
                layout_intent=layout_intent,
                route=content["route"],
                design_contract=design_contract,
                layout_safety_slide=safety_slide_for_prompt(layout_safety, slide_index),
            )
        else:
            if content is None or briefs is None or deck_style is None or layout_intent is None:
                raise ValidationError("stage3 prompt assets are required")
            source_stage2 = _load_stage2_source(root, slide_index)
            restore_targets = restore_targets_for_slide(ownership_map, slide_index)
            target_hash = restore_targets_hash(restore_targets)
            prompt = compile_stage3_background_prompt(
                content_slide=content_by_index[slide_index],
                prompt_brief=brief_by_index[slide_index],
                deck_style=deck_style,
                layout_intent=layout_intent,
                source_stage2=source_stage2,
                restore_targets=restore_targets,
            )
        execution_group = _execution_group(normalized_stage, total_packets, packet_index, route=generation_route)
        if batch_group is None:
            batch_group = execution_group
        packet = {
            "schema_version": "2.0",
            "packet_id": f"{normalized_stage}-slide-{slide_index:03d}",
            "stage": batch_stage,
            "purpose": purpose,
            "slide_index": slide_index,
            "title": slide["title"],
            "image_generation_route": generation_route,
            "execution_tool": route_tool(generation_route),
            "execution_tool_function": execution_group["tool_call"],
            "execution_mode": "parallel_required",
            "execution_group": execution_group,
            "prompt": prompt,
            "prompt_hash": prompt_hash(prompt),
            "asset_hashes": asset_hashes,
            **image_size_contract(),
            "formal_mode": True,
            "created_at": now_iso(),
            "expected_output_relpath": _expected_output_relpath(normalized_stage, slide_index),
        }
        scope = stage3_scope_summary(state)
        if normalized_stage == "stage3-background" and scope is not None:
            packet["stage3_scope"] = scope
        packet.update(_route_input(generation_route, stage=normalized_stage, source_stage2=source_stage2 if normalized_stage != "stage2" else None))
        if normalized_stage == "stage2":
            packet["attempt_id"] = f"slide-{slide_index:03d}-attempt-001"
            packet["version"] = 1
            packet["layout_safety_contract_hash"] = layout_safety_contract_hash(root)
            packet["layout_safety_contract"] = str(layout_safety_contract_path(root).relative_to(root))
        else:
            packet.update(
                {
                    "background_route": STAGE3_BACKGROUND_ROUTE,
                    "source_stage2": source_stage2,
                    "restore_targets": restore_targets,
                    "restore_targets_hash": target_hash,
                    "text_ownership_map_hash": text_ownership_map_hash(root),
                    "text_ownership_map": str(text_ownership_map_path(root).relative_to(root)),
                    "remove_text_scope": [
                        "title",
                        "body",
                        "page_number",
                        "section_label",
                        "readable_chart_labels_if_recreated_as_text",
                    ],
                    "preserve_visual_scope": [
                        "composition",
                        "complex_illustrations",
                        "photos",
                        "icons",
                        "cards",
                        "lines",
                        "charts_as_visual_texture",
                        "lighting",
                        "colors",
                    ],
                }
            )
        packet_path = packet_root / f"slide_{slide_index:03d}.json"
        write_json(packet_path, packet)
        packet_paths.append(packet_path)
        if prompt_root is not None:
            prompt_path = prompt_root / f"slide_{slide_index:03d}.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(f"# 第 {slide_index} 页提示词\n\n{prompt}\n", encoding="utf-8")

    if batch_group is not None:
        create_image_generation_batch(root, batch_group, packet_paths, stage=batch_stage, purpose=purpose, route=generation_route)

    state["status"] = "waiting_for_image_generation_results"
    state["required_actor"] = "main_controller"
    if normalized_stage == "stage2":
        state["next_required_action"] = _next_action_for_route(generation_route, "阶段2正式整页图片")
    else:
        state["next_required_action"] = _next_action_for_route(generation_route, "基于阶段2参考图生成阶段3保真去字背景")
    write_state(root, state)
    append_event(
        root,
        "image_generation_packets_dispatched",
        "runtime",
        stage=normalized_stage,
        packets_count=len(packet_paths),
        image_generation_route=generation_route,
        execution_tool=route_tool(generation_route),
        execution_mode="parallel_required",
        stage3_scope=stage3_scope_summary(state) if normalized_stage == "stage3-background" else None,
    )
    return packet_paths


def dispatch_image_api_packets(run_dir: str | Path, stage: str) -> list[Path]:
    return dispatch_image_generation_packets(run_dir, stage, route=IMAGE_ROUTE_OPENAI_IMAGE_API)


def _execution_group(stage: str, total_packets: int, packet_index: int, *, route: str) -> dict[str, Any]:
    generation_route = normalize_image_generation_route(route)
    return {
        "group_id": _group_id(stage, generation_route),
        "image_generation_route": generation_route,
        "required_tool": route_tool(generation_route),
        "tool_call": route_tool_function(generation_route, edit=stage == "stage3-background"),
        "mode": "parallel_required",
        "parallel_required": True,
        "total_packets": total_packets,
        "packet_index": packet_index,
        "max_parallel": min(DEFAULT_IMAGE_API_PARALLELISM, max(total_packets, 1)),
    }


def _group_id(stage: str, route: str) -> str:
    if normalize_image_generation_route(route) == IMAGE_ROUTE_OPENAI_IMAGE_API:
        return f"{stage}-image-api"
    return f"{stage}-image-gen"


def _stage3_image_api_input(source_stage2: dict[str, Any]) -> dict[str, Any]:
    size_contract = image_size_contract()
    provider_url = source_stage2.get("provider_image_url")
    if isinstance(provider_url, str) and provider_url.strip():
        return {
            "endpoint": DEFAULT_IMAGE_API_GENERATION_ENDPOINT,
            "model": DEFAULT_IMAGE_API_MODEL,
            "size": DEFAULT_IMAGE_API_SIZE,
            "aspectRatio": DEFAULT_IMAGE_API_SIZE,
            "quality": DEFAULT_IMAGE_API_QUALITY,
            "n": 1,
            "output_format": "png",
            **size_contract,
            "urls": [provider_url],
            "edit_intent": "remove_editable_text_only",
        }
    return {
        "endpoint": "/v1/images/edits",
        "model": DEFAULT_IMAGE_API_MODEL,
        "size": DEFAULT_IMAGE_API_SIZE,
        "quality": DEFAULT_IMAGE_API_QUALITY,
        "n": 1,
        "output_format": "png",
        **size_contract,
        "referenced_image_paths": [source_stage2["image_path"]],
        "edit_intent": "remove_editable_text_only",
    }


def _route_input(route: str, *, stage: str, source_stage2: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_image_generation_route(route)
    size_contract = image_size_contract()
    if normalized == IMAGE_ROUTE_OPENAI_IMAGE_API:
        if stage == "stage3-background":
            if source_stage2 is None:
                raise ValidationError("stage3 image API input requires source_stage2")
            return {"image_api_input": _stage3_image_api_input(source_stage2)}
        return {
            "image_api_input": {
                "endpoint": DEFAULT_IMAGE_API_GENERATION_ENDPOINT,
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
        if stage == "stage3-background":
            if source_stage2 is None:
                raise ValidationError("stage3 image_gen input requires source_stage2")
            return {
                "image_gen_input": {
                    "mode": "edit",
                    "tool": "image_gen.imagegen",
                    "size": DEFAULT_IMAGE_GEN_SIZE,
                    "quality": DEFAULT_IMAGE_GEN_QUALITY,
                    "output_format": "png",
                    "project_bound": True,
                    "edit_intent": "remove_editable_text_only",
                    **size_contract,
                    "referenced_image_paths": [source_stage2["image_path"]],
                    "expected_save_policy": "copy_generated_output_to_expected_output_relpath_then_record_result",
                }
            }
        return {
            "image_gen_input": {
                "mode": "generate",
                "tool": "image_gen.imagegen",
                "size": DEFAULT_IMAGE_GEN_SIZE,
                "quality": DEFAULT_IMAGE_GEN_QUALITY,
                "output_format": "png",
                "project_bound": True,
                **size_contract,
                "expected_save_policy": "copy_generated_output_to_expected_output_relpath_then_record_result",
            }
        }
    raise ValidationError(f"unsupported image generation route: {route}")


def _next_action_for_route(route: str, description: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == DEFAULT_IMAGE_GENERATION_ROUTE:
        return f"主控大模型必须调用 Codex 内置 image_gen 工具{description}，优先目标 2048x1152，尽量保留生成原始尺寸，把输出复制到项目目录，并逐页记录 image_gen evidence、batch、尺寸和图片 sha"
    return f"主控大模型必须运行图片 API 批量执行器，按 6 并发{description}，优先目标 2048x1152，尽量保留生成原始尺寸，并逐页记录 API evidence、batch、尺寸和图片 sha"


def _normalize_stage(stage: str) -> str:
    if stage in {"stage2", "阶段2"}:
        return "stage2"
    if stage in {"stage3", "stage3-background", "stage3_background", "阶段3"}:
        return "stage3-background"
    raise ValidationError(f"unsupported image API stage: {stage}")


def _require_stage2_open(state: dict[str, Any]) -> None:
    if state["current_stage"] != "stage2" or not state["confirmed"].get("stage1_plan"):
        raise ValidationError("stage2 image packets require approved stage1 plan")
    if not state["confirmed"].get("stage2_cover_style"):
        raise ValidationError("stage2 image deck packets require approved cover style")


def _require_stage3_open(state: dict[str, Any]) -> None:
    if state["current_stage"] != "stage3" or not state["confirmed"].get("stage2_image_deck"):
        raise ValidationError("stage3 background packets require approved stage2 image deck")


def _build_prompt(slide: dict[str, Any], stage: str) -> str:
    if stage == "stage2":
        return (
            "生成一张 16:9 中文 PPT 整页图片。\n"
            f"页面标题：{slide['title']}\n"
            f"页面目的：{slide['purpose']}\n"
            f"核心内容：{slide['core_content']}\n"
            f"视觉意图：{slide['visual_intent']}\n"
            "要求：中文文字必须清晰、真实可读；不要出现英文占位词、拼音、乱码、假字或 lorem ipsum；"
            "保持信息层级清楚，适合作为阶段2图片版 PDF 的单页。"
        )
    return (
        "生成一张 16:9 PPT 无字背景图。\n"
        f"参考页面标题：{slide['title']}\n"
        f"页面目的：{slide['purpose']}\n"
        f"视觉意图：{slide['visual_intent']}\n"
        "要求：画面中不要出现任何文字、数字、字母、标志、可读字符或类似文字的纹理；"
        "背景需要给后续可编辑中文文本留出清晰层级和留白。"
    )


def _expected_output_relpath(stage: str, slide_index: int) -> str:
    if stage == "stage2":
        return f"阶段2_图片版PPT/img/slide_{slide_index:03d}.png"
    return f"阶段3_可编辑PPT/img/background_{slide_index:03d}.png"


def _load_stage2_source(root: Path, slide_index: int) -> dict[str, Any]:
    result_path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
    if not result_path.exists():
        raise ValidationError(f"stage3 background packet requires stage2 image result for slide {slide_index}")
    result = validate_image_result(read_json(result_path), production=False)
    image_path = root / result["image_path"]
    if not image_path.exists():
        raise FileNotFoundError(f"stage2 source image does not exist: {image_path}")
    source = {
        "image_path": result["image_path"],
        "result_path": str(result_path.relative_to(root)),
        "image_sha256": result["image_sha256"],
        "generation_id": result.get("generation_id", ""),
    }
    if isinstance(result.get("provider_image_url"), str) and result["provider_image_url"].strip():
        source["provider_image_url"] = result["provider_image_url"]
    return source


# Backward-compatible name for old task cards and tests. It now creates default
# image generation route packets, which prefer the Codex built-in image_gen path.
dispatch_imagegen_packets = dispatch_image_generation_packets
