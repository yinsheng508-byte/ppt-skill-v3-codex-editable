from __future__ import annotations

from pathlib import Path
from typing import Any

from .validation import ValidationError


IMAGE_ROUTE_CODEX_IMAGE_GEN = "codex_image_gen"
IMAGE_ROUTE_OPENAI_IMAGE_API = "openai_image_api"
SUPPORTED_IMAGE_GENERATION_ROUTES = {IMAGE_ROUTE_CODEX_IMAGE_GEN, IMAGE_ROUTE_OPENAI_IMAGE_API}
DEFAULT_IMAGE_GENERATION_ROUTE = IMAGE_ROUTE_OPENAI_IMAGE_API
DEFAULT_PPT_IMAGE_SIZE_16_9 = "1672x941"
DEFAULT_PPT_IMAGE_WIDTH_PX = 1672
DEFAULT_PPT_IMAGE_HEIGHT_PX = 941
PREFERRED_PPT_IMAGE_WIDTH_PX = 1600
PREFERRED_PPT_IMAGE_HEIGHT_PX = 900
MINIMUM_ACCEPTABLE_PPT_IMAGE_WIDTH_PX = PREFERRED_PPT_IMAGE_WIDTH_PX
MINIMUM_ACCEPTABLE_PPT_IMAGE_HEIGHT_PX = PREFERRED_PPT_IMAGE_HEIGHT_PX
TARGET_SIZE_TOLERANCE_RATIO = 0.02
TARGET_SIZE_TOLERANCE_MIN_PX = 16
DEFAULT_PPT_IMAGE_WIDTH_TOLERANCE_PX = max(
    TARGET_SIZE_TOLERANCE_MIN_PX,
    round(DEFAULT_PPT_IMAGE_WIDTH_PX * TARGET_SIZE_TOLERANCE_RATIO),
)
DEFAULT_PPT_IMAGE_HEIGHT_TOLERANCE_PX = max(
    TARGET_SIZE_TOLERANCE_MIN_PX,
    round(DEFAULT_PPT_IMAGE_HEIGHT_PX * TARGET_SIZE_TOLERANCE_RATIO),
)
IMAGE_SIZE_POLICY_PRESERVE_GENERATED_RASTER = "preserve_generated_raster_no_downscale"
IMAGE_POSTPROCESS_POLICY_NO_DOWNSCALE = "prefer_no_downscale_or_compress_generated_image"

CODEX_IMAGE_GEN_TOOL = "codex_image_gen"
CODEX_IMAGE_GEN_TOOL_FUNCTION_GENERATE = "image_gen.generate"
CODEX_IMAGE_GEN_TOOL_FUNCTION_EDIT = "image_gen.edit"
CODEX_IMAGE_GEN_TOOL_FUNCTIONS = {
    CODEX_IMAGE_GEN_TOOL_FUNCTION_GENERATE,
    CODEX_IMAGE_GEN_TOOL_FUNCTION_EDIT,
}

OPENAI_IMAGE_API_TOOL = "openai_image_api"
OPENAI_IMAGE_API_GENERATE_FUNCTION = "openai.images.generate"
OPENAI_IMAGE_API_EDIT_FUNCTION = "openai.images.edit"
OPENAI_IMAGE_API_TOOL_FUNCTIONS = {
    OPENAI_IMAGE_API_GENERATE_FUNCTION,
    OPENAI_IMAGE_API_EDIT_FUNCTION,
}


def normalize_image_generation_route(route: str | None) -> str:
    if route is None or not str(route).strip():
        return DEFAULT_IMAGE_GENERATION_ROUTE
    normalized = str(route).strip().lower().replace("-", "_")
    aliases = {
        "image_gen": IMAGE_ROUTE_CODEX_IMAGE_GEN,
        "codex_imagegen": IMAGE_ROUTE_CODEX_IMAGE_GEN,
        "codex_image_gen": IMAGE_ROUTE_CODEX_IMAGE_GEN,
        "official_image_gen": IMAGE_ROUTE_CODEX_IMAGE_GEN,
        "built_in_image_gen": IMAGE_ROUTE_CODEX_IMAGE_GEN,
        "builtin_image_gen": IMAGE_ROUTE_CODEX_IMAGE_GEN,
        "api": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "image_api": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "openai_image_api": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "direct_api": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "cangyuan": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "cangyuan_api": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "grsai": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "relay_api": IMAGE_ROUTE_OPENAI_IMAGE_API,
        "transit_api": IMAGE_ROUTE_OPENAI_IMAGE_API,
    }
    if normalized not in aliases:
        raise ValidationError(f"unsupported image generation route: {route}")
    return aliases[normalized]


