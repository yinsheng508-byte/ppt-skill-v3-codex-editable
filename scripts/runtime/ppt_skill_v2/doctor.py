from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .json_io import read_json
from .coordinate_stage3_qa import COORDINATE_QA_CHECK_KEYS, validate_coordinate_stage3_qa_review
from .image_geometry import read_image_dimensions
from .officecli_utils import SLIDE_HEIGHT_PT, SLIDE_WIDTH_PT
from .stage3_artifact_hashes import stage3_artifacts_stale
from .validation import (
    TEXT_FILL_EXECUTION_ACTUAL_SOURCES,
    validate_speaker_script_manifest,
    validate_stage2_aesthetic_review,
)


FORBIDDEN_SUFFIXES = {".json", ".jsonl", ".log"}
FORBIDDEN_NAME_PARTS = ("packet", "manifest", "worker", "prompt_raw")
HIGH_RISK_DELTA_NOTE_ANCHORS = ("阶段2", "层级", "结构", "强调", "背景", "前景", "公式", "卡片", "清单", "风险", "相似")
USER_STAGE_DIRS = [
    "阶段0_资料整理",
    "阶段1_规划确认",
    "阶段2_图片版PPT",
    "阶段3_可编辑PPT",
    "阶段4_演讲稿输出",
]


def check_project(run_dir: str | Path) -> dict[str, object]:
    root = Path(run_dir)
    issues: list[str] = []
    warnings: list[str] = []
    required = ["项目总览.md", "_state/project_state.json", "_state/events.jsonl", "_decisions"]
    for relative in required:
        if not (root / relative).exists():
            issues.append(f"缺少必要路径：{relative}")
    for dirname in USER_STAGE_DIRS:
        stage_dir = root / dirname
        if not stage_dir.exists():
            issues.append(f"缺少阶段目录：{dirname}")
            continue
        for path in stage_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if path.suffix in FORBIDDEN_SUFFIXES:
                issues.append(f"阶段目录包含过程文件：{relative}")
                continue
            lower_name = path.name.lower()
            if any(part in lower_name for part in FORBIDDEN_NAME_PARTS):
                issues.append(f"阶段目录包含疑似过程文件：{relative}")
    _check_stage1_stage2_consistency(root, issues, warnings)
    _check_stage3_consistency(root, issues, warnings)
    _check_stage4_consistency(root, issues, warnings)
    return {"ok": not issues, "issues": issues, "warnings": warnings}


def _check_stage1_stage2_consistency(root: Path, issues: list[str], warnings: list[str]) -> None:
    state_path = root / "_state" / "project_state.json"
    if not state_path.exists():
        return
    try:
        state = read_json(state_path)
    except Exception:
        return

    current_stage = state.get("current_stage")
    confirmed = state.get("confirmed") if isinstance(state.get("confirmed"), dict) else {}
    status = state.get("status")
    if current_stage in {"stage1", "stage2", "stage3", "stage4"} or confirmed.get("stage1_plan"):
        if not (root / "_state" / "阶段1" / "design_contract.json").exists():
            warnings.append("阶段1缺少 design_contract.json；新流程应先补齐设计合同再进入阶段2")
    if current_stage in {"stage2", "stage3", "stage4"}:
        if not (root / "_state" / "阶段1" / "layout_safety_contract.json").exists():
            issues.append("新流程进入阶段2后必须有 _state/阶段1/layout_safety_contract.json")

    trial_summary = root / "阶段2_图片版PPT" / "前5页试样" / "前5页试样说明.md"
    if status == "waiting_user_trial_first5_confirmation" and not trial_summary.exists():
        issues.append("阶段2状态等待试样确认，但缺少 前5页试样说明.md")
    if current_stage == "stage2" and status == "waiting_user_confirmation" and not (root / "阶段2_图片版PPT" / "pdf" / "图片版PPT.pdf").exists():
        issues.append("阶段2状态等待图片版 PDF 确认，但缺少 阶段2_图片版PPT/pdf/图片版PPT.pdf")

    visual_qa = root / "_state" / "阶段2" / "visual_qa" / "stage2_aesthetic_review.json"
    if visual_qa.exists():
        try:
            review = validate_stage2_aesthetic_review(read_json(visual_qa))
        except Exception as exc:
            issues.append(f"stage2_aesthetic_review.json 无法通过校验：{exc}")
            return
        if review.get("overall_status") == "needs_rework" and status not in {
            "trial_first5_revision_requested",
            "cover_style_revision_requested",
            "revision_requested",
        }:
            warnings.append("stage2_aesthetic_review.json 要求返工，但 project_state 未处于阶段2返工状态")
    elif current_stage == "stage2" and status in {"waiting_user_trial_first5_confirmation", "waiting_user_confirmation"}:
        warnings.append("阶段2已进入用户确认相关状态，但尚未记录 stage2_aesthetic_review.json")


