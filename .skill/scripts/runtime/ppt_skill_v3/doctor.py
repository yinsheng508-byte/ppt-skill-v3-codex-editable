from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .deliverable_naming import (
    existing_stage2_image_pdf_rel,
    existing_stage3_lesson_plan_output_rel,
    existing_stage3_output_rel,
)
from .json_io import read_json
from .paths import decisions_dir, existing_decision_path, legacy_decisions_dir
from .image_geometry import read_image_dimensions, review_image_aspect_ratio
from .image_style import result_is_current
from .stage1_plan import load_stage1_slides
from .stage2_trial import stage2_trial_first5_results_complete
from .state import stage3_lesson_plan_required
from .validation import (
    validate_image_result,
    validate_lesson_plan_manifest,
    validate_lesson_plan_qa,
    validate_project_state_relations,
    validate_speaker_script_manifest,
    validate_stage2_aesthetic_review,
    validate_stage1_plan,
    validate_stage4_organize_summary,
    validate_stage4_organize_requirements,
)


FORBIDDEN_SUFFIXES = {".json", ".jsonl", ".log"}
FORBIDDEN_NAME_PARTS = ("packet", "manifest", "worker", "prompt_raw")
USER_STAGE_DIRS = [
    "阶段0_资料整理",
    "阶段1_规划确认",
    "阶段2_图片版PPT",
    "阶段3_逐字稿与教案输出",
    "阶段4_文件整理交付",
]
LEGACY_STAGE3_FORMAL_ARTIFACTS = [
    "_state/阶段3/no_text_background_results",
    "_state/阶段3/visual_slot_map.json",
    "_state/阶段3/text_fill_plan.json",
    "_state/阶段3/text_ownership_map.json",
    "_state/阶段3/editable_coordinate_plan.json",
    "_state/阶段3/manifests/editable_deck.json",
    "_state/阶段3/render_review/stage3_visual_qa_review.json",
    "阶段3_可编辑PPT",
]
STAGE2_FORMAL_IMAGE_COMPLETE_STATUSES = {"stage2_results_complete", "waiting_user_confirmation"}
STAGE2_RESULT_RECORDING_STATUSES = {
    "stage2_image_result_recorded",
    "waiting_for_stage2_remaining_image_results",
    "ready_for_stage2_remaining_images",
}
STAGE2_CURRENT_IMAGE_CHECK_STATUSES = (
    STAGE2_FORMAL_IMAGE_COMPLETE_STATUSES
    | STAGE2_RESULT_RECORDING_STATUSES
    | {"revision_requested", "trial_first5_revision_requested"}
)


def check_project(run_dir: str | Path) -> dict[str, object]:
    root = Path(run_dir)
    issues: list[str] = []
    warnings: list[str] = []
    required = ["项目总览.md", "_state/project_state.json", "_state/events.jsonl"]
    for relative in required:
        if not (root / relative).exists():
            issues.append(f"缺少必要路径：{relative}")
    if not decisions_dir(root).exists() and not legacy_decisions_dir(root).exists():
        issues.append("缺少必要路径：_state/decisions")
    if legacy_decisions_dir(root).exists():
        warnings.append("检测到旧版根目录 _decisions；请迁移到 _state/decisions 后删除根目录 _decisions")
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
    _check_project_state_relations(root, issues)
    _check_stage1_stage2_consistency(root, issues, warnings)
    _check_stage3_consistency(root, issues, warnings)
    _check_stage4_consistency(root, issues, warnings)
    return {"ok": not issues, "issues": issues, "warnings": warnings}


