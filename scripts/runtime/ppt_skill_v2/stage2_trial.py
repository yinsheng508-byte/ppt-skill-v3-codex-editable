from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .events import append_event
from .image_batches import create_image_generation_batch
from .image_packets import (
    DEFAULT_IMAGE_GEN_QUALITY,
    DEFAULT_IMAGE_GEN_SIZE,
    DEFAULT_IMAGE_API_GENERATION_ENDPOINT,
    DEFAULT_IMAGE_API_MODEL,
    DEFAULT_IMAGE_API_PARALLELISM,
    DEFAULT_IMAGE_API_QUALITY,
    DEFAULT_IMAGE_API_SIZE,
    IMAGE_API_GENERATE_FUNCTION,
    IMAGE_API_TOOL,
    prompt_hash,
)
from .image_routes import (
    DEFAULT_IMAGE_GENERATION_ROUTE,
    IMAGE_ROUTE_CODEX_IMAGE_GEN,
    IMAGE_ROUTE_OPENAI_IMAGE_API,
    image_size_contract,
    normalize_image_generation_route,
    route_tool,
    route_tool_function,
)
from .json_io import read_json, write_json
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
from .prompt_compiler import compile_stage2_prompt, file_hash
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
    require_matching_slide_indices,
    require_matching_visible_text,
    validate_content_asset,
    validate_deck_style,
    validate_design_contract,
    validate_image_result,
    validate_layout_intent,
    validate_slide_prompt_briefs,
    validate_stage1_plan,
)


TRIAL_FIRST5_PURPOSE = "trial_first5"
TRIAL_FIRST5_GROUP_ID = "stage2-trial-first5-image-api"
REMAINING_GROUP_ID = "stage2-remaining-image-api"
DEFAULT_TRIAL_SAMPLE_COUNT = 3
MAX_TRIAL_SAMPLE_COUNT = 5


def select_trial_slide_indices(
    plan: dict[str, Any],
    extra_complex_slides: list[dict[str, Any]] | None = None,
    *,
    sample_count: int = DEFAULT_TRIAL_SAMPLE_COUNT,
) -> list[int]:
    validated = validate_stage1_plan(plan)
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1 or sample_count > MAX_TRIAL_SAMPLE_COUNT:
        raise ValidationError(f"stage2 trial sample_count must be between 1 and {MAX_TRIAL_SAMPLE_COUNT}")
    ordered = [slide["slide_index"] for slide in validated["slides"]]
    selected = ordered[:sample_count]
    extra_map = _extra_reason_map(extra_complex_slides, ordered)
    for slide_index in ordered:
        if slide_index in extra_map and slide_index not in selected:
            selected.append(slide_index)
    return selected


