from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .canonical_images import CANONICAL_POLICIES, canonicalize_image, parse_size
from .dev_mode import require_dev_fixture_enabled
from .events import append_event
from .image_batches import record_image_generation_batch_result, require_image_generation_batch_for_packet
from .image_geometry import read_image_dimensions
from .image_routes import (
    CODEX_IMAGE_GEN_TOOL,
    DEFAULT_PPT_IMAGE_SIZE_16_9,
    IMAGE_POSTPROCESS_POLICY_NO_DOWNSCALE,
    IMAGE_ROUTE_CODEX_IMAGE_GEN,
    IMAGE_ROUTE_OPENAI_IMAGE_API,
    IMAGE_SIZE_POLICY_PRESERVE_GENERATED_RASTER,
    OPENAI_IMAGE_API_TOOL,
    PREFERRED_PPT_IMAGE_HEIGHT_PX,
    PREFERRED_PPT_IMAGE_WIDTH_PX,
    evidence_path_for_route,
    normalize_image_generation_route,
    route_tool,
)
from .json_io import read_json, write_json
from .cover_options import cover_option_results_complete, write_cover_options_review
from .stage2_trial import stage2_trial_first5_results_complete, write_stage2_trial_summary
from .state import read_state, write_state
from .time_utils import now_iso
from .validation import STAGE3_BACKGROUND_PURPOSE, STAGE3_BACKGROUND_ROUTE, ValidationError, validate_image_result


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_API_PROVIDER = OPENAI_IMAGE_API_TOOL
IMAGE_GEN_PROVIDER = CODEX_IMAGE_GEN_TOOL