def _check_project_state_relations(root: Path, issues: list[str]) -> None:
    state_path = root / "_state" / "project_state.json"
    if not state_path.exists():
        return
    try:
        validate_project_state_relations(read_json(state_path))
    except Exception as exc:
        issues.append(f"project_state 状态关系不一致：{exc}")


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
        _check_ppt_consistency_entry(root, current_stage, confirmed, issues, warnings)
        _check_image_style_entry(root, current_stage, confirmed, issues, warnings)
        if not (root / "_state" / "阶段1" / "design_contract.json").exists():
            warnings.append("阶段1缺少 design_contract.json；新流程应先补齐设计合同再进入阶段2")
    elif current_stage == "stage0":
        _check_ppt_consistency_entry(root, current_stage, confirmed, issues, warnings)
        _check_image_style_entry(root, current_stage, confirmed, issues, warnings)
    if current_stage in {"stage2", "stage3", "stage4"}:
        if not (root / "_state" / "阶段1" / "layout_safety_contract.json").exists():
            issues.append("新流程进入阶段2后必须有 _state/阶段1/layout_safety_contract.json")

    if status == "waiting_user_trial_first5_confirmation" and not stage2_trial_first5_results_complete(root):
        issues.append("阶段2状态等待试样确认，但当前试样集合图片缺失、过期或记录不一致")
    if current_stage == "stage2" and status == "waiting_user_confirmation" and not existing_stage2_image_pdf_rel(root, state):
        issues.append("阶段2状态等待图片版 PDF 确认，但缺少主题化命名的阶段2图片版 PDF")
    if current_stage in {"stage2", "stage3", "stage4"}:
        prompt_doc = root / "阶段2_图片版PPT" / "图片生成提示词.md"
        if not prompt_doc.exists():
            warnings.append("阶段2尚未生成用户可读的 图片生成提示词.md")
        else:
            _check_prompt_document_links(root, prompt_doc, issues, warnings)
    if _should_check_stage2_current_image_results(state):
        _check_stage2_current_image_results(
            root,
            issues,
            warnings,
            require_complete=_stage2_formal_images_required(state),
        )
    if current_stage in {"stage2", "stage3", "stage4"}:
        _check_stage2_image_geometry(root, warnings)

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


def _check_image_style_entry(root: Path, current_stage: Any, confirmed: dict[str, Any], issues: list[str], warnings: list[str]) -> None:
    new = root / "阶段1_规划确认" / "图片风格.md"
    legacy = root / "阶段1_规划确认" / "风格与提示词方案.md"
    if current_stage == "stage0":
        if new.exists() or legacy.exists():
            issues.append("阶段0不应生成图片风格文档；只登记参考图和用户风格描述")
        return
    if new.exists() and legacy.exists():
        issues.append("阶段1同时存在 图片风格.md 和旧 风格与提示词方案.md；请显式合并为唯一风格入口")
    elif not new.exists() and legacy.exists():
        warnings.append("当前项目仅存在旧名 风格与提示词方案.md；可只读恢复，后续修改前请显式迁移")
    elif not new.exists() and current_stage in {"stage1", "stage2"}:
        issues.append("阶段1缺少唯一图片风格文档：阶段1_规划确认/图片风格.md")
    elif not new.exists() and current_stage in {"stage3", "stage4"}:
        warnings.append("阶段1缺少新图片风格文档；按旧项目只读恢复处理，后续返工前请补齐或显式迁移")


def _check_ppt_consistency_entry(root: Path, current_stage: Any, confirmed: dict[str, Any], issues: list[str], warnings: list[str]) -> None:
    path = root / "阶段1_规划确认" / "PPT一致性.md"
    if current_stage == "stage0":
        if path.exists():
            issues.append("阶段0不应生成PPT一致性文档；阶段1再形成标题、模块页和公共元素规则")
        return
    if path.exists():
        return
    if confirmed.get("stage1_plan"):
        warnings.append("阶段1缺少PPT一致性.md；按旧项目只读恢复处理，后续返工或重新生图前请补齐")
    elif current_stage in {"stage1", "stage2"}:
        issues.append("阶段1缺少PPT一致性文档：阶段1_规划确认/PPT一致性.md")
    elif current_stage in {"stage3", "stage4"}:
        warnings.append("阶段1缺少PPT一致性.md；按旧项目只读恢复处理，后续返工或重新生图前请补齐")


