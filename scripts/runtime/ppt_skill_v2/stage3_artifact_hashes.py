from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .json_io import read_json
from .stage3_scope import stage3_scope_slide_indices
from .validation import ValidationError


TEXT_OWNERSHIP_MAP_REL = "_state/阶段3/text_ownership_map.json"
TEXT_UNIT_SPLIT_PLAN_REL = "_state/阶段3/text_unit_split_plan.json"
FONT_CALIBRATION_PROFILE_REL = "_state/阶段3/font_calibration_profile.json"
EDITABLE_COORDINATE_PLAN_REL = "_state/阶段3/editable_coordinate_plan.json"
STAGE3_BACKGROUND_RESULTS_REL = "_state/阶段3/no_text_background_results"
EDITABLE_DECK_MANIFEST_REL = "_state/阶段3/manifests/editable_deck.json"
VISUAL_QA_REVIEW_REL = "_state/阶段3/render_review/stage3_visual_qa_review.json"
REQUIRED_STAGE3_INPUT_HASH_KEYS = (
    "stage3_background_results_hash",
    "text_ownership_map_hash",
    "editable_coordinate_plan_hash",
)
OPTIONAL_STAGE3_INPUT_HASH_KEYS = (
    "text_unit_split_plan_hash",
    "font_calibration_profile_hash",
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def current_stage3_input_hashes(run_dir: str | Path) -> dict[str, str]:
    root = Path(run_dir)
    state = _read_optional_json(root / "_state" / "project_state.json")
    scoped_slide_indices = stage3_scope_slide_indices(state) if isinstance(state, dict) else None
    hashes: dict[str, str] = {}
    for key, relpath in (
        ("text_ownership_map_hash", TEXT_OWNERSHIP_MAP_REL),
        ("text_unit_split_plan_hash", TEXT_UNIT_SPLIT_PLAN_REL),
        ("font_calibration_profile_hash", FONT_CALIBRATION_PROFILE_REL),
        ("editable_coordinate_plan_hash", EDITABLE_COORDINATE_PLAN_REL),
    ):
        path = root / relpath
        if path.exists():
            hashes[key] = file_sha256(path)
    background_hash = _stage3_background_results_hash(root, scoped_slide_indices=scoped_slide_indices)
    if background_hash:
        hashes["stage3_background_results_hash"] = background_hash
    return hashes


def stage3_artifacts_stale(run_dir: str | Path) -> dict[str, str]:
    root = Path(run_dir)
    current_hashes = current_stage3_input_hashes(root)
    stale: dict[str, str] = {}
    manifest = _read_optional_json(root / EDITABLE_DECK_MANIFEST_REL)
    if manifest is not None:
        reason = _stale_reason_for_input_hashes(manifest.get("input_hashes"), current_hashes, "deck")
        if reason:
            stale["editable_deck"] = reason
    qa = _read_optional_json(root / VISUAL_QA_REVIEW_REL)
    if qa is not None:
        reason = _stale_reason_for_input_hashes(qa.get("input_hashes"), current_hashes, "qa")
        if reason:
            stale["visual_qa"] = reason
        elif manifest is None:
            stale["visual_qa"] = "editable_deck_manifest_missing_for_qa"
        elif isinstance(manifest, dict):
            manifest_sha = manifest.get("pptx_sha256")
            qa_hashes = qa.get("input_hashes")
            if isinstance(manifest_sha, str) and isinstance(qa_hashes, dict):
                qa_deck_sha = qa_hashes.get("editable_deck_pptx_sha256")
                if qa_deck_sha != manifest_sha:
                    stale["visual_qa"] = "editable_deck_changed_after_qa"
    return stale


def refresh_stage3_stale_artifacts(run_dir: str | Path, state: dict[str, Any]) -> dict[str, str]:
    stale = stage3_artifacts_stale(run_dir)
    if stale:
        state["stage3_stale_artifacts"] = stale
    else:
        state.pop("stage3_stale_artifacts", None)
    return stale


def require_no_stage3_stale_artifacts(
    run_dir: str | Path,
    *,
    state: dict[str, Any] | None = None,
    ignore: set[str] | None = None,
) -> None:
    stale = stage3_artifacts_stale(run_dir)
    if state is not None and isinstance(state.get("stage3_stale_artifacts"), dict):
        stale.update({str(key): str(value) for key, value in state["stage3_stale_artifacts"].items()})
    for key in ignore or set():
        stale.pop(key, None)
    if stale:
        details = ", ".join(f"{key}={value}" for key, value in sorted(stale.items()))
        raise ValidationError(f"stage3 artifacts are stale: {details}")


def _stage3_background_results_hash(root: Path, scoped_slide_indices: list[int] | None = None) -> str:
    directory = root / STAGE3_BACKGROUND_RESULTS_REL
    if not directory.exists():
        return ""
    entries = []
    if scoped_slide_indices is None:
        paths = sorted(directory.glob("slide_*.json"))
    else:
        paths = [directory / f"slide_{slide_index:03d}.json" for slide_index in scoped_slide_indices]
    for path in paths:
        if not path.exists():
            continue
        entries.append({"path": str(path.relative_to(root)), "sha256": file_sha256(path)})
    if not entries:
        return ""
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def _stale_reason_for_input_hashes(recorded: Any, current: dict[str, str], suffix: str) -> str:
    if not isinstance(recorded, dict):
        return f"{suffix}_missing_input_hashes"
    for key in REQUIRED_STAGE3_INPUT_HASH_KEYS:
        if key not in recorded:
            return f"{key}_missing_from_{suffix}_hashes"
        if key not in current:
            return f"{key}_missing_current_for_{suffix}"
    for key in OPTIONAL_STAGE3_INPUT_HASH_KEYS:
        if key in recorded and key not in current:
            return f"{key}_missing_current_for_{suffix}"
    for key, current_value in sorted(current.items()):
        recorded_value = recorded.get(key)
        if recorded_value is None:
            return f"{key}_missing_from_{suffix}_hashes"
        if recorded_value != current_value:
            return f"{key}_changed_after_{suffix}"
    return ""