def record_image_result(
    run_dir: str | Path,
    packet_file: str | Path,
    image_file: str | Path,
    provider: str,
    source: str,
    generation_id: str,
    *,
    tool_call_id: str | None = None,
    image_gen_result_id: str | None = None,
    api_call_id: str | None = None,
    image_api_result_id: str | None = None,
    request_id: str | None = None,
    api_base_url: str | None = None,
    api_endpoint: str | None = None,
    model: str | None = None,
    api_evidence_path: str | None = None,
    image_gen_evidence_path: str | None = None,
    provider_image_url: str | None = None,
    canonical_policy: str | None = None,
    canonical_size: str | None = None,
    canonical_method: str = "fit_center_crop",
    dev_fixture: bool = False,
) -> dict[str, Any]:
    if dev_fixture:
        require_dev_fixture_enabled()

    root = Path(run_dir)
    packet_path = Path(packet_file)
    packet = read_json(packet_path)
    generation_route = normalize_image_generation_route(packet.get("image_generation_route") or packet.get("execution_tool"))
    expected_tool = route_tool(generation_route)
    if packet.get("execution_tool") != expected_tool:
        raise ValidationError(f"packet.execution_tool must be {expected_tool}")
    stage = packet.get("stage")
    purpose = packet.get("purpose") or ("full_slide" if stage == "stage2" else "stage3_background")
    option_id = packet.get("option_id")
    slide_index = packet.get("slide_index")
    if stage not in {"stage2", "stage3"}:
        raise ValidationError("packet.stage must be stage2 or stage3")
    if not isinstance(slide_index, int):
        raise ValidationError("packet.slide_index must be an integer")

    image_path = Path(image_file)
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"image file not found: {image_path}")
    suffix = image_path.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValidationError(f"unsupported image suffix: {suffix}")
    resolved_canonical_policy = canonical_policy or packet.get("canonical_policy") or "preserve_api_raster"
    if resolved_canonical_policy not in CANONICAL_POLICIES:
        raise ValidationError(f"unsupported canonical image policy: {resolved_canonical_policy}")
    if dev_fixture:
        if generation_route == IMAGE_ROUTE_OPENAI_IMAGE_API:
            api_call_id = api_call_id or tool_call_id or f"dev-api-call-{generation_id}"
            image_api_result_id = image_api_result_id or image_gen_result_id or f"dev-image-api-result-{generation_id}"
            tool_call_id = tool_call_id or api_call_id
            image_gen_result_id = image_gen_result_id or image_api_result_id
        else:
            tool_call_id = tool_call_id or f"dev-image-gen-call-{generation_id}"
            image_gen_result_id = image_gen_result_id or generation_id
    else:
        if generation_route == IMAGE_ROUTE_OPENAI_IMAGE_API:
            api_call_id = api_call_id or tool_call_id
            image_api_result_id = image_api_result_id or image_gen_result_id
            if not isinstance(api_call_id, str) or not api_call_id.strip():
                raise ValidationError("production image_result requires api_call_id from image API")
            if not isinstance(image_api_result_id, str) or not image_api_result_id.strip():
                raise ValidationError("production image_result requires image_api_result_id")
            tool_call_id = tool_call_id or api_call_id
            image_gen_result_id = image_gen_result_id or image_api_result_id
        else:
            image_gen_result_id = image_gen_result_id or generation_id
            if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                raise ValidationError("production codex_image_gen result requires tool_call_id")
            if not isinstance(image_gen_result_id, str) or not image_gen_result_id.strip():
                raise ValidationError("production codex_image_gen result requires image_gen_result_id")

    batch_path = require_image_generation_batch_for_packet(root, packet)
    execution_group = packet["execution_group"]
    input_dimensions = read_image_dimensions(image_path)
    target_size_contract = _target_size_contract(packet)
    preferred_size_contract = _preferred_minimum_size_contract(packet)
    size_policy = _size_policy(packet)
    postprocess_policy = _postprocess_policy(packet)

    recorded_image_path = image_path
    postprocess_manifest_path: Path | None = None
    postprocess: dict[str, Any] | None = None
    if resolved_canonical_policy == "normalize_at_stage2":
        if not isinstance(canonical_size, str) or not canonical_size.strip():
            canonical_size = _canonical_size_from_packet(packet)
        target_size = parse_size(canonical_size)
        if stage == "stage3":
            _require_stage3_source_canonical(root, packet, target_size)
        canonical_dirname = "canonical_api_outputs" if generation_route == IMAGE_ROUTE_OPENAI_IMAGE_API else "canonical_image_gen_outputs"
        canonical_dir = root / "_state" / ("阶段2" if stage == "stage2" else "阶段3") / canonical_dirname
        canonical_output = canonical_dir / f"{Path(image_path).stem}.png"
        postprocess = canonicalize_image(image_path, canonical_output, target_size=target_size, method=canonical_method)
        recorded_image_path = canonical_output
        postprocess_manifest_path = root / "_state" / ("阶段2" if stage == "stage2" else "阶段3") / "postprocess" / f"{packet.get('packet_id', Path(image_path).stem)}.json"
        postprocess_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(postprocess_manifest_path, _relativize_postprocess(root, postprocess))

    recorded_suffix = recorded_image_path.suffix.lower()
    rel_image_path = _visible_image_relpath_for_purpose(stage, purpose, slide_index, option_id, recorded_suffix)
    result_path = _result_path(root, stage, purpose, slide_index, option_id)
    dimensions = read_image_dimensions(recorded_image_path)
    postprocess_size_warnings = _postprocess_size_warnings(input_dimensions, dimensions, postprocess is not None)
    size_review = _size_review(dimensions, target_size_contract, preferred_size_contract, extra_warnings=postprocess_size_warnings)
    image_sha256 = _sha256_file(recorded_image_path)
    if generation_route == IMAGE_ROUTE_CODEX_IMAGE_GEN and not image_gen_evidence_path:
        evidence_image_path = image_path if postprocess is not None else recorded_image_path
        evidence_image_sha = _sha256_file(evidence_image_path)
        image_gen_evidence_path = _write_image_gen_evidence(
            root,
            packet_path,
            packet,
            evidence_image_path,
            image_sha256=evidence_image_sha,
            generation_id=generation_id,
            tool_call_id=tool_call_id,
            image_gen_result_id=image_gen_result_id,
            model=model,
        )
    result = {
        "schema_version": "2.0",
        "stage": stage,
        "slide_index": slide_index,
        "image_generation_route": generation_route,
        "provider": provider,
        "source": source,
        "execution_tool": packet["execution_tool"],
        "generation_id": generation_id,
        "tool_call_id": tool_call_id,
        "image_gen_result_id": image_gen_result_id,
        "request_id": request_id,
        "provider_image_url": provider_image_url,
        "execution_group_id": execution_group["group_id"],
        "prompt_hash": packet["prompt_hash"],
        "image_sha256": image_sha256,
        "width_px": dimensions["width_px"],
        "height_px": dimensions["height_px"],
        "aspect_ratio": dimensions["aspect_ratio"],
        "target_size": {
            "width_px": target_size_contract[0],
            "height_px": target_size_contract[1],
        },
        "preferred_minimum_size": {
            "width_px": preferred_size_contract[0],
            "height_px": preferred_size_contract[1],
        },
        "size_policy": size_policy,
        "postprocess_policy": postprocess_policy,
        "meets_preferred_size": size_review["meets_preferred_size"],
        "size_warnings": size_review["size_warnings"],
        "canonical_policy": resolved_canonical_policy,
        "purpose": purpose,
        "option_id": option_id,
        "attempt_id": packet.get("attempt_id"),
        "version": packet.get("version"),
        "image_path": rel_image_path,
        "parallel_batch_path": _relative_or_text(root, batch_path),
        "created_at": now_iso(),
        "formal_mode": not dev_fixture,
        "fixture": dev_fixture,
        "packet_path": _relative_or_text(root, packet_path),
        "result_path": _relative_or_text(root, result_path),
    }
    if generation_route == IMAGE_ROUTE_OPENAI_IMAGE_API:
        result.update(
            {
                "api_call_id": api_call_id,
                "image_api_result_id": image_api_result_id,
                "api_base_url": api_base_url,
                "api_endpoint": api_endpoint,
                "model": model,
                "api_evidence_path": api_evidence_path,
            }
        )
    else:
        result["image_gen_evidence_path"] = image_gen_evidence_path
    if postprocess is not None and postprocess_manifest_path is not None:
        result["original_api_output"] = {
            "path": _relative_or_text(root, image_path),
            "image_sha256": _sha256_file(image_path),
            "width_px": input_dimensions["width_px"],
            "height_px": input_dimensions["height_px"],
            "aspect_ratio": input_dimensions["aspect_ratio"],
        }
        result["postprocess"] = {
            "type": "canonical_image_postprocess",
            "manifest_path": _relative_or_text(root, postprocess_manifest_path),
            "method": canonical_method,
            "target_size": postprocess["target_size"],
            "postprocess_policy": postprocess_policy,
        }
    if stage == "stage3":
        result["background_route"] = packet.get("background_route")
        result["source_stage2"] = packet.get("source_stage2")
        result["restore_targets_hash"] = packet.get("restore_targets_hash")
        result["restore_targets"] = packet.get("restore_targets", [])
        result["stage2_reference_policy"] = "reference_edit_remove_text_only"
    if stage == "stage3" and purpose == STAGE3_BACKGROUND_PURPOSE:
        result["background_route"] = result["background_route"] or STAGE3_BACKGROUND_ROUTE
    validate_image_result(result, production=not dev_fixture)
    if not dev_fixture:
        if generation_route == IMAGE_ROUTE_OPENAI_IMAGE_API:
            _validate_api_evidence(root, packet, result)
        else:
            _validate_image_gen_evidence(root, packet, result)

    dest = root / rel_image_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(recorded_image_path, dest)

    write_json(result_path, result)
    if generation_route == IMAGE_ROUTE_CODEX_IMAGE_GEN and image_gen_evidence_path:
        _update_image_gen_evidence_after_record(root, result)
    record_image_generation_batch_result(root, packet, result)
    _write_attempt_record(root, result, purpose, slide_index)

    state = read_state(root)
    state["required_actor"] = "main_controller"
    if purpose == "cover_option":
        state["status"] = "cover_option_result_recorded"
        if cover_option_results_complete(root):
            review = write_cover_options_review(root)
            state["status"] = "waiting_user_cover_style_selection"
            state["required_actor"] = "user"
            state["user_artifacts"]["stage2_cover_options"] = str(review.relative_to(root))
            state["quality"]["stage2_cover_options"] = "pending_user_review"
            state["next_required_action"] = "等待用户从四张封面候选中选择整套PPT风格"
        else:
            state["next_required_action"] = "继续记录剩余封面候选图片结果"
    elif purpose == "trial_first5":
        state["status"] = "stage2_trial_first5_result_recorded"
        if stage2_trial_first5_results_complete(root, batch_path):
            summary = write_stage2_trial_summary(root, batch_path)
            state["status"] = "waiting_user_trial_first5_confirmation"
            state["required_actor"] = "user"
            state["user_artifacts"]["stage2_trial_first5"] = str(summary.relative_to(root))
            state["quality"]["stage2_trial_first5"] = "pending_user_review"
            state["next_required_action"] = "等待用户确认阶段2B试样；有问题则返工阶段2设计规划和提示词"
        else:
            state["next_required_action"] = "继续记录剩余阶段2B试样图片结果"
    elif stage == "stage2":
        state["status"] = f"{stage}_image_result_recorded"
        state["next_required_action"] = "主控大模型检查阶段2图片结果，全部合格后打包图片版 PDF"
    else:
        state["status"] = f"{stage}_image_result_recorded"
        state["next_required_action"] = "主控大模型检查阶段3无字背景，合格后构建可编辑 PPT brief"
    write_state(root, state)
    append_event(
        root,
        "image_result_recorded",
        "runtime",
        stage=stage,
        slide_index=slide_index,
        purpose=purpose,
        option_id=option_id,
        image_generation_route=generation_route,
        api_call_id=api_call_id,
        image_api_result_id=image_api_result_id,
        image_gen_result_id=image_gen_result_id,
        request_id=request_id,
        dev_fixture=dev_fixture,
    )
    return result