def _check_stage3_consistency(root: Path, issues: list[str], warnings: list[str]) -> None:
    state_path = root / "_state" / "project_state.json"
    if not state_path.exists():
        return
    try:
        state = read_json(state_path)
    except Exception as exc:  # pragma: no cover - corrupted JSON detail is enough for doctor
        issues.append(f"project_state.json 无法读取：{exc}")
        return
    current_stage = state.get("current_stage")
    status = state.get("status")
    if current_stage == "stage4" and _stage4_source_mode(state) in {"stage2_image_deck", "external_editable_deck"}:
        return

    stage3_results = root / "_state" / "阶段3" / "no_text_background_results"
    if stage3_results.exists():
        for result_path in sorted(stage3_results.glob("slide_*.json")):
            try:
                result = read_json(result_path)
            except Exception as exc:
                issues.append(f"阶段3背景结果无法读取：{result_path.relative_to(root)}: {exc}")
                continue
            if result.get("fixture"):
                continue
            if result.get("purpose") != "stage2_text_removed_background":
                issues.append(f"阶段3背景使用旧路线或未知 purpose：{result_path.relative_to(root)}")
            if result.get("background_route") != "stage2_preserve_text_removed_background":
                issues.append(f"阶段3背景缺少保真去字 route：{result_path.relative_to(root)}")
            source_stage2 = result.get("source_stage2")
            if not isinstance(source_stage2, dict) or not source_stage2.get("image_sha256"):
                issues.append(f"阶段3背景缺少 source_stage2 证据：{result_path.relative_to(root)}")
            if not isinstance(result.get("restore_targets_hash"), str) or not result["restore_targets_hash"].startswith("sha256:"):
                issues.append(f"阶段3背景缺少 restore_targets_hash：{result_path.relative_to(root)}")
            if not isinstance(result.get("restore_targets"), list) or not result["restore_targets"]:
                issues.append(f"阶段3背景缺少 restore_targets 账本：{result_path.relative_to(root)}")

    if current_stage not in {"stage3", "stage4"}:
        return
    stale = {}
    state_stale = state.get("stage3_stale_artifacts")
    if isinstance(state_stale, dict):
        stale.update({str(key): str(value) for key, value in state_stale.items()})
    stale.update(stage3_artifacts_stale(root))
    for key, reason in sorted(stale.items()):
        issues.append(f"阶段3存在过期产物：{key}={reason}")

    slot_map = root / "_state" / "阶段3" / "visual_slot_map.json"
    text_plan = root / "_state" / "阶段3" / "text_fill_plan.json"
    ownership_map = root / "_state" / "阶段3" / "text_ownership_map.json"
    coordinate_plan = root / "_state" / "阶段3" / "editable_coordinate_plan.json"
    editable_manifest = root / "_state" / "阶段3" / "manifests" / "editable_deck.json"
    visual_qa = root / "_state" / "阶段3" / "render_review" / "stage3_visual_qa_review.json"
    editable_pptx = root / "阶段3_可编辑PPT" / "ppt" / "可编辑PPT.pptx"
    _check_stage3_timestamps(root, coordinate_plan, editable_manifest, visual_qa, warnings)
    _check_stage3_canonical_geometry(root, coordinate_plan, issues, warnings)

    if slot_map.exists() or text_plan.exists():
        warnings.append("阶段3存在旧 fixed overlay 产物；新流程不会把 visual_slot_map/text_fill_plan 作为正式通过依据")

    if status in {
        "stage3_text_ownership_ready",
        "waiting_user_coordinate_plan_confirmation",
        "stage3_editable_coordinate_plan_ready",
        "stage3_coordinate_plan_confirmed",
        "stage3_coordinate_plugin_handoff_ready",
        "stage3_coordinate_builder_handoff_ready",
        "stage3_officecli_deck_built",
        "stage3_native_style_probe_built",
        "stage3_editable_qa_required",
        "waiting_user_confirmation",
    }:
        if not ownership_map.exists():
            issues.append("阶段3缺少 text_ownership_map.json")
    if status in {
        "waiting_user_coordinate_plan_confirmation",
        "stage3_editable_coordinate_plan_ready",
        "stage3_coordinate_plan_confirmed",
        "stage3_coordinate_plugin_handoff_ready",
        "stage3_coordinate_builder_handoff_ready",
        "stage3_officecli_deck_built",
        "stage3_native_style_probe_built",
        "stage3_editable_qa_required",
        "waiting_user_confirmation",
    }:
        if not coordinate_plan.exists():
            issues.append("阶段3缺少 editable_coordinate_plan.json")
    if status == "stage3_coordinate_plugin_handoff_ready":
        warnings.append("阶段3仍使用 legacy plugin handoff 状态；新流程应改为 stage3_coordinate_builder_handoff_ready")
    if status in {
        "stage3_coordinate_plugin_handoff_ready",
        "stage3_coordinate_builder_handoff_ready",
        "stage3_officecli_deck_built",
        "stage3_native_style_probe_built",
        "stage3_editable_qa_required",
        "waiting_user_confirmation",
    }:
        if not state.get("confirmed", {}).get("stage3_coordinate_plan"):
            issues.append("阶段3尚未记录用户确认文字坐标复刻，不能进入 OfficeCLI 坐标填字或可编辑 PPT 确认")

    if editable_pptx.exists() and not editable_manifest.exists():
        issues.append("阶段3存在可编辑 PPTX 但缺少 editable_deck.json manifest")
    if editable_manifest.exists():
        _check_editable_manifest(root, editable_manifest, issues)
    if status in {"waiting_user_confirmation"} or current_stage == "stage4":
        if not visual_qa.exists():
            issues.append("阶段3缺少 stage3_visual_qa_review.json")
        else:
            _check_visual_qa(root, visual_qa, issues)
    elif visual_qa.exists():
        warnings.append(f"阶段3存在 QA 文件但 state.status={status}，请以当前状态为准，必要时重新记录 QA")
        _check_visual_qa(root, visual_qa, warnings)
    elif status == "stage3_editable_qa_required":
        warnings.append("阶段3可编辑 PPT 已入账，等待主控记录坐标复刻 QA")


