from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .stage3_restore_targets import RESTORE_TARGET_ACTIONS, restore_targets_hash


FORBIDDEN_PRODUCTION_SOURCES = {
    "local",
    "fixture",
    "html_canvas",
    "svg",
    "copied_source_render",
    "source_replay",
}

DEFAULT_IMAGE_GENERATION_ROUTE = "codex_image_gen"
CODEX_IMAGE_GEN_TOOL = "codex_image_gen"
OPENAI_IMAGE_API_TOOL = "openai_image_api"
SUPPORTED_IMAGE_GENERATION_ROUTES = {CODEX_IMAGE_GEN_TOOL, OPENAI_IMAGE_API_TOOL}
IMAGE_GENERATION_TOOL_BY_ROUTE = {
    CODEX_IMAGE_GEN_TOOL: CODEX_IMAGE_GEN_TOOL,
    OPENAI_IMAGE_API_TOOL: OPENAI_IMAGE_API_TOOL,
}
STAGE2_IMAGE_API_ENDPOINTS = {"/v1/images/generations", "/v1/draw/completions"}
STAGE3_IMAGE_API_ENDPOINTS = {"/v1/images/edits", "/v1/draw/completions"}
STAGE3_BACKGROUND_ROUTE = "stage2_preserve_text_removed_background"
STAGE3_BACKGROUND_PURPOSE = "stage2_text_removed_background"
LEGACY_STAGE3_BACKGROUND_PURPOSE = "stage3_background"
STAGE2_TRIAL_FIRST5_PURPOSE = "trial_first5"

CONTENT_MUTATION_LEVELS = {"preserve", "soft_polish", "restructure", "compress"}
DESIGN_CONTRACT_ROUTE_FAMILIES = {
    "teaching",
    "nursing_care",
    "academic_defense",
    "competition_pitch",
    "professional_report",
    "speech_launch",
    "source_redesign",
    "visual_remake",
}
DESIGN_CONTRACT_COMMUNICATION_PATHS = {
    "learning_path",
    "care_action_path",
    "argument_path",
    "pitch_thesis_path",
    "report_decision_path",
    "original_slide_upgrade_path",
}
DESIGN_CONTRACT_SOURCE_MODES = {"new_deck", "source_rewrite", "visual_remake"}
COVER_OPTION_IDS = {"A", "B", "C", "D"}
STAGE2_QA_SCOPES = {"cover_options", "trial_first5", "full_image_deck"}
STAGE2_QA_STATUSES = {"pass", "needs_rework"}
STAGE2_QA_CHECK_KEYS = {
    "visual_system_consistency",
    "text_readability",
    "content_text_accuracy",
    "page_role_fit",
    "image_relevance",
    "no_fake_text_or_placeholders",
    "density_and_hierarchy",
}
STAGE2_QA_REWORK_TARGETS = {"stage2_design_plan", "stage2_cover", "stage2_prompt", "selected_slides", "none"}

TEXT_FILL_EXECUTION_ACTUAL_SOURCES = {"pptx_inspect", "pptx_ooxml", "inspect"}

FORBIDDEN_FIELD_FRAGMENTS = {
    "ocr",
    "ocr_text",
    "match_score",
    "confidence",
    "detected_text",
    "detected_bbox",
    "source_image_bbox",
}

FORBIDDEN_FONT_FAMILY_PATTERNS = ("pingfang", "苹方")

DECISIONS_REQUIRING_USER_CONFIRMATION = {
    "approve_stage1_start_stage2",
    "approve_stage2_cover_style_start_image_deck",
    "approve_stage2_trial_first5_continue_remaining",
    "approve_stage2_start_stage3",
    "approve_stage2_skip_stage3_start_script_output",
    "reopen_stage3_sample_after_stage4",
    "approve_stage3_coordinate_plan_start_text_fill",
    "approve_stage3_start_script_output",
}

DECISION_ROUTES = {
    "stage1_ready_for_user_review": ("stage0", "stage1"),
    "approve_stage1_start_stage2": ("stage1", "stage2"),
    "request_stage1_revision": ("stage1", "stage1"),
    "stage2_cover_options_ready_for_user_review": ("stage2", "stage2"),
    "approve_stage2_cover_style_start_image_deck": ("stage2", "stage2"),
    "request_stage2_cover_style_revision": ("stage2", "stage2"),
    "stage2_trial_first5_ready_for_user_review": ("stage2", "stage2"),
    "approve_stage2_trial_first5_continue_remaining": ("stage2", "stage2"),
    "request_stage2_trial_first5_revision": ("stage2", "stage2"),
    "stage2_ready_for_user_review": ("stage2", "stage2"),
    "approve_stage2_start_stage3": ("stage2", "stage3"),
    "approve_stage2_skip_stage3_start_script_output": ("stage2", "stage4"),
    "request_stage2_revision": ("stage2", "stage2"),
    "reopen_stage3_sample_after_stage4": ("stage4", "stage3"),
    "approve_stage3_coordinate_plan_start_text_fill": ("stage3", "stage3"),
    "request_stage3_coordinate_plan_revision": ("stage3", "stage3"),
    "stage3_ready_for_user_review": ("stage3", "stage3"),
    "approve_stage3_start_script_output": ("stage3", "stage4"),
    "request_stage3_revision": ("stage3", "stage3"),
    "stage4_script_completed": ("stage4", "stage4"),
}