def _visible_image_relpath(stage: str, slide_index: int, suffix: str) -> str:
    return _visible_image_relpath_for_purpose(stage, "full_slide" if stage == "stage2" else "stage3_background", slide_index, None, suffix)


def _visible_image_relpath_for_purpose(stage: str, purpose: str, slide_index: int, option_id: object, suffix: str) -> str:
    if purpose == "cover_option":
        if not isinstance(option_id, str) or not option_id.strip():
            raise ValidationError("cover option image result requires option_id")
        return f"阶段2_图片版PPT/封面风格候选/cover_option_{option_id}{suffix}"
    if purpose == "trial_first5":
        return f"阶段2_图片版PPT/前5页试样/slide_{slide_index:03d}{suffix}"
    if stage == "stage2":
        return f"阶段2_图片版PPT/img/slide_{slide_index:03d}{suffix}"
    return f"阶段3_可编辑PPT/img/background_{slide_index:03d}{suffix}"


def _target_size_contract(packet: dict[str, Any]) -> tuple[int, int]:
    return _size_tuple_from_packet(
        packet,
        "target_size",
        default=DEFAULT_PPT_IMAGE_SIZE_16_9,
    )


def _preferred_minimum_size_contract(packet: dict[str, Any]) -> tuple[int, int]:
    for source in _size_contract_sources(packet):
        value = source.get("preferred_minimum_size") or source.get("minimum_acceptable_size")
        if isinstance(value, dict):
            width = value.get("width_px")
            height = value.get("height_px")
            if (
                isinstance(width, int)
                and not isinstance(width, bool)
                and width > 0
                and isinstance(height, int)
                and not isinstance(height, bool)
                and height > 0
            ):
                return width, height
    return PREFERRED_PPT_IMAGE_WIDTH_PX, PREFERRED_PPT_IMAGE_HEIGHT_PX