def _check_stage3_timestamps(root: Path, coordinate_plan: Path, editable_manifest: Path, visual_qa: Path, warnings: list[str]) -> None:
    if coordinate_plan.exists() and editable_manifest.exists() and coordinate_plan.stat().st_mtime > editable_manifest.stat().st_mtime:
        warnings.append(f"editable_coordinate_plan 晚于 editable_deck manifest：{coordinate_plan.relative_to(root)}")
    if coordinate_plan.exists() and visual_qa.exists() and coordinate_plan.stat().st_mtime > visual_qa.stat().st_mtime:
        warnings.append(f"editable_coordinate_plan 晚于 stage3_visual_qa_review：{coordinate_plan.relative_to(root)}")


def _check_stage3_canonical_geometry(root: Path, coordinate_plan: Path, issues: list[str], warnings: list[str]) -> None:
    if not coordinate_plan.exists():
        return
    try:
        plan = read_json(coordinate_plan)
    except Exception as exc:
        issues.append(f"editable_coordinate_plan.json 无法读取：{exc}")
        return
    for slide in plan.get("slides", []):
        if not isinstance(slide, dict) or not isinstance(slide.get("slide_index"), int):
            continue
        slide_index = slide["slide_index"]
        source = slide.get("source_image") if isinstance(slide.get("source_image"), dict) else {}
        background = slide.get("stage3_background_image") if isinstance(slide.get("stage3_background_image"), dict) else {}
        canvas = slide.get("coordinate_canvas") if isinstance(slide.get("coordinate_canvas"), dict) else {}
        if isinstance(source, dict):
            _check_declared_image_dimensions(root, source, f"第 {slide_index} 页 coordinate source", issues)
        if isinstance(background, dict):
            _check_declared_image_dimensions(root, background, f"第 {slide_index} 页 stage3 background", issues)
        stage2_result = _read_optional_json(root / "_state" / "阶段2" / "results" / f"slide_{slide_index:03d}.json")
        stage3_result = _read_optional_json(root / "_state" / "阶段3" / "no_text_background_results" / f"slide_{slide_index:03d}.json")
        if isinstance(stage2_result, dict) and isinstance(stage3_result, dict):
            stage2_policy = stage2_result.get("canonical_policy", "preserve_api_raster")
            stage3_policy = stage3_result.get("canonical_policy", "preserve_api_raster")
            if stage2_policy == "preserve_api_raster" and stage3_policy != "preserve_api_raster":
                issues.append(f"第 {slide_index} 页阶段2保留 API 原始尺寸但阶段3使用 canonical 后处理，存在尺寸策略混用")
            if source.get("sha256") and stage2_result.get("image_sha256") and source.get("sha256") != stage2_result.get("image_sha256"):
                issues.append(f"第 {slide_index} 页 coordinate source sha 与阶段2正式结果不一致")
            if background.get("sha256") and stage3_result.get("image_sha256") and background.get("sha256") != stage3_result.get("image_sha256"):
                issues.append(f"第 {slide_index} 页 stage3 background sha 与阶段3正式结果不一致")
        if isinstance(background, dict) and isinstance(canvas, dict):
            if canvas.get("width_px") != background.get("width_px") or canvas.get("height_px") != background.get("height_px"):
                issues.append(f"第 {slide_index} 页 coordinate_canvas 尺寸与 stage3 background 不一致")
        elif background or canvas:
            warnings.append(f"第 {slide_index} 页 coordinate plan 缺少完整 stage3_background_image/coordinate_canvas 画布记录")