def _check_prompt_document_links(root: Path, prompt_doc: Path, issues: list[str], warnings: list[str]) -> None:
    import re
    text = prompt_doc.read_text(encoding="utf-8")
    links = re.findall(r'!\[[^\]]*\]\(([^)]+)\)|!\[[^\]]*\]\(<([^>]+)>\)|\[[^\]]+\]\(([^)]+)\)|\[[^\]]+\]\(<([^>]+)>\)', text)
    for groups in links:
        raw = next((item for item in groups if item), "")
        target = raw.strip()
        if not target or "://" in target or target.startswith("#"):
            continue
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        target = target.split("#", 1)[0]
        resolved = (prompt_doc.parent / target).resolve(strict=False)
        try:
            rel = resolved.relative_to(root.resolve())
        except ValueError:
            issues.append(f"图片生成提示词.md 链接指向项目外文件：{target}")
            continue
        if str(rel).startswith("_state/"):
            issues.append(f"图片生成提示词.md 不应直接依赖内部 _state 链接：{target}")
        if not resolved.exists():
            issues.append(f"图片生成提示词.md 存在坏链接：{target}")


def _should_check_stage2_current_image_results(state: dict[str, Any]) -> bool:
    current_stage = state.get("current_stage")
    status = state.get("status")
    if current_stage != "stage2":
        return False
    return status in STAGE2_CURRENT_IMAGE_CHECK_STATUSES


def _stage2_formal_images_required(state: dict[str, Any]) -> bool:
    current_stage = state.get("current_stage")
    status = state.get("status")
    return current_stage == "stage2" and status in STAGE2_FORMAL_IMAGE_COMPLETE_STATUSES


def _check_stage2_current_image_results(
    root: Path,
    issues: list[str],
    warnings: list[str],
    *,
    require_complete: bool,
) -> None:
    state_path = root / "_state" / "project_state.json"
    state = read_json(state_path) if state_path.exists() else {}
    planned_rework: set[int] = set()
    if (state.get('current_stage') == 'stage2' and state.get('required_actor') == 'main_controller'
            and state.get('status') in {'revision_requested', 'trial_first5_revision_requested'}
            and not state.get('confirmed', {}).get('stage2_image_deck')):
        decision_path = existing_decision_path(root, str(state.get('last_decision_id', '')))
        if decision_path.is_file():
            decision = read_json(decision_path)
            if decision.get('decision_type') in {'request_stage2_revision', 'request_stage2_trial_first5_revision'}:
                planned_rework = set(decision.get('execution', {}).get('slide_indices', []))
    prompt_doc = root / "阶段2_图片版PPT" / "图片生成提示词.md"
    prompt_text = prompt_doc.read_text(encoding="utf-8") if prompt_doc.exists() else ""
    formal_images: set[str] = set()
    results_dir = root / "_state" / "阶段2" / "results"
    result_paths = sorted(results_dir.glob("slide_*.json")) if results_dir.exists() else []
    expected_slide_indices: set[int] = set()
    try:
        stage1_plan = validate_stage1_plan(load_stage1_slides(root))
        expected_slide_indices = {slide["slide_index"] for slide in stage1_plan["slides"]}
    except Exception as exc:
        if require_complete:
            issues.append(f"阶段2无法读取阶段1页清单，不能确认正式图片完整性：{exc}")
        elif result_paths or state.get("status") in STAGE2_RESULT_RECORDING_STATUSES:
            warnings.append(f"阶段2无法读取阶段1页清单，暂不能判断正式图片是否齐全：{exc}")
        else:
            warnings.append("阶段2暂未读取到阶段1页清单；正式出图完整性将在结果记录后检查")
    seen_slide_indices: set[int] = set()
    for result_path in result_paths:
        try:
            result = validate_image_result(read_json(result_path), production=False)
        except Exception as exc:
            issues.append(f"阶段2正式图片结果无法校验：{result_path.relative_to(root)}：{exc}")
            continue
        if isinstance(result.get("slide_index"), int):
            seen_slide_indices.add(result["slide_index"])
        image_path = root / result.get("image_path", "")
        if not image_path.exists():
            issues.append(f"阶段2正式图片缺失：{result.get('image_path')}")
            continue
        actual_sha = f"sha256:{hashlib.sha256(image_path.read_bytes()).hexdigest()}"
        if actual_sha != result.get("image_sha256"):
            issues.append(f"阶段2正式图片 sha256 不匹配：{result.get('image_path')}")
            continue
        try:
            if not result_is_current(root, result):
                if result.get('slide_index') in planned_rework:
                    warnings.append(f"阶段2第{result['slide_index']}页已按主控决策排入返工，旧图片依据过期，生成后须重新验收。")
                else:
                    issues.append(f"阶段2正式图片已不是当前风格/页面依据：{result_path.relative_to(root)}")
        except Exception as exc:
            issues.append(f"阶段2正式图片当前性检查失败：{result_path.relative_to(root)}：{exc}")
        image_rel = result.get("image_path")
        if isinstance(image_rel, str):
            formal_images.add(image_rel)
            if prompt_text and image_rel not in prompt_text and Path(image_rel).name not in prompt_text:
                issues.append(f"图片生成提示词.md 未引用第{result.get('slide_index')}页当前正式图片：{image_rel}")
    missing_slide_indices = sorted(expected_slide_indices - seen_slide_indices)
    if require_complete:
        for slide_index in missing_slide_indices:
            issues.append(f"阶段2正式图片结果缺失：_state/阶段2/results/slide_{slide_index:03d}.json")
    elif missing_slide_indices and result_paths:
        preview = ", ".join(f"{slide_index:03d}" for slide_index in missing_slide_indices[:5])
        if len(missing_slide_indices) > 5:
            preview += " ..."
        warnings.append(f"阶段2正式图片仍在生成或整理中，尚未覆盖全部页面：{preview}")
    trial_selection = root / "_state" / "阶段2" / "trial_first5" / "selection.json"
    if trial_selection.exists():
        try:
            selection = read_json(trial_selection)
            selected = selection.get("selected_slide_indices") or []
        except Exception:
            warnings.append("阶段2试样 selection.json 无法读取")
            return
        for slide_index in selected:
            if not isinstance(slide_index, int):
                issues.append("阶段2试样 selection.json 包含非整数页码")
    current_stage = state.get("current_stage")
    status = state.get("status")
    if require_complete and (
        (current_stage == "stage2" and status == "waiting_user_confirmation")
        or current_stage in {"stage3", "stage4"}
    ):
        _check_stage2_pdf_manifest(root, formal_images, issues)