def _size_policy(packet: dict[str, Any]) -> str:
    return _string_contract_value(packet, "size_policy", IMAGE_SIZE_POLICY_PRESERVE_GENERATED_RASTER)


def _postprocess_policy(packet: dict[str, Any]) -> str:
    return _string_contract_value(packet, "postprocess_policy", IMAGE_POSTPROCESS_POLICY_NO_DOWNSCALE)


def _canonical_size_from_packet(packet: dict[str, Any]) -> str:
    value = packet.get("canonical_size")
    if isinstance(value, str) and value.strip():
        return value
    return _string_contract_value(packet, "target_size", DEFAULT_PPT_IMAGE_SIZE_16_9)


def _string_contract_value(packet: dict[str, Any], key: str, default: str) -> str:
    for source in _size_contract_sources(packet):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _size_tuple_from_packet(packet: dict[str, Any], key: str, *, default: str) -> tuple[int, int]:
    for source in _size_contract_sources(packet):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return parse_size(value)
        if isinstance(value, dict):
            width = value.get("width_px")
            height = value.get("height_px")
            if (
                isinstance(width, int)
                and not isinstance(width, bool)
                and width > 0
                and isinstance(height, int)
                and not isinstance(height, bool)
                and height > 0
            ):
                return width, height
    return parse_size(default)