@dataclass
class ValidationError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _require_mapping(data: Any, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError(f"{label} must be an object")
    return data


def _require_fields(data: dict[str, Any], fields: Iterable[str], label: str) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise ValidationError(f"{label} missing required fields: {', '.join(missing)}")


def _reject_unexpected_fields(data: dict[str, Any], allowed_fields: Iterable[str], label: str) -> None:
    unexpected = sorted(set(data) - set(allowed_fields))
    if unexpected:
        raise ValidationError(f"{label} has unexpected fields: {', '.join(unexpected)}")


def _require_string(data: dict[str, Any], field: str, label: str) -> None:
    if not isinstance(data.get(field), str) or not data[field].strip():
        raise ValidationError(f"{label}.{field} must be a non-empty string")


def _require_sha256(data: dict[str, Any], field: str, label: str) -> None:
    _require_string(data, field, label)
    if not data[field].startswith("sha256:"):
        raise ValidationError(f"{label}.{field} must start with sha256:")


def _require_bool(data: dict[str, Any], field: str, label: str) -> None:
    if not isinstance(data.get(field), bool):
        raise ValidationError(f"{label}.{field} must be a boolean")


def _require_number(data: dict[str, Any], field: str, label: str) -> float | int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label}.{field} must be a number")
    return value


