from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from .image_routes import (
    CODEX_IMAGE_GEN_TOOL,
    CODEX_IMAGE_GEN_TOOL_FUNCTIONS,
    IMAGE_ROUTE_OPENAI_IMAGE_API,
    OPENAI_IMAGE_API_TOOL,
    OPENAI_IMAGE_API_TOOL_FUNCTIONS,
    batch_path_for_route,
    normalize_image_generation_route,
    route_tool,
)
from .json_io import read_json, write_json
from .image_prompt_docs import record_prompt_document, prepare_image_request, atomic_json
from .time_utils import now_iso
from .validation import ValidationError


IMAGE_API_TOOL = OPENAI_IMAGE_API_TOOL
IMAGE_API_GENERATE_FUNCTION = "openai.images.generate"
IMAGE_API_EDIT_FUNCTION = "openai.images.edit"
IMAGE_API_TOOL_FUNCTIONS = {IMAGE_API_GENERATE_FUNCTION, IMAGE_API_EDIT_FUNCTION}


def create_image_generation_batch(
    run_dir: str | Path,
    execution_group: dict[str, Any],
    packet_paths: list[Path],
    *,
    stage: str,
    purpose: str,
    route: str | None = None,
) -> Path:
    root = Path(run_dir)
    resolved_route = normalize_image_generation_route(route or execution_group.get("image_generation_route"))
    group = _validate_execution_group(execution_group, route=resolved_route)
    if group["total_packets"] != len(packet_paths):
        raise ValidationError("image generation batch total_packets must match packet_paths count")

    batch_path = image_generation_batch_path(root, stage, purpose, group["group_id"], route=resolved_route)
    timestamp = now_iso()
    batch_id = uuid.uuid4().hex
    snapshot_batch = batch_path.parent / "history" / (batch_id + ".json")
    manifest = {
        "schema_version": "2.0",
        "batch_id": group["group_id"],
        "generation_batch_id": batch_id,
        "current_batch_path": _relative_or_text(root, batch_path),
        "packet_prompt_hashes": {},
        "execution_group_id": group["group_id"],
        "stage": _normalize_stage(stage),
        "purpose": purpose,
        "image_generation_route": resolved_route,
        "execution_tool": route_tool(resolved_route),
        "tool_call": group["tool_call"],
        "execution_mode": "parallel_required",
        "parallel_required": True,
        "max_parallel": group["max_parallel"],
        "total_packets": group["total_packets"],
        "packet_paths": [],
        "source_packet_paths": [_relative_or_text(root, path) for path in packet_paths],
        "completed_packets": 0,
        "status": "awaiting_results",
        "results": {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if resolved_route == IMAGE_ROUTE_OPENAI_IMAGE_API:
        manifest["legacy_batch_kind"] = "image_api"
    for packet_path in packet_paths:
        packet = read_json(packet_path)
        packet["generation_batch_path"] = _relative_or_text(root, snapshot_batch)
        # Each dispatch creates a new planned request; repeated executions create new attempts.
        packet.pop("generation_request_id", None)
        frozen_path, packet = prepare_image_request(root, packet_path, packet, submitted=False)
        manifest["packet_paths"].append(_relative_or_text(root, frozen_path))
        atomic_json(packet_path, packet)
        manifest["packet_prompt_hashes"][packet["packet_id"]] = hashlib.sha256(packet["prompt"].encode()).hexdigest()
    atomic_json(snapshot_batch, manifest)
    atomic_json(batch_path, manifest)
    return batch_path


def create_image_api_batch(
    run_dir: str | Path,
    execution_group: dict[str, Any],
    packet_paths: list[Path],
    *,
    stage: str,
    purpose: str,
) -> Path:
    return create_image_generation_batch(
        run_dir,
        execution_group,
        packet_paths,
        stage=stage,
        purpose=purpose,
        route=IMAGE_ROUTE_OPENAI_IMAGE_API,
    )


def require_image_generation_batch_for_packet(run_dir: str | Path, packet: dict[str, Any]) -> Path:
    root = Path(run_dir)
    route = normalize_image_generation_route(packet.get("image_generation_route") or packet.get("execution_tool"))
    _validate_packet_tool(packet, route=route)
    group = _validate_execution_group(packet["execution_group"], route=route)
    stage = packet.get("stage")
    if stage != "stage2":
        raise ValidationError("image generation packet.stage must be stage2")
    purpose = packet.get("purpose") or "full_slide"
    batch_path = root / packet["generation_batch_path"] if packet.get("generation_batch_path") else image_generation_batch_path(root, stage, purpose, group["group_id"], route=route)
    if not batch_path.exists():
        raise ValidationError(f"image generation batch manifest is missing: {_relative_or_text(root, batch_path)}")
    return batch_path


def require_image_api_batch_for_packet(run_dir: str | Path, packet: dict[str, Any]) -> Path:
    return require_image_generation_batch_for_packet(run_dir, packet)


def record_image_generation_batch_result(run_dir: str | Path, packet: dict[str, Any], result: dict[str, Any]) -> Path:
    root = Path(run_dir)
    route = normalize_image_generation_route(result.get("image_generation_route") or packet.get("image_generation_route") or packet.get("execution_tool"))
    batch_path = require_image_generation_batch_for_packet(root, packet)
    manifest = read_json(batch_path)
    _validate_batch_manifest(manifest, route=route)

    packet_id = packet.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id.strip():
        raise ValidationError("image generation packet.packet_id must be a non-empty string")
    for field in ("image_sha256", "image_path"):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"image_result.{field} is required for image generation batch record")
    route_result_id_field = "image_gen_result_id" if route == "codex_image_gen" else "image_api_result_id"
    route_call_id_field = "tool_call_id" if route == "codex_image_gen" else "api_call_id"
    for field in (route_call_id_field, route_result_id_field):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"image_result.{field} is required for {route} batch record")

    results = manifest.setdefault("results", {})
    if not isinstance(results, dict):
        raise ValidationError("image generation batch.results must be an object")
    entry = {
        "slide_index": packet["slide_index"],
        "generation_request_id": packet.get("generation_request_id"),
        "prompt_hash": packet.get("prompt_hash"),
        "prompt_text_sha256": hashlib.sha256(packet["prompt"].encode()).hexdigest(),
        "option_id": packet.get("option_id"),
        "image_generation_route": route,
        "tool_call_id": result.get("tool_call_id"),
        "generation_id": result.get("generation_id"),
        "image_gen_result_id": result.get("image_gen_result_id"),
        "api_call_id": result.get("api_call_id"),
        "image_api_result_id": result.get("image_api_result_id"),
        "request_id": result.get("request_id"),
        "api_endpoint": result.get("api_endpoint"),
        "model": result.get("model"),
        "response_format": result.get("response_format"),
        "provider_image_url": result.get("provider_image_url"),
        "image_sha256": result["image_sha256"],
        "width_px": result.get("width_px"),
        "height_px": result.get("height_px"),
        "aspect_ratio": result.get("aspect_ratio"),
        "target_aspect_ratio": result.get("target_aspect_ratio"),
        "aspect_ratio_error": result.get("aspect_ratio_error"),
        "aspect_ratio_tolerance": result.get("aspect_ratio_tolerance"),
        "meets_target_aspect_ratio": result.get("meets_target_aspect_ratio"),
        "target_size": result.get("target_size"),
        "preferred_minimum_size": result.get("preferred_minimum_size"),
        "target_size_tolerance_px": result.get("target_size_tolerance_px"),
        "size_policy": result.get("size_policy"),
        "postprocess_policy": result.get("postprocess_policy"),
        "meets_preferred_size": result.get("meets_preferred_size"),
        "meets_target_size": result.get("meets_target_size"),
        "size_warnings": result.get("size_warnings"),
        "image_path": result["image_path"],
        "recorded_at": now_iso(),
    }
    if isinstance(result.get("image_gen_evidence_path"), str):
        entry["image_gen_evidence_path"] = result["image_gen_evidence_path"]
    if isinstance(result.get("api_evidence_path"), str):
        entry["api_evidence_path"] = result["api_evidence_path"]
    expected = manifest.get("packet_prompt_hashes", {}).get(packet_id)
    if expected and expected != entry["prompt_text_sha256"]:
        raise ValidationError("实际请求与所属批次提示词不一致")
    results[packet_id] = entry
    manifest["completed_packets"] = len(results)
    manifest["status"] = "completed" if len(results) >= manifest["total_packets"] else "partial"
    manifest["updated_at"] = now_iso()
    atomic_json(batch_path, manifest)
    alias = manifest.get("current_batch_path")
    if alias and (root / alias).exists() and read_json(root / alias).get("generation_batch_id") == manifest.get("generation_batch_id"):
        atomic_json(root / alias, manifest)
    return batch_path