def _check_stage2_image_geometry(root: Path, warnings: list[str]) -> None:
    """Read current images, including legacy results, without updating files or confirmation."""
    result_directories = ("results", "cover_options/results", "trial_first5/results")
    checked: set[Path] = set()
    for relative in result_directories:
        for result_path in sorted((root / "_state/阶段2" / relative).glob("*.json")):
            try:
                result = read_json(result_path)
                image_rel = result.get("image_path")
                if not isinstance(image_rel, str) or not image_rel:
                    continue
                image_path = root / image_rel
                resolved = image_path.resolve()
                if resolved in checked:
                    continue
                checked.add(resolved)
                dimensions = read_image_dimensions(image_path)
                review = review_image_aspect_ratio(dimensions["width_px"], dimensions["height_px"])
                if not review["meets_target_aspect_ratio"]:
                    warnings.append(
                        f"阶段2图片比例偏离目标：{image_rel}；实际{dimensions['width_px']}×{dimensions['height_px']}"
                        f"（{dimensions['aspect_ratio']}），相对16:9偏差{review['aspect_ratio_error']:.2%}，"
                        "超过2%容差；像素足够不代表横版验收通过，请主控核对。"
                    )
                if all(field in result for field in ("width_px", "height_px")) and any(
                    result[field] != dimensions[field] for field in ("width_px", "height_px")
                ):
                    warnings.append(f"阶段2图片实际宽高与结果记录不一致：{image_rel}；比例已按实际图片核算。")
            except Exception as exc:
                warnings.append(f"阶段2图片比例无法核算：{result_path.relative_to(root)}：{exc}")


def _check_stage2_pdf_manifest(root: Path, formal_images: set[str], issues: list[str]) -> None:
    manifest_path = root / "_state" / "阶段2" / "manifests" / "image_deck.json"
    if not manifest_path.exists():
        issues.append("阶段2等待图片版 PDF 确认，但缺少 image_deck manifest")
        return
    try:
        manifest = read_json(manifest_path)
    except Exception as exc:
        issues.append(f"image_deck manifest 无法读取：{exc}")
        return
    images = manifest.get("images")
    if not isinstance(images, list) or not images:
        issues.append("image_deck manifest 缺少正式图片列表")
        return
    for image_rel in images:
        if not isinstance(image_rel, str):
            issues.append("image_deck manifest images 包含非字符串路径")
            continue
        if image_rel not in formal_images:
            issues.append(f"image_deck manifest 引用了未确认或无当前结果记录的图片：{image_rel}")


