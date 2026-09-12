"""Render only resolved visual instructions; page copy is never cleaned."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .image_prompt_plan import check_instruction, unique, validate_image_prompt_plan
from .prompt_rule_utils import rule_semantic_key
from .validation import ValidationError


def file_hash(path: str | Path) -> str:
    return 'sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _page_number(policy: dict, visible: list[str], plan: dict, slide_index: int) -> str:
    if not isinstance(policy, dict):
        raise ValidationError('page_number_policy必须为对象')
    enabled = policy.get('enabled') is True or policy.get('visible') is True
    existing = plan.get('text_roles', {}).get('page_number')
    if not enabled:
        if existing is not None:
            raise ValidationError('正文已有页码角色，但当前页码策略关闭，请主控对齐')
        return '不显示页码。'
    text = policy.get('text', str(slide_index))
    if not isinstance(text, str) or not text.strip():
        raise ValidationError('页码显示文字无效')
    if existing is not None:
        if 'text' in policy and text != visible[existing]:
            raise ValidationError('批准页码文字与page_number_policy不一致')
        label = '页面文字中指定的页码'
    else:
        check_instruction(text, label='页码文字', allow_page_number=True)
        label = f'页码“{text}”'
    position = policy.get('position', '右下角')
    style = policy.get('style', '')
    if not isinstance(position, str) or not isinstance(style, str):
        raise ValidationError('页码位置和样式必须为具体文字')
    instruction = f'{position}显示{label}' + (f'，{style}' if style else '') + '。'
    check_instruction(instruction, label='页码规则', allow_page_number=True)
    return instruction


def render_image_prompt(visible: list[str], plan: dict, page_number_policy: dict, slide_index: int, *, cover: bool = False) -> str:
    if not isinstance(visible, list) or not visible or not all(isinstance(x, str) and x.strip() for x in visible):
        raise ValidationError('正式生图必须有完整的批准页面文字')
    validate_image_prompt_plan(plan, visible)
    rows = ['生成一张横版中文PPT' + ('封面。' if cover else '图片。'), '', '画面文字，按段完整呈现：', '\n\n'.join(visible)]
    role_names = {'title': '标题', 'subtitle': '副标题', 'module_index': '章节编号', 'module_title': '章节标题', 'module_subtitle': '章节说明', 'page_number': '页码文字'}
    role_instructions = []
    for index, text in enumerate(visible):
        labels = [name for role, name in role_names.items() if plan['text_roles'].get(role) == index]
        if labels:
            role_instructions.append(f'第{index + 1}段作为' + '、'.join(labels))
    if role_instructions:
        rows += ['', '排版要求：' + '，'.join(role_instructions) + '；这些用途名称不出现在画面中。']
    emitted: set[str] = set()
    for field, label in [('visual', '构图'), ('style', '图片风格'), ('layout', '文字与布局'), ('constraints', '画面限制')]:
        items = []
        for rule in unique(plan[field]):
            key = rule_semantic_key(rule)
            if key not in emitted:
                emitted.add(key)
                items.append(rule)
        if items:
            rows += ['', label + '：' + '；'.join(x.rstrip('。；; ') for x in items) + '。']
    rows += ['', _page_number(page_number_policy, visible, plan, slide_index), '仅呈现指定文字' + ('和页码。' if page_number_policy.get('enabled') is True or page_number_policy.get('visible') is True else '。')]
    return '\n'.join(rows)


def compile_stage2_prompt(*, content_slide: dict[str, Any], prompt_brief: dict[str, Any], deck_style: dict[str, Any], layout_intent: dict[str, Any], route: str, design_contract: dict[str, Any] | None = None, layout_safety_slide: dict[str, Any] | None = None, image_style: dict[str, Any] | None = None) -> str:
    """Compatibility signature; only the controller's resolved plan is rendered.

    Formal dispatch additionally validates its source basis with current_plan.
    Raw deck/layout/safety prose cannot be appended at this stage.
    """
    visible = content_slide.get('final_visible_text')
    if prompt_brief.get('final_visible_text') != visible:
        raise ValidationError('final_visible_text与content不一致')
    return render_image_prompt(visible, prompt_brief.get('image_prompt_plan'), deck_style.get('page_number_policy', {}), content_slide['slide_index'], cover=content_slide.get('page_type') == 'cover')