def _size_contract_sources(packet: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [packet]
    for key in ("image_gen_input", "image_api_input"):
        value = packet.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _postprocess_size_warnings(source_dimensions: dict[str, Any], result_dimensions: dict[str, Any], postprocessed: bool) -> list[str]:
    if not postprocessed:
        return []
    source_width = source_dimensions.get("width_px")
    source_height = source_dimensions.get("height_px")
    result_width = result_dimensions.get("width_px")
    result_height = result_dimensions.get("height_px")
    if not all(isinstance(value, int) for value in (source_width, source_height, result_width, result_height)):
        return []
    if result_width < source_width or result_height < source_height:
        return [f"postprocess_downscaled_from_{source_width}x{source_height}_to_{result_width}x{result_height}"]
    return []


def _size_review(
    dimensions: dict[str, Any],
    target_size: tuple[int, int],
    preferred_size: tuple[int, int],
    *,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    width = dimensions.get("width_px")
    height = dimensions.get("height_px")
    if not isinstance(width, int) or not isinstance(height, int):
        return {
            "meets_preferred_size": False,
            "size_warnings": ["image_dimensions_unreadable"] + (extra_warnings or []),
        }
    warnings: list[str] = list(extra_warnings or [])
    meets_preferred = width >= preferred_size[0] and height >= preferred_size[1]
    if not meets_preferred:
        warnings.append(f"below_preferred_2k_size_{preferred_size[0]}x{preferred_size[1]}")
    elif width != target_size[0] or height != target_size[1]:
        warnings.append(f"actual_raster_preserved_not_exact_target_{target_size[0]}x{target_size[1]}")
    return {
        "meets_preferred_size": meets_preferred,
        "size_warnings": warnings,
    }


def _require_stage3_source_canonical(root: Path, packet: dict[str, Any], target_size: tuple[int, int]) -> None:
    source_stage2 = packet.get("source_stage2")
    if not isinstance(source_stage2, dict):
        return
    result_path = source_stage2.get("result_path")
    if not isinstance(result_path, str) or not result_path.strip():
        return
    resolved = Path(result_path)
    if not resolved.is_absolute():
        resolved = root / resolved
    if not resolved.exists():
        return
    stage2_result = read_json(resolved)
    if stage2_result.get("canonical_policy") == "normalize_at_stage2":
        return
    if stage2_result.get("width_px") == target_size[0] and stage2_result.get("height_px") == target_size[1]:
        return
    raise ValidationError(
        "stage3 normalize_at_stage2 requires its source stage2 result to already use the same canonical canvas; "
        "record stage2 with canonical_policy=normalize_at_stage2 before generating stage3 backgrounds"
    )


def _result_path(root: Path, stage: str, purpose: str, slide_index: int, option_id: object) -> Path:
    if purpose == "cover_option":
        if not isinstance(option_id, str) or not option_id.strip():
            raise ValidationError("cover option result requires option_id")
        return root / "_state" / "阶段2" / "cover_options" / "results" / f"cover_option_{option_id}.json"
    if purpose == "trial_first5":
        return root / "_state" / "阶段2" / "trial_first5" / "results" / f"slide_{slide_index:03d}.json"
    if stage == "stage2":
        return root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json"
    return root / "_state" / "阶段3" / "no_text_background_results" / f"slide_{slide_index:03d}.json"


def _write_attempt_record(root: Path, result: dict[str, Any], purpose: str, slide_index: int) -> None:
    if purpose != "full_slide":
        return
    attempt_id = result.get("attempt_id") or f"slide-{slide_index:03d}-attempt-001"
    attempt_dir = root / "_state" / "阶段2" / "attempts" / f"slide_{slide_index:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    write_json(attempt_dir / f"{attempt_id}.json", result)


def _validate_api_evidence(root: Path, packet: dict[str, Any], result: dict[str, Any]) -> None:
    evidence_path = _state_path(root, result["api_evidence_path"], "image_result.api_evidence_path")
    if not evidence_path.exists() or not evidence_path.is_file():
        raise ValidationError(f"production image_result.api_evidence_path does not exist: {result['api_evidence_path']}")
    evidence = read_json(evidence_path)
    if evidence.get("provider") != IMAGE_API_PROVIDER:
        raise ValidationError("api evidence provider must be openai_image_api")
    evidence_image_sha = result["image_sha256"]
    original_api_output = result.get("original_api_output")
    if isinstance(original_api_output, dict) and isinstance(original_api_output.get("image_sha256"), str):
        evidence_image_sha = original_api_output["image_sha256"]
    expected = {
        "packet_id": packet.get("packet_id"),
        "api_call_id": result["api_call_id"],
        "image_api_result_id": result["image_api_result_id"],
        "api_endpoint": result["api_endpoint"],
        "model": result["model"],
        "image_sha256": evidence_image_sha,
    }
    for field, value in expected.items():
        if evidence.get(field) != value:
            raise ValidationError(f"api evidence {field} does not match image_result")
    if evidence.get("prompt_hash") not in {None, result["prompt_hash"]}:
        raise ValidationError("api evidence prompt_hash does not match image_result")
    if evidence.get("http_status") != 200:
        raise ValidationError("api evidence http_status must be 200")


def _write_image_gen_evidence(
    root: Path,
    packet_path: Path,
    packet: dict[str, Any],
    image_path: Path,
    *,
    image_sha256: str,
    generation_id: str,
    tool_call_id: str | None,
    image_gen_result_id: str | None,
    model: str | None,
) -> str:
    evidence_path = evidence_path_for_route(root, packet, IMAGE_ROUTE_CODEX_IMAGE_GEN)
    evidence = {
        "schema_version": "1.0",
        "provider": IMAGE_GEN_PROVIDER,
        "image_generation_route": IMAGE_ROUTE_CODEX_IMAGE_GEN,
        "execution_tool": IMAGE_GEN_PROVIDER,
        "packet_id": packet.get("packet_id"),
        "packet_path": _relative_or_text(root, packet_path),
        "prompt_hash": packet.get("prompt_hash"),
        "tool_call_id": tool_call_id,
        "generation_id": generation_id,
        "image_gen_result_id": image_gen_result_id,
        "model": model,
        "image_gen_input": packet.get("image_gen_input"),
        "output_image_path": _relative_or_text(root, image_path),
        "image_sha256": image_sha256,
        "created_at": now_iso(),
        "evidence_kind": "controller_recorded_codex_image_gen_tool_call",
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(evidence_path, evidence)
    return _relative_or_text(root, evidence_path)


def _validate_image_gen_evidence(root: Path, packet: dict[str, Any], result: dict[str, Any]) -> None:
    evidence_path = _state_path(root, result["image_gen_evidence_path"], "image_result.image_gen_evidence_path")
    if not evidence_path.exists() or not evidence_path.is_file():
        raise ValidationError(f"production image_result.image_gen_evidence_path does not exist: {result['image_gen_evidence_path']}")
    evidence = read_json(evidence_path)
    if evidence.get("provider") != IMAGE_GEN_PROVIDER:
        raise ValidationError("image_gen evidence provider must be codex_image_gen")
    evidence_image_sha = result["image_sha256"]
    original_output = result.get("original_api_output")
    if isinstance(original_output, dict) and isinstance(original_output.get("image_sha256"), str):
        evidence_image_sha = original_output["image_sha256"]
    expected = {
        "packet_id": packet.get("packet_id"),
        "tool_call_id": result["tool_call_id"],
        "image_gen_result_id": result["image_gen_result_id"],
        "image_sha256": evidence_image_sha,
    }
    for field, value in expected.items():
        if evidence.get(field) != value:
            raise ValidationError(f"image_gen evidence {field} does not match image_result")
    if evidence.get("prompt_hash") not in {None, result["prompt_hash"]}:
        raise ValidationError("image_gen evidence prompt_hash does not match image_result")


def _update_image_gen_evidence_after_record(root: Path, result: dict[str, Any]) -> None:
    evidence_path_value = result.get("image_gen_evidence_path")
    if not isinstance(evidence_path_value, str) or not evidence_path_value.strip():
        return
    evidence_path = _state_path(root, evidence_path_value, "image_result.image_gen_evidence_path")
    if not evidence_path.exists():
        return
    evidence = read_json(evidence_path)
    evidence["recorded_result_path"] = result.get("result_path")
    evidence["visible_image_path"] = result["image_path"]
    evidence["recorded_at"] = now_iso()
    write_json(evidence_path, evidence)


def _state_path(root: Path, path: str, label: str) -> Path:
    value = Path(path)
    resolved = value if value.is_absolute() else root / value
    try:
        resolved.resolve().relative_to((root / "_state").resolve())
    except ValueError as exc:
        raise ValidationError(f"{label} must be inside project _state") from exc
    return resolved


def _relative_or_text(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _relativize_postprocess(root: Path, value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    for key in ("source", "output"):
        item = dict(result.get(key, {}))
        path = item.get("path")
        if isinstance(path, str) and path:
            item["path"] = _relative_or_text(root, Path(path))
        result[key] = item
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"
