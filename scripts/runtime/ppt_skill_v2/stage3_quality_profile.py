from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .json_io import read_json, write_json
from .time_utils import now_iso


AI_QUALITY_DIR_REL = "_state/阶段3/ai_quality"
QUALITY_PROFILE_REL = f"{AI_QUALITY_DIR_REL}/stage3_quality_profile.json"
CONTROLLER_REVIEW_PLAN_DRAFT_REL = f"{AI_QUALITY_DIR_REL}/controller_review_plan.draft.json"

INPUT_RELPATHS = {
    "project_state": "_state/project_state.json",
    "text_unit_split_plan": "_state/阶段3/text_unit_split_plan.json",
    "text_ownership_map": "_state/阶段3/text_ownership_map.json",
    "editable_coordinate_plan": "_state/阶段3/editable_coordinate_plan.json",
    "coordinate_plan_warnings": "_state/阶段3/coordinate_plan_warnings.json",
    "font_calibration_profile": "_state/阶段3/font_calibration_profile.json",
    "officecli_manifest": "_state/阶段3/manifests/officecli_manifest.json",
    "editable_deck_manifest": "_state/阶段3/manifests/editable_deck.json",
    "text_fill_execution_report": "_state/阶段3/text_fill_execution_report.json",
    "stage3_visual_qa_review": "_state/阶段3/render_review/stage3_visual_qa_review.json",
}

SPECIAL_LAYOUT_KEYWORDS = (
    "table",
    "flow",
    "process",
    "case",
    "module",
    "source",
    "metric",
    "timeline",
    "step",
    "matrix",
    "表",
    "流程",
    "案例",
    "模块",
    "数据",
)


def stage3_quality_profile_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / QUALITY_PROFILE_REL


def stage3_controller_review_plan_draft_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / CONTROLLER_REVIEW_PLAN_DRAFT_REL


def build_stage3_quality_profile(run_dir: str | Path, output_file: str | Path | None = None) -> Path:
    root = Path(run_dir)
    if not root.exists():
        raise FileNotFoundError(f"run_dir not found: {root}")

    state = _read_required_json(root / INPUT_RELPATHS["project_state"], "project_state")
    project_name = state.get("project_name") if isinstance(state, dict) else None
    project_name = project_name if isinstance(project_name, str) and project_name.strip() else root.name

    inputs = {name: relpath for name, relpath in INPUT_RELPATHS.items()}
    loaded = {name: _read_optional_json(root / relpath) for name, relpath in INPUT_RELPATHS.items()}

    coordinate_metrics = _coordinate_metrics(loaded["editable_coordinate_plan"])
    warning_summary = _coordinate_warning_summary(loaded["coordinate_plan_warnings"])
    font_summary = _font_profile_summary(root, loaded["font_calibration_profile"])
    execution_summary = _execution_summary(loaded["text_fill_execution_report"])
    builder_summary = _officecli_builder_warning_summary(
        root,
        loaded["editable_deck_manifest"],
        loaded["officecli_manifest"],
    )
    qa_summary = _qa_summary(loaded["stage3_visual_qa_review"])
    lineage = _decision_lineage(root)

    ranked_high_risk_slides = _recommended_high_risk_slides(
        coordinate_metrics=coordinate_metrics,
        warning_summary=warning_summary,
        execution_summary=execution_summary,
        lineage=lineage,
        limit=None,
    )
    recommended = _with_secondary_note(ranked_high_risk_slides[:10], ranked_high_risk_slides[10:])
    secondary_review_slides = ranked_high_risk_slides[10:30]
    probe_recommendation = _native_style_probe_recommendation(
        coordinate_metrics=coordinate_metrics,
        warning_summary=warning_summary,
        font_summary=font_summary,
        builder_summary=builder_summary,
        recommended_high_risk_slides=recommended,
    )
    qa_coverage = _qa_coverage_review(recommended, qa_summary)
    risk_signals = _risk_signals(
        coordinate_metrics=coordinate_metrics,
        warning_summary=warning_summary,
        font_summary=font_summary,
        execution_summary=execution_summary,
        builder_summary=builder_summary,
        qa_coverage=qa_coverage,
        lineage=lineage,
    )

    summary = {
        "slide_count": coordinate_metrics["slide_count"],
        "text_unit_count": coordinate_metrics["text_unit_count"],
        "avg_text_units_per_slide": coordinate_metrics["avg_text_units_per_slide"],
        "max_text_units_on_slide": coordinate_metrics["max_text_units_on_slide"],
        "max_line_count": coordinate_metrics["max_line_count"],
        "font_profile_status": font_summary["status"],
        "coordinate_warning_count": warning_summary["warning_count"],
        "unresolved_coordinate_warning_count": warning_summary["unresolved_warning_count"],
        "execution_missing_text_units": execution_summary["missing_text_units"],
        "execution_deviations": execution_summary["deviations"],
        "possible_merged_text_shapes": execution_summary["possible_merged_text_shapes"],
    }

    profile = {
        "schema_version": "1.0",
        "project_name": project_name,
        "run_dir": str(root),
        "generated_at": now_iso(),
        "mode": "non_blocking_controller_assist",
        "inputs": inputs,
        "input_status": _input_status(root, inputs, loaded),
        "profile_warnings": _profile_warnings(loaded, font_summary),
        "summary": summary,
        "coordinate_metrics": coordinate_metrics,
        "coordinate_warning_summary": warning_summary,
        "font_profile_summary": font_summary,
        "execution_summary": execution_summary,
        "officecli_builder_warning_summary": builder_summary,
        "qa_summary": qa_summary,
        "decision_lineage": lineage,
        "risk_signals": risk_signals,
        "recommended_high_risk_slides": recommended,
        "secondary_review_slides": secondary_review_slides,
        "qa_coverage_review": qa_coverage,
        "native_style_probe_recommendation": probe_recommendation,
        "controller_next_actions": _controller_next_actions(risk_signals, probe_recommendation, qa_coverage),
    }

    target = Path(output_file) if output_file else stage3_quality_profile_path(root)
    write_json(target, profile)
    return target


