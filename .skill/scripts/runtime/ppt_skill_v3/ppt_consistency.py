"""Project-level PPT consistency rules for stage1 and prompt planning."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .prompt_rule_utils import (
    clean_rule_text,
    filter_rule_lines,
    is_optional_label_rule,
    page_refs,
    strip_list_marker,
    unique_rules,
)
from .validation import ValidationError

CONSISTENCY_RELPATH = "阶段1_规划确认/PPT一致性.md"
REQUIRED_SECTIONS = ("标题统一", "模块页统一", "全套公共元素", "不适用与例外", "统一禁用项")
PLACEHOLDER_MARKERS = ("待主控大模型", "TODO", "TBD", "禁止待主控大模型填写")
SPECIAL_ROLES = {"cover", "agenda", "ending"}

ROLE_ALIASES = {
    "封面": "cover",
    "封面页": "cover",
    "内容页": "content",
    "普通页": "content",
    "普通内容页": "content",
    "concept": "content",
    "概念页": "content",
    "case": "content",
    "案例页": "content",
    "section": "section_intro",
    "chapter": "section_intro",
    "module": "section_intro",
    "chapter_intro": "section_intro",
    "section_divider": "section_intro",
    "章节页": "section_intro",
    "模块页": "section_intro",
    "单元页": "section_intro",
    "目录": "agenda",
    "目录页": "agenda",
    "toc": "agenda",
    "流程页": "process",
    "图表页": "chart",
    "数据页": "chart",
    "表格页": "chart",
    "结束页": "ending",
    "致谢页": "ending",
    "end": "ending",
    "closing": "ending",
}


def consistency_document_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / CONSISTENCY_RELPATH


def consistency_template_path() -> Path:
    return Path(__file__).resolve().parents[3] / "assets/templates/阶段1PPT一致性模板.md"


def ensure_ppt_consistency_doc(run_dir: str | Path) -> Path:
    """Explicit stage1 draft operation. Reads and validators must not create it."""
    path = consistency_document_path(run_dir)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(consistency_template_path().read_text(encoding="utf-8"), encoding="utf-8")
    return path


def load_ppt_consistency(run_dir: str | Path) -> tuple[str, str]:
    path = consistency_document_path(run_dir)
    if not path.exists():
        raise ValidationError("缺少PPT一致性.md；请主控在阶段1形成标题、模块页、公共元素和例外规则")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValidationError("PPT一致性.md 为空")
    if any(marker in text for marker in PLACEHOLDER_MARKERS):
        raise ValidationError("PPT一致性.md 仍包含占位内容，请主控填写实际一致性规则")
    current = re.split(r"(?m)^## 调整记录\s*$", text)[0].strip()
    return current, "sha256:" + hashlib.sha256(current.encode()).hexdigest()


def validate_ppt_consistency_doc(run_dir: str | Path, content: dict[str, Any] | None = None) -> Path:
    text, _ = load_ppt_consistency(run_dir)
    sections = _sections(text, 2)
    missing = [section for section in REQUIRED_SECTIONS if not _clean(sections.get(section, ""))]
    if missing:
        raise ValidationError("PPT一致性.md 缺少必填章节：" + "、".join(missing))
    if _project_has_section_pages(content) and _module_section_declares_absent(sections["模块页统一"]):
        raise ValidationError("PPT一致性.md 有模块页但缺少模块页统一规则")
    return consistency_document_path(run_dir)


def ppt_consistency_rules(run_dir: str | Path) -> dict[str, Any]:
    text, text_hash = load_ppt_consistency(run_dir)
    sections = _sections(text, 2)
    missing = [section for section in REQUIRED_SECTIONS if section not in sections]
    if missing:
        raise ValidationError("PPT一致性.md 缺少必填章节：" + "、".join(missing))
    return {
        "schema_version": "1.0",
        "document_path": CONSISTENCY_RELPATH,
        "hash": text_hash,
        "sections": {section: _clean(sections.get(section, "")) for section in REQUIRED_SECTIONS},
    }


def ppt_consistency_snapshot(
    run_dir: str | Path,
    slide_index: int,
    page_role: str | None = None,
    *,
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = ppt_consistency_rules(run_dir)
    sections = rules["sections"]
    role = normalize_consistency_role(page_role)
    has_section_pages = _project_has_section_pages(content)
    module_declares_absent = _module_section_declares_absent(sections["模块页统一"])
    if role == "section_intro" and module_declares_absent:
        raise ValidationError(f"第{slide_index}页是模块页，但PPT一致性.md未提供模块页统一规则")
    if has_section_pages and module_declares_absent:
        raise ValidationError("PPT一致性.md 有模块页但缺少模块页统一规则")

    title_component_rules = _title_component_rules(_lines(sections["标题统一"]), slide_index)
    optional_label_rules = _optional_label_rules(_lines(sections["标题统一"]), slide_index)
    module_component_rules = filter_rule_lines(_lines(sections["模块页统一"]), slide_index=slide_index)
    exception_rules = _exception_rules(_lines(sections["不适用与例外"]), slide_index, role)
    layout_rules: list[str] = []
    if role == "section_intro":
        layout_rules.extend(module_component_rules)
    elif role in SPECIAL_ROLES:
        layout_rules.extend(exception_rules)
    else:
        layout_rules.extend(title_component_rules)
        layout_rules.extend(exception_rules)

    common_rules, page_number_rules = _split_page_number_rules(
        filter_rule_lines(_lines(sections["全套公共元素"]), slide_index=slide_index, drop_optional_labels=False)
    )
    layout_rules.extend(common_rules)
    constraints = filter_rule_lines(_lines(sections["统一禁用项"]), slide_index=slide_index, drop_optional_labels=False)
    snapshot = {
        "schema_version": "1.0",
        "document_path": rules["document_path"],
        "document_hash": rules["hash"],
        "slide_index": slide_index,
        "page_role": role,
        "layout_rules": unique_rules(layout_rules),
        "constraints": unique_rules(constraints),
        "page_number_rules": page_number_rules,
        "exception_rules": unique_rules(exception_rules),
        "title_component_rules": title_component_rules,
        "optional_label_rules": optional_label_rules,
        "module_component_rules": module_component_rules,
        "common_element_rules": common_rules,
        "has_section_pages": has_section_pages,
    }
    effective = {
        key: snapshot[key]
        for key in (
            "slide_index",
            "page_role",
            "layout_rules",
            "constraints",
            "page_number_rules",
            "exception_rules",
            "title_component_rules",
            "module_component_rules",
            "common_element_rules",
        )
    }
    snapshot["hash"] = "sha256:" + hashlib.sha256(
        json.dumps(effective, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return snapshot


def normalize_consistency_role(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        return "content"
    return ROLE_ALIASES.get(value.strip(), value.strip())


def _project_has_section_pages(content: dict[str, Any] | None) -> bool:
    if not isinstance(content, dict):
        return False
    for slide in content.get("slides", []):
        if not isinstance(slide, dict):
            continue
        role = normalize_consistency_role(slide.get("page_role") or slide.get("page_type"))
        if role == "section_intro":
            return True
    return False


def _module_section_declares_absent(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    absent_patterns = ("无模块页", "不使用模块页模板", "没有模块页", "无章节页")
    return any(pattern in compact for pattern in absent_patterns)


def _sections(text: str, level: int) -> dict[str, str]:
    parts = re.split(r"(?m)^" + "#" * level + r"\s+([^\n]+)\n", text)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts), 2)}


def _clean(value: str) -> str:
    return "\n".join(line.strip() for line in value.strip().splitlines() if line.strip())


def _lines(value: str) -> list[str]:
    return [strip_list_marker(x) for x in value.splitlines() if x.strip()]


def _title_component_rules(lines: list[str], slide_index: int) -> list[str]:
    return filter_rule_lines(lines, slide_index=slide_index, drop_optional_labels=True)


def _optional_label_rules(lines: list[str], slide_index: int) -> list[str]:
    result: list[str] = []
    for line in lines:
        rule = clean_rule_text(line)
        if rule and is_optional_label_rule(rule) and (not page_refs(rule) or slide_index in page_refs(rule)):
            result.append(rule)
    return unique_rules(result)


def _exception_rules(lines: list[str], slide_index: int, role: str) -> list[str]:
    role_tokens = {
        "cover": ("封面", "cover"),
        "agenda": ("目录", "agenda", "toc"),
        "ending": ("结束", "致谢", "ending", "closing"),
    }
    special_tokens = tuple(token for values in role_tokens.values() for token in values)
    result: list[str] = []
    for line in filter_rule_lines(lines, slide_index=slide_index, drop_optional_labels=True):
        compact = re.sub(r"\s+", "", line).lower()
        refs = page_refs(line)
        if role in role_tokens:
            if any(token.lower() in compact for token in role_tokens[role]):
                result.append(line)
            continue
        if refs and slide_index in refs and not any(token.lower() in compact for token in special_tokens):
            result.append(line)
    return unique_rules(result)


def _split_page_number_rules(lines: list[str]) -> tuple[list[str], list[str]]:
    common: list[str] = []
    page_number: list[str] = []
    for line in lines:
        if "页码" in line:
            page_number.append(line)
        else:
            common.append(line)
    return common, page_number


def _unique(items: list[str]) -> list[str]:
    return unique_rules(items)
