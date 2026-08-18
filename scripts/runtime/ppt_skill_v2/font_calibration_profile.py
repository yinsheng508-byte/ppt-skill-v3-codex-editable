from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .box_utils import require_bool, require_number, require_string
from .events import append_event
from .json_io import read_json, write_json
from .stage1_plan import load_stage1_slides
from .stage3_artifact_hashes import refresh_stage3_stale_artifacts
from .stage3_restore_targets import stable_json_hash
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .validation import ValidationError, validate_stage1_plan


RENDER_PROBE_STATUSES = {"draft", "passed", "needs_rework"}
RENDER_PROBE_PROVIDERS = {"officecli"}
HORIZONTAL_ALIGNS = {"left", "center", "right"}
VERTICAL_ALIGNS = {"top", "middle", "bottom"}
FORBIDDEN_FONT_FAMILIES = ("pingfang", "苹方")


def font_calibration_profile_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "font_calibration_profile.json"


def load_font_calibration_profile(run_dir: str | Path) -> dict[str, Any]:
    return validate_font_calibration_profile(read_json(font_calibration_profile_path(run_dir)))


def font_calibration_profile_hash(run_dir: str | Path) -> str:
    path = font_calibration_profile_path(run_dir)
    return stable_json_hash(read_json(path)) if path.exists() else ""


def record_font_calibration_profile(run_dir: str | Path, profile_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("font calibration profile can only be recorded in stage3")
    source = Path(profile_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"font calibration profile not found: {source}")
    profile = validate_font_calibration_profile(read_json(source))
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    _require_probe_slide_exists(profile, {slide["slide_index"] for slide in stage1["slides"]})
    _require_passed_probe_assets(root, profile)
    target = font_calibration_profile_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    state["status"] = "stage3_font_calibration_profile_ready"
    state["required_actor"] = "main_controller"
    state["runtime_artifacts"]["stage3_font_calibration_profile"] = "_state/阶段3/font_calibration_profile.json"
    state["quality"]["stage3_font_calibration_profile"] = profile["render_probe"]["review_status"]
    state["next_required_action"] = "主控大模型基于 font_calibration_profile 细化 editable_coordinate_plan"
    refresh_stage3_stale_artifacts(root, state)
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "font_calibration_profile_recorded",
        "runtime",
        profiles_count=len(profile["profiles"]),
        stage3_scope=stage3_scope_summary(state),
    )
    return target


def create_font_calibration_profile_draft(
    run_dir: str | Path,
    probe_slide_index: int,
    output_file: str | Path | None = None,
) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("font calibration profile draft can only be created in stage3")
    if isinstance(probe_slide_index, bool) or not isinstance(probe_slide_index, int) or probe_slide_index <= 0:
        raise ValidationError("probe_slide_index must be a positive integer")
    stage1 = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    _require_probe_slide_exists({"basis": {"probe_slide_index": probe_slide_index}}, {slide["slide_index"] for slide in stage1["slides"]})
    style_ids = _draft_style_profile_ids(root)
    draft = {
        "schema_version": "1.0",
        "basis": {
            "probe_slide_index": probe_slide_index,
            "stage2_image": f"阶段2_图片版PPT/img/slide_{probe_slide_index:03d}.png",
            "stage3_background": f"阶段3_可编辑PPT/img/background_{probe_slide_index:03d}.png",
            "probe_route": "officecli_native_style_probe",
            "status": "draft",
            "controller_review_required": True,
        },
        "render_probe": {
            "provider": "officecli",
            "probe_manifest": "_state/阶段3/officecli/probe/native_style_probe.json",
            "review_status": "draft",
            "notes": "Run OfficeCLI native style probe, compare visually, then mark passed only after controller review.",
        },
        "profiles": [_draft_profile(style_id) for style_id in style_ids],
    }
    validate_font_calibration_profile(draft)
    target = Path(output_file) if output_file else root / "_state" / "阶段3" / "drafts" / "font_calibration_profile.draft.json"
    write_json(target, draft)
    return target