def route_tool(route: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return CODEX_IMAGE_GEN_TOOL
    return OPENAI_IMAGE_API_TOOL


def route_tool_function(route: str, *, edit: bool = False) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return CODEX_IMAGE_GEN_TOOL_FUNCTION_EDIT if edit else CODEX_IMAGE_GEN_TOOL_FUNCTION_GENERATE
    return OPENAI_IMAGE_API_EDIT_FUNCTION if edit else OPENAI_IMAGE_API_GENERATE_FUNCTION


def image_size_contract() -> dict[str, Any]:
    return {
        "target_size": DEFAULT_PPT_IMAGE_SIZE_16_9,
        "target_width_px": DEFAULT_PPT_IMAGE_WIDTH_PX,
        "target_height_px": DEFAULT_PPT_IMAGE_HEIGHT_PX,
        "preferred_minimum_size": {
            "width_px": PREFERRED_PPT_IMAGE_WIDTH_PX,
            "height_px": PREFERRED_PPT_IMAGE_HEIGHT_PX,
        },
        "target_size_tolerance_px": {
            "width_px": DEFAULT_PPT_IMAGE_WIDTH_TOLERANCE_PX,
            "height_px": DEFAULT_PPT_IMAGE_HEIGHT_TOLERANCE_PX,
        },
        "size_policy": IMAGE_SIZE_POLICY_PRESERVE_GENERATED_RASTER,
        "postprocess_policy": IMAGE_POSTPROCESS_POLICY_NO_DOWNSCALE,
    }


def evidence_field_for_route(route: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return "image_gen_evidence_path"
    return "api_evidence_path"


def batch_dir_name_for_route(route: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return "image_gen_batches"
    return "image_api_batches"


def output_dir_name_for_route(route: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return "image_gen_outputs"
    return "api_outputs"


def evidence_dir_name_for_route(route: str) -> str:
    normalized = normalize_image_generation_route(route)
    if normalized == IMAGE_ROUTE_CODEX_IMAGE_GEN:
        return "image_gen_calls"
    return "api_calls"


def batch_path_for_route(run_dir: str | Path, stage: str, purpose: str, group_id: str, route: str) -> Path:
    root = Path(run_dir)
    normalized = normalize_image_generation_route(route)
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValidationError("image generation execution_group.group_id must be a non-empty string")
    stage_name = _normalize_stage(stage)
    if purpose == "cover_option":
        return root / "_state" / "阶段2" / "cover_options" / "batches" / f"{group_id}.json"
    if purpose == "trial_first5":
        return root / "_state" / "阶段2" / "trial_first5" / "batches" / f"{group_id}.json"
    if stage_name == "stage2":
        return root / "_state" / "阶段2" / batch_dir_name_for_route(normalized) / f"{group_id}.json"
    raise ValidationError(f"unsupported image generation batch stage: {stage}")


def evidence_path_for_route(run_dir: str | Path, packet: dict[str, Any], route: str) -> Path:
    root = Path(run_dir)
    packet_id = packet.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id.strip():
        raise ValidationError("packet.packet_id must be a non-empty string")
    evidence_dir = evidence_dir_name_for_route(route)
    if packet.get("purpose") == "cover_option":
        return root / "_state" / "阶段2" / "cover_options" / evidence_dir / f"{packet_id}.json"
    if packet.get("purpose") == "trial_first5":
        return root / "_state" / "阶段2" / "trial_first5" / evidence_dir / f"{packet_id}.json"
    if packet.get("stage") == "stage2":
        return root / "_state" / "阶段2" / evidence_dir / f"{packet_id}.json"
    if packet.get("stage") == "stage3":
        raise ValidationError("stage3 background image generation was removed from the formal workflow")
    raise ValidationError("packet.stage must be stage2 or stage3")


def output_path_for_route(run_dir: str | Path, packet: dict[str, Any], output_format: str, route: str) -> Path:
    root = Path(run_dir)
    packet_id = packet.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id.strip():
        raise ValidationError("packet.packet_id must be a non-empty string")
    suffix = f".{output_format.lower()}"
    output_dir = output_dir_name_for_route(route)
    if packet.get("purpose") == "cover_option":
        return root / "_state" / "阶段2" / "cover_options" / output_dir / f"{packet_id}{suffix}"
    if packet.get("purpose") == "trial_first5":
        return root / "_state" / "阶段2" / "trial_first5" / output_dir / f"{packet_id}{suffix}"
    if packet.get("stage") == "stage2":
        return root / "_state" / "阶段2" / output_dir / f"{packet_id}{suffix}"
    if packet.get("stage") == "stage3":
        raise ValidationError("stage3 background image generation was removed from the formal workflow")
    raise ValidationError("packet.stage must be stage2 or stage3")


def _normalize_stage(stage: str) -> str:
    if stage in {"stage2", "阶段2"}:
        return "stage2"
    if stage in {"stage3", "stage3-background", "stage3_background", "阶段3"}:
        raise ValidationError("stage3 background image generation was removed from the formal workflow")
    raise ValidationError(f"unsupported image generation batch stage: {stage}")