def _check_declared_image_dimensions(root: Path, value: dict[str, Any], label: str, issues: list[str]) -> None:
    relpath = value.get("path")
    if not isinstance(relpath, str) or not relpath.strip():
        return
    path = root / relpath
    if not path.exists():
        issues.append(f"{label} 指向不存在图片：{relpath}")
        return
    try:
        dimensions = read_image_dimensions(path)
    except Exception as exc:
        issues.append(f"{label} 无法读取图片尺寸：{exc}")
        return
    if value.get("width_px") != dimensions["width_px"] or value.get("height_px") != dimensions["height_px"]:
        issues.append(f"{label} 声明尺寸与文件真实尺寸不一致：{relpath}")


def _read_optional_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _check_editable_manifest(root: Path, manifest_path: Path, issues: list[str]) -> None:
    try:
        manifest: dict[str, Any] = read_json(manifest_path)
    except Exception as exc:
        issues.append(f"editable_deck.json 无法读取：{exc}")
        return
    deck_rel = manifest.get("deck_path")
    if not isinstance(deck_rel, str) or not deck_rel.strip():
        issues.append("editable_deck.json 缺少 deck_path")
        return
    deck_path = root / deck_rel
    if not deck_path.exists():
        issues.append("editable_deck.json 指向的 PPTX 不存在")
    expected_sha = manifest.get("pptx_sha256")
    if not isinstance(expected_sha, str) or not expected_sha.startswith("sha256:"):
        issues.append("editable_deck.json 缺少 pptx_sha256")
    elif deck_path.exists():
        actual_sha = f"sha256:{hashlib.sha256(deck_path.read_bytes()).hexdigest()}"
        if actual_sha != expected_sha:
            issues.append("editable_deck.json 的 pptx_sha256 与文件不一致")
    if manifest.get("provider") != "officecli":
        issues.append("editable_deck.json provider 必须是 officecli")
    evidence = manifest.get("runtime_evidence")
    if isinstance(evidence, dict):
        for key in ("text_ownership_map", "editable_coordinate_plan", "officecli_manifest", "inspect", "render_review", "text_fill_execution_report"):
            value = evidence.get(key)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"editable_deck.json 缺少 runtime_evidence.{key}")
            elif not (root / value).exists():
                issues.append(f"editable_deck.json runtime_evidence.{key} 指向不存在路径：{value}")
            elif key == "text_fill_execution_report":
                _check_execution_report(root, root / value, manifest, issues)
            elif key == "officecli_manifest":
                _check_officecli_manifest(root, root / value, manifest, issues)
        if isinstance(evidence.get("plugin_manifest"), str):
            issues.append("editable_deck.json 仍包含 legacy runtime_evidence.plugin_manifest")
    else:
        issues.append("editable_deck.json 缺少 runtime_evidence")