def validate_font_calibration_profile(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("font_calibration_profile must be an object")
    for field in ("schema_version", "basis", "render_probe", "profiles"):
        if field not in data:
            raise ValidationError(f"font_calibration_profile missing required field: {field}")
    if data["schema_version"] != "1.0":
        raise ValidationError("font_calibration_profile.schema_version must be 1.0")
    _validate_basis(data["basis"])
    _validate_render_probe(data["render_probe"])
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValidationError("font_calibration_profile.profiles must be a non-empty list")
    seen_ids: set[str] = set()
    for index, profile in enumerate(profiles, start=1):
        _validate_profile(profile, f"font_calibration_profile.profiles[{index}]", seen_ids)
    return data


def profile_ids(profile: dict[str, Any]) -> set[str]:
    return {item["style_profile_id"] for item in profile.get("profiles", []) if isinstance(item, dict)}


def profile_by_id(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["style_profile_id"]: item for item in profile.get("profiles", []) if isinstance(item, dict)}


def _validate_basis(basis: Any) -> None:
    if not isinstance(basis, dict):
        raise ValidationError("font_calibration_profile.basis must be an object")
    probe_slide_index = basis.get("probe_slide_index")
    if isinstance(probe_slide_index, bool) or not isinstance(probe_slide_index, int):
        raise ValidationError("font_calibration_profile.basis.probe_slide_index must be an integer")
    for field in ("stage2_image", "stage3_background"):
        if field in basis:
            require_string(basis, field, "font_calibration_profile.basis")


def _validate_render_probe(render_probe: Any) -> None:
    if not isinstance(render_probe, dict):
        raise ValidationError("font_calibration_profile.render_probe must be an object")
    status = require_string(render_probe, "review_status", "font_calibration_profile.render_probe")
    if status not in RENDER_PROBE_STATUSES:
        raise ValidationError(f"font_calibration_profile.render_probe.review_status is invalid: {status}")
    provider = render_probe.get("provider")
    if provider is not None:
        if not isinstance(provider, str) or provider not in RENDER_PROBE_PROVIDERS:
            raise ValidationError("font_calibration_profile.render_probe.provider must be officecli")
    for field in ("probe_manifest", "probe_pptx", "render_image", "compare_image", "notes"):
        if field in render_probe and not isinstance(render_probe[field], str):
            raise ValidationError(f"font_calibration_profile.render_probe.{field} must be a string")


def _validate_profile(profile: Any, label: str, seen_ids: set[str]) -> None:
    if not isinstance(profile, dict):
        raise ValidationError(f"{label} must be an object")
    style_profile_id = require_string(profile, "style_profile_id", label)
    if style_profile_id in seen_ids:
        raise ValidationError(f"{label}.style_profile_id is duplicated: {style_profile_id}")
    seen_ids.add(style_profile_id)
    matched_roles = profile.get("matched_roles")
    if not isinstance(matched_roles, list) or not matched_roles:
        raise ValidationError(f"{label}.matched_roles must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in matched_roles):
        raise ValidationError(f"{label}.matched_roles must contain non-empty strings")
    font_family = require_string(profile, "font_family", label)
    if any(pattern in font_family.lower() for pattern in FORBIDDEN_FONT_FAMILIES):
        raise ValidationError(f"{label}.font_family contains forbidden font family PingFang/苹方")
    if require_number(profile.get("font_size_scale"), f"{label}.font_size_scale") <= 0:
        raise ValidationError(f"{label}.font_size_scale must be positive")
    if require_number(profile.get("line_height_scale"), f"{label}.line_height_scale") <= 0:
        raise ValidationError(f"{label}.line_height_scale must be positive")
    require_bool(profile, "bold", label)
    insets = profile.get("text_box_insets_pt")
    if not isinstance(insets, list) or len(insets) != 4:
        raise ValidationError(f"{label}.text_box_insets_pt must contain four numbers")
    for inset_index, inset in enumerate(insets, start=1):
        require_number(inset, f"{label}.text_box_insets_pt[{inset_index}]")
    vertical = require_string(profile, "vertical_align", label)
    if vertical not in VERTICAL_ALIGNS:
        raise ValidationError(f"{label}.vertical_align is invalid: {vertical}")
    horizontal = require_string(profile, "horizontal_align", label)
    if horizontal not in HORIZONTAL_ALIGNS:
        raise ValidationError(f"{label}.horizontal_align is invalid: {horizontal}")
    if "notes" in profile and not isinstance(profile["notes"], str):
        raise ValidationError(f"{label}.notes must be a string")


def _require_probe_slide_exists(profile: dict[str, Any], known_slide_indices: set[int]) -> None:
    probe_slide_index = profile["basis"]["probe_slide_index"]
    if probe_slide_index not in known_slide_indices:
        raise ValidationError(f"font_calibration_profile basis.probe_slide_index is unknown: {probe_slide_index}")


def _require_passed_probe_assets(root: Path, profile: dict[str, Any]) -> None:
    if profile["render_probe"]["review_status"] != "passed":
        return
    required_assets = [
        ("basis.stage2_image", profile["basis"].get("stage2_image")),
        ("basis.stage3_background", profile["basis"].get("stage3_background")),
        ("render_probe.render_image", profile["render_probe"].get("render_image")),
        ("render_probe.compare_image", profile["render_probe"].get("compare_image")),
    ]
    for label, relpath in required_assets:
        if not isinstance(relpath, str) or not relpath.strip():
            raise ValidationError(f"font_calibration_profile.{label} is required when render_probe.review_status=passed")
        path = root / relpath
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"font calibration probe asset missing: {relpath}")
    probe_pptx = profile["render_probe"].get("probe_pptx")
    if isinstance(probe_pptx, str) and probe_pptx.strip() and not (root / probe_pptx).exists():
        raise FileNotFoundError(f"font calibration probe PPTX missing: {probe_pptx}")
    probe_manifest = profile["render_probe"].get("probe_manifest")
    if isinstance(probe_manifest, str) and probe_manifest.strip() and not (root / probe_manifest).exists():
        raise FileNotFoundError(f"font calibration probe manifest missing: {probe_manifest}")


def _draft_style_profile_ids(root: Path) -> list[str]:
    coordinate_plan = root / "_state" / "阶段3" / "editable_coordinate_plan.json"
    style_ids: set[str] = set()
    if coordinate_plan.exists():
        value = read_json(coordinate_plan)
        if isinstance(value, dict):
            for slide in value.get("slides", []):
                if not isinstance(slide, dict):
                    continue
                for unit in slide.get("text_units", []):
                    if isinstance(unit, dict) and isinstance(unit.get("style_profile_id"), str) and unit["style_profile_id"].strip():
                        style_ids.add(unit["style_profile_id"])
                    elif isinstance(unit, dict) and isinstance(unit.get("semantic_role"), str) and unit["semantic_role"].strip():
                        style_ids.add(unit["semantic_role"])
    if not style_ids:
        style_ids.update(["page_title", "card_title", "card_body", "node_number", "node_title", "node_body", "source_note"])
    return sorted(style_ids)


def _draft_profile(style_id: str) -> dict[str, Any]:
    bold = style_id in {"page_title", "card_title", "node_number", "node_title"}
    size_scale = 1.0 if bold else 0.96
    return {
        "style_profile_id": style_id,
        "matched_roles": [style_id],
        "font_family": "Microsoft YaHei",
        "font_size_scale": size_scale,
        "line_height_scale": 1.12,
        "bold": bold,
        "text_box_insets_pt": [0, 1, 0, 1],
        "vertical_align": "top",
        "horizontal_align": "left",
        "notes": "draft; calibrate with one-page OfficeCLI native style probe before formal record",
    }