def dispatch_stage2_trial_first5_packets(
    run_dir: str | Path,
    *,
    extra_complex_slides: list[dict[str, Any]] | None = None,
    sample_count: int = DEFAULT_TRIAL_SAMPLE_COUNT,
    route: str | None = None,
) -> list[Path]:
    root = Path(run_dir)
    generation_route = normalize_image_generation_route(route)
    state = read_state(root)
    _require_stage2_trial_open(state)
    assets = _load_stage2_assets(root)
    slide_indices = select_trial_slide_indices(assets["plan"], extra_complex_slides, sample_count=sample_count)
    default_sample = set([slide["slide_index"] for slide in assets["plan"]["slides"][:sample_count]])
    extra_reasons = _extra_reason_map(extra_complex_slides, [slide["slide_index"] for slide in assets["plan"]["slides"]])
    reused_formal_slide_indices = [slide_index for slide_index in slide_indices if _has_valid_formal_stage2_result(root, slide_index)]
    dispatch_slide_indices = [slide_index for slide_index in slide_indices if slide_index not in reused_formal_slide_indices]
    _write_trial_selection(
        root,
        selected_slide_indices=slide_indices,
        dispatched_slide_indices=dispatch_slide_indices,
        reused_formal_slide_indices=reused_formal_slide_indices,
        sample_count=sample_count,
        extra_reasons=extra_reasons,
    )

    if not dispatch_slide_indices:
        summary = write_stage2_trial_summary(root, None)
        state["status"] = "waiting_user_trial_first5_confirmation"
        state["required_actor"] = "user"
        state["quality"]["stage2_trial_first5"] = "pending_user_review"
        state["user_artifacts"]["stage2_trial_first5"] = str(summary.relative_to(root))
        state["next_required_action"] = "等待用户确认阶段2B试样；本次试样全部复用已转正正式页面，没有重复生图"
        write_state(root, state)
        append_event(
            root,
            "stage2_trial_first5_reused_formal_results",
            "runtime",
            reused_count=len(reused_formal_slide_indices),
        )
        return []

    packet_paths = _dispatch_stage2_subset(
        root,
        assets,
        dispatch_slide_indices,
        purpose=TRIAL_FIRST5_PURPOSE,
        packet_root=root / "_state" / "阶段2" / "trial_first5" / "packets",
        prompt_root=root / "_state" / "阶段2" / "trial_first5" / "prompts",
        group_id=TRIAL_FIRST5_GROUP_ID,
        packet_prefix="stage2-trial-first5",
        expected_output=lambda slide_index: f"阶段2_图片版PPT/前5页试样/slide_{slide_index:03d}.png",
        route=generation_route,
        trial_selection=lambda slide_index: {
            "default_sample": slide_index in default_sample,
            "default_first5": slide_index in default_sample,
            "sample_count": sample_count,
            "extra_complex_reason": extra_reasons.get(slide_index),
        },
    )

    state["status"] = "waiting_for_stage2_trial_first5_results"
    state["required_actor"] = "main_controller"
    state["quality"]["stage2_trial_first5"] = "awaiting_results"
    if reused_formal_slide_indices:
        reused_text = "，已转正页面将直接复用不重复生图"
    else:
        reused_text = ""
    state["next_required_action"] = _next_action_for_route(
        generation_route,
        f"阶段2B试样（默认 {sample_count} 页，可含额外复杂页{reused_text}）",
    )
    write_state(root, state)
    append_event(
        root,
        "stage2_trial_first5_packets_dispatched",
        "runtime",
        packets_count=len(packet_paths),
        reused_formal_count=len(reused_formal_slide_indices),
        image_generation_route=generation_route,
    )
    return packet_paths


def dispatch_stage2_remaining_packets(
    run_dir: str | Path,
    *,
    route: str | None = None,
) -> list[Path]:
    root = Path(run_dir)
    generation_route = normalize_image_generation_route(route)
    state = read_state(root)
    if state["current_stage"] != "stage2" or not state["confirmed"].get("stage2_trial_first5"):
        raise ValidationError("stage2 remaining packets require approved trial first5")
    assets = _load_stage2_assets(root)
    missing = [
        slide["slide_index"]
        for slide in assets["plan"]["slides"]
        if not _has_valid_formal_stage2_result(root, slide["slide_index"])
    ]
    if not missing:
        state["status"] = "stage2_results_complete"
        state["required_actor"] = "main_controller"
        state["next_required_action"] = "阶段2正式整页图片已覆盖全部页面，可以打包图片版 PDF"
        write_state(root, state)
        return []

    packet_paths = _dispatch_stage2_subset(
        root,
        assets,
        missing,
        purpose="full_slide",
        packet_root=root / "_state" / "阶段2" / "packets",
        prompt_root=root / "_state" / "阶段2" / "final_prompts",
        group_id=REMAINING_GROUP_ID,
        packet_prefix="stage2-remaining",
        expected_output=lambda slide_index: f"阶段2_图片版PPT/img/slide_{slide_index:03d}.png",
        route=generation_route,
    )

    state["status"] = "waiting_for_stage2_remaining_image_results"
    state["required_actor"] = "main_controller"
    state["next_required_action"] = _next_action_for_route(generation_route, "剩余页面，并逐页记录正式 full_slide 结果")
    write_state(root, state)
    append_event(
        root,
        "stage2_remaining_packets_dispatched",
        "runtime",
        packets_count=len(packet_paths),
        image_generation_route=generation_route,
    )
    return packet_paths


