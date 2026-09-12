"""Project-level PPT consistency rules for stage1 and prompt planning."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

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

    layout_rules: list[str] = []
    exception_rules: list[str] = []
    if role == "section_intro":
        layout_rules.extend(_lines(sections["模块页统一"]))
    elif role in SPECIAL_ROLES:
        exception_rules.extend(_lines(sections["不适用与例外"]))
        layout_rules.extend(exception_rules)
    else:
        layout_rules.extend(_lines(sections["标题统一"]))

    common_rules, page_number_rules = _split_page_number_rules(_lines(sections["全套公共元素"]))
    layout_rules.extend(common_rules)
    constraints = _lines(sections["统一禁用项"])
    snapshot = {
        "schema_version": "1.0",
        "document_path": rules["document_path"],
        "document_hash": rules["hash"],
        "slide_index": slide_index,
        "page_role": role,
        "layout_rules": _unique(layout_rules),
        "constraints": _unique(constraints),
        "page_number_rules": page_number_rules,
        "exception_rules": _unique(exception_rules),
        "has_section_pages": has_section_pages,
    }
    snapshot["hash"] = "sha256:" + hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
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
    return [re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", x).strip() for x in value.splitlines() if x.strip()]


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
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = re.sub(r"\s+", " ", item).strip().rstrip("。；; ")
        if key and key not in seen:
            seen.add(key)
            result.append(re.sub(r"\s+", " ", item).strip())
    return result