def _check_officecli_manifest(root: Path, manifest_path: Path, editable_manifest: dict[str, Any], issues: list[str]) -> None:
    try:
        manifest = read_json(manifest_path)
    except Exception as exc:
        issues.append(f"officecli_manifest 无法读取：{manifest_path.relative_to(root)}: {exc}")
        return
    if manifest.get("provider") != "officecli":
        issues.append(f"officecli_manifest provider 不是 officecli：{manifest_path.relative_to(root)}")
    if manifest.get("mode") != "full_deck":
        issues.append(f"officecli_manifest mode 不是 full_deck：{manifest_path.relative_to(root)}")
    if manifest.get("pptx_sha256") != editable_manifest.get("pptx_sha256"):
        issues.append("officecli_manifest pptx_sha256 与 editable_deck.json 不一致")
    slides_count = manifest.get("slides_count")
    if isinstance(slides_count, bool) or not isinstance(slides_count, int) or slides_count < 1:
        issues.append("officecli_manifest 缺少有效 slides_count")
    for key in ("commands", "command_results"):
        _check_manifest_evidence_path(root, manifest.get(key), f"officecli_manifest.{key}", issues)
    readback = manifest.get("readback")
    if not isinstance(readback, dict):
        issues.append("officecli_manifest 缺少 readback evidence")
    else:
        _check_manifest_evidence_path(root, readback.get("path"), "officecli_manifest.readback.path", issues)
        if isinstance(slides_count, int) and readback.get("slides_count") != slides_count:
            issues.append("officecli_manifest readback.slides_count 与 slides_count 不一致")
    placements = manifest.get("background_placements")
    if not isinstance(placements, list) or not placements:
        issues.append("officecli_manifest 缺少 background_placements")
    else:
        if isinstance(slides_count, int) and len(placements) != slides_count:
            issues.append("officecli_manifest background_placements 数量与 slides_count 不一致")
        for placement in placements:
            if not isinstance(placement, dict):
                continue
            mode = str(placement.get("placement_mode") or placement.get("mode") or "").lower()
            if mode != "exact_full_slide" or placement.get("crop") is True:
                issues.append("officecli_manifest background_placements 必须是 exact_full_slide 且 crop=false")
                break
            if not _number_close(placement.get("x"), 0) or not _number_close(placement.get("y"), 0):
                issues.append("officecli_manifest background_placements 必须从 0,0 开始铺底")
                break
            if not _number_close(placement.get("width"), SLIDE_WIDTH_PT) or not _number_close(placement.get("height"), SLIDE_HEIGHT_PT):
                issues.append("officecli_manifest background_placements 尺寸必须是 960x540pt")
                break
            image_path = placement.get("image_path")
            if not isinstance(image_path, str) or not image_path.strip() or not (root / image_path).exists():
                issues.append("officecli_manifest background_placements 缺少可访问 image_path")
                break
    text_shapes = manifest.get("text_shapes")
    if not isinstance(text_shapes, list) or not text_shapes:
        issues.append("officecli_manifest 缺少 text_shapes")
    else:
        summary = manifest.get("source_plan_summary") if isinstance(manifest.get("source_plan_summary"), dict) else {}
        expected_count = summary.get("text_unit_count")
        if isinstance(expected_count, int) and not isinstance(expected_count, bool) and len(text_shapes) != expected_count:
            issues.append("officecli_manifest text_shapes 数量与 source_plan_summary.text_unit_count 不一致")
        seen_paths: set[str] = set()
        for item in text_shapes:
            if not isinstance(item, dict):
                issues.append("officecli_manifest text_shapes 包含非对象条目")
                continue
            text_unit_id = item.get("text_unit_id")
            shape_name = item.get("shape_name")
            if not isinstance(text_unit_id, str) or not text_unit_id.strip():
                issues.append("officecli_manifest text_shapes 缺少 text_unit_id")
                continue
            if shape_name != text_unit_id:
                issues.append(f"officecli_manifest text_shape {text_unit_id} 的 shape_name 未与 text_unit_id 对齐")
            shape_path = item.get("shape_path")
            if not isinstance(shape_path, str) or not shape_path.strip():
                issues.append(f"officecli_manifest text_shape {text_unit_id} 缺少 OfficeCLI readback shape_path")
            elif shape_path in seen_paths:
                issues.append(f"officecli_manifest text_shape {text_unit_id} 重复使用 shape_path")
            else:
                seen_paths.add(shape_path)
            if item.get("shape_id") in (None, ""):
                issues.append(f"officecli_manifest text_shape {text_unit_id} 缺少 OfficeCLI readback shape_id")
            if not isinstance(item.get("readback_relative_box"), dict):
                issues.append(f"officecli_manifest text_shape {text_unit_id} 缺少 readback_relative_box")