def stage2_trial_first5_results_complete(run_dir: str | Path, batch_file: str | Path) -> bool:
    root = Path(run_dir)
    batch_path = _resolve_path(root, batch_file)
    if not batch_path.exists():
        return False
    batch = read_json(batch_path)
    return batch.get("purpose") == TRIAL_FIRST5_PURPOSE and batch.get("status") == "completed"


def write_stage2_trial_summary(run_dir: str | Path, batch_file: str | Path | None) -> Path:
    root = Path(run_dir)
    results = {}
    if batch_file is not None:
        batch = read_json(_resolve_path(root, batch_file))
        results = batch.get("results") if isinstance(batch.get("results"), dict) else {}
    target = root / "阶段2_图片版PPT" / "前5页试样" / "前5页试样说明.md"
    lines = [
        "# 阶段2B试样说明",
        "",
        "以下图片是阶段2B内部试样，用于确认整体视觉、文字、密度和风格方向；这不是阶段2最终图片版 PDF 确认。",
        "",
        "| 页码 | 来源 | 图片 | 结果记录 |",
        "| --- | --- | --- | --- |",
    ]
    rows: list[dict[str, Any]] = []
    rows.extend(_reused_trial_rows(root))
    for packet_id, result in sorted(results.items(), key=lambda item: item[1].get("slide_index", 0)):
        slide_index = result.get("slide_index")
        image_path = result.get("image_path", "")
        result_path = f"_state/阶段2/trial_first5/results/slide_{slide_index:03d}.json" if isinstance(slide_index, int) else ""
        rows.append(
            {
                "slide_index": slide_index,
                "source": "新生成试样",
                "image_path": image_path,
                "result_path": result_path,
            }
        )
    for row in sorted(rows, key=lambda item: item.get("slide_index") or 0):
        lines.append(f"| {row.get('slide_index')} | {row.get('source')} | `{row.get('image_path', '')}` | `{row.get('result_path', '')}` |")
    lines.extend(
        [
            "",
            "如果试样方向没问题，用户确认后主控会 promotion 已通过试样并继续生成剩余页面。",
            "已转正的封面候选直接作为正式封面页复用，不重复调用图片 API；如果封面本身需要修改，应返工阶段2A封面或明确要求重做封面。",
            "如果试样有问题，默认返工阶段2设计规划、版式意图或提示词，不修改阶段1页面文字合同。",
            "",
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def promote_stage2_trial_first5(run_dir: str | Path, *, force: bool = False) -> list[Path]:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage2" or not state["confirmed"].get("stage2_trial_first5"):
        raise ValidationError("trial first5 promotion requires user-approved trial first5")
    trial_result_paths = sorted((root / "_state" / "阶段2" / "trial_first5" / "results").glob("slide_*.json"))
    if not trial_result_paths:
        reused_rows = _reused_trial_rows(root)
        if not reused_rows:
            raise ValidationError("no trial first5 results to promote")
        state["status"] = "stage2_trial_first5_promoted"
        state["required_actor"] = "main_controller"
        state["next_required_action"] = "阶段2B试样均为已转正正式页面，无需 promotion；继续派发剩余页面"
        write_state(root, state)
        append_event(
            root,
            "stage2_trial_first5_promoted",
            "runtime",
            promoted_count=0,
            reused_count=len(reused_rows),
        )
        return []

    promoted_paths: list[Path] = []
    for trial_result_path in trial_result_paths:
        trial_result = _validate_trial_result(read_json(trial_result_path))
        slide_index = trial_result["slide_index"]
        trial_image_relpath = trial_result["image_path"]
        source_image = root / trial_image_relpath
        if not source_image.exists():
            raise FileNotFoundError(f"trial image missing: {source_image}")
        formal_image_relpath = f"阶段2_图片版PPT/img/slide_{slide_index:03d}{source_image.suffix.lower()}"
        formal_result_path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
        if formal_result_path.exists() and not force:
            raise ValidationError(f"formal stage2 result already exists for slide {slide_index}")

        dest_image = root / formal_image_relpath
        dest_image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_image, dest_image)
        promoted = dict(trial_result)
        promoted.update(
            {
                "purpose": "full_slide",
                "image_path": formal_image_relpath,
                "promoted_from_trial_first5": True,
                "trial_result_path": _relative_or_text(root, trial_result_path),
                "trial_image_path": trial_image_relpath,
                "result_path": _relative_or_text(root, formal_result_path),
                "created_at": now_iso(),
            }
        )
        validate_image_result(promoted, production=not bool(promoted.get("fixture")))
        write_json(formal_result_path, promoted)
        promoted_paths.append(formal_result_path)

    state["status"] = "stage2_trial_first5_promoted"
    state["required_actor"] = "main_controller"
    state["next_required_action"] = "阶段2B试样已 promotion 到正式结果；继续派发剩余页面"
    write_state(root, state)
    append_event(root, "stage2_trial_first5_promoted", "runtime", promoted_count=len(promoted_paths))
    return promoted_paths


def _trial_selection_path(root: Path) -> Path:
    return root / "_state" / "阶段2" / "trial_first5" / "selection.json"


def _write_trial_selection(
    root: Path,
    *,
    selected_slide_indices: list[int],
    dispatched_slide_indices: list[int],
    reused_formal_slide_indices: list[int],
    sample_count: int,
    extra_reasons: dict[int, str],
) -> None:
    write_json(
        _trial_selection_path(root),
        {
            "schema_version": "1.0",
            "selected_slide_indices": selected_slide_indices,
            "dispatched_slide_indices": dispatched_slide_indices,
            "reused_formal_slide_indices": reused_formal_slide_indices,
            "sample_count": sample_count,
            "extra_reasons": {str(key): value for key, value in extra_reasons.items()},
            "created_at": now_iso(),
        },
    )


def _reused_trial_rows(root: Path) -> list[dict[str, Any]]:
    selection_path = _trial_selection_path(root)
    if not selection_path.exists():
        return []
    selection = read_json(selection_path)
    reused_indices = selection.get("reused_formal_slide_indices")
    if not isinstance(reused_indices, list):
        return []
    rows: list[dict[str, Any]] = []
    for slide_index in reused_indices:
        if not isinstance(slide_index, int):
            continue
        result_path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
        if not result_path.exists():
            continue
        result = validate_image_result(read_json(result_path), production=False)
        source = "复用已选封面候选" if result.get("promoted_from_cover_option") else "复用已有正式页"
        rows.append(
            {
                "slide_index": slide_index,
                "source": source,
                "image_path": result.get("image_path", ""),
                "result_path": _relative_or_text(root, result_path),
            }
        )
    return rows


def _load_stage2_assets(root: Path) -> dict[str, Any]:
    plan = validate_stage1_plan(load_stage1_slides(root))
    content = validate_content_asset(load_content(root))
    briefs = validate_slide_prompt_briefs(load_slide_prompt_briefs(root))
    require_matching_slide_indices(("stage1_plan", plan), ("content", content), ("slide_prompt_briefs", briefs))
    require_matching_visible_text(content, briefs)
    deck_style = validate_deck_style(load_deck_style(root))
    layout_intent = validate_layout_intent(load_layout_intent(root))
    design_contract = validate_design_contract(load_design_contract(root))
    layout_safety = require_layout_safety_ready(root)
    return {
        "plan": plan,
        "content": content,
        "briefs": briefs,
        "deck_style": deck_style,
        "layout_intent": layout_intent,
        "design_contract": design_contract,
        "layout_safety": layout_safety,
        "content_by_index": {slide["slide_index"]: slide for slide in content["slides"]},
        "brief_by_index": {slide["slide_index"]: slide for slide in briefs["slides"]},
        "asset_hashes": {
            "content": file_hash(content_path(root)),
            "slide_prompt_briefs": file_hash(slide_prompt_briefs_path(root)),
            "design_contract": file_hash(design_contract_path(root)),
            "deck_style": file_hash(deck_style_path(root)),
            "layout_intent": file_hash(layout_intent_path(root)),
            "layout_safety_contract": layout_safety_contract_hash(root),
        },
    }


def _dispatch_stage2_subset(
    root: Path,
    assets: dict[str, Any],
    slide_indices: list[int],
    *,
    purpose: str,
    packet_root: Path,
    prompt_root: Path,
    group_id: str,
    packet_prefix: str,
    expected_output: Any,
    route: str,
    trial_selection: Any | None = None,
) -> list[Path]:
    generation_route = normalize_image_generation_route(route)
    total_packets = len(slide_indices)
    if total_packets < 1:
        raise ValidationError("stage2 packet dispatch requires at least one slide")
    routed_group_id = _routed_group_id(group_id, generation_route)
    execution_group_base = {
        "group_id": routed_group_id,
        "image_generation_route": generation_route,
        "required_tool": route_tool(generation_route),
        "tool_call": route_tool_function(generation_route),
        "mode": "parallel_required",
        "parallel_required": True,
        "total_packets": total_packets,
        "packet_index": 1,
        "max_parallel": min(DEFAULT_IMAGE_API_PARALLELISM, total_packets),
    }
    packet_paths: list[Path] = []
    plan_by_index = {slide["slide_index"]: slide for slide in assets["plan"]["slides"]}
    for packet_index, slide_index in enumerate(slide_indices, start=1):
        if slide_index not in plan_by_index:
            raise ValidationError(f"slide {slide_index} is not in stage1 plan")
        content_slide = assets["content_by_index"][slide_index]
        prompt_brief = assets["brief_by_index"][slide_index]
        prompt = compile_stage2_prompt(
            content_slide=content_slide,
            prompt_brief=prompt_brief,
            deck_style=assets["deck_style"],
            layout_intent=assets["layout_intent"],
            route=assets["content"]["route"],
            design_contract=assets["design_contract"],
            layout_safety_slide=safety_slide_for_prompt(assets["layout_safety"], slide_index),
        )
        if purpose == TRIAL_FIRST5_PURPOSE:
            prompt = "阶段2B试样：本图用于用户确认整体视觉方向，仍须达到正式页面质量。\n" + prompt
        execution_group = {**execution_group_base, "packet_index": packet_index}
        packet = {
            "schema_version": "2.0",
            "packet_id": f"{packet_prefix}-slide-{slide_index:03d}",
            "stage": "stage2",
            "purpose": purpose,
            "slide_index": slide_index,
            "title": plan_by_index[slide_index]["title"],
            "image_generation_route": generation_route,
            "execution_tool": route_tool(generation_route),
            "execution_tool_function": route_tool_function(generation_route),
            "execution_mode": "parallel_required",
            "execution_group": execution_group,
            "prompt": prompt,
            "prompt_hash": prompt_hash(prompt),
            "asset_hashes": assets["asset_hashes"],
            "layout_safety_contract": str(layout_safety_contract_path(root).relative_to(root)),
            "layout_safety_contract_hash": layout_safety_contract_hash(root),
            **image_size_contract(),
            "formal_mode": True,
            "created_at": now_iso(),
            "expected_output_relpath": expected_output(slide_index),
        }
        packet.update(_route_input(generation_route))
        if purpose == TRIAL_FIRST5_PURPOSE and trial_selection is not None:
            packet["trial_selection"] = trial_selection(slide_index)
        if purpose == "full_slide":
            packet["attempt_id"] = f"slide-{slide_index:03d}-attempt-001"
            packet["version"] = 1
        packet_path = packet_root / f"slide_{slide_index:03d}.json"
        write_json(packet_path, packet)
        packet_paths.append(packet_path)
        prompt_path = prompt_root / f"slide_{slide_index:03d}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(f"# 第 {slide_index} 页提示词\n\n{prompt}\n", encoding="utf-8")

    create_image_generation_batch(root, execution_group_base, packet_paths, stage="stage2", purpose=purpose, route=generation_route)
    return packet_paths


def _routed_group_id(group_id: str, route: str) -> str:
    if normalize_image_generation_route(route) == IMAGE_ROUTE_OPENAI_IMAGE_API:
        return group_id
    if group_id.endswith("-image-api"):
        return group_id.removesuffix("-image-api") + "-image-gen"
    return group_id + "-image-gen"


def _route_input(route: str) -> dict[str, Any]:
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
                "output_format": "png",
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
                "tool_argument_policy": "built_in_image_gen_size_is_a_target_not_a_guaranteed_raw_argument",
            }
        }
    raise ValidationError(f"unsupported image generation route: {route}")


