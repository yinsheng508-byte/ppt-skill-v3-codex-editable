from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import append_event
from .json_io import read_json
from .planning_assets import save_stage2_aesthetic_review, stage2_aesthetic_review_path
from .stage_docs import sync_stage_docs
from .state import read_state, write_state
from .validation import ValidationError, validate_stage2_aesthetic_review


def load_stage2_aesthetic_review(run_dir: str | Path) -> dict[str, Any]:
    return validate_stage2_aesthetic_review(read_json(stage2_aesthetic_review_path(run_dir)))


def record_stage2_aesthetic_review(run_dir: str | Path, review_file: str | Path) -> Path:
    root = Path(run_dir)
    state = read_state(root)
    if state["current_stage"] != "stage2":
        raise ValidationError("stage2 aesthetic review can only be recorded in stage2")
    source = Path(review_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"stage2 aesthetic review not found: {source}")
    review = validate_stage2_aesthetic_review(read_json(source))
    save_stage2_aesthetic_review(root, review)

    scope = review["review_scope"]
    status = review["overall_status"]
    if status == "needs_rework":
        state["required_actor"] = "main_controller"
        if scope == "trial_first5":
            state["status"] = "trial_first5_revision_requested"
            state["quality"]["stage2_trial_first5"] = "needs_revision"
            state["next_required_action"] = "主控大模型返工阶段2设计规划、layout_intent 或提示词；除非用户明确改内容，不修改阶段1任务"
        elif scope == "cover_options":
            state["status"] = "cover_style_revision_requested"
            state["quality"]["stage2_cover_options"] = "needs_revision"
            state["next_required_action"] = "主控大模型组织阶段2A封面风格候选返工"
        else:
            state["status"] = "revision_requested"
            state["quality"]["stage2"] = "needs_revision"
            state["next_required_action"] = "主控大模型组织阶段2正式图片页返工"
    else:
        if scope == "trial_first5":
            state["quality"]["stage2_trial_first5"] = "qa_passed"
            if state["status"] != "waiting_user_trial_first5_confirmation":
                state["status"] = "stage2_trial_first5_qa_passed"
                state["required_actor"] = "main_controller"
                state["next_required_action"] = "阶段2B试样 QA 已通过，可交给用户确认"
        elif scope == "cover_options":
            state["quality"]["stage2_cover_options"] = "qa_passed"
        else:
            state["quality"]["stage2"] = "qa_passed"
            state["next_required_action"] = "阶段2图片版已通过轻量审美 QA，可由主控提交用户确认"

    state["runtime_artifacts"]["stage2_visual_qa_review"] = "_state/阶段2/visual_qa/stage2_aesthetic_review.json"
    write_state(root, state)
    sync_stage_docs(root)
    append_event(root, "stage2_aesthetic_review_recorded", "runtime", review_scope=scope, overall_status=status)
    return stage2_aesthetic_review_path(root)