def _check_manifest_evidence_path(root: Path, value: Any, label: str, issues: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{label} 缺少证据路径")
        return
    path = Path(value)
    resolved = path if path.is_absolute() else root / path
    if not resolved.exists():
        issues.append(f"{label} 指向不存在路径：{value}")


def _number_close(value: Any, expected: float, tolerance: float = 0.01) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return abs(float(value) - expected) <= tolerance


def _check_stage4_consistency(root: Path, issues: list[str], warnings: list[str]) -> None:
    state_path = root / "_state" / "project_state.json"
    if not state_path.exists():
        return
    try:
        state = read_json(state_path)
    except Exception:
        return
    if state.get("current_stage") != "stage4":
        return

    manifest_path = root / "_state" / "阶段4" / "speaker_script_manifest.json"
    markdown = root / "阶段4_演讲稿输出" / "演讲逐字稿.md"
    docx = root / "阶段4_演讲稿输出" / "docx" / "演讲逐字稿.docx"
    pdf = root / "阶段4_演讲稿输出" / "pdf" / "演讲逐字稿.pdf"
    note = root / "阶段4_演讲稿输出" / "讲稿生成说明.md"

    status = state.get("status")
    _check_stage4_locked_source(root, state, issues)
    if status in {"stage4_script_generated", "completed"}:
        for path, label in [(markdown, "演讲逐字稿.md"), (docx, "演讲逐字稿.docx"), (pdf, "演讲逐字稿.pdf"), (note, "讲稿生成说明.md")]:
            if not path.exists():
                issues.append(f"阶段4缺少{label}")
        if not manifest_path.exists():
            issues.append("阶段4缺少 speaker_script_manifest.json")
            return
        try:
            manifest = validate_speaker_script_manifest(read_json(manifest_path))
        except Exception as exc:
            issues.append(f"speaker_script_manifest.json 无法通过校验：{exc}")
            return
        known = {file_info.get("path") for file_info in manifest.get("files", []) if isinstance(file_info, dict)}
        for expected in {
            "阶段4_演讲稿输出/演讲逐字稿.md",
            "阶段4_演讲稿输出/docx/演讲逐字稿.docx",
            "阶段4_演讲稿输出/pdf/演讲逐字稿.pdf",
        }:
            if expected not in known:
                issues.append(f"speaker_script_manifest.json 缺少文件记录：{expected}")
        if manifest.get("summary", {}).get("pdf_text_probe") == "no_selectable_text_detected":
            issues.append("阶段4 PDF 未检测到可选择文本")
    elif status == "ready_for_stage4_script":
        if manifest_path.exists():
            warnings.append("阶段4状态仍待生成讲稿，但已存在 speaker_script_manifest.json；请以 project_state 为准")


def _stage4_source_mode(state: dict[str, Any]) -> str | None:
    source = state.get("stage4_locked_presentation_source")
    if isinstance(source, dict) and isinstance(source.get("source_mode"), str):
        return source["source_mode"]
    if state.get("confirmed", {}).get("stage3_editable_deck"):
        return "stage3_editable_deck"
    return None


def _check_stage4_locked_source(root: Path, state: dict[str, Any], issues: list[str]) -> None:
    source = state.get("stage4_locked_presentation_source")
    if not isinstance(source, dict):
        if not state.get("confirmed", {}).get("stage3_editable_deck"):
            issues.append("阶段4缺少已确认锁定稿来源")
        return
    mode = source.get("source_mode")
    if mode not in {"stage3_editable_deck", "stage2_image_deck", "external_editable_deck"}:
        issues.append("阶段4锁定稿来源 mode 无效")
    source_path = source.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        issues.append("阶段4锁定稿来源缺少 source_path")
        return
    resolved = _resolve_stage4_source_path(root, source_path)
    if not resolved.exists():
        issues.append("阶段4锁定稿来源文件不存在")
        return
    expected_sha = source.get("source_sha256")
    if isinstance(expected_sha, str) and expected_sha.startswith("sha256:"):
        actual_sha = f"sha256:{hashlib.sha256(resolved.read_bytes()).hexdigest()}"
        if actual_sha != expected_sha:
            issues.append("阶段4锁定稿来源 sha256 不匹配")


def _resolve_stage4_source_path(root: Path, source_path: str) -> Path:
    path = Path(source_path)
    return path if path.is_absolute() else root / path


def _check_execution_report(root: Path, report_path: Path, manifest: dict[str, Any], issues: list[str]) -> None:
    try:
        report = read_json(report_path)
    except Exception as exc:
        issues.append(f"text_fill_execution_report 无法读取：{report_path.relative_to(root)}: {exc}")
        return
    if report.get("actual_source") != "pptx_ooxml":
        allowed = ", ".join(sorted(TEXT_FILL_EXECUTION_ACTUAL_SOURCES))
        issues.append(f"text_fill_execution_report actual_source 必须是 pptx_ooxml（旧允许值：{allowed}）：{report_path.relative_to(root)}")
    if report.get("pptx_sha256") != manifest.get("pptx_sha256"):
        issues.append(f"text_fill_execution_report pptx_sha256 与 editable_deck.json 不一致：{report_path.relative_to(root)}")


def _check_visual_qa(root: Path, review_path: Path, issues: list[str]) -> None:
    try:
        review = read_json(review_path)
    except Exception as exc:
        issues.append(f"stage3_visual_qa_review.json 无法读取：{exc}")
        return
    try:
        validate_coordinate_stage3_qa_review(review)
    except Exception as exc:
        issues.append(f"stage3_visual_qa_review.json 无法通过校验：{exc}")
        return
    if review.get("overall_status") != "passed":
        issues.append("stage3_visual_qa_review.json 未通过")
    if review.get("schema_version") != "2.0":
        issues.append("stage3_visual_qa_review.json 不是坐标复刻 QA v2")
    contact_sheet = review.get("contact_sheet")
    if not isinstance(contact_sheet, str) or not contact_sheet.strip() or not (root / contact_sheet).exists():
        issues.append("stage3_visual_qa_review 缺少可访问的 contact_sheet")
    checks = review.get("checks")
    if isinstance(checks, dict):
        missing_checks = sorted(COORDINATE_QA_CHECK_KEYS - set(checks))
        if missing_checks:
            issues.append(f"stage3_visual_qa_review 缺少坐标复刻 checks：{', '.join(missing_checks)}")
    else:
        issues.append("stage3_visual_qa_review 缺少 checks")
    for slide in review.get("slides", []):
        assets = slide.get("review_assets", {}) if isinstance(slide, dict) else {}
        slide_index = slide.get("slide_index", "?") if isinstance(slide, dict) else "?"
        checked_units = slide.get("checked_text_unit_ids") if isinstance(slide, dict) else None
        if not isinstance(checked_units, list):
            issues.append(f"stage3_visual_qa_review 第 {slide_index} 页缺少 checked_text_unit_ids")
        if not isinstance(assets, dict):
            continue
        for key in ("stage2_image", "stage3_background", "editable_render"):
            value = assets.get(key)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"stage3_visual_qa_review 缺少 {key}")
            elif not (root / value).exists():
                issues.append(f"stage3_visual_qa_review {key} 指向不存在路径：{value}")