def create_stage3_controller_review_plan_draft(
    run_dir: str | Path,
    output_file: str | Path | None = None,
) -> Path:
    root = Path(run_dir)
    profile_path = build_stage3_quality_profile(root)
    profile = read_json(profile_path)

    recommended = [
        item for item in profile.get("recommended_high_risk_slides", [])
        if isinstance(item, dict) and isinstance(item.get("slide_index"), int)
    ]
    secondary = [
        item for item in profile.get("secondary_review_slides", [])
        if isinstance(item, dict) and isinstance(item.get("slide_index"), int)
    ]
    qa_coverage = profile.get("qa_coverage_review") if isinstance(profile.get("qa_coverage_review"), dict) else {}
    native_style_probe = profile.get("native_style_probe_recommendation")
    native_style_probe = native_style_probe if isinstance(native_style_probe, dict) else {}

    must_review_slides = _unique_ints(
        [item["slide_index"] for item in recommended if item.get("priority") == "P0"]
        + qa_coverage.get("recommended_not_in_qa_high_risk", [])
    )[:8]
    if not must_review_slides:
        must_review_slides = _unique_ints([item["slide_index"] for item in recommended[:3]])
    optional_review_slides = _unique_ints(
        [item["slide_index"] for item in recommended if item["slide_index"] not in set(must_review_slides)]
        + [item["slide_index"] for item in secondary if item["slide_index"] not in set(must_review_slides)]
    )[:8]

    probe_decision = _native_style_probe_plan_decision(native_style_probe)
    draft = {
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "mode": "controller_review_plan_draft",
        "basis": {
            "quality_profile": _relpath_or_abs(root, profile_path),
            "quality_profile_mode": profile.get("mode"),
        },
        "review_scope": {
            "must_review_slides": must_review_slides,
            "optional_review_slides": optional_review_slides,
            "reasoning": _review_scope_reasoning(profile, must_review_slides),
        },
        "native_style_probe_decision": probe_decision,
        "risk_signals": profile.get("risk_signals", []),
        "learned_controller_patterns": _learned_controller_patterns(
            profile,
            must_review_slides,
            optional_review_slides,
        ),
        "bad_case_avoidance_checks": _bad_case_avoidance_checks(profile, probe_decision),
        "accepted_tradeoffs": [],
        "planned_actions": _draft_planned_actions(profile, probe_decision, must_review_slides),
        "controller_fill_required": [
            "确认 must_review_slides 是否已逐页看过 stage2 reference、stage3 editable render 和局部截图。",
            "说明稳定页如何保护，只对画像命中页、用户点名页或真实渲染暴露的问题页做定点调整。",
            "对孤立标点、孤字掉行、标题贴线、文字压装饰线、深浅底对比不足做一次真实渲染复查。",
            "如清理制作备注或多余可见文字，同步更新 content/split plan/ownership/coordinate plan，不只隐藏 PPT 对象。",
            "如不采纳 native_style_probe_decision，补写接受理由。",
            "最终 QA 前把推荐页覆盖情况写入 stage3_visual_qa_review 的 optional 字段。",
        ],
        "notes": "该 draft 只辅助主控调度，不改变阶段状态，也不作为硬门禁。",
    }

    target = Path(output_file) if output_file else stage3_controller_review_plan_draft_path(root)
    write_json(target, draft)
    return target


def _read_required_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return read_json(path)


def _read_optional_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception as exc:  # pragma: no cover - surfaced in profile for corrupted historical projects
        return {"_read_error": str(exc), "_path": str(path)}


