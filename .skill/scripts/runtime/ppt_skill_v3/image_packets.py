from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .events import append_event
from .image_api_defaults import (
    DEFAULT_IMAGE_API_GENERATION_ENDPOINT,
    DEFAULT_IMAGE_API_MODEL,
    DEFAULT_IMAGE_API_OUTPUT_FORMAT,
    DEFAULT_IMAGE_API_PARALLELISM,
    DEFAULT_IMAGE_API_QUALITY,
    DEFAULT_IMAGE_API_RESPONSE_FORMAT,
    DEFAULT_IMAGE_API_SIZE,
)
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
from .json_io import read_json, write_json
from .image_prompt_docs import apply_image_style, refresh_prompt_delivery
from .image_style import image_style_snapshot, result_is_current
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
from .prompt_compiler import file_hash
from .image_prompt_plan import compile_current_prompt
from .layout_safety_contract import (
    layout_safety_contract_hash,
    layout_safety_contract_path,
    require_layout_safety_ready,
    safety_slide_for_prompt,
)
from .stage1_plan import load_stage1_slides
from .state import read_state, write_state
from .time_utils import now_iso
from .validation import (
    ValidationError,
    validate_image_result,
    require_matching_slide_indices,
    require_matching_visible_text,
    validate_content_asset,
    validate_deck_style,
    validate_design_contract,
    validate_layout_intent,
    validate_slide_prompt_briefs,
    validate_stage1_plan,
)


IMAGE_API_TOOL = OPENAI_IMAGE_API_TOOL
IMAGE_API_GENERATE_FUNCTION = "openai.images.generate"
IMAGE_API_EDIT_FUNCTION = "openai.images.edit"
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

    _require_stage2_open(state)
    packet_root = root / "_state" / "阶段2" / "packets"
    prompt_root = root / "_state" / "阶段2" / "final_prompts"
    purpose = "full_slide"

    content = briefs = deck_style = layout_intent = design_contract = None
    content_by_index: dict[int, dict[str, Any]] = {}
    brief_by_index: dict[int, dict[str, Any]] = {}
    asset_hashes: dict[str, str] = {}
    content = validate_content_asset(load_content(root))
    briefs = validate_slide_prompt_briefs(load_slide_prompt_briefs(root))
    deck_style = validate_deck_style(load_deck_style(root))
    layout_intent = validate_layout_intent(load_layout_intent(root))
    require_matching_slide_indices(("stage1_plan", plan), ("content", content), ("slide_prompt_briefs", briefs))
    require_matching_visible_text(content, briefs)
    if design_contract_path(root).exists():
        design_contract = validate_design_contract(load_design_contract(root))
    else:
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
    layout_safety = require_layout_safety_ready(root)
    asset_hashes["layout_safety_contract"] = layout_safety_contract_hash(root)

    slides = [slide for slide in plan["slides"] if not _has_current_formal_result(root, slide["slide_index"])]
    if not slides:
        state["status"] = "stage2_results_complete"
        state["required_actor"] = "main_controller"
        state["next_required_action"] = "阶段2正式整页图片已覆盖全部页面，可以打包图片版 PDF"
        write_state(root, state)
        refresh_prompt_delivery(root)
        return []
    total_packets = len(slides)
    packet_paths: list[Path] = []
    batch_group: dict[str, Any] | None = None
    batch_stage = "stage2"
    for packet_index, slide in enumerate(slides, start=1):
        slide_index = slide["slide_index"]
        if content is None or briefs is None or deck_style is None or layout_intent is None:
            raise ValidationError("stage2 prompt assets are required")
        prompt = compile_current_prompt(root, slide_index)
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
        packet.update(_route_input(generation_route, stage=normalized_stage))
        if normalized_stage == "stage2":
            packet["attempt_id"] = f"slide-{slide_index:03d}-attempt-001"
            packet["version"] = 1
            packet["layout_safety_contract_hash"] = layout_safety_contract_hash(root)
            packet["layout_safety_contract"] = str(layout_safety_contract_path(root).relative_to(root))
        apply_image_style(root, packet)
        prompt = packet["prompt"]
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
    state["next_required_action"] = _next_action_for_route(generation_route, "阶段2正式整页图片")
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
        "tool_call": route_tool_function(generation_route, edit=False),
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


def _route_input(route: str, *, stage: str) -> dict[str, Any]:
    normalized = normalize_image_generation_route(route)
    size_contract = image_size_contract()
    if normalized == IMAGE_ROUTE_OPENAI_IMAGE_API:
        return {
            "image_api_input": {
                "endpoint": DEFAULT_IMAGE_API_GENERATION_ENDPOINT,
                "model": DEFAULT_IMAGE_API_MODEL,
                "size": DEFAULT_IMAGE_API_SIZE,
                "aspectRatio": DEFAULT_IMAGE_API_SIZE,
                "quality": DEFAULT_IMAGE_API_QUALITY,
                "n": 1,
                "output_format": DEFAULT_IMAGE_API_OUTPUT_FORMAT,
                "response_format": DEFAULT_IMAGE_API_RESPONSE_FORMAT,
                **size_contract,
            }
        }
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
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
    if normalized == IMAGE_ROUTE_OPENAI_IMAGE_API:
        return f"主控大模型必须运行图片 API 批量执行器，按 6 并发{description}，优先目标 {DEFAULT_PPT_IMAGE_SIZE_16_9}，允许生成器返回存在轻微尺寸差异；尽量保留生成原始尺寸，并逐页记录 API evidence、batch、尺寸和图片 sha"
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return f"主控大模型必须调用 Codex 内置 image_gen 工具{description}，优先目标 {DEFAULT_PPT_IMAGE_SIZE_16_9}，允许生成器返回存在轻微尺寸差异；尽量保留生成原始尺寸，把输出复制到项目目录，并逐页记录 image_gen evidence、batch、尺寸和图片 sha"
    raise ValidationError(f"unsupported image generation route: {route}")


def _normalize_stage(stage: str) -> str:
    if stage in {"stage2", "阶段2"}:
        return "stage2"
    if stage in {"stage3", "stage3-background", "stage3_background", "阶段3"}:
        raise ValidationError("stage3 background image generation was removed from the formal workflow")
    raise ValidationError(f"unsupported image API stage: {stage}")


def _require_stage2_open(state: dict[str, Any]) -> None:
    if state["current_stage"] != "stage2" or not state["confirmed"].get("stage1_plan"):
        raise ValidationError("stage2 image packets require approved stage1 plan")
    if not state["confirmed"].get("stage2_cover_style"):
        raise ValidationError("stage2 image deck packets require approved cover style")
    skip = state.get("stage2_trial_skip", {})
    if not state["confirmed"].get("stage2_trial_first5") and not (skip.get("user_authorized") is True and skip.get("reason")):
        raise ValidationError("先确认总共5页试样；用户明确跳过时须记录授权理由")


def _has_current_formal_result(root: Path, slide_index: int) -> bool:
    path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
    if not path.exists():
        return False
    try:
        result = validate_image_result(read_json(path), production=False)
        return result.get("stage") == "stage2" and result.get("purpose") == "full_slide" and result_is_current(root, result)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _expected_output_relpath(stage: str, slide_index: int) -> str:
    if stage != "stage2":
        raise ValidationError("image packet output relpath is only defined for stage2")
    return f"阶段2_图片版PPT/img/slide_{slide_index:03d}.png"


# Backward-compatible name for old task cards and tests. It now creates packets
# for the current default image generation route.
dispatch_imagegen_packets = dispatch_image_generation_packets
