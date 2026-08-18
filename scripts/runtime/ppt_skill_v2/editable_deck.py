from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .dev_mode import require_dev_fixture_enabled
from .events import append_event
from .json_io import read_json, write_json
from .planning_assets import content_path, deck_style_path, layout_intent_path
from .stage1_plan import load_stage1_slides
from .stage_docs import sync_stage_docs
from .stage3_artifact_hashes import current_stage3_input_hashes, refresh_stage3_stale_artifacts
from .stage3_scope import apply_stage3_scope, stage3_scope_summary
from .state import read_state, write_state
from .editable_coordinate_plan import editable_coordinate_plan_path, load_editable_coordinate_plan, validate_coordinate_execution_report
from .font_calibration_profile import font_calibration_profile_path
from .text_ownership_map import text_ownership_map_path
from .text_unit_split_plan import text_unit_split_plan_path
from .time_utils import now_iso
from .validation import ValidationError, validate_stage1_plan


FORMAL_EDITABLE_PROVIDERS = {"officecli"}
DEV_EDITABLE_PROVIDER = "dev_officecli_fixture"


def manifest_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "_state" / "阶段3" / "manifests" / "editable_deck.json"


def record_editable_deck(
    run_dir: str | Path,
    pptx_file: str | Path,
    *,
    provider: str,
    provider_evidence_id: str | None = None,
    tool_call_id: str | None = None,
    inspect_path: str | Path | None = None,
    render_review_path: str | Path | None = None,
    text_fill_execution_report: str | Path | None = None,
    officecli_manifest: str | Path | None = None,
    native_style_probe: str | Path | None = None,
) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage3":
        raise ValidationError("editable deck can only be recorded in stage3")
    if not state.get("confirmed", {}).get("stage3_coordinate_plan"):
        raise ValidationError("editable deck requires user-confirmed stage3 coordinate plan before text fill")

    source = Path(pptx_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"editable pptx not found: {source}")
    if source.suffix.lower() != ".pptx":
        raise ValidationError("editable deck must be a .pptx file")

    if not isinstance(provider, str) or not provider.strip():
        raise ValidationError("provider is required")
    provider = provider.strip()
    is_dev_provider = provider == DEV_EDITABLE_PROVIDER
    if is_dev_provider:
        require_dev_fixture_enabled()
        provider_evidence_id = provider_evidence_id or "dev-officecli-fixture"
        tool_call_id = tool_call_id or "dev-officecli-tool-call"
    else:
        if provider not in FORMAL_EDITABLE_PROVIDERS:
            raise ValidationError("editable deck provider must be officecli")
        if not isinstance(provider_evidence_id, str) or not provider_evidence_id.strip():
            raise ValidationError("editable deck requires provider_evidence_id")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise ValidationError("editable deck requires tool_call_id")

    plan = apply_stage3_scope(validate_stage1_plan(load_stage1_slides(root)), state, "stage1_plan")
    officecli_manifest_rel, officecli_manifest_data = _normalize_officecli_manifest_path(root, officecli_manifest, required=not is_dev_provider)
    slides_count = _slides_count_from_officecli_manifest(officecli_manifest_data, default=len(plan["slides"]))
    if slides_count != len(plan["slides"]):
        raise ValidationError(f"editable deck slides count mismatch: expected {len(plan['slides'])}, got {slides_count}")

    pptx_sha256 = _sha256_file(source)
    coordinate_plan_rel, coordinate_plan = _load_coordinate_plan(root, required=not is_dev_provider)
    if coordinate_plan is not None:
        coordinate_plan = apply_stage3_scope(coordinate_plan, state, "editable_coordinate_plan", strict=True)
    inspect_rel = _normalize_existing_path(root, inspect_path, "inspect", required=not is_dev_provider)
    render_rel = _normalize_existing_path(root, render_review_path, "render review", required=not is_dev_provider)
    report_rel = _normalize_execution_report_path(
        root,
        text_fill_execution_report,
        required=not is_dev_provider,
        coordinate_plan=coordinate_plan,
        pptx_sha256=pptx_sha256,
    )
    native_style_probe_rel = _normalize_existing_path(root, native_style_probe, "native style probe", required=False)

    deck_path = root / "阶段3_可编辑PPT" / "ppt" / "可编辑PPT.pptx"
    deck_path.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != deck_path.resolve():
        shutil.copy2(source, deck_path)

    manifest = {
        "schema_version": "2.4",
        "project_name": state["project_name"],
        "run_dir": state["run_dir"],
        "provider": provider,
        "provider_evidence_id": provider_evidence_id,
        "tool_call_id": tool_call_id,
        "deck_path": "阶段3_可编辑PPT/ppt/可编辑PPT.pptx",
        "slides_count": slides_count,
        "pptx_sha256": pptx_sha256,
        "created_at": now_iso(),
        "stage3_scope": stage3_scope_summary(state),
        "input_hashes": current_stage3_input_hashes(root),
        "runtime_evidence": {
            "text_unit_split_plan": _relative_existing_optional(root, text_unit_split_plan_path(root)),
            "text_ownership_map": _relative_existing_optional(root, text_ownership_map_path(root)),
            "font_calibration_profile": _relative_existing_optional(root, font_calibration_profile_path(root)),
            "native_style_probe": native_style_probe_rel or _relative_existing_optional(root, _native_style_probe_path(root)),
            "editable_coordinate_plan": coordinate_plan_rel,
            "officecli_manifest": officecli_manifest_rel,
            "inspect": inspect_rel,
            "render_review": render_rel,
            "text_fill_execution_report": report_rel,
        },
        "validation": {
            "file_exists": True,
            "extension": ".pptx",
            "page_count_matched_stage1": True,
            "page_count_matched_stage3_scope": True,
            "pptx_sha256_recorded": True,
            "provider_evidence_present": True,
            "quality_review_owner": "main_controller",
        },
        "assets": {
            "content": str(content_path(root).relative_to(root)),
            "deck_style": str(deck_style_path(root).relative_to(root)),
            "layout_intent": str(layout_intent_path(root).relative_to(root)),
        },
    }
    write_json(manifest_path(root), manifest)

    state["status"] = "stage3_editable_qa_required"
    state["required_actor"] = "main_controller"
    state["user_artifacts"]["stage3_editable_deck"] = "阶段3_可编辑PPT/ppt/可编辑PPT.pptx"
    state["runtime_artifacts"]["stage3_editable_deck_manifest"] = "_state/阶段3/manifests/editable_deck.json"
    state["quality"]["stage3"] = "editable_qa_required"
    state["next_required_action"] = "主控大模型读取 render/inspect/coordinate execution report，记录阶段3坐标 QA 后再交给用户确认"
    refresh_stage3_stale_artifacts(root, state)
    write_state(root, state)
    sync_stage_docs(root)
    append_event(
        root,
        "editable_deck_recorded",
        "runtime",
        provider=provider,
        provider_evidence_id=provider_evidence_id,
        tool_call_id=tool_call_id,
        slides_count=slides_count,
        pptx_sha256=pptx_sha256,
        stage3_scope=stage3_scope_summary(state),
    )
    return deck_path