def _check_stage3_consistency(root: Path, issues: list[str], warnings: list[str]) -> None:
    state_path = root / "_state" / "project_state.json"
    if not state_path.exists():
        return
    try:
        state = read_json(state_path)
    except Exception as exc:  # pragma: no cover - corrupted JSON detail is enough for doctor
        issues.append(f"project_state.json 无法读取：{exc}")
        return

    for relpath in LEGACY_STAGE3_FORMAL_ARTIFACTS:
        path = root / relpath
        if path.is_file() or (path.is_dir() and any(path.iterdir())):
            warnings.append(f"存在 legacy 阶段3编辑重建产物，不作为当前阶段3完成依据：{relpath}")

    current_stage = state.get("current_stage")
    status = state.get("status")
    stage3_started = current_stage in {"stage3", "stage4"} or any(
        (root / relpath).exists()
        for relpath in (
            "_state/阶段3/speaker_script_manifest.json",
            "_state/阶段3/lesson_plan_manifest.json",
            "阶段3_逐字稿与教案输出",
        )
    )
    if not stage3_started:
        return

    if current_stage in {"stage3", "stage4"}:
        _check_stage3_locked_source(root, state, issues)

    speaker_manifest_path = root / "_state" / "阶段3" / "speaker_script_manifest.json"
    speaker_generated = (
        status in {"stage3_script_generated", "ready_for_stage4_organize", "completed"}
        or current_stage == "stage4"
        or speaker_manifest_path.exists()
        or any(
            existing_stage3_output_rel(root, key, state=state)
            for key in ("stage3_speaker_script", "stage3_speaker_script_docx", "stage3_speaker_script_pdf")
        )
    )
    if speaker_generated:
        _check_stage3_speaker_script_consistency(root, state, issues, warnings)
    elif status == "ready_for_stage3_script":
        return

    lesson_manifest_path = root / "_state" / "阶段3" / "lesson_plan_manifest.json"
    lesson_generated = (
        status == "stage3_lesson_plan_generated"
        or lesson_manifest_path.exists()
        or any(
            existing_stage3_lesson_plan_output_rel(root, key, state=state)
            for key in ("stage3_lesson_plan", "stage3_lesson_plan_docx", "stage3_lesson_plan_pdf")
        )
    )
    if stage3_lesson_plan_required(state):
        if lesson_generated or current_stage == "stage4" or status == "completed":
            _check_stage3_lesson_plan_consistency(root, state, issues, warnings)
        elif status == "stage3_script_generated":
            warnings.append("K12阶段3逐字稿已生成，教案设计尚未生成或未入账")
    elif lesson_generated:
        warnings.append("当前项目未标记 K12 教案必选，但已存在阶段3教案产物；请确认是否需要保留")


def _check_stage3_speaker_script_consistency(
    root: Path,
    state: dict[str, Any],
    issues: list[str],
    warnings: list[str],
) -> None:
    manifest_path = root / "_state" / "阶段3" / "speaker_script_manifest.json"
    if not manifest_path.exists():
        issues.append("阶段3缺少 speaker_script_manifest.json")
        return
    try:
        manifest = validate_speaker_script_manifest(read_json(manifest_path))
    except Exception as exc:
        issues.append(f"speaker_script_manifest.json 无法通过校验：{exc}")
        return
    markdown_rel = existing_stage3_output_rel(root, "stage3_speaker_script", state=state, manifest=manifest)
    docx_rel = existing_stage3_output_rel(root, "stage3_speaker_script_docx", state=state, manifest=manifest)
    pdf_rel = existing_stage3_output_rel(root, "stage3_speaker_script_pdf", state=state, manifest=manifest)
    for relpath, label in [(markdown_rel, "逐字稿 Markdown"), (docx_rel, "逐字稿 Word"), (pdf_rel, "逐字稿 PDF")]:
        if not relpath or not (root / relpath).exists():
            issues.append(f"阶段3缺少{label}")
    known = {file_info.get("path") for file_info in manifest.get("files", []) if isinstance(file_info, dict)}
    for expected in {markdown_rel, docx_rel, pdf_rel}:
        if expected and expected not in known:
            issues.append(f"speaker_script_manifest.json 缺少文件记录：{expected}")
    _check_manifest_file_hashes(root, manifest, "speaker_script_manifest.json", issues)
    if manifest.get("summary", {}).get("pdf_text_probe") == "no_selectable_text_detected":
        issues.append("阶段3逐字稿 PDF 未检测到可选择文本")