def record_image_api_batch_result(run_dir: str | Path, packet: dict[str, Any], result: dict[str, Any]) -> Path:
    return record_image_generation_batch_result(run_dir, packet, result)


def image_generation_batch_path(run_dir: str | Path, stage: str, purpose: str, group_id: str, *, route: str | None = None) -> Path:
    return batch_path_for_route(run_dir, stage, purpose, group_id, normalize_image_generation_route(route))


def image_api_batch_path(run_dir: str | Path, stage: str, purpose: str, group_id: str) -> Path:
    return image_generation_batch_path(run_dir, stage, purpose, group_id, route=IMAGE_ROUTE_OPENAI_IMAGE_API)


def _validate_packet_tool(packet: dict[str, Any], *, route: str) -> None:
    tool = route_tool(route)
    if packet.get("execution_tool") != tool:
        raise ValidationError(f"image generation packet.execution_tool must be {tool}")
    if packet.get("execution_tool_function") not in _tool_functions(route):
        raise ValidationError(f"image generation packet.execution_tool_function must be supported for {route}")
    if packet.get("execution_mode") != "parallel_required":
        raise ValidationError("image generation packet.execution_mode must be parallel_required")
    if not isinstance(packet.get("execution_group"), dict):
        raise ValidationError("image generation packet.execution_group must be an object")