def _reject_forbidden_fields(value: Any, label: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_FIELD_FRAGMENTS or any(fragment in normalized for fragment in FORBIDDEN_FIELD_FRAGMENTS):
                raise ValidationError(f"{label}.{key}: OCR-derived field is forbidden")
            _reject_forbidden_fields(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, f"{label}[{index}]")


def _reject_forbidden_font_families(value: Any, label: str) -> None:
    if isinstance(value, str):
        normalized = value.lower()
        if any(pattern in normalized for pattern in FORBIDDEN_FONT_FAMILY_PATTERNS):
            raise ValidationError(f"{label} contains forbidden font family PingFang/苹方")
    elif isinstance(value, dict):
        for key, child in value.items():
            _reject_forbidden_font_families(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_font_families(child, f"{label}[{index}]")


def _require_list(data: dict[str, Any], field: str, label: str) -> list[Any]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ValidationError(f"{label}.{field} must be a list")
    return value


def _require_non_empty_list(data: dict[str, Any], field: str, label: str) -> list[Any]:
    value = _require_list(data, field, label)
    if not value:
        raise ValidationError(f"{label}.{field} must be a non-empty list")
    return value


def _require_string_list(data: dict[str, Any], field: str, label: str, *, non_empty: bool = False) -> list[Any]:
    values = _require_non_empty_list(data, field, label) if non_empty else _require_list(data, field, label)
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise ValidationError(f"{label}.{field} must contain non-empty strings")
    return values


def _validate_relative_box(box: Any, label: str) -> dict[str, float | int]:
    if not isinstance(box, dict):
        raise ValidationError(f"{label} must be an object")
    _require_fields(box, ["x", "y", "w", "h"], label)
    values = {field: _require_number(box, field, label) for field in ("x", "y", "w", "h")}
    if values["x"] < 0 or values["x"] > 1:
        raise ValidationError(f"{label}.x must be between 0 and 1")
    if values["y"] < 0 or values["y"] > 1:
        raise ValidationError(f"{label}.y must be between 0 and 1")
    if values["w"] <= 0 or values["w"] > 1:
        raise ValidationError(f"{label}.w must be greater than 0 and at most 1")
    if values["h"] <= 0 or values["h"] > 1:
        raise ValidationError(f"{label}.h must be greater than 0 and at most 1")
    if values["x"] + values["w"] > 1.000001:
        raise ValidationError(f"{label} must fit within slide width")
    if values["y"] + values["h"] > 1.000001:
        raise ValidationError(f"{label} must fit within slide height")
    return values


def _box_contains(parent: dict[str, float | int], child: dict[str, float | int]) -> bool:
    epsilon = 0.000001
    return (
        child["x"] >= parent["x"] - epsilon
        and child["y"] >= parent["y"] - epsilon
        and child["x"] + child["w"] <= parent["x"] + parent["w"] + epsilon
        and child["y"] + child["h"] <= parent["y"] + parent["h"] + epsilon
    )


def _validate_slide_indices(slides: list[Any], label: str) -> set[int]:
    seen: set[int] = set()
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise ValidationError(f"{label}[{index}] must be an object")
        if not isinstance(slide.get("slide_index"), int):
            raise ValidationError(f"{label}[{index}].slide_index must be an integer")
        slide_index = slide["slide_index"]
        if slide_index in seen:
            raise ValidationError(f"{label}[{index}].slide_index is duplicated: {slide_index}")
        seen.add(slide_index)
    return seen


def validate_restore_targets(value: Any, label: str = "restore_targets") -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{label} must be a non-empty list")
    seen: set[str] = set()
    targets: list[dict[str, Any]] = []
    for index, target in enumerate(value, start=1):
        item_label = f"{label}[{index}]"
        if not isinstance(target, dict):
            raise ValidationError(f"{item_label} must be an object")
        _require_fields(target, ["target_id", "action", "text", "source"], item_label)
        for field in ("target_id", "action", "text"):
            _require_string(target, field, item_label)
        if target["target_id"] in seen:
            raise ValidationError(f"{item_label}.target_id is duplicated: {target['target_id']}")
        seen.add(target["target_id"])
        if target["action"] not in RESTORE_TARGET_ACTIONS:
            raise ValidationError(f"{item_label}.action is invalid: {target['action']}")
        source = target.get("source")
        if not isinstance(source, dict):
            raise ValidationError(f"{item_label}.source must be an object")
        if not any(isinstance(source.get(field), str) and source[field].strip() for field in ("content_json_path", "slide_prompt_briefs_path")):
            raise ValidationError(f"{item_label}.source requires content_json_path or slide_prompt_briefs_path")
        _require_string(source, "source_field", f"{item_label}.source")
        if "expected_restore_as" in target:
            _require_string(target, "expected_restore_as", item_label)
        targets.append(target)
    return targets


def validate_restore_targets_hash(value: Any, targets: list[dict[str, Any]], label: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValidationError(f"{label} must start with sha256:")
    expected = restore_targets_hash(targets)
    if value != expected:
        raise ValidationError(f"{label} does not match restore_targets")


def validate_project_state(data: Any) -> dict[str, Any]:
    state = _require_mapping(data, "project_state")
    _require_fields(
        state,
        [
            "schema_version",
            "project_name",
            "run_dir",
            "current_stage",
            "status",
            "required_actor",
            "confirmed",
            "user_artifacts",
            "runtime_artifacts",
            "updated_at",
        ],
        "project_state",
    )
    if state["schema_version"] != "2.0":
        raise ValidationError("project_state.schema_version must be 2.0")
    if state["current_stage"] not in {"stage0", "stage1", "stage2", "stage3", "stage4"}:
        raise ValidationError("project_state.current_stage is invalid")
    for field in ("project_name", "run_dir", "status", "required_actor", "updated_at"):
        _require_string(state, field, "project_state")
    for field in ("confirmed", "user_artifacts", "runtime_artifacts"):
        if not isinstance(state.get(field), dict):
            raise ValidationError(f"project_state.{field} must be an object")
    return state


def validate_controller_decision(data: Any) -> dict[str, Any]:
    decision = _require_mapping(data, "controller_decision")
    _require_fields(
        decision,
        [
            "schema_version",
            "decision_id",
            "project_name",
            "run_dir",
            "decision_type",
            "from_stage",
            "to_stage",
            "actor",
            "user_confirmed",
            "controller_reviewed",
            "basis",
            "execution",
            "created_at",
        ],
        "controller_decision",
    )
    if decision["schema_version"] != "2.0":
        raise ValidationError("controller_decision.schema_version must be 2.0")
    if decision["actor"] != "main_controller":
        raise ValidationError("controller_decision.actor must be main_controller")
    for field in (
        "decision_id",
        "project_name",
        "run_dir",
        "decision_type",
        "from_stage",
        "to_stage",
        "created_at",
    ):
        _require_string(decision, field, "controller_decision")
    _require_bool(decision, "user_confirmed", "controller_decision")
    _require_bool(decision, "controller_reviewed", "controller_decision")
    if not isinstance(decision.get("basis"), dict):
        raise ValidationError("controller_decision.basis must be an object")
    execution = decision.get("execution")
    if not isinstance(execution, dict):
        raise ValidationError("controller_decision.execution must be an object")
    actions = execution.get("allowed_actions", [])
    if actions is not None and not isinstance(actions, list):
        raise ValidationError("controller_decision.execution.allowed_actions must be a list")
    if decision["decision_type"] not in DECISION_ROUTES:
        raise ValidationError(f"unsupported controller_decision.decision_type: {decision['decision_type']}")
    expected_from, expected_to = DECISION_ROUTES[decision["decision_type"]]
    if decision["from_stage"] != expected_from or decision["to_stage"] != expected_to:
        raise ValidationError(
            "controller_decision route does not match decision_type: "
            f"expected {expected_from}->{expected_to}"
        )
    if decision["decision_type"] in DECISIONS_REQUIRING_USER_CONFIRMATION:
        if not decision["user_confirmed"]:
            raise ValidationError("user_confirmed is required for this decision type")
        if not decision["controller_reviewed"]:
            raise ValidationError("controller_reviewed is required for this decision type")
    return decision


def validate_stage1_plan(data: Any) -> dict[str, Any]:
    plan = _require_mapping(data, "stage1_plan")
    _require_fields(plan, ["schema_version", "slides"], "stage1_plan")
    if plan["schema_version"] != "2.0":
        raise ValidationError("stage1_plan.schema_version must be 2.0")
    slides = plan["slides"]
    if not isinstance(slides, list) or not slides:
        raise ValidationError("stage1_plan.slides must be a non-empty list")
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise ValidationError(f"stage1_plan.slides[{index}] must be an object")
        _require_fields(
            slide,
            ["slide_index", "title", "purpose", "core_content", "visual_intent"],
            f"stage1_plan.slides[{index}]",
        )
        if not isinstance(slide["slide_index"], int):
            raise ValidationError(f"stage1_plan.slides[{index}].slide_index must be an integer")
        for field in ("title", "purpose", "core_content", "visual_intent"):
            _require_string(slide, field, f"stage1_plan.slides[{index}]")
    return plan


def validate_content_asset(data: Any) -> dict[str, Any]:
    content = _require_mapping(data, "content")
    _reject_forbidden_fields(content)
    _require_fields(content, ["schema_version", "deck_title", "audience", "route", "slides"], "content")
    if content["schema_version"] != "2.3":
        raise ValidationError("content.schema_version must be 2.3")
    for field in ("deck_title", "audience", "route"):
        _require_string(content, field, "content")
    slides = _require_non_empty_list(content, "slides", "content")
    _validate_slide_indices(slides, "content.slides")
    for index, slide in enumerate(slides, start=1):
        _require_fields(slide, ["slide_index", "page_type", "title", "purpose", "final_visible_text"], f"content.slides[{index}]")
        for field in ("page_type", "title", "purpose"):
            _require_string(slide, field, f"content.slides[{index}]")
        visible_text = _require_non_empty_list(slide, "final_visible_text", f"content.slides[{index}]")
        if not all(isinstance(item, str) and item.strip() for item in visible_text):
            raise ValidationError(f"content.slides[{index}].final_visible_text must contain non-empty strings")
        if "page_role" in slide:
            _require_string(slide, "page_role", f"content.slides[{index}]")
        if "content_mutation_level" in slide:
            _require_string(slide, "content_mutation_level", f"content.slides[{index}]")
            if slide["content_mutation_level"] not in CONTENT_MUTATION_LEVELS:
                raise ValidationError(f"content.slides[{index}].content_mutation_level is invalid")
        if "source_basis" in slide:
            _validate_source_basis(slide["source_basis"], f"content.slides[{index}].source_basis")
        if "text_contract" in slide:
            _validate_text_contract(slide["text_contract"], f"content.slides[{index}].text_contract")
    return content


def validate_slide_prompt_briefs(data: Any) -> dict[str, Any]:
    briefs = _require_mapping(data, "slide_prompt_briefs")
    _reject_forbidden_fields(briefs)
    _require_fields(briefs, ["schema_version", "slides"], "slide_prompt_briefs")
    if briefs["schema_version"] != "2.3":
        raise ValidationError("slide_prompt_briefs.schema_version must be 2.3")
    slides = _require_non_empty_list(briefs, "slides", "slide_prompt_briefs")
    _validate_slide_indices(slides, "slide_prompt_briefs.slides")
    for index, slide in enumerate(slides, start=1):
        _require_fields(
            slide,
            [
                "slide_index",
                "page_role",
                "message_goal",
                "final_visible_text",
                "visual_composition",
                "negative_constraints",
                "acceptance_criteria",
            ],
            f"slide_prompt_briefs.slides[{index}]",
        )
        for field in ("page_role", "message_goal", "visual_composition"):
            _require_string(slide, field, f"slide_prompt_briefs.slides[{index}]")
        for field in ("final_visible_text", "negative_constraints", "acceptance_criteria"):
            values = _require_non_empty_list(slide, field, f"slide_prompt_briefs.slides[{index}]")
            if not all(isinstance(item, str) and item.strip() for item in values):
                raise ValidationError(f"slide_prompt_briefs.slides[{index}].{field} must contain non-empty strings")
        for field in ("layout_family", "density_budget", "visual_anchor", "content_fidelity_policy"):
            if field in slide:
                _require_string(slide, field, f"slide_prompt_briefs.slides[{index}]")
    return briefs


def require_matching_visible_text(content: dict[str, Any], briefs: dict[str, Any]) -> None:
    content_by_index = {slide["slide_index"]: slide for slide in content.get("slides", []) if isinstance(slide, dict)}
    for brief in briefs.get("slides", []):
        if not isinstance(brief, dict):
            continue
        slide_index = brief.get("slide_index")
        content_slide = content_by_index.get(slide_index)
        if not content_slide:
            raise ValidationError(f"slide_prompt_briefs slide {slide_index} has no matching content slide")
        if brief.get("final_visible_text") != content_slide.get("final_visible_text"):
            raise ValidationError(f"slide {slide_index} final_visible_text does not match content.json")


def _validate_source_basis(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    for index, item in enumerate(value, start=1):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{item_label} must be an object")
        if not any(isinstance(item.get(field), str) and item[field].strip() for field in ("material_id", "material", "source")):
            raise ValidationError(f"{item_label} requires material_id, material, or source")
        if "locator" in item:
            _require_string(item, "locator", item_label)
        if "usage" in item:
            _require_string(item, "usage", item_label)
    return value


def _validate_text_contract(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("must_keep", "can_soft_polish", "do_not_remove", "do_not_invent"):
        if field in value:
            values = value[field]
            if not isinstance(values, list) or not all(isinstance(item, str) and item.strip() for item in values):
                raise ValidationError(f"{label}.{field} must contain non-empty strings")
    return value


def validate_design_contract(data: Any) -> dict[str, Any]:
    contract = _require_mapping(data, "design_contract")
    _reject_forbidden_fields(contract)
    _require_fields(
        contract,
        [
            "schema_version",
            "route_family",
            "communication_path",
            "source_policy",
            "audience_profile",
            "visual_system_intent",
            "layout_grammar",
            "stage2_cover_option_strategy",
            "stage2_qa_focus",
        ],
        "design_contract",
    )
    if contract["schema_version"] != "1.0":
        raise ValidationError("design_contract.schema_version must be 1.0")
    for field in ("route_family", "communication_path"):
        _require_string(contract, field, "design_contract")
    if contract["route_family"] not in DESIGN_CONTRACT_ROUTE_FAMILIES:
        raise ValidationError("design_contract.route_family is invalid")
    if contract["communication_path"] not in DESIGN_CONTRACT_COMMUNICATION_PATHS:
        raise ValidationError("design_contract.communication_path is invalid")
    source_policy = contract.get("source_policy")
    if not isinstance(source_policy, dict):
        raise ValidationError("design_contract.source_policy must be an object")
    _require_fields(source_policy, ["mode", "content_mutation_level", "rules"], "design_contract.source_policy")
    _require_string(source_policy, "mode", "design_contract.source_policy")
    _require_string(source_policy, "content_mutation_level", "design_contract.source_policy")
    if source_policy["mode"] not in DESIGN_CONTRACT_SOURCE_MODES:
        raise ValidationError("design_contract.source_policy.mode is invalid")
    if source_policy["content_mutation_level"] not in CONTENT_MUTATION_LEVELS:
        raise ValidationError("design_contract.source_policy.content_mutation_level is invalid")
    for field in ("primary_materials", "supporting_materials", "rules"):
        if field in source_policy:
            values = source_policy[field]
            if not isinstance(values, list):
                raise ValidationError(f"design_contract.source_policy.{field} must be a list")
    if "conflict_resolution" in source_policy:
        _require_string(source_policy, "conflict_resolution", "design_contract.source_policy")

    audience = contract.get("audience_profile")
    if not isinstance(audience, dict):
        raise ValidationError("design_contract.audience_profile must be an object")
    _require_string(audience, "primary_audience", "design_contract.audience_profile")

    intent = contract.get("visual_system_intent")
    if not isinstance(intent, dict):
        raise ValidationError("design_contract.visual_system_intent must be an object")
    _require_string_list(intent, "tone_keywords", "design_contract.visual_system_intent", non_empty=True)

    grammar = contract.get("layout_grammar")
    if not isinstance(grammar, dict):
        raise ValidationError("design_contract.layout_grammar must be an object")
    _require_string_list(grammar, "page_role_taxonomy", "design_contract.layout_grammar", non_empty=True)

    strategy = contract.get("stage2_cover_option_strategy")
    if not isinstance(strategy, dict):
        raise ValidationError("design_contract.stage2_cover_option_strategy must be an object")
    option_briefs = _require_non_empty_list(strategy, "option_briefs", "design_contract.stage2_cover_option_strategy")
    for index, option in enumerate(option_briefs, start=1):
        label = f"design_contract.stage2_cover_option_strategy.option_briefs[{index}]"
        if not isinstance(option, dict):
            raise ValidationError(f"{label} must be an object")
        _require_string(option, "option_id", label)
        if option["option_id"] not in COVER_OPTION_IDS:
            raise ValidationError(f"{label}.option_id must be one of A, B, C, D")
        if "style_positioning" in option:
            _require_string(option, "style_positioning", label)
    _require_string_list(contract, "stage2_qa_focus", "design_contract", non_empty=True)
    return contract


def validate_deck_style(data: Any) -> dict[str, Any]:
    style = _require_mapping(data, "deck_style")
    _reject_forbidden_fields(style)
    _require_fields(
        style,
        [
            "schema_version",
            "selected_cover_option",
            "visual_world",
            "typography",
            "logo_policy",
            "page_number_policy",
            "header_policy",
            "content_policy",
            "forbidden_visuals",
        ],
        "deck_style",
    )
    if style["schema_version"] != "2.3":
        raise ValidationError("deck_style.schema_version must be 2.3")
    for field in ("selected_cover_option", "visual_world", "header_policy", "content_policy"):
        _require_string(style, field, "deck_style")
    for field in ("typography", "logo_policy", "page_number_policy"):
        if not isinstance(style.get(field), dict):
            raise ValidationError(f"deck_style.{field} must be an object")
    _reject_forbidden_font_families(style["typography"], "deck_style.typography")
    for field in ("style_atoms", "color_contract", "typography_contract", "image_language", "motif_system"):
        if field in style and not isinstance(style.get(field), dict):
            raise ValidationError(f"deck_style.{field} must be an object")
    if isinstance(style.get("typography_contract"), dict):
        _reject_forbidden_font_families(style["typography_contract"], "deck_style.typography_contract")
    _require_list(style, "forbidden_visuals", "deck_style")
    return style


def validate_layout_intent(data: Any) -> dict[str, Any]:
    intent = _require_mapping(data, "layout_intent")
    _reject_forbidden_fields(intent)
    _require_fields(
        intent,
        [
            "schema_version",
            "basis",
            "global_layout",
            "density_policy",
            "editable_text_policy",
            "page_type_rules",
        ],
        "layout_intent",
    )
    if intent["schema_version"] != "2.3":
        raise ValidationError("layout_intent.schema_version must be 2.3")
    basis = intent.get("basis")
    if not isinstance(basis, dict):
        raise ValidationError("layout_intent.basis must be an object")
    _require_fields(basis, ["mode", "reason"], "layout_intent.basis")
    _require_string(basis, "mode", "layout_intent.basis")
    _require_string(basis, "reason", "layout_intent.basis")
    for field in ("global_layout", "density_policy", "editable_text_policy", "page_type_rules"):
        if not isinstance(intent.get(field), dict):
            raise ValidationError(f"layout_intent.{field} must be an object")
    for field in ("composition_grammar", "layout_slot_contracts", "variation_schedule"):
        if field in intent and not isinstance(intent.get(field), dict):
            raise ValidationError(f"layout_intent.{field} must be an object")
    if "slide_role_map" in intent:
        slide_role_map = intent["slide_role_map"]
        if not isinstance(slide_role_map, list):
            raise ValidationError("layout_intent.slide_role_map must be a list")
        for index, item in enumerate(slide_role_map, start=1):
            label = f"layout_intent.slide_role_map[{index}]"
            if not isinstance(item, dict):
                raise ValidationError(f"{label} must be an object")
            _require_fields(item, ["slide_index", "page_role", "layout_family"], label)
            if not isinstance(item["slide_index"], int):
                raise ValidationError(f"{label}.slide_index must be an integer")
            for field in ("page_role", "layout_family"):
                _require_string(item, field, label)
    return intent


def validate_cover_option_style_card(data: Any) -> dict[str, Any]:
    card = _require_mapping(data, "cover_option_style_card")
    _reject_forbidden_fields(card)
    _require_fields(
        card,
        [
            "schema_version",
            "option_id",
            "basis_design_contract",
            "style_positioning",
            "best_for",
            "composition",
            "visual_medium",
            "palette_strategy",
            "typography_direction",
            "layout_extension",
            "risk_notes",
            "prompt_constraints",
            "selection_explanation",
        ],
        "cover_option_style_card",
    )
    if card["schema_version"] != "1.0":
        raise ValidationError("cover_option_style_card.schema_version must be 1.0")
    _require_string(card, "option_id", "cover_option_style_card")
    if card["option_id"] not in COVER_OPTION_IDS:
        raise ValidationError("cover_option_style_card.option_id must be one of A, B, C, D")
    for field in ("basis_design_contract", "style_positioning", "composition", "visual_medium", "palette_strategy", "typography_direction", "selection_explanation"):
        _require_string(card, field, "cover_option_style_card")
    for field in ("best_for", "risk_notes", "prompt_constraints"):
        _require_string_list(card, field, "cover_option_style_card")
    extension = card.get("layout_extension")
    if not isinstance(extension, dict):
        raise ValidationError("cover_option_style_card.layout_extension must be an object")
    _require_string(extension, "cover_to_inner_pages", "cover_option_style_card.layout_extension")
    for field in ("suitable_page_roles", "risky_page_roles"):
        _require_string_list(extension, field, "cover_option_style_card.layout_extension")
    return card


def validate_stage2_aesthetic_review(data: Any) -> dict[str, Any]:
    review = _require_mapping(data, "stage2_aesthetic_review")
    _reject_forbidden_fields(review)
    _require_fields(
        review,
        ["schema_version", "overall_status", "review_scope", "checks", "slide_findings", "rework_recommendation"],
        "stage2_aesthetic_review",
    )
    if review["schema_version"] != "1.0":
        raise ValidationError("stage2_aesthetic_review.schema_version must be 1.0")
    if review["overall_status"] not in STAGE2_QA_STATUSES:
        raise ValidationError("stage2_aesthetic_review.overall_status is invalid")
    if review["review_scope"] not in STAGE2_QA_SCOPES:
        raise ValidationError("stage2_aesthetic_review.review_scope is invalid")
    checks = review.get("checks")
    if not isinstance(checks, dict):
        raise ValidationError("stage2_aesthetic_review.checks must be an object")
    missing = sorted(STAGE2_QA_CHECK_KEYS - set(checks))
    if missing:
        raise ValidationError("stage2_aesthetic_review.checks missing required keys: " + ", ".join(missing))
    for key in STAGE2_QA_CHECK_KEYS:
        if checks[key] not in STAGE2_QA_STATUSES:
            raise ValidationError(f"stage2_aesthetic_review.checks.{key} is invalid")
    if review["overall_status"] == "pass" and any(checks[key] != "pass" for key in STAGE2_QA_CHECK_KEYS):
        raise ValidationError("stage2_aesthetic_review cannot pass while checks require rework")
    findings = review.get("slide_findings")
    if not isinstance(findings, list):
        raise ValidationError("stage2_aesthetic_review.slide_findings must be a list")
    for index, finding in enumerate(findings, start=1):
        label = f"stage2_aesthetic_review.slide_findings[{index}]"
        if not isinstance(finding, dict):
            raise ValidationError(f"{label} must be an object")
        if "slide_index" in finding and not isinstance(finding["slide_index"], int):
            raise ValidationError(f"{label}.slide_index must be an integer")
        if "issue" in finding:
            _require_string(finding, "issue", label)
    recommendation = review.get("rework_recommendation")
    if not isinstance(recommendation, dict):
        raise ValidationError("stage2_aesthetic_review.rework_recommendation must be an object")
    _require_string(recommendation, "target", "stage2_aesthetic_review.rework_recommendation")
    if recommendation["target"] not in STAGE2_QA_REWORK_TARGETS:
        raise ValidationError("stage2_aesthetic_review.rework_recommendation.target is invalid")
    if review["overall_status"] == "pass" and recommendation["target"] != "none":
        raise ValidationError("stage2_aesthetic_review.rework_recommendation.target must be none when review passes")
    if recommendation["target"] == "none" and review["overall_status"] != "pass":
        raise ValidationError("stage2_aesthetic_review.rework_recommendation.target cannot be none when review needs rework")
    _require_string(recommendation, "reason", "stage2_aesthetic_review.rework_recommendation")
    return review


def require_matching_slide_indices(*assets: tuple[str, dict[str, Any]]) -> None:
    expected: set[int] | None = None
    expected_label = ""
    for label, asset in assets:
        slides = asset.get("slides")
        if not isinstance(slides, list):
            raise ValidationError(f"{label}.slides must be a list")
        indices = _validate_slide_indices(slides, f"{label}.slides")
        if expected is None:
            expected = indices
            expected_label = label
        elif indices != expected:
            raise ValidationError(f"{label}.slides indices do not match {expected_label}.slides")


def validate_image_result(data: Any, *, production: bool = True) -> dict[str, Any]:
    result = _require_mapping(data, "image_result")
    _require_fields(
        result,
        [
            "schema_version",
            "stage",
            "slide_index",
            "provider",
            "source",
            "execution_tool",
            "generation_id",
            "tool_call_id",
            "image_gen_result_id",
            "execution_group_id",
            "prompt_hash",
            "image_sha256",
            "image_path",
            "parallel_batch_path",
            "created_at",
            "formal_mode",
            "fixture",
        ],
        "image_result",
    )
    if result["schema_version"] != "2.0":
        raise ValidationError("image_result.schema_version must be 2.0")
    if result["stage"] not in {"stage2", "stage3"}:
        raise ValidationError("image_result.stage is invalid")
    image_generation_route = result.get("image_generation_route") or result.get("execution_tool")
    if image_generation_route not in SUPPORTED_IMAGE_GENERATION_ROUTES:
        raise ValidationError("image_result.image_generation_route is invalid")
    result["image_generation_route"] = image_generation_route
    purpose = result.get("purpose")
    if purpose is None:
        purpose = "full_slide" if result["stage"] == "stage2" else "stage3_background"
        result["purpose"] = purpose
    if purpose not in {"cover_option", STAGE2_TRIAL_FIRST5_PURPOSE, "full_slide", LEGACY_STAGE3_BACKGROUND_PURPOSE, STAGE3_BACKGROUND_PURPOSE}:
        raise ValidationError("image_result.purpose is invalid")
    if result["stage"] == "stage3" and purpose not in {LEGACY_STAGE3_BACKGROUND_PURPOSE, STAGE3_BACKGROUND_PURPOSE}:
        raise ValidationError("stage3 image_result requires a stage3 background purpose")
    if result["stage"] == "stage2" and purpose in {LEGACY_STAGE3_BACKGROUND_PURPOSE, STAGE3_BACKGROUND_PURPOSE}:
        raise ValidationError("stage2 image_result cannot use purpose=stage3_background")
    if not isinstance(result["slide_index"], int):
        raise ValidationError("image_result.slide_index must be an integer")
    for field in (
        "provider",
        "source",
        "execution_tool",
        "generation_id",
        "tool_call_id",
        "image_gen_result_id",
        "execution_group_id",
        "prompt_hash",
        "image_sha256",
        "image_path",
        "parallel_batch_path",
        "created_at",
    ):
        _require_string(result, field, "image_result")
    expected_tool = IMAGE_GENERATION_TOOL_BY_ROUTE[image_generation_route]
    if result["execution_tool"] != expected_tool:
        raise ValidationError(f"image_result.execution_tool must be {expected_tool}")
    if not result["image_sha256"].startswith("sha256:"):
        raise ValidationError("image_result.image_sha256 must start with sha256:")
    has_dimensions = all(field in result for field in ("width_px", "height_px", "aspect_ratio"))
    if production and not has_dimensions:
        raise ValidationError("production image_result requires width_px, height_px and aspect_ratio")
    if has_dimensions:
        _validate_image_dimensions(result, "image_result")
    if "target_size" in result:
        _validate_size_box(result["target_size"], "image_result.target_size")
    if "preferred_minimum_size" in result:
        _validate_size_box(result["preferred_minimum_size"], "image_result.preferred_minimum_size")
    if "minimum_acceptable_size" in result:
        _validate_size_box(result["minimum_acceptable_size"], "image_result.minimum_acceptable_size")
    if "size_policy" in result:
        _require_string(result, "size_policy", "image_result")
    if "postprocess_policy" in result:
        _require_string(result, "postprocess_policy", "image_result")
    if "meets_preferred_size" in result:
        _require_bool(result, "meets_preferred_size", "image_result")
    if "meets_target_size" in result:
        _require_bool(result, "meets_target_size", "image_result")
    if "size_warnings" in result:
        _validate_string_list(result["size_warnings"], "image_result.size_warnings")
    if "canonical_policy" in result and result["canonical_policy"] not in {"preserve_api_raster", "normalize_at_stage2"}:
        raise ValidationError("image_result.canonical_policy is invalid")
    if "original_api_output" in result:
        _validate_image_dimensions(result["original_api_output"], "image_result.original_api_output")
        _require_sha256(result["original_api_output"], "image_sha256", "image_result.original_api_output")
    if "postprocess" in result:
        _validate_image_postprocess(result["postprocess"], "image_result.postprocess")
    _require_bool(result, "formal_mode", "image_result")
    _require_bool(result, "fixture", "image_result")
    if production:
        if not result["formal_mode"]:
            raise ValidationError("production image_result requires formal_mode=true")
        if result["fixture"]:
            raise ValidationError("production image_result cannot be fixture")
        if result["source"] in FORBIDDEN_PRODUCTION_SOURCES:
            raise ValidationError(f"production image_result source is forbidden: {result['source']}")
        if result["provider"] in FORBIDDEN_PRODUCTION_SOURCES:
            raise ValidationError(f"production image_result provider is forbidden: {result['provider']}")
        if result["provider"] != expected_tool:
            raise ValidationError(f"production image_result.provider must be {expected_tool}")
        if result["source"] != expected_tool:
            raise ValidationError(f"production image_result.source must be {expected_tool}")
        if image_generation_route == OPENAI_IMAGE_API_TOOL:
            _require_string(result, "api_call_id", "image_result")
            _require_string(result, "image_api_result_id", "image_result")
            _require_string(result, "api_endpoint", "image_result")
            _require_string(result, "model", "image_result")
            _require_string(result, "api_evidence_path", "image_result")
            expected_endpoints = STAGE3_IMAGE_API_ENDPOINTS if result["stage"] == "stage3" else STAGE2_IMAGE_API_ENDPOINTS
            if result["api_endpoint"] not in expected_endpoints:
                raise ValidationError(f"production image_result.api_endpoint must be one of {sorted(expected_endpoints)}")
        else:
            _require_string(result, "tool_call_id", "image_result")
            _require_string(result, "image_gen_result_id", "image_result")
            _require_string(result, "image_gen_evidence_path", "image_result")
        if result["stage"] == "stage3":
            if purpose != STAGE3_BACKGROUND_PURPOSE:
                raise ValidationError(f"production stage3 image_result.purpose must be {STAGE3_BACKGROUND_PURPOSE}")
            if result.get("background_route") != STAGE3_BACKGROUND_ROUTE:
                raise ValidationError(f"production stage3 image_result.background_route must be {STAGE3_BACKGROUND_ROUTE}")
            if not _is_16_9(result["width_px"], result["height_px"]):
                raise ValidationError("production stage3 image_result must be 16:9")
            _validate_stage2_source_evidence(result.get("source_stage2"), "image_result.source_stage2")
            _require_sha256(result, "restore_targets_hash", "image_result")
            targets = validate_restore_targets(result.get("restore_targets"), "image_result.restore_targets")
            validate_restore_targets_hash(result["restore_targets_hash"], targets, "image_result.restore_targets_hash")
    return result


def _validate_image_dimensions(value: dict[str, Any], label: str) -> None:
    width = value.get("width_px")
    height = value.get("height_px")
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValidationError(f"{label}.width_px must be a positive integer")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValidationError(f"{label}.height_px must be a positive integer")
    aspect = value.get("aspect_ratio")
    if not isinstance(aspect, str) or ":" not in aspect:
        raise ValidationError(f"{label}.aspect_ratio must be a ratio string")


def _validate_size_box(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    width = value.get("width_px")
    height = value.get("height_px")
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValidationError(f"{label}.width_px must be a positive integer")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValidationError(f"{label}.height_px must be a positive integer")


def _validate_string_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be a list of strings")


def _validate_image_postprocess(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    _require_fields(value, ["type", "manifest_path", "method", "target_size"], label)
    if value["type"] != "canonical_image_postprocess":
        raise ValidationError(f"{label}.type must be canonical_image_postprocess")
    _require_string(value, "manifest_path", label)
    if value["method"] not in {"fit_center_crop", "contain_pad"}:
        raise ValidationError(f"{label}.method is invalid")
    target = value.get("target_size")
    if not isinstance(target, dict):
        raise ValidationError(f"{label}.target_size must be an object")
    width = target.get("width_px")
    height = target.get("height_px")
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValidationError(f"{label}.target_size.width_px must be a positive integer")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValidationError(f"{label}.target_size.height_px must be a positive integer")


def _is_16_9(width_px: int, height_px: int) -> bool:
    if width_px <= 0 or height_px <= 0:
        return False
    return abs((width_px / height_px) - (16 / 9)) <= 0.0015


def _validate_stage2_source_evidence(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    _require_fields(value, ["image_path", "result_path", "image_sha256"], label)
    for field in ("image_path", "result_path", "image_sha256"):
        _require_string(value, field, label)
    if not value["image_sha256"].startswith("sha256:"):
        raise ValidationError(f"{label}.image_sha256 must start with sha256:")
    return value


def validate_speaker_script(data: Any) -> dict[str, Any]:
    script = _require_mapping(data, "speaker_script")
    _require_fields(
        script,
        ["schema_version", "project_name", "run_dir", "talk", "basis", "slides", "created_at"],
        "speaker_script",
    )
    if script["schema_version"] != "2.0":
        raise ValidationError("speaker_script.schema_version must be 2.0")
    for field in ("project_name", "run_dir", "created_at"):
        _require_string(script, field, "speaker_script")

    talk = script.get("talk")
    if not isinstance(talk, dict):
        raise ValidationError("speaker_script.talk must be an object")
    _require_fields(talk, ["title", "speaker_role"], "speaker_script.talk")
    _reject_unexpected_fields(talk, ["title", "speaker_role"], "speaker_script.talk")
    for field in ("title", "speaker_role"):
        _require_string(talk, field, "speaker_script.talk")

    basis = script.get("basis")
    if not isinstance(basis, dict):
        raise ValidationError("speaker_script.basis must be an object")
    _require_fields(basis, ["stage1_page_plan", "stage1_content"], "speaker_script.basis")
    for field in ("stage1_page_plan", "stage1_content"):
        _require_string(basis, field, "speaker_script.basis")
    if "locked_presentation_source" in basis:
        _validate_locked_presentation_source(basis["locked_presentation_source"], "speaker_script.basis.locked_presentation_source")
    elif "stage3_editable_deck" in basis:
        _require_string(basis, "stage3_editable_deck", "speaker_script.basis")
    else:
        raise ValidationError("speaker_script.basis requires locked_presentation_source or legacy stage3_editable_deck")
    if "stage3_editable_deck_sha256" in basis:
        _require_sha256(basis, "stage3_editable_deck_sha256", "speaker_script.basis")

    slides = _require_non_empty_list(script, "slides", "speaker_script")
    _validate_slide_indices(slides, "speaker_script.slides")
    for index, slide in enumerate(slides, start=1):
        label = f"speaker_script.slides[{index}]"
        _require_fields(slide, ["slide_index", "slide_title", "script"], label)
        _reject_unexpected_fields(slide, ["slide_index", "slide_title", "script"], label)
        _require_string(slide, "slide_title", label)
        _require_string_list(slide, "script", label, non_empty=True)
    return script


def _validate_locked_presentation_source(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    _require_fields(value, ["source_mode", "source_path", "source_sha256"], label)
    mode = value.get("source_mode")
    if mode not in {"stage3_editable_deck", "stage2_image_deck", "external_editable_deck"}:
        raise ValidationError(f"{label}.source_mode is invalid")
    _require_string(value, "source_path", label)
    _require_sha256(value, "source_sha256", label)
    if "confirmation_basis" in value:
        _require_string(value, "confirmation_basis", label)
    return value


def validate_speaker_script_manifest(data: Any) -> dict[str, Any]:
    manifest = _require_mapping(data, "speaker_script_manifest")
    _require_fields(
        manifest,
        ["schema_version", "project_name", "run_dir", "files", "conversion", "summary", "created_at", "status"],
        "speaker_script_manifest",
    )
    if manifest["schema_version"] != "2.0":
        raise ValidationError("speaker_script_manifest.schema_version must be 2.0")
    for field in ("project_name", "run_dir", "created_at", "status"):
        _require_string(manifest, field, "speaker_script_manifest")
    if manifest["status"] not in {"generated", "needs_review", "failed"}:
        raise ValidationError("speaker_script_manifest.status is invalid")

    files = _require_non_empty_list(manifest, "files", "speaker_script_manifest")
    for index, file_info in enumerate(files, start=1):
        label = f"speaker_script_manifest.files[{index}]"
        if not isinstance(file_info, dict):
            raise ValidationError(f"{label} must be an object")
        _require_fields(file_info, ["label", "path", "sha256"], label)
        for field in ("label", "path"):
            _require_string(file_info, field, label)
        _require_sha256(file_info, "sha256", label)

    conversion = manifest.get("conversion")
    if not isinstance(conversion, dict):
        raise ValidationError("speaker_script_manifest.conversion must be an object")
    _require_fields(conversion, ["source", "pdf_path", "tool"], "speaker_script_manifest.conversion")
    for field in ("source", "pdf_path", "tool"):
        _require_string(conversion, field, "speaker_script_manifest.conversion")
    if "paired_docx" in conversion:
        _require_string(conversion, "paired_docx", "speaker_script_manifest.conversion")

    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        raise ValidationError("speaker_script_manifest.summary must be an object")
    for field in ("slides", "script_characters"):
        if not isinstance(summary.get(field), int) or summary[field] < 1:
            raise ValidationError(f"speaker_script_manifest.summary.{field} must be a positive integer")
    if "estimated_minutes" in summary and _require_number(summary, "estimated_minutes", "speaker_script_manifest.summary") <= 0:
        raise ValidationError("speaker_script_manifest.summary.estimated_minutes must be positive")
    return manifest