def _check_stage3_lesson_plan_consistency(
    root: Path,
    state: dict[str, Any],
    issues: list[str],
    warnings: list[str],
) -> None:
    manifest_path = root / "_state" / "阶段3" / "lesson_plan_manifest.json"
    qa_path = root / "_state" / "阶段3" / "lesson_plan_qa.json"
    if not manifest_path.exists():
        issues.append("K12阶段3缺少 lesson_plan_manifest.json")
        return
    try:
        manifest = validate_lesson_plan_manifest(read_json(manifest_path))
    except Exception as exc:
        issues.append(f"lesson_plan_manifest.json 无法通过校验：{exc}")
        return
    markdown_rel = existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan", state=state, manifest=manifest)
    docx_rel = existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_docx", state=state, manifest=manifest)
    pdf_rel = existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_pdf", state=state, manifest=manifest)
    for relpath, label in [(markdown_rel, "教案 Markdown"), (docx_rel, "教案 Word"), (pdf_rel, "教案 PDF")]:
        if not relpath or not (root / relpath).exists():
            issues.append(f"K12阶段3缺少{label}")
    known = {file_info.get("path") for file_info in manifest.get("files", []) if isinstance(file_info, dict)}
    for expected in {markdown_rel, docx_rel, pdf_rel}:
        if expected and expected not in known:
            issues.append(f"lesson_plan_manifest.json 缺少文件记录：{expected}")
    _check_manifest_file_hashes(root, manifest, "lesson_plan_manifest.json", issues)
    if manifest.get("summary", {}).get("pdf_text_probe") == "no_selectable_text_detected":
        issues.append("K12阶段3教案 PDF 未检测到可选择文本")
    if qa_path.exists():
        try:
            qa = validate_lesson_plan_qa(read_json(qa_path))
        except Exception as exc:
            issues.append(f"lesson_plan_qa.json 无法通过校验：{exc}")
            return
        if qa.get("status") == "fail" or qa.get("blockers"):
            issues.append("lesson_plan_qa.json 记录了阻断项")
        if qa.get("status") == "pass_with_warnings" or qa.get("warnings"):
            warnings.append("lesson_plan_qa.json 记录了 warning，完成前请主控确认不影响交付")
        if qa.get("status") == "needs_controller_review" and state.get("current_stage") == "stage4":
            warnings.append("lesson_plan_qa.json 仍是运行时自审草稿，完成阶段3决策前请主控完成语义复核")
        if qa.get("teacher_confirmation_items"):
            warnings.append("lesson_plan_qa.json 仍包含教师课前确认提示，请确认这些项不影响交付")


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

    status = state.get("status")
    confirmed = state.get("confirmed") if isinstance(state.get("confirmed"), dict) else {}
    needs_organized = status == "completed" or confirmed.get("stage4_deliverables")
    organized_rel = _stage4_organized_dir_from_state(state)
    summary_rel = _stage4_summary_rel_from_state(state)
    raw_summary = _read_first_summary(root, summary_rel)
    summary: dict[str, Any] | None = None
    if isinstance(raw_summary, dict):
        try:
            summary = validate_stage4_organize_summary(raw_summary)
            validate_stage4_organize_requirements(summary, state)
        except Exception as exc:
            issues.append(f"阶段4整理摘要无法通过校验：{exc}")
        if summary:
            summary_organized_rel = _string_or_none(summary.get("organized_dir"))
            if organized_rel and summary_organized_rel:
                if _resolve_path(root, organized_rel).resolve(strict=False) != _resolve_path(root, summary_organized_rel).resolve(strict=False):
                    issues.append("阶段4整理目录记录与整理摘要 organized_dir 不一致")
            organized_rel = organized_rel or summary_organized_rel
    elif needs_organized:
        issues.append(f"阶段4已完成但缺少有效整理摘要：{summary_rel or '_state/阶段4/organize_summary.json'}")

    if needs_organized:
        if not organized_rel:
            issues.append("阶段4已完成但缺少整理交付目录记录")
        elif not _resolve_path(root, organized_rel).is_dir():
            issues.append(f"阶段4整理交付目录不存在：{organized_rel}")
    elif status in {"ready_for_stage4_organize", "stage4_organize_revision_requested"}:
        if organized_rel or raw_summary:
            warnings.append("阶段4状态仍待整理或返工，但已经存在整理产物记录；请以 project_state 为准")