def _load_coordinate_plan(root: Path, *, required: bool) -> tuple[str | None, dict | None]:
    path = editable_coordinate_plan_path(root)
    if path.exists():
        plan = load_editable_coordinate_plan(root)
        return str(path.relative_to(root)), plan
    if required:
        raise ValidationError("editable deck requires _state/阶段3/editable_coordinate_plan.json")
    return None, None


def _normalize_existing_path(root: Path, value: str | Path | None, label: str, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValidationError(f"editable deck requires {label}")
        return None
    path = Path(value)
    actual = path if path.is_absolute() else root / path
    if not actual.exists():
        raise FileNotFoundError(f"{label} not found: {actual}")
    try:
        return str(actual.relative_to(root))
    except ValueError:
        return str(actual)


def _normalize_execution_report_path(
    root: Path,
    value: str | Path | None,
    *,
    required: bool,
    coordinate_plan: dict | None,
    pptx_sha256: str,
) -> str | None:
    rel = _normalize_existing_path(root, value, "coordinate execution report", required=required)
    if rel is not None:
        report = validate_coordinate_execution_report(read_json(root / rel), coordinate_plan or {"slides": []}, pptx_sha256=pptx_sha256)
        if report.get("actual_source") != "pptx_ooxml":
            raise ValidationError("coordinate execution report must use actual_source=pptx_ooxml for OfficeCLI editable deck")
        if coordinate_plan is not None:
            _require_execution_report_covers_plan(report, coordinate_plan)
    return rel


def _relative_existing_optional(root: Path, path: Path) -> str | None:
    if path.exists():
        return str(path.relative_to(root))
    return None


def _native_style_probe_path(root: Path) -> Path:
    return root / "_state" / "阶段3" / "officecli" / "probe" / "native_style_probe.json"


def _normalize_officecli_manifest_path(
    root: Path,
    value: str | Path | None,
    *,
    required: bool,
) -> tuple[str | None, dict | None]:
    rel = _normalize_existing_path(root, value, "OfficeCLI manifest", required=required)
    if rel is None:
        return None, None
    data = read_json(root / rel)
    if not isinstance(data, dict):
        raise ValidationError("OfficeCLI manifest must be an object")
    if data.get("provider") != "officecli":
        raise ValidationError("OfficeCLI manifest provider must be officecli")
    return rel, data


def _slides_count_from_officecli_manifest(data: dict | None, *, default: int) -> int:
    if data is None:
        return default
    slides_count = data.get("slides_count")
    if isinstance(slides_count, bool):
        raise ValidationError("OfficeCLI manifest slides_count must be an integer")
    if isinstance(slides_count, int):
        return slides_count
    slides = data.get("slides")
    if isinstance(slides, list):
        return len(slides)
    readback = data.get("readback")
    if isinstance(readback, dict):
        readback_slides = readback.get("slides")
        if isinstance(readback_slides, list):
            return len(readback_slides)
    raise ValidationError("OfficeCLI manifest must include slides_count or slides/readback.slides")


def _require_execution_report_covers_plan(report: dict, coordinate_plan: dict) -> None:
    report_by_slide = {slide["slide_index"]: slide for slide in report["slides"]}
    for plan_slide in coordinate_plan["slides"]:
        slide_index = plan_slide["slide_index"]
        report_slide = report_by_slide.get(slide_index)
        if report_slide is None:
            raise ValidationError(f"coordinate execution report missing slide {slide_index}")
        planned_ids = {text_unit["text_unit_id"] for text_unit in plan_slide["text_units"]}
        report_text_by_id = {text_unit["text_unit_id"]: text_unit for text_unit in report_slide["coordinate_text_units"]}
        reported_ids = set(report_text_by_id)
        missing = sorted(planned_ids - reported_ids)
        if missing:
            raise ValidationError(f"coordinate execution report slide {slide_index} missing text unit(s): {', '.join(missing)}")
        plan_text_by_id = {text_unit["text_unit_id"]: text_unit for text_unit in plan_slide["text_units"]}
        for object_id in sorted(planned_ids):
            _require_reported_text_object_matches_plan(slide_index, plan_text_by_id[object_id], report_text_by_id[object_id])


def _require_reported_text_object_matches_plan(slide_index: int, planned: dict, reported: dict) -> None:
    if not reported["within_allowed_range"]:
        return
    actual = reported["actual"]
    actual_font = actual.get("font", {})
    planned_font = planned.get("font", {})
    size = actual_font.get("target_font_size_pt")
    allowed_range = planned_font.get("allowed_font_size_range_pt", [])
    if not isinstance(allowed_range, list) or len(allowed_range) != 2:
        raise ValidationError(f"editable_coordinate_plan slide {slide_index} text unit {planned['text_unit_id']} has invalid allowed font range")
    if size < allowed_range[0] or size > allowed_range[1]:
        raise ValidationError(
            f"coordinate execution report slide {slide_index} text unit {planned['text_unit_id']} reports in-range but actual font size is outside allowed range"
        )
    for field in ("resolved_family", "resolved_color"):
        if actual_font.get(field) != planned_font.get(field):
            raise ValidationError(
                f"coordinate execution report slide {slide_index} text unit {planned['text_unit_id']} reports in-range but actual {field} differs"
            )
    if not _relative_box_close(planned.get("relative_box", {}), actual.get("relative_box", {})):
        raise ValidationError(
            f"coordinate execution report slide {slide_index} text unit {planned['text_unit_id']} reports in-range but actual box differs"
        )


def _require_reported_foreground_matches_plan(slide_index: int, planned: dict, reported: dict) -> None:
    if not reported["exists"] or not reported["within_allowed_range"]:
        return
    actual = reported["actual"]
    if not _relative_box_close(planned.get("relative_box", {}), actual.get("relative_box", {})):
        raise ValidationError(
            f"text fill execution report slide {slide_index} foreground {planned['element_id']} reports in-range but actual box differs"
        )


def _relative_box_close(planned: dict, actual: dict, tolerance: float = 0.01) -> bool:
    for field in ("x", "y", "w", "h"):
        planned_value = planned.get(field)
        actual_value = actual.get(field)
        if not isinstance(planned_value, (int, float)) or not isinstance(actual_value, (int, float)):
            return False
        if abs(planned_value - actual_value) > tolerance:
            return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"