def _next_action_for_route(route: str, description: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == DEFAULT_IMAGE_GENERATION_ROUTE:
        return f"调用 Codex 内置 image_gen 工具生成{description}，优先目标 2048x1152，尽量保留生成原始尺寸，把输出复制到项目目录，并逐页记录 image_gen evidence、batch、尺寸和图片 sha"
    return f"运行图片 API 批量执行器生成{description}，优先目标 2048x1152，尽量保留生成原始尺寸，并逐页记录 API evidence、batch、尺寸和图片 sha"


def _require_stage2_trial_open(state: dict[str, Any]) -> None:
    if state["current_stage"] != "stage2" or not state["confirmed"].get("stage1_plan"):
        raise ValidationError("stage2 trial first5 requires approved stage1 plan")
    if not state["confirmed"].get("stage2_cover_style"):
        raise ValidationError("stage2 trial first5 requires approved cover style")
    if state["confirmed"].get("stage2_trial_first5"):
        raise ValidationError("stage2 trial first5 is already approved")


def _extra_reason_map(extra_complex_slides: list[dict[str, Any]] | None, available_indices: list[int]) -> dict[int, str]:
    if not extra_complex_slides:
        return {}
    available = set(available_indices)
    extra: dict[int, str] = {}
    for position, item in enumerate(extra_complex_slides, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"extra_complex_slides[{position}] must be an object")
        slide_index = item.get("slide_index")
        reason = item.get("reason")
        if not isinstance(slide_index, int):
            raise ValidationError(f"extra_complex_slides[{position}].slide_index must be an integer")
        if slide_index not in available:
            raise ValidationError(f"extra_complex_slides[{position}].slide_index is not in stage1 plan")
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError(f"extra_complex_slides[{position}].reason is required")
        extra[slide_index] = reason.strip()
    return extra


def _validate_trial_result(data: dict[str, Any]) -> dict[str, Any]:
    result = validate_image_result(data, production=not bool(data.get("fixture")))
    if result["stage"] != "stage2" or result.get("purpose") != TRIAL_FIRST5_PURPOSE:
        raise ValidationError("only stage2 trial_first5 results can be promoted")
    return result


def _has_valid_formal_stage2_result(root: Path, slide_index: int) -> bool:
    result_path = root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
    if not result_path.exists():
        return False
    try:
        raw = read_json(result_path)
        result = validate_image_result(raw, production=not bool(raw.get("fixture")))
    except Exception:
        return False
    if result.get("stage") != "stage2" or result.get("purpose") != "full_slide":
        return False
    image_path = root / result["image_path"]
    return image_path.exists() and image_path.is_file()


def _resolve_path(root: Path, path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else root / value


def _relative_or_text(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