def _check_stage3_locked_source(root: Path, state: dict[str, Any], issues: list[str]) -> None:
    source = state.get("stage3_locked_presentation_source")
    if not isinstance(source, dict):
        issues.append("阶段3缺少已确认锁定稿来源")
        return
    mode = source.get("source_mode")
    if mode not in {"stage2_image_deck", "external_locked_deck"}:
        issues.append("阶段3锁定稿来源 mode 无效")
    source_path = source.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        issues.append("阶段3锁定稿来源缺少 source_path")
        return
    resolved = _resolve_path(root, source_path)
    if not resolved.exists():
        issues.append("阶段3锁定稿来源文件不存在")
        return
    expected_sha = source.get("source_sha256")
    if isinstance(expected_sha, str) and expected_sha.startswith("sha256:"):
        actual_sha = f"sha256:{hashlib.sha256(resolved.read_bytes()).hexdigest()}"
        if actual_sha != expected_sha:
            issues.append("阶段3锁定稿来源 sha256 不匹配")


def _check_manifest_file_hashes(root: Path, manifest: dict[str, Any], label: str, issues: list[str]) -> None:
    for file_info in manifest.get("files", []):
        if not isinstance(file_info, dict):
            continue
        relpath = file_info.get("path")
        expected_sha = file_info.get("sha256")
        if not isinstance(relpath, str) or not relpath.strip() or not isinstance(expected_sha, str):
            continue
        path = root / relpath
        if not path.exists():
            issues.append(f"{label} 记录的文件不存在：{relpath}")
            continue
        actual_sha = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if expected_sha.startswith("sha256:") and actual_sha != expected_sha:
            issues.append(f"{label} 文件 sha256 不匹配：{relpath}")


def _stage4_organized_dir_from_state(state: dict[str, Any]) -> str | None:
    stage4 = state.get("stage4_deliverables") if isinstance(state.get("stage4_deliverables"), dict) else {}
    user_artifacts = state.get("user_artifacts") if isinstance(state.get("user_artifacts"), dict) else {}
    return _string_or_none(user_artifacts.get("stage4_organized_dir")) or _string_or_none(stage4.get("organized_dir"))


def _stage4_summary_rel_from_state(state: dict[str, Any]) -> str | None:
    stage4 = state.get("stage4_deliverables") if isinstance(state.get("stage4_deliverables"), dict) else {}
    user_artifacts = state.get("user_artifacts") if isinstance(state.get("user_artifacts"), dict) else {}
    runtime_artifacts = state.get("runtime_artifacts") if isinstance(state.get("runtime_artifacts"), dict) else {}
    return (
        _string_or_none(user_artifacts.get("stage4_organize_summary"))
        or _string_or_none(stage4.get("summary"))
        or _string_or_none(runtime_artifacts.get("stage4_organize_summary"))
        or "_state/阶段4/organize_summary.json"
    )


def _read_first_summary(root: Path, summary_rel: str | None) -> dict[str, Any] | None:
    candidates = [summary_rel, "_state/阶段4/organize_summary.json", "_state/阶段4/deliverable_manifest.json"]
    seen: set[str] = set()
    for relpath in candidates:
        if not relpath or relpath in seen:
            continue
        seen.add(relpath)
        path = _resolve_path(root, relpath)
        if not path.exists():
            continue
        try:
            value = read_json(path)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return None


def _resolve_path(root: Path, relpath: str) -> Path:
    path = Path(relpath)
    return path if path.is_absolute() else root / path


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
