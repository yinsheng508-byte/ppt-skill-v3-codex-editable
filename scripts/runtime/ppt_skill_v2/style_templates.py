from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .json_io import read_json
from .validation import ValidationError


STYLE_TEMPLATE_REGISTRY_REL_PATH = Path("assets/templates/风格模板/registry.json")
STYLE_TEMPLATE_ROOT_REL_PATH = Path("assets/templates/风格模板")
STYLE_TEMPLATE_SCHEMA_VERSION = "1.0"
STYLE_TEMPLATE_STATUSES = {"active", "draft", "deprecated"}
STYLE_TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


def default_skill_root() -> Path:
    return Path(__file__).resolve().parents[3]


def registry_path(skill_root: str | Path | None = None) -> Path:
    root = Path(skill_root) if skill_root is not None else default_skill_root()
    return root / STYLE_TEMPLATE_REGISTRY_REL_PATH


def load_style_template_registry(skill_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(skill_root) if skill_root is not None else default_skill_root()
    registry = read_json(root / STYLE_TEMPLATE_REGISTRY_REL_PATH)
    return validate_style_template_registry(registry, root)


def validate_style_template_registry(data: Any, skill_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(skill_root) if skill_root is not None else default_skill_root()
    if not isinstance(data, dict):
        raise ValidationError("style_template_registry must be an object")
    if data.get("schema_version") != STYLE_TEMPLATE_SCHEMA_VERSION:
        raise ValidationError(f"style_template_registry.schema_version must be {STYLE_TEMPLATE_SCHEMA_VERSION}")
    templates = data.get("templates")
    if not isinstance(templates, list) or not templates:
        raise ValidationError("style_template_registry.templates must be a non-empty list")

    seen_ids: set[str] = set()
    seen_triggers: dict[str, str] = {}
    for index, template in enumerate(templates, start=1):
        label = f"style_template_registry.templates[{index}]"
        _validate_style_template_record(template, label, root, seen_ids, seen_triggers)
    return data


def list_style_templates(
    *,
    include_deprecated: bool = False,
    skill_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    registry = load_style_template_registry(skill_root)
    templates = registry["templates"]
    if include_deprecated:
        return templates
    return [template for template in templates if template.get("status") != "deprecated"]


def resolve_style_template(query: str, skill_root: str | Path | None = None) -> dict[str, Any]:
    normalized = query.strip()
    if not normalized:
        raise ValidationError("style template query must be non-empty")
    normalized_id = normalized.lower()
    for template in list_style_templates(include_deprecated=True, skill_root=skill_root):
        names = {template["id"], template["name"], template.get("display_name", "")}
        triggers = set(template.get("triggers") or [])
        if normalized in names or normalized in triggers or normalized_id == template["id"].lower():
            if template.get("status") == "deprecated":
                raise ValidationError(f"style template is deprecated: {template['id']}")
            return template
    raise ValidationError(f"style template not found: {query}")


def style_template_summary(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": template["id"],
        "name": template["name"],
        "display_name": template.get("display_name", template["name"]),
        "status": template["status"],
        "triggers": template["triggers"],
        "template_path": template["template_path"],
        "description": template["description"],
        "route_hints": template.get("route_hints", []),
        "style_tags": template.get("style_tags", []),
        "default_font_family": template.get("default_font_family"),
        "palette_hint": template.get("palette_hint", {}),
        "usage_policy": template.get("usage_policy", {}),
    }


def validate_style_templates_report(skill_root: str | Path | None = None) -> dict[str, Any]:
    try:
        registry = load_style_template_registry(skill_root)
        templates = [style_template_summary(template) for template in registry["templates"]]
        active_templates = [template for template in templates if template["status"] == "active"]
        return {
            "schema_version": STYLE_TEMPLATE_SCHEMA_VERSION,
            "ok": True,
            "registry": str(STYLE_TEMPLATE_REGISTRY_REL_PATH),
            "templates_count": len(templates),
            "active_count": len(active_templates),
            "triggers": sorted(trigger for template in templates for trigger in template["triggers"]),
            "templates": templates,
        }
    except Exception as exc:
        return {
            "schema_version": STYLE_TEMPLATE_SCHEMA_VERSION,
            "ok": False,
            "registry": str(STYLE_TEMPLATE_REGISTRY_REL_PATH),
            "error": str(exc),
        }


def _validate_style_template_record(
    template: Any,
    label: str,
    root: Path,
    seen_ids: set[str],
    seen_triggers: dict[str, str],
) -> None:
    if not isinstance(template, dict):
        raise ValidationError(f"{label} must be an object")
    required = ["id", "name", "status", "template_path", "triggers", "description", "usage_policy"]
    missing = [field for field in required if field not in template]
    if missing:
        raise ValidationError(f"{label} missing required fields: {', '.join(missing)}")

    template_id = _require_non_empty_string(template, "id", label)
    if not STYLE_TEMPLATE_ID_RE.match(template_id):
        raise ValidationError(f"{label}.id must use lowercase letters, digits, and hyphens")
    if template_id in seen_ids:
        raise ValidationError(f"{label}.id is duplicated: {template_id}")
    seen_ids.add(template_id)

    for field in ("name", "status", "template_path", "description"):
        _require_non_empty_string(template, field, label)
    if template["status"] not in STYLE_TEMPLATE_STATUSES:
        raise ValidationError(f"{label}.status is invalid: {template['status']}")

    triggers = template.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        raise ValidationError(f"{label}.triggers must be a non-empty list")
    for trigger in triggers:
        if not isinstance(trigger, str) or not trigger.strip():
            raise ValidationError(f"{label}.triggers must contain non-empty strings")
        if not trigger.startswith("/"):
            raise ValidationError(f"{label}.triggers must start with /: {trigger}")
        if any(char.isspace() for char in trigger):
            raise ValidationError(f"{label}.triggers must not contain whitespace: {trigger}")
        previous = seen_triggers.get(trigger)
        if previous is not None:
            raise ValidationError(f"{label}.triggers duplicates {trigger} from {previous}")
        seen_triggers[trigger] = template_id

    template_rel = _validate_template_relpath(template["template_path"], label)
    template_path = root / template_rel
    if not template_path.exists():
        raise ValidationError(f"{label}.template_path does not exist: {template['template_path']}")
    if template_path.suffix.lower() != ".md":
        raise ValidationError(f"{label}.template_path must point to a markdown file")
    text = template_path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("# "):
        raise ValidationError(f"{label}.template_path must start with a markdown H1")
    if not any(trigger in text for trigger in triggers):
        raise ValidationError(f"{label}.template_path must mention at least one registered trigger")

    _validate_optional_string_list(template, "route_hints", label)
    _validate_optional_string_list(template, "style_tags", label)
    if "default_font_family" in template:
        _require_non_empty_string(template, "default_font_family", label)
    if "palette_hint" in template and not isinstance(template["palette_hint"], dict):
        raise ValidationError(f"{label}.palette_hint must be an object")
    _validate_usage_policy(template["usage_policy"], f"{label}.usage_policy")


def _validate_template_relpath(value: str, label: str) -> Path:
    relpath = Path(value)
    if relpath.is_absolute() or ".." in relpath.parts:
        raise ValidationError(f"{label}.template_path must be a safe relative path")
    if relpath.parts[:3] != STYLE_TEMPLATE_ROOT_REL_PATH.parts:
        raise ValidationError(f"{label}.template_path must be under {STYLE_TEMPLATE_ROOT_REL_PATH}")
    if relpath.name == "registry.json":
        raise ValidationError(f"{label}.template_path must not point to registry.json")
    return relpath


def _validate_usage_policy(policy: Any, label: str) -> None:
    if not isinstance(policy, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("requires_stage_flow", "skip_user_confirmations", "page_number_default"):
        if not isinstance(policy.get(field), bool):
            raise ValidationError(f"{label}.{field} must be a boolean")
    if policy["skip_user_confirmations"]:
        raise ValidationError(f"{label}.skip_user_confirmations must be false for PPT Skill v2")


def _validate_optional_string_list(template: dict[str, Any], field: str, label: str) -> None:
    if field not in template:
        return
    values = template[field]
    if not isinstance(values, list) or not all(isinstance(item, str) and item.strip() for item in values):
        raise ValidationError(f"{label}.{field} must be a list of non-empty strings")


def _require_non_empty_string(template: dict[str, Any], field: str, label: str) -> str:
    value = template.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label}.{field} must be a non-empty string")
    return value
