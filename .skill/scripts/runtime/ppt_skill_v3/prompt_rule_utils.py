"""Small deterministic helpers for source rules before they become prompts."""
from __future__ import annotations

import re
from typing import Iterable


LABEL_TERMS = (
    "章节标签",
    "章节导航",
    "眉题",
    "模块导航",
    "section_label",
    "chapter_label",
    "chapter_tag",
    "eyebrow",
)

DOCUMENT_META_PREFIXES = (
    "适用页面",
    "允许变化",
    "例外",
    "基准页",
    "调整记录",
    "说明",
)

_PAGE_REF = re.compile(r"(?:[Pp]|第)\s*(\d{1,3})(?:\s*(?:[-–—~至到]|/)\s*(?:[Pp]|第)?\s*(\d{1,3}))?")


def strip_list_marker(value: str) -> str:
    return re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", value).strip()


def clean_rule_text(value: str) -> str:
    text = strip_list_marker(str(value))
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"[（(]\s*(?:详见|见)[^）)]*[）)]", "", text)
    text = text.replace("：；", "：").replace(":;", ":")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def page_refs(value: str) -> set[int]:
    refs: set[int] = set()
    for match in _PAGE_REF.finditer(value):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end < start:
            start, end = end, start
        refs.update(range(start, end + 1))
    return refs


def rule_applies_to_slide(value: str, slide_index: int | None) -> bool:
    if slide_index is None:
        return True
    refs = page_refs(value)
    return not refs or slide_index in refs


def is_optional_label_rule(value: str) -> bool:
    compact = re.sub(r"\s+", "", value).lower()
    return any(term.lower() in compact for term in LABEL_TERMS)


def is_document_meta_rule(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if any(compact.startswith(prefix) for prefix in DOCUMENT_META_PREFIXES):
        return True
    return compact.startswith(("见「", "见《", "详见", "参考", "适用于"))


def filter_rule_lines(
    values: Iterable[str],
    *,
    slide_index: int | None = None,
    drop_optional_labels: bool = True,
    drop_document_meta: bool = True,
) -> list[str]:
    result: list[str] = []
    for value in values:
        rule = clean_rule_text(value)
        if not rule:
            continue
        if drop_document_meta and is_document_meta_rule(rule):
            continue
        if drop_optional_labels and is_optional_label_rule(rule):
            continue
        if not rule_applies_to_slide(rule, slide_index):
            continue
        result.append(rule)
    return unique_rules(result)


def rule_semantic_key(value: str) -> str:
    text = clean_rule_text(value)
    compact = re.sub(r"\s+", "", text).lower().rstrip("。；; ")
    if any(token in compact for token in ("照片", "写实", "3d渲染", "3d", "摄影")) and any(
        token in compact for token in ("禁止", "不使用", "不要", "避免", "不得", "不能")
    ):
        return "ban:photo_realistic_3d"
    if any(token in compact for token in ("未批准文字", "拼音", "乱码", "水印", "logo")) and any(
        token in compact for token in ("禁止", "不使用", "不要", "避免", "不得", "不能")
    ):
        return "ban:unapproved_text_logo_watermark"
    if any(token in compact for token in ("温暖积极", "阴暗压抑", "负面情绪")):
        return "ban:mood_positive"
    if any(token in compact for token in ("低龄", "幼稚", "涂鸦")):
        return "ban:childish_doodle"
    if "页码" in compact and any(token in compact for token in ("禁止", "不显示", "不加", "不要", "不得", "不能", "未要求")):
        return "ban:page_number"
    return compact


def unique_rules(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        rule = clean_rule_text(value)
        key = rule_semantic_key(rule)
        if key and key not in seen:
            seen.add(key)
            result.append(rule)
    return result


def is_unbound_label_region(region: dict, bound_roles: set[str]) -> bool:
    chunks: list[str] = []
    for key in ("region_id", "zone_id", "id", "name", "role", "type"):
        value = region.get(key)
        if isinstance(value, str):
            chunks.append(value)
    roles = region.get("required_text_roles")
    if isinstance(roles, list):
        chunks.extend(str(role) for role in roles)
    text = " ".join(chunks).lower()
    if not any(term.lower() in text for term in LABEL_TERMS):
        return False
    return not any(role in bound_roles for role in ("section_label", "chapter_label", "eyebrow", "chapter_tag"))