def _input_status(root: Path, inputs: dict[str, str], loaded: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, relpath in inputs.items():
        path = root / relpath
        if isinstance(loaded.get(name), dict) and loaded[name].get("_read_error"):
            result[name] = "read_error"
        else:
            result[name] = "present" if path.exists() else "missing"
    return result


def _profile_warnings(loaded: dict[str, Any], font_summary: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for name, value in loaded.items():
        if isinstance(value, dict) and value.get("_read_error"):
            warnings.append(
                {
                    "warning_type": "optional_input_read_error",
                    "input": name,
                    "path": value.get("_path"),
                    "message": value.get("_read_error"),
                }
            )
    if font_summary.get("missing_assets"):
        warnings.append(
            {
                "warning_type": "font_profile_asset_missing",
                "assets": font_summary["missing_assets"],
                "message": "font calibration profile references assets that are missing on disk.",
            }
        )
    return warnings


def _coordinate_metrics(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or not isinstance(plan.get("slides"), list):
        return {
            "status": "missing",
            "slide_count": 0,
            "text_unit_count": 0,
            "avg_text_units_per_slide": 0,
            "max_text_units_on_slide": 0,
            "top_density_slides": [],
            "max_line_count": 0,
            "dense_multiline_units": [],
            "units_with_split_unit_id": 0,
            "units_with_style_profile_id": 0,
            "special_layout_slides": [],
        }

    slides = [slide for slide in plan.get("slides", []) if isinstance(slide, dict)]
    counts: list[tuple[int, int]] = []
    dense_units: list[dict[str, Any]] = []
    special_layout: dict[int, set[str]] = {}
    split_count = 0
    style_count = 0
    max_line_count = 0

    for slide in slides:
        slide_index = _int_or_none(slide.get("slide_index"))
        if slide_index is None:
            continue
        units = [unit for unit in slide.get("text_units", []) if isinstance(unit, dict)]
        counts.append((slide_index, len(units)))
        for unit in units:
            if isinstance(unit.get("split_unit_id"), str) and unit["split_unit_id"].strip():
                split_count += 1
            if isinstance(unit.get("style_profile_id"), str) and unit["style_profile_id"].strip():
                style_count += 1
            line_count = _line_count(unit)
            max_line_count = max(max_line_count, line_count)
            if line_count > 3:
                dense_units.append(
                    {
                        "slide_index": slide_index,
                        "text_unit_id": unit.get("text_unit_id"),
                        "line_count": line_count,
                    }
                )
            keywords = _special_layout_keywords(unit)
            if keywords:
                special_layout.setdefault(slide_index, set()).update(keywords)

    text_unit_count = sum(count for _, count in counts)
    slide_count = len(counts)
    top_density = sorted(counts, key=lambda item: item[1], reverse=True)[:10]
    return {
        "status": "present",
        "slide_count": slide_count,
        "text_unit_count": text_unit_count,
        "avg_text_units_per_slide": round(text_unit_count / slide_count, 2) if slide_count else 0,
        "max_text_units_on_slide": max((count for _, count in counts), default=0),
        "top_density_slides": [{"slide_index": slide, "text_unit_count": count} for slide, count in top_density],
        "max_line_count": max_line_count,
        "dense_multiline_units": dense_units,
        "units_with_split_unit_id": split_count,
        "units_with_style_profile_id": style_count,
        "special_layout_slides": [
            {"slide_index": slide, "keywords": sorted(keywords)}
            for slide, keywords in sorted(special_layout.items())
        ],
    }


def _line_count(unit: dict[str, Any]) -> int:
    wrap = unit.get("wrap_policy")
    if isinstance(wrap, dict):
        value = wrap.get("line_count")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    text = unit.get("display_text") if isinstance(unit.get("display_text"), str) else unit.get("text")
    if not isinstance(text, str) or not text:
        return 0
    return max(1, len(text.splitlines()))


def _special_layout_keywords(unit: dict[str, Any]) -> set[str]:
    blob = " ".join(
        str(unit.get(field, ""))
        for field in ("semantic_role", "style_profile_id", "visual_group_id", "text_unit_id")
    ).lower()
    return {keyword for keyword in SPECIAL_LAYOUT_KEYWORDS if keyword.lower() in blob}


def _coordinate_warning_summary(warnings: Any) -> dict[str, Any]:
    items = warnings.get("warnings") if isinstance(warnings, dict) else []
    items = [item for item in items if isinstance(item, dict)]
    unresolved = [item for item in items if item.get("resolved") is not True]
    by_type = Counter(str(item.get("warning_type", "unknown")) for item in items)
    return {
        "status": "present" if isinstance(warnings, dict) else "missing",
        "overall_status": warnings.get("overall_status") if isinstance(warnings, dict) else "missing",
        "warning_count": len(items),
        "unresolved_warning_count": len(unresolved),
        "warning_slides": sorted({item.get("slide_index") for item in items if isinstance(item.get("slide_index"), int)}),
        "unresolved_warning_slides": sorted(
            {item.get("slide_index") for item in unresolved if isinstance(item.get("slide_index"), int)}
        ),
        "warning_types": dict(sorted(by_type.items())),
        "warnings": items,
    }


def _font_profile_summary(root: Path, profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {
            "status": "missing",
            "review_status": "missing",
            "profile_count": 0,
            "probe_slide_index": None,
            "assets": {},
        }
    render_probe = profile.get("render_probe") if isinstance(profile.get("render_probe"), dict) else {}
    basis = profile.get("basis") if isinstance(profile.get("basis"), dict) else {}
    assets = {}
    for key, relpath in {
        "stage2_image": basis.get("stage2_image"),
        "stage3_background": basis.get("stage3_background"),
        "probe_manifest": render_probe.get("probe_manifest"),
        "probe_pptx": render_probe.get("probe_pptx"),
        "render_image": render_probe.get("render_image"),
        "compare_image": render_probe.get("compare_image"),
    }.items():
        if isinstance(relpath, str) and relpath.strip():
            assets[key] = {"path": relpath, "exists": (root / relpath).exists()}
    missing_assets = sorted(key for key, item in assets.items() if item.get("exists") is False)
    review_status = render_probe.get("review_status", "unknown")
    return {
        "status": review_status if isinstance(review_status, str) else "unknown",
        "review_status": review_status,
        "profile_count": len(profile.get("profiles", [])) if isinstance(profile.get("profiles"), list) else 0,
        "probe_slide_index": basis.get("probe_slide_index"),
        "assets": assets,
        "missing_assets": missing_assets,
    }


def _execution_summary(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or not isinstance(report.get("slides"), list):
        return {
            "status": "missing",
            "slides_count": 0,
            "expected_text_units": 0,
            "matched_text_shapes": 0,
            "missing_text_units": 0,
            "deviations": 0,
            "possible_merged_text_shapes": 0,
            "possible_merged_slides": [],
        }
    totals = Counter()
    possible_slides: list[dict[str, Any]] = []
    for slide in report.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_index = slide.get("slide_index")
        summary = slide.get("summary") if isinstance(slide.get("summary"), dict) else {}
        totals["expected_text_units"] += _safe_int(summary.get("expected_text_units"))
        totals["matched_text_shapes"] += _safe_int(summary.get("matched_text_shapes"))
        totals["missing_text_units"] += _safe_int(summary.get("missing_text_units"))
        totals["deviations"] += _safe_int(summary.get("deviations"))
        merged = _safe_int(summary.get("possible_merged_text_shapes"))
        totals["possible_merged_text_shapes"] += merged
        if merged and isinstance(slide_index, int):
            possible_slides.append({"slide_index": slide_index, "possible_merged_text_shapes": merged})
    return {
        "status": "present",
        "slides_count": len([item for item in report.get("slides", []) if isinstance(item, dict)]),
        "expected_text_units": totals["expected_text_units"],
        "matched_text_shapes": totals["matched_text_shapes"],
        "missing_text_units": totals["missing_text_units"],
        "deviations": totals["deviations"],
        "possible_merged_text_shapes": totals["possible_merged_text_shapes"],
        "possible_merged_slides": possible_slides,
    }


def _officecli_builder_warning_summary(root: Path, editable_manifest: Any, default_manifest: Any) -> dict[str, Any]:
    officecli_manifest = _load_officecli_manifest(root, editable_manifest, default_manifest)
    if not isinstance(officecli_manifest, dict):
        return {
            "status": "missing",
            "warning_count": 0,
            "warning_types": {},
            "warning_slides": [],
            "text_shape_count": 0,
            "background_placement_count": 0,
        }
    warnings = officecli_manifest.get("warnings", [])
    warnings = [item for item in warnings if isinstance(item, dict)]
    placements = officecli_manifest.get("background_placements")
    placements = [item for item in placements if isinstance(item, dict)] if isinstance(placements, list) else []
    text_shapes = officecli_manifest.get("text_shapes")
    text_shapes = [item for item in text_shapes if isinstance(item, dict)] if isinstance(text_shapes, list) else []
    manifest_warnings: list[dict[str, Any]] = []
    if officecli_manifest.get("provider") != "officecli":
        manifest_warnings.append({"warning_type": "officecli_manifest_provider_invalid"})
    if officecli_manifest.get("mode") not in {"full_deck", "native_style_probe"}:
        manifest_warnings.append({"warning_type": "officecli_manifest_mode_invalid"})
    for field in ("commands", "command_results"):
        value = officecli_manifest.get(field)
        if not isinstance(value, str) or not value.strip() or not (root / value).exists():
            manifest_warnings.append({"warning_type": f"officecli_manifest_{field}_evidence_missing"})
    readback = officecli_manifest.get("readback") if isinstance(officecli_manifest.get("readback"), dict) else {}
    readback_path = readback.get("path") if isinstance(readback, dict) else None
    if not isinstance(readback_path, str) or not readback_path.strip() or not (root / readback_path).exists():
        manifest_warnings.append({"warning_type": "officecli_manifest_readback_evidence_missing"})
    for placement in placements:
        mode = str(placement.get("placement_mode") or placement.get("mode") or "").lower()
        if mode != "exact_full_slide" or placement.get("crop") is True:
            manifest_warnings.append(
                {
                    "slide_index": placement.get("slide_index"),
                    "warning_type": "officecli_background_not_exact_full_slide",
                }
            )
        if (
            not _number_close(placement.get("x"), 0)
            or not _number_close(placement.get("y"), 0)
            or not _number_close(placement.get("width"), 960.0)
            or not _number_close(placement.get("height"), 540.0)
        ):
            manifest_warnings.append(
                {
                    "slide_index": placement.get("slide_index"),
                    "warning_type": "officecli_background_geometry_mismatch",
                }
            )
        image_path = placement.get("image_path")
        if not isinstance(image_path, str) or not image_path.strip() or not (root / image_path).exists():
            manifest_warnings.append(
                {
                    "slide_index": placement.get("slide_index"),
                    "warning_type": "officecli_background_image_missing",
                }
            )
    for item in text_shapes:
        text_unit_id = item.get("text_unit_id")
        if not isinstance(item.get("shape_path"), str) or not item["shape_path"].strip():
            manifest_warnings.append(
                {
                    "slide_index": item.get("slide_index"),
                    "text_unit_id": text_unit_id,
                    "warning_type": "officecli_text_shape_readback_path_missing",
                }
            )
        if item.get("shape_id") in (None, ""):
            manifest_warnings.append(
                {
                    "slide_index": item.get("slide_index"),
                    "text_unit_id": text_unit_id,
                    "warning_type": "officecli_text_shape_readback_id_missing",
                }
            )
        if not isinstance(item.get("readback_relative_box"), dict):
            manifest_warnings.append(
                {
                    "slide_index": item.get("slide_index"),
                    "text_unit_id": text_unit_id,
                    "warning_type": "officecli_text_shape_readback_box_missing",
                }
            )
    all_warnings = [*warnings, *manifest_warnings]
    by_type = Counter(str(item.get("warning_type", "unknown")) for item in all_warnings)
    return {
        "status": "present",
        "warning_count": len(all_warnings),
        "warning_types": dict(sorted(by_type.items())),
        "warning_slides": sorted(
            {
                item.get("slide_index")
                for item in all_warnings
                if isinstance(item.get("slide_index"), int)
            }
        ),
        "text_shape_count": len(text_shapes),
        "background_placement_count": len(placements),
        "warnings": all_warnings,
    }


def _load_officecli_manifest(root: Path, editable_manifest: Any, default_manifest: Any) -> Any | None:
    if isinstance(default_manifest, dict) and not default_manifest.get("_read_error"):
        return default_manifest
    candidates: list[Path] = []
    if isinstance(editable_manifest, dict):
        evidence = editable_manifest.get("runtime_evidence")
        if isinstance(evidence, dict) and isinstance(evidence.get("officecli_manifest"), str):
            candidates.append(root / evidence["officecli_manifest"])
    candidates.append(root / "_state" / "阶段3" / "manifests" / "officecli_manifest.json")
    for path in candidates:
        if path.exists():
            return _read_optional_json(path)
    return None


def _qa_summary(review: Any) -> dict[str, Any]:
    if not isinstance(review, dict):
        return {"status": "missing", "overall_status": "missing", "reviewed_slides": [], "qa_high_risk_slides": []}
    reviewed = [
        slide.get("slide_index")
        for slide in review.get("slides", [])
        if isinstance(slide, dict) and isinstance(slide.get("slide_index"), int)
    ]
    split_review = review.get("split_granularity_review") if isinstance(review.get("split_granularity_review"), dict) else {}
    high_risk = split_review.get("high_risk_slides", [])
    high_risk = [item for item in high_risk if isinstance(item, int)]
    native_style_probe = review.get("native_style_probe") if isinstance(review.get("native_style_probe"), dict) else {}
    if not native_style_probe:
        native_style_probe = review.get("font_probe") if isinstance(review.get("font_probe"), dict) else {}
    recommended_coverage = (
        review.get("recommended_high_risk_coverage")
        if isinstance(review.get("recommended_high_risk_coverage"), dict)
        else {}
    )
    recommended_reviewed = _safe_int_list(recommended_coverage.get("reviewed_slides", []))
    recommended_declared = _safe_int_list(recommended_coverage.get("recommended_slides", []))
    return {
        "status": "present",
        "overall_status": review.get("overall_status"),
        "reviewed_slides": sorted(set(reviewed)),
        "qa_high_risk_slides": sorted(set(high_risk)),
        "recommended_high_risk_coverage": {
            "recommended_slides": recommended_declared,
            "reviewed_slides": recommended_reviewed,
            "not_reviewed_with_reason_count": len(
                recommended_coverage.get("not_reviewed_with_reason", [])
                if isinstance(recommended_coverage.get("not_reviewed_with_reason"), list)
                else []
            ),
        },
        "native_style_probe_review_status": native_style_probe.get("review_status"),
    }


def _decision_lineage(root: Path) -> dict[str, Any]:
    directory = root / "_decisions"
    flags = {
        "skipped_stage3_before": False,
        "reopened_stage3_after_stage4": False,
        "stage3_revision_requested": False,
    }
    decision_ids: list[str] = []
    slide_mentions: dict[int, list[str]] = {}
    if not directory.exists():
        return {"status": "missing", **flags, "decision_ids": decision_ids, "mentioned_slides": []}

    stage3_was_skipped_or_completed = False
    for path in sorted(directory.glob("*.json")):
        value = _read_optional_json(path)
        decisions = value if isinstance(value, list) else [value]
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            decision_id = str(decision.get("decision_id") or path.stem)
            decision_ids.append(decision_id)
            decision_type = str(decision.get("decision_type", ""))
            blob = _decision_text_blob(decision)
            if "skip_stage3" in decision_type or "跳过阶段3" in blob:
                flags["skipped_stage3_before"] = True
                stage3_was_skipped_or_completed = True
            if decision_type == "approve_stage3_start_script_output" or decision_type == "stage4_script_completed":
                stage3_was_skipped_or_completed = True
            if stage3_was_skipped_or_completed and _is_stage3_reopen_decision(decision_type, blob):
                flags["reopened_stage3_after_stage4"] = True
            if (
                "request_stage3_revision" in decision_type
                or (_is_stage3_action_decision(decision_type, blob) and ("二次精修" in blob or "返工" in blob))
            ):
                flags["stage3_revision_requested"] = True
            if _is_stage3_action_decision(decision_type, blob):
                for slide_index in _extract_slide_numbers(blob):
                    slide_mentions.setdefault(slide_index, []).append(decision_id)
    return {
        "status": "present",
        **flags,
        "decision_ids": decision_ids,
        "mentioned_slides": [
            {"slide_index": slide_index, "decision_ids": ids}
            for slide_index, ids in sorted(slide_mentions.items())
        ],
    }


def _decision_text_blob(decision: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(decision)
    return "\n".join(parts)


def _is_stage3_decision(decision_type: str, blob: str) -> bool:
    normalized_type = decision_type.lower()
    return (
        "stage3" in normalized_type
        or "阶段3" in blob
        or "可编辑" in blob
        or "坐标" in blob
        or "二次精修" in blob
    )


def _is_stage3_action_decision(decision_type: str, blob: str) -> bool:
    normalized_type = decision_type.lower()
    if "stage3" in normalized_type:
        return True
    if _is_stage3_reopen_decision(decision_type, blob):
        return True
    action_phrases = (
        "阶段3返工",
        "返工阶段3",
        "阶段三返工",
        "返工阶段三",
        "阶段3二次精修",
        "二次精修阶段3",
        "阶段三二次精修",
        "二次精修阶段三",
        "阶段3坐标",
        "阶段三坐标",
        "坐标确认",
        "坐标返工",
        "可编辑PPT返工",
        "可编辑PPT确认",
    )
    return any(phrase in blob for phrase in action_phrases)


def _is_stage3_reopen_decision(decision_type: str, blob: str) -> bool:
    normalized_type = decision_type.lower()
    normalized_blob = blob.lower()
    if _has_negated_stage3_reopen(blob, normalized_blob):
        return False
    has_reopen_intent = (
        "reopen" in normalized_type
        or "reopen" in normalized_blob
        or "回补" in blob
        or "补做" in blob
        or "重新打开" in blob
    )
    return has_reopen_intent and _is_stage3_decision(decision_type, blob)


def _has_negated_stage3_reopen(blob: str, normalized_blob: str) -> bool:
    negative_phrases = (
        "不涉及阶段3回补",
        "不涉及阶段三回补",
        "不回补阶段3",
        "不回补阶段三",
        "未回补阶段3",
        "未回补阶段三",
        "没有回补阶段3",
        "没有回补阶段三",
        "不重新打开阶段3",
        "不重新打开阶段三",
        "未重新打开阶段3",
        "未重新打开阶段三",
    )
    if any(phrase in blob for phrase in negative_phrases):
        return True
    return "no stage3 reopen" in normalized_blob or "without stage3 reopen" in normalized_blob


def _extract_slide_numbers(text: str) -> list[int]:
    numbers: set[int] = set()
    for pattern in (r"第\s*(\d{1,3})\s*页", r"slide[_\s-]*(\d{1,3})", r"Slide\s*(\d{1,3})"):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = int(match.group(1))
            if 1 <= value <= 300:
                numbers.add(value)
    return sorted(numbers)


def _recommended_high_risk_slides(
    *,
    coordinate_metrics: dict[str, Any],
    warning_summary: dict[str, Any],
    execution_summary: dict[str, Any],
    lineage: dict[str, Any],
    limit: int | None = 10,
) -> list[dict[str, Any]]:
    reasons: dict[int, set[str]] = {}

    for item in coordinate_metrics.get("top_density_slides", [])[:5]:
        slide = item.get("slide_index")
        count = item.get("text_unit_count")
        if isinstance(slide, int) and _safe_int(count) > 18:
            reasons.setdefault(slide, set()).add(f"top_text_unit_density:{count}")

    for item in coordinate_metrics.get("dense_multiline_units", []):
        slide = item.get("slide_index")
        if isinstance(slide, int):
            reasons.setdefault(slide, set()).add(f"dense_multiline_unit:{item.get('line_count')}")

    for slide in warning_summary.get("unresolved_warning_slides", []):
        if isinstance(slide, int):
            reasons.setdefault(slide, set()).add("unresolved_coordinate_warning")

    for item in execution_summary.get("possible_merged_slides", []):
        slide = item.get("slide_index")
        if isinstance(slide, int):
            reasons.setdefault(slide, set()).add(f"possible_merged_text_shapes:{item.get('possible_merged_text_shapes')}")

    for item in coordinate_metrics.get("special_layout_slides", []):
        slide = item.get("slide_index")
        keywords = item.get("keywords", [])
        if isinstance(slide, int):
            reasons.setdefault(slide, set()).add("special_layout:" + ",".join(str(keyword) for keyword in keywords[:3]))

    for item in lineage.get("mentioned_slides", []):
        slide = item.get("slide_index")
        if isinstance(slide, int):
            reasons.setdefault(slide, set()).add("mentioned_in_stage3_decision")

    ranked = []
    for slide, slide_reasons in reasons.items():
        priority = _risk_priority(slide_reasons)
        ranked.append(
            {
                "slide_index": slide,
                "priority": priority,
                "risk_score": _risk_score(slide_reasons),
                "reasons": sorted(slide_reasons),
            }
        )
    ranked.sort(key=lambda item: (_priority_rank(item["priority"]), -item["risk_score"], item["slide_index"]))
    if limit is None:
        return ranked
    return _with_secondary_note(ranked[:limit], ranked[limit:])


def _with_secondary_note(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in primary:
        if secondary:
            item.setdefault("notes", "More secondary review slides exist in coordinate_metrics/special_layout_slides.")
    return primary


def _risk_priority(reasons: set[str]) -> str:
    joined = " ".join(reasons)
    has_warning_or_dense = "unresolved_coordinate_warning" in reasons or "dense_multiline" in joined
    has_execution_or_density = "top_text_unit_density" in joined or "possible_merged" in joined
    if has_warning_or_dense:
        return "P0"
    if has_execution_or_density:
        return "P1"
    return "P2"


def _risk_score(reasons: set[str]) -> int:
    score = 0
    for reason in reasons:
        if reason == "unresolved_coordinate_warning":
            score += 100
        elif reason.startswith("dense_multiline_unit"):
            score += 90
            score += _reason_number(reason)
        elif reason.startswith("possible_merged_text_shapes"):
            score += 70
            score += _reason_number(reason)
        elif reason.startswith("top_text_unit_density"):
            score += 50
            score += _reason_number(reason)
        elif reason == "mentioned_in_stage3_decision":
            score += 30
        elif reason.startswith("special_layout"):
            score += 10
    return score


def _reason_number(reason: str) -> int:
    match = re.search(r":(\d+)", reason)
    return int(match.group(1)) if match else 0


def _priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


def _native_style_probe_recommendation(
    *,
    coordinate_metrics: dict[str, Any],
    warning_summary: dict[str, Any],
    font_summary: dict[str, Any],
    builder_summary: dict[str, Any],
    recommended_high_risk_slides: list[dict[str, Any]],
) -> dict[str, Any]:
    status = font_summary.get("status")
    reasons: list[str] = []
    if coordinate_metrics.get("slide_count", 0) > 20:
        reasons.append("large_deck")
    if coordinate_metrics.get("text_unit_count", 0) > 250:
        reasons.append("many_text_units")
    if coordinate_metrics.get("max_text_units_on_slide", 0) > 20:
        reasons.append("dense_slide")
    if coordinate_metrics.get("max_line_count", 0) > 3:
        reasons.append("dense_multiline_units")
    if warning_summary.get("unresolved_warning_count", 0) > 0:
        reasons.append("unresolved_coordinate_warnings")
    builder_warning_types = builder_summary.get("warning_types", {})
    if "line_spacing_readback_mismatch" in builder_warning_types or "line_spacing_not_applied_by_builder" in builder_warning_types:
        reasons.append("line_spacing_readback_risk")
    if any(str(key).startswith("officecli_text_shape_readback_") for key in builder_warning_types):
        reasons.append("officecli_text_shape_readback_incomplete")
    if font_summary.get("missing_assets"):
        reasons.append("font_profile_assets_missing")

    if status == "passed" and not reasons:
        strength = "not_needed"
    elif status == "passed" and "font_profile_assets_missing" not in reasons:
        strength = "reuse_existing_profile"
    elif status == "passed":
        strength = "recommended"
    elif status in {"draft", "needs_rework"}:
        strength = "recommended"
        reasons.append(f"font_profile_{status}")
    elif status == "missing" and reasons:
        strength = "strongly_recommended"
        reasons.append("missing_profile")
    elif status == "missing":
        strength = "recommended" if coordinate_metrics.get("text_unit_count", 0) > 120 else "not_needed"
        if strength == "recommended":
            reasons.append("missing_profile")
    else:
        strength = "recommended"
        reasons.append("font_profile_unknown")

    candidates: list[int] = []
    existing_probe = font_summary.get("probe_slide_index")
    if isinstance(existing_probe, int):
        candidates.append(existing_probe)
    for item in recommended_high_risk_slides:
        slide = item.get("slide_index")
        if isinstance(slide, int) and slide not in candidates:
            candidates.append(slide)
    return {
        "strength": strength,
        "candidate_probe_slides": candidates[:3],
        "reasons": sorted(set(reasons)),
    }


def _qa_coverage_review(recommended: list[dict[str, Any]], qa_summary: dict[str, Any]) -> dict[str, Any]:
    recommended_slides = [item["slide_index"] for item in recommended if isinstance(item.get("slide_index"), int)]
    qa_high_risk = qa_summary.get("qa_high_risk_slides", [])
    qa_high_risk = [item for item in qa_high_risk if isinstance(item, int)]
    recommended_coverage = (
        qa_summary.get("recommended_high_risk_coverage")
        if isinstance(qa_summary.get("recommended_high_risk_coverage"), dict)
        else {}
    )
    reviewed_from_coverage = _safe_int_list(recommended_coverage.get("reviewed_slides", []))
    reviewed_set = set(qa_high_risk) | set(reviewed_from_coverage)
    missing = [slide for slide in recommended_slides if slide not in reviewed_set]
    return {
        "qa_high_risk_slides": sorted(set(qa_high_risk)),
        "qa_recommended_coverage_reviewed_slides": sorted(set(reviewed_from_coverage)),
        "recommended_high_risk_slides": recommended_slides,
        "recommended_not_in_qa_high_risk": missing,
        "notes": "该字段只提示主控复核，不自动判失败。",
    }


def _risk_signals(
    *,
    coordinate_metrics: dict[str, Any],
    warning_summary: dict[str, Any],
    font_summary: dict[str, Any],
    execution_summary: dict[str, Any],
    builder_summary: dict[str, Any],
    qa_coverage: dict[str, Any],
    lineage: dict[str, Any],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    if font_summary.get("status") == "missing" and coordinate_metrics.get("text_unit_count", 0) > 120:
        signals.append(
            {
                "severity": "attention",
                "signal": "font_profile_missing_for_nontrivial_deck",
                "slides": [],
                "reason": "阶段3文本对象数量较多，但缺少 font calibration profile。",
            }
        )
    if warning_summary.get("unresolved_warning_count", 0):
        signals.append(
            {
                "severity": "attention",
                "signal": "unresolved_coordinate_warnings",
                "slides": warning_summary.get("unresolved_warning_slides", []),
                "reason": "坐标计划仍有未解决 warning，需要主控复核或说明接受理由。",
            }
        )
    if execution_summary.get("possible_merged_text_shapes", 0):
        signals.append(
            {
                "severity": "review",
                "signal": "possible_merged_text_shapes",
                "slides": [item["slide_index"] for item in execution_summary.get("possible_merged_slides", [])],
                "reason": "execution report 发现可能合并的 PPT 文本框。",
            }
        )
    if builder_summary.get("warning_count", 0):
        signals.append(
            {
                "severity": "review",
                "signal": "officecli_builder_warnings",
                "slides": builder_summary.get("warning_slides", []),
                "reason": "OfficeCLI builder manifest 中存在 warning，主控需查看是否影响多行文本或背景。",
            }
        )
    if font_summary.get("missing_assets"):
        signals.append(
            {
                "severity": "review",
                "signal": "font_profile_asset_missing",
                "slides": [],
                "reason": "font calibration profile 引用的 probe 资产缺失，主控需要确认 profile 是否仍可复用。",
            }
        )
    if qa_coverage.get("recommended_not_in_qa_high_risk"):
        signals.append(
            {
                "severity": "review",
                "signal": "qa_high_risk_coverage_gap",
                "slides": qa_coverage["recommended_not_in_qa_high_risk"],
                "reason": "部分推荐高风险页未出现在 QA high_risk_slides 中。",
            }
        )
    if lineage.get("reopened_stage3_after_stage4"):
        signals.append(
            {
                "severity": "review",
                "signal": "stage3_reopened_after_stage4",
                "slides": [],
                "reason": "该项目曾在阶段4完成后回补阶段3，需要主控额外核对锁定稿和可编辑稿一致性。",
            }
        )
    return signals


def _controller_next_actions(
    risk_signals: list[dict[str, Any]],
    probe_recommendation: dict[str, Any],
    qa_coverage: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if risk_signals:
        actions.append("主控先复核 risk_signals 和 recommended_high_risk_slides，再决定是否返工。")
    if probe_recommendation.get("strength") in {"strongly_recommended", "recommended"}:
        actions.append("主控建议基于 candidate_probe_slides 选择一页执行 OfficeCLI native style probe。")
    if qa_coverage.get("recommended_not_in_qa_high_risk"):
        actions.append("最终 QA 前补看 recommended_not_in_qa_high_risk，或写明不采纳理由。")
    if not actions:
        actions.append("未发现明显阶段3质量画像风险；按现有坐标复刻 QA 流程继续。")
    return actions


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _safe_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def _number_close(value: Any, expected: float, tolerance: float = 0.01) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return abs(float(value) - expected) <= tolerance


def _unique_ints(values: Any) -> list[int]:
    result: list[int] = []
    try:
        iterator = iter(values)
    except TypeError:
        return result
    for value in iterator:
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value not in result:
            result.append(value)
    return result


def _relpath_or_abs(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _native_style_probe_plan_decision(native_style_probe: dict[str, Any]) -> dict[str, Any]:
    strength = native_style_probe.get("strength")
    candidates = _unique_ints(native_style_probe.get("candidate_probe_slides", []))
    if strength in {"strongly_recommended", "recommended"}:
        decision = "run_probe"
    elif strength == "reuse_existing_profile":
        decision = "reuse_existing_profile"
    elif strength == "not_needed":
        decision = "not_needed"
    else:
        decision = "controller_decision_required"
    return {
        "decision": decision,
        "probe_slide_index": candidates[0] if candidates else None,
        "candidate_probe_slides": candidates,
        "recommendation_strength": strength,
        "reasons": native_style_probe.get("reasons", []),
    }


def _review_scope_reasoning(profile: dict[str, Any], must_review_slides: list[int]) -> str:
    signals = [
        signal.get("signal")
        for signal in profile.get("risk_signals", [])
        if isinstance(signal, dict) and isinstance(signal.get("signal"), str)
    ]
    if not must_review_slides and not signals:
        return "质量画像未发现明显阶段3风险；主控可按常规 QA 抽检。"
    pieces: list[str] = []
    if must_review_slides:
        pieces.append("must_review_slides 覆盖 P0 推荐页、QA 尚未覆盖的推荐页或画像排序靠前页面")
    if signals:
        pieces.append("主要信号：" + "、".join(signals[:6]))
    return "；".join(pieces) + "。"


def _draft_planned_actions(
    profile: dict[str, Any],
    probe_decision: dict[str, Any],
    must_review_slides: list[int],
) -> list[str]:
    actions: list[str] = []
    if must_review_slides:
        actions.append("主控逐页复核 must_review_slides，对不返工的风险写 accepted_tradeoffs。")
    if probe_decision.get("decision") == "run_probe":
        actions.append("优先使用 probe_slide_index 执行或复核 OfficeCLI native style probe。")
    qa_gap = profile.get("qa_coverage_review", {})
    if isinstance(qa_gap, dict) and qa_gap.get("recommended_not_in_qa_high_risk"):
        actions.append("record-coordinate-stage3-qa 前补齐 recommended_high_risk_coverage 或写明未覆盖原因。")
    if not actions:
        actions.append("按常规阶段3 QA 继续，并保留 quality_profile 引用。")
    return actions


def _learned_controller_patterns(
    profile: dict[str, Any],
    must_review_slides: list[int],
    optional_review_slides: list[int],
) -> list[dict[str, Any]]:
    slide_hint = _unique_ints([*must_review_slides, *optional_review_slides])
    reviewed_hint = "、".join(f"第{slide}页" for slide in slide_hint[:8]) if slide_hint else "画像推荐页"
    lineage = profile.get("decision_lineage") if isinstance(profile.get("decision_lineage"), dict) else {}
    revision_requested = bool(lineage.get("stage3_revision_requested"))
    return [
        {
            "pattern_id": "targeted_page_micro_refinement",
            "source": "三个优秀会话的共同落地动作",
            "controller_instruction": (
                f"先复核 {reviewed_hint}，只对真实渲染暴露问题的页面做坐标、字号、换行或颜色微调；"
                "已稳定页面只做确认和保护，避免连带重排。"
            ),
            "apply_when": "质量画像推荐页、用户点名页、返工决策提到的页或渲染复核发现局部瑕疵时。",
        },
        {
            "pattern_id": "native_render_micro_defect_scan",
            "source": "优秀会话反复捕捉到的 PowerPoint 实际排版问题",
            "controller_instruction": (
                "最终交付前复查孤立标点、孤字掉行、长句二次换行、标题贴近色块或装饰线、"
                "正文压线、浅底低对比和表格/流程页局部拥挤。"
            ),
            "apply_when": "execution report 通过后仍必须执行；0 missing/0 deviation 不代表视觉通过。",
        },
        {
            "pattern_id": "ledger_synchronized_cleanup",
            "source": "优秀会话清理制作备注的做法",
            "controller_instruction": (
                "如果页面上出现制作备注、内部标签、重复对象或需要补回漏录文字，必须同步更新阶段1内容资产、"
                "拆字计划、ownership map 和坐标计划，禁止只在 PPTX 层临时隐藏或补框。"
            ),
            "apply_when": "清理可见文字、修复重复文字、补回阶段2确认图可见文字或新增拆分对象时。",
        },
        {
            "pattern_id": "auditable_iteration_loop",
            "source": "优秀会话的返工闭环",
            "controller_instruction": (
                "每轮微调都写清主控决策、范围、依据、接受取舍和复核结果；生成后重跑渲染、"
                "execution report、QA 和必要的 doctor，而不是只覆盖最终 PPTX。"
            ),
            "apply_when": "发生阶段3返工、二次精修或最终微调时。" if revision_requested else "发生任何阶段3返工或最终微调时。",
        },
    ]


def _bad_case_avoidance_checks(profile: dict[str, Any], probe_decision: dict[str, Any]) -> list[dict[str, Any]]:
    summary = profile.get("summary") if isinstance(profile.get("summary"), dict) else {}
    qa_coverage = profile.get("qa_coverage_review") if isinstance(profile.get("qa_coverage_review"), dict) else {}
    lineage = profile.get("decision_lineage") if isinstance(profile.get("decision_lineage"), dict) else {}
    risk_signals = profile.get("risk_signals") if isinstance(profile.get("risk_signals"), list) else []
    execution_clean = (
        summary.get("execution_missing_text_units") == 0
        and summary.get("execution_deviations") == 0
        and (summary.get("text_unit_count") or 0) > 0
    )
    checks = [
        {
            "check_id": "do_not_treat_execution_clean_as_visual_pass",
            "triggered": bool(execution_clean and risk_signals),
            "controller_check": (
                "即使 execution report 是 0 missing/0 deviation，只要还有画像风险信号，仍要看渲染图、"
                "重点页大图和对象粒度。"
            ),
        },
        {
            "check_id": "missing_or_stale_native_style_probe_on_dense_deck",
            "triggered": probe_decision.get("decision") == "run_probe",
            "controller_check": (
                "大页数、多文字对象、长行或缺 profile 时，优先执行或复核 OfficeCLI native style probe；"
                "不做 probe 必须说明为什么当前字体档案仍可信。"
            ),
        },
        {
            "check_id": "unresolved_coordinate_warnings_cannot_be_silent",
            "triggered": (summary.get("unresolved_coordinate_warning_count") or 0) > 0,
            "controller_check": "未解决 coordinate warning 必须返工、转入重点页复核，或写明可接受取舍。",
        },
        {
            "check_id": "qa_recommended_pages_must_be_accounted_for",
            "triggered": bool(qa_coverage.get("recommended_not_in_qa_high_risk")),
            "controller_check": (
                "质量画像推荐页如果未进入 QA high risk/recommended coverage，最终 QA 必须补看或写明未覆盖理由。"
            ),
        },
        {
            "check_id": "possible_merged_requires_object_level_review",
            "triggered": (summary.get("possible_merged_text_shapes") or 0) > 0,
            "controller_check": (
                "possible merged 不是自动失败，但要结合对象名、文本框数量和渲染图确认没有把应独立编辑的文字合并。"
            ),
        },
        {
            "check_id": "stage4_reopen_requires_consistency_review",
            "triggered": bool(lineage.get("reopened_stage3_after_stage4")),
            "controller_check": "阶段4后回补阶段3时，额外核对锁定稿、可编辑稿、讲稿和最终交付状态是否一致。",
        },
    ]
    return checks
