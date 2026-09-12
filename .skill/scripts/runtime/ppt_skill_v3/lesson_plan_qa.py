from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .deliverable_naming import existing_stage3_lesson_plan_output_rel
from .events import append_event
from .json_io import read_json, write_json
from .state import read_state, stage3_lesson_plan_required, write_state
from .validation import LESSON_PLAN_QA_PASS_STATUSES, ValidationError, validate_lesson_plan_manifest, validate_lesson_plan_qa


QA_REL = "_state/阶段3/lesson_plan_qa.json"
MANIFEST_REL = "_state/阶段3/lesson_plan_manifest.json"


def lesson_plan_qa_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / QA_REL


def record_lesson_plan_qa(run_dir: str | Path, review_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state.get("current_stage") != "stage3":
        raise ValidationError("lesson plan QA can only be recorded in stage3")
    if not stage3_lesson_plan_required(state):
        raise ValidationError("lesson plan QA requires K12 stage3_outputs.lesson_plan.required=true")
    review = validate_lesson_plan_qa(read_json(review_file))
    if review["project_name"] != state["project_name"]:
        raise ValidationError("lesson_plan_qa.project_name does not match project state")
    if review["run_dir"] != state["run_dir"]:
        raise ValidationError("lesson_plan_qa.run_dir does not match project state")
    if review["status"] in LESSON_PLAN_QA_PASS_STATUSES:
        _require_passable_lesson_plan_outputs(root, state)

    target = lesson_plan_qa_path(root)
    write_json(target, review)
    stage3_outputs = state.setdefault("stage3_outputs", {})
    lesson_output = stage3_outputs.setdefault("lesson_plan", {})
    lesson_output["required"] = True
    if review["status"] == "pass":
        lesson_output["status"] = "qa_passed"
    elif review["status"] == "pass_with_warnings":
        lesson_output["status"] = "qa_passed_with_warnings"
    elif review["status"] == "fail":
        lesson_output["status"] = "qa_failed"
    elif review["status"] == "needs_controller_review":
        lesson_output["status"] = "needs_controller_review"
    else:
        lesson_output["status"] = "needs_teacher_confirmation"
    state.setdefault("runtime_artifacts", {})["stage3_lesson_plan_qa"] = QA_REL
    state.setdefault("quality", {})["stage3"] = "pending_controller_review"
    state["required_actor"] = "main_controller"
    state["next_required_action"] = "主控大模型检查阶段3逐字稿与教案全部产物；通过后记录阶段3输出完成决策"
    write_state(root, state)
    append_event(root, "lesson_plan_qa_recorded", "runtime", status=review["status"])
    return target


def _require_passable_lesson_plan_outputs(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    manifest_path = root / MANIFEST_REL
    if not manifest_path.exists():
        raise ValidationError("lesson plan manifest is required before lesson plan QA pass")
    manifest = validate_lesson_plan_manifest(read_json(manifest_path))
    if manifest["status"] != "generated":
        raise ValidationError("lesson plan manifest status must be generated before lesson plan QA pass")

    for artifact_key, label in [
        ("stage3_lesson_plan", "Markdown"),
        ("stage3_lesson_plan_docx", "DOCX"),
        ("stage3_lesson_plan_pdf", "PDF"),
    ]:
        relpath = existing_stage3_lesson_plan_output_rel(root, artifact_key, state=state, manifest=manifest)
        if not relpath:
            raise ValidationError(f"lesson plan {label} is required before lesson plan QA pass")
        path = root / relpath
        if not path.exists():
            raise ValidationError(f"lesson plan {label} path does not exist before lesson plan QA pass: {relpath}")

    known = {file_info.get("path") for file_info in manifest.get("files", []) if isinstance(file_info, dict)}
    for expected in [
        existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan", state=state, manifest=manifest),
        existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_docx", state=state, manifest=manifest),
        existing_stage3_lesson_plan_output_rel(root, "stage3_lesson_plan_pdf", state=state, manifest=manifest),
    ]:
        if expected and expected not in known:
            raise ValidationError(f"lesson plan manifest must record generated file before QA pass: {expected}")
    _require_manifest_hashes(root, manifest)
    if manifest.get("summary", {}).get("pdf_text_probe") == "no_selectable_text_detected":
        raise ValidationError("lesson plan PDF selectable text is required before lesson plan QA pass")
    return manifest


def _require_manifest_hashes(root: Path, manifest: dict[str, Any]) -> None:
    for file_info in manifest.get("files", []):
        if not isinstance(file_info, dict):
            continue
        relpath = file_info.get("path")
        expected_sha = file_info.get("sha256")
        if not isinstance(relpath, str) or not relpath.strip() or not isinstance(expected_sha, str):
            continue
        path = root / relpath
        if not path.exists():
            raise ValidationError(f"lesson plan manifest records missing file before QA pass: {relpath}")
        actual_sha = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if expected_sha.startswith("sha256:") and actual_sha != expected_sha:
            raise ValidationError(f"lesson plan manifest sha256 mismatch before QA pass: {relpath}")