def _validate_execution_group(group: dict[str, Any], *, route: str) -> dict[str, Any]:
    for field in ("group_id", "required_tool", "tool_call", "mode"):
        value = group.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"image generation execution_group.{field} must be a non-empty string")
    tool = route_tool(route)
    if group["required_tool"] != tool:
        raise ValidationError(f"image generation execution_group.required_tool must be {tool}")
    if group["tool_call"] not in _tool_functions(route):
        raise ValidationError(f"image generation execution_group.tool_call must be supported for {route}")
    if group["mode"] != "parallel_required":
        raise ValidationError("image generation execution_group.mode must be parallel_required")
    if group.get("parallel_required") is not True:
        raise ValidationError("image generation execution_group.parallel_required must be true")
    for field in ("total_packets", "packet_index", "max_parallel"):
        value = group.get(field)
        if not isinstance(value, int) or value < 1:
            raise ValidationError(f"image generation execution_group.{field} must be a positive integer")
    if group["packet_index"] > group["total_packets"]:
        raise ValidationError("image generation execution_group.packet_index cannot exceed total_packets")
    route_value = group.get("image_generation_route")
    if route_value is not None and normalize_image_generation_route(route_value) != route:
        raise ValidationError("image generation execution_group.image_generation_route does not match route")
    return group


def _validate_batch_manifest(manifest: dict[str, Any], *, route: str | None = None) -> None:
    if manifest.get("schema_version") != "2.0":
        raise ValidationError("image generation batch.schema_version must be 2.0")
    resolved_route = normalize_image_generation_route(route or manifest.get("image_generation_route") or manifest.get("execution_tool"))
    if manifest.get("execution_tool") != route_tool(resolved_route):
        raise ValidationError(f"image generation batch.execution_tool must be {route_tool(resolved_route)}")
    if manifest.get("tool_call") not in _tool_functions(resolved_route):
        raise ValidationError(f"image generation batch.tool_call must be supported for {resolved_route}")
    if manifest.get("execution_mode") != "parallel_required":
        raise ValidationError("image generation batch.execution_mode must be parallel_required")
    if manifest.get("parallel_required") is not True:
        raise ValidationError("image generation batch.parallel_required must be true")
    if not isinstance(manifest.get("total_packets"), int) or manifest["total_packets"] < 1:
        raise ValidationError("image generation batch.total_packets must be a positive integer")


def _tool_functions(route: str) -> set[str]:
    normalized = normalize_image_generation_route(route)
    if normalized == IMAGE_ROUTE_OPENAI_IMAGE_API:
        return OPENAI_IMAGE_API_TOOL_FUNCTIONS
    if route_tool(normalized) == CODEX_IMAGE_GEN_TOOL:
        return CODEX_IMAGE_GEN_TOOL_FUNCTIONS
    raise ValidationError(f"unsupported image generation route: {route}")


def _normalize_stage(stage: str) -> str:
    if stage in {"stage2", "阶段2"}:
        return "stage2"
    if stage in {"stage3", "stage3-background", "stage3_background", "阶段3"}:
        raise ValidationError("stage3 background image generation was removed from the formal workflow")
    raise ValidationError(f"unsupported image generation batch stage: {stage}")


def _relative_or_text(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
