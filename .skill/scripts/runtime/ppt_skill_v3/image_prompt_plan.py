"""Controller-authored visual plans; deterministic preparation and request checks.

Plans are derived fields in existing briefs/cover option briefs. No code here
summarizes prose or decides which of two conflicting visual instructions wins.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .json_io import read_json, write_json
from .prompt_rule_utils import (
    clean_rule_text,
    is_document_meta_rule,
    is_optional_label_rule,
    is_unbound_label_region,
    strip_list_marker,
    unique_rules,
)
from .validation import ValidationError

PROMPT_FORMAT_VERSION = '3'
PLAN_FIELDS = ('visual', 'style', 'layout', 'constraints')
ROLE_ALIASES = {
    '封面': 'cover', '封面页': 'cover', '内容页': 'content',
    'section': 'section_intro', 'chapter': 'section_intro', 'module': 'section_intro',
    'chapter_intro': 'section_intro', 'section_divider': 'section_intro',
    '章节页': 'section_intro', '模块页': 'section_intro',
    '目录': 'agenda', '目录页': 'agenda', 'toc': 'agenda',
    '流程页': 'process', '图表页': 'chart', '结束页': 'ending', 'end': 'ending', 'closing': 'ending',
}
_DIMENSIONS = re.compile(r'\d{3,5}\s*[x×X]\s*\d{3,5}|(?<![A-Za-z0-9_])(?:1|2|4|8)[kK](?![A-Za-z0-9_])|(?<!\d)16\s*[:：]\s*9(?!\d)|(?:目标|输出|画布|生成)(?:图片|图像)?(?:尺寸|分辨率)')
_INTERNAL = re.compile(
    r'_state(?:/|\\)|sha256:|(?<![A-Za-z0-9_])(?:material_id|generation_request_id|title_and_points|main_visual|page_number_\d+|final_visible_text)(?![A-Za-z0-9_])'
    r'|页面文字层|可编辑图层|待主控|待生成|待重试|生成失败|参考图风格已提炼|根据参考图提炼'
    r'|本次以文字描述表达参考风格|所有候选|四张候选|沿用上一页|与上一页一致|与前面一致|保持其他不变'
)
_TOKEN = re.compile(r'\{([A-Za-z_][A-Za-z_0-9]*)\}')


def digest(value: Any) -> str:
    return 'sha256:' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def normalize_role(value: str) -> str:
    return ROLE_ALIASES.get(value, value)


def applies_to_page(rule: dict, slide_index: int, role: str) -> bool:
    applies = rule.get('applies_to')
    excluded = rule.get('exclude_slide_indices', [])
    if applies is not None and (not isinstance(applies, list) or not all(isinstance(x, str) for x in applies)):
        raise ValidationError('applies_to必须为页面角色列表')
    if not isinstance(excluded, list) or any(type(x) is not int or x < 1 for x in excluded):
        raise ValidationError('exclude_slide_indices必须为正整数列表')
    return (applies is None or role in {normalize_role(x) for x in applies}) and slide_index not in excluded


def page_number_policy(policy: dict, slide_index: int, role: str) -> dict:
    if not isinstance(policy, dict):
        raise ValidationError('page_number_policy必须为对象')
    enabled = policy.get('enabled') is True or policy.get('visible') is True
    enabled = enabled and applies_to_page(policy, slide_index, role)
    # Cover candidates and a promoted cover follow the same default exemption.
    if role == 'cover' and policy.get('applies_to') is None:
        enabled = False
    return {'enabled': enabled, **{k: policy[k] for k in ('text', 'position', 'style') if k in policy}} if enabled else {'enabled': False}


def page_role(content: dict, brief: dict, layout: dict | None = None) -> str:
    mapped = next((x.get('page_role') for x in (layout or {}).get('slide_role_map', []) if x.get('slide_index') == content['slide_index']), None)
    values = [normalize_role(x) for x in (content.get('page_role'), brief.get('page_role'), mapped, content.get('page_type')) if x]
    specific = set(values) - {'content'}
    if len(specific) > 1:
        raise ValidationError(f"第{content['slide_index']}页的页面角色冲突，请主控对齐规划：" + '、'.join(sorted(specific)))
    return next(iter(specific), 'content')


def _lines(value: str) -> list[str]:
    return [strip_list_marker(x) for x in value.splitlines() if x.strip()]


def unique(items: list[str]) -> list[str]:
    return unique_rules(items)


def check_instruction(text: str, *, label: str = '画面规则', allow_page_number: bool = False) -> None:
    if _DIMENSIONS.search(text):
        raise ValidationError(f'{label}混入输出尺寸/分辨率指令，请在请求参数中设置')
    if _INTERNAL.search(text) or _TOKEN.search(text):
        raise ValidationError(f'{label}混入内部说明或未解析变量，请主控整理')
    if '**' in text or re.search(r'[`*_]{2,}', text):
        raise ValidationError(f'{label}混入Markdown标记，请主控整理')
    if is_document_meta_rule(text) or '详见' in text:
        raise ValidationError(f'{label}混入文档说明或内部引用，请主控整理')
    if is_optional_label_rule(text):
        raise ValidationError(f'{label}混入未启用的章节标签规则，请主控整理')
    if re.search(r'(?:[Pp]\s*\d+|第\s*\d+\s*页).*(?:[、,/]|[-–—~至到]).*(?:[Pp]?\s*\d+|第\s*\d+\s*页)', text):
        raise ValidationError(f'{label}混入跨页映射，请主控整理为当前页规则')
    if not allow_page_number and '页码' in text and not _is_page_number_constraint(text):
        raise ValidationError(f'{label}不应另写页码规则，请使用page_number_policy')


def _is_page_number_constraint(text: str) -> bool:
    compact = re.sub(r'\s+', '', text)
    if '页码' not in compact:
        return False
    return any(word in compact for word in ('不显示', '不加', '不要', '不得', '不能', '禁止', '避免', '未要求'))


def validate_image_prompt_plan(plan: Any, visible: list[str] | None = None) -> dict:
    if not isinstance(plan, dict) or plan.get('version') != '1':
        raise ValidationError('缺少有效image_prompt_plan，请主控准备本页画面计划')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', str(plan.get('basis_hash', ''))):
        raise ValidationError('image_prompt_plan缺少当前来源摘要，请重新准备')
    if set(plan) - {*PLAN_FIELDS, 'version', 'basis_hash', 'text_roles'}:
        raise ValidationError('image_prompt_plan包含未知字段')
    for field in PLAN_FIELDS:
        items = plan.get(field)
        if not isinstance(items, list) or (field in {'visual', 'style'} and not items):
            raise ValidationError(f'image_prompt_plan.{field}必须为画面规则列表')
        for item in items:
            if not isinstance(item, str) or not item.strip():
                raise ValidationError(f'image_prompt_plan.{field}含空规则')
            check_instruction(item, label=field)
    roles = plan.get('text_roles')
    if not isinstance(roles, dict) or set(roles) - {'title', 'subtitle', 'module_index', 'module_title', 'module_subtitle', 'page_number'}:
        raise ValidationError('image_prompt_plan.text_roles包含未知文字角色')
    for role, index in roles.items():
        if type(index) is not int or index < 0 or (visible is not None and index >= len(visible)):
            raise ValidationError(f'文字角色{role}引用越界')
    return plan


def load_prompt_sources(run_dir: str | Path, slide_index: int, *, option_id: str | None = None) -> dict:
    from .image_style import image_style_snapshot
    from .ppt_consistency import ppt_consistency_snapshot
    root = Path(run_dir)
    def asset(rel: str) -> dict:
        path = root / rel
        return read_json(path) if path.exists() else {}
    def slide(data: dict) -> dict:
        return next((x for x in data.get('slides', []) if x.get('slide_index') == slide_index), {})
    content = slide(asset('_state/阶段1/content.json'))
    brief = slide(asset('_state/阶段1/slide_prompt_briefs.json'))
    if not content or not brief or not content.get('final_visible_text'):
        raise ValidationError(f'第{slide_index}页缺少已确认的页面文字或brief')
    if content['final_visible_text'] != brief.get('final_visible_text'):
        raise ValidationError(f'第{slide_index}页final_visible_text与content不一致')
    layout = asset('_state/阶段2/layout_intent.json')
    deck = asset('_state/阶段2/deck_style.json')
    role = 'cover' if option_id else page_role(content, brief, layout)
    style = image_style_snapshot(root, slide_index, role, normalize_roles=True)
    consistency = ppt_consistency_snapshot(root, slide_index, role, content=asset('_state/阶段1/content.json'))
    option = next((x for x in asset('_state/阶段1/design_contract.json').get('stage2_cover_option_strategy', {}).get('option_briefs', []) if x.get('option_id') == option_id), {}) if option_id else {}
    if option_id and not option:
        raise ValidationError('封面候选缺少主控规划：' + option_id)
    selected_shared = 'section_intro_template' if role == 'section_intro' else 'header_lock'
    shared = (deck.get(selected_shared) or layout.get(selected_shared)) if role not in {'cover', 'agenda', 'ending'} else None
    shared_configured = shared is not None
    if isinstance(shared, dict):
        if shared.get('enabled') is False or not applies_to_page(shared, slide_index, role):
            shared = None
        else:
            shared = {'prompt_block': shared.get('prompt_block')}
    safety = slide(asset('_state/阶段1/layout_safety_contract.json'))
    layouts = [value for key, value in layout.get('page_type_rules', {}).items() if normalize_role(key) == role]
    # Only effective visual inputs participate. Metadata and derived plans do not.
    sources = {
        'slide_index': slide_index, 'option_id': option_id, 'page_role': role,
        'visible': content['final_visible_text'],
        'ppt_consistency': {
            k: consistency.get(k)
            for k in ('document_path', 'hash', 'layout_rules', 'constraints', 'page_number_rules', 'exception_rules', 'title_component_rules', 'module_component_rules', 'common_element_rules')
        },
        'style': {k: style.get(k, '') for k in ('common', 'forbidden', 'type_rule', 'page_rule')},
        'brief': {k: brief.get(k) for k in ('visual_composition', 'main_visual_elements', 'style_constraints', 'negative_constraints', 'density_budget')},
        'option': {k: v for k, v in option.items() if k in {'composition', 'style_positioning', 'visual_medium', 'palette_strategy', 'typography_direction', 'prompt_constraints'}},
        'shared': shared,
        'header_policy': deck.get('section_policy' if role == 'section_intro' else 'header_policy') if not shared_configured and role not in {'cover', 'agenda', 'ending'} else None,
        'page_number_policy': page_number_policy(deck.get('page_number_policy', {}), slide_index, role),
        'page_layout': layouts[0] if len(layouts) == 1 else layouts or None,
        'safety': {k: safety.get(k) for k in ('text_safe_regions', 'editable_text_regions', 'visual_regions', 'exclusion_zones')},
    }
    return {'sources': sources, 'basis_hash': digest(sources), 'plan': (option if option_id else brief).get('image_prompt_plan')}


def _box_instruction(region: dict, kind: str) -> str:
    box = region.get('relative_box', region.get('box', region.get('bbox', region)))
    if not isinstance(box, dict):
        return ''
    fields = [('x', '左边距'), ('y', '上边距'), ('w', '宽度'), ('h', '高度')]
    parts = []
    for key, label in fields:
        value = box.get(key, box.get({'w': 'width', 'h': 'height'}.get(key, key)))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f'{label}{value * 100:g}%')
    return f'{kind}相对画布：' + '，'.join(parts) if parts else ''


def layout_components(sources: dict, roles: dict[str, int]) -> list[str]:
    """Prepare components once, with role references instead of duplicate text."""
    names = {'title': '标题', 'subtitle': '副标题', 'module_title': '章节标题', 'module_index': '章节编号', 'module_subtitle': '章节说明'}
    result: list[str] = []
    shared = sources.get('shared')
    if isinstance(shared, dict) and shared.get('prompt_block'):
        def replace(match):
            key = match.group(1)
            key = 'title' if key == 'slide_title' else key
            if key not in roles or key not in names:
                raise ValidationError('共享图片规则含未绑定到批准文字的变量：' + key)
            return names[key]
        result.append(_TOKEN.sub(replace, shared['prompt_block']))
    elif sources.get('header_policy'):
        header = clean_rule_text(sources['header_policy'])
        if header and not is_document_meta_rule(header) and not is_optional_label_rule(header):
            result.append(header)
    safety = sources.get('safety') or {}
    bound_roles = set(roles)
    for key, kind in [('text_safe_regions', '文字区域'), ('visual_regions', '图解区域')]:
        regions = safety.get(key) or (safety.get('editable_text_regions') if key == 'text_safe_regions' else []) or []
        for region in regions:
            if isinstance(region, dict):
                if key == 'text_safe_regions' and is_unbound_label_region(region, bound_roles):
                    continue
                rule = _box_instruction(region, kind)
                if rule:
                    result.append(rule)
    for zone in safety.get('exclusion_zones') or []:
        # Text-owned metadata/IDs never become prose. Page-number zones are
        # handled by the single page number policy in the final compiler.
        if isinstance(zone, dict) and not any('page_number' in str(zone.get(key, '')) for key in ('zone_id', 'id', 'name')):
            rule = _box_instruction(zone, '留白区域')
            if rule:
                result.append(rule)
    return unique(result)


def prepare_plan(run_dir: str | Path, slide_index: int, draft: dict, *, option_id: str | None = None) -> dict:
    """Freeze the controller's resolved plan without re-expanding source prose.

    ``PPT一致性.md`` and ``图片风格.md`` remain in ``load_prompt_sources`` so
    the controller can make a page-specific decision.  Runtime records the
    source basis and validates the result, but must not turn every applicable
    upstream sentence back into the submitted prompt.
    """
    context = load_prompt_sources(run_dir, slide_index, option_id=option_id)
    plan = deepcopy(draft)
    plan['version'] = '1'
    plan['basis_hash'] = context['basis_hash']
    plan.setdefault('text_roles', {})
    for field in PLAN_FIELDS:
        plan.setdefault(field, [])
        if not isinstance(plan[field], list) or not all(isinstance(x, str) for x in plan[field]):
            raise ValidationError(f'image_prompt_plan.{field}必须为字符串列表')
    validate_image_prompt_plan(plan, context['sources']['visible'])
    for field in PLAN_FIELDS:
        plan[field] = unique(plan[field])
    validate_image_prompt_plan(plan, context['sources']['visible'])
    return plan


def record_image_prompt_plan(run_dir: str | Path, slide_index: int, draft: dict, *, option_id: str | None = None) -> dict:
    from .state import read_state
    if read_state(run_dir)['current_stage'] not in {'stage1', 'stage2'}:
        raise ValidationError('画面计划只能在阶段1或阶段2准备')
    plan = prepare_plan(run_dir, slide_index, draft, option_id=option_id)
    root = Path(run_dir)
    rel = '_state/阶段1/design_contract.json' if option_id else '_state/阶段1/slide_prompt_briefs.json'
    data = read_json(root / rel)
    records = data['stage2_cover_option_strategy']['option_briefs'] if option_id else data['slides']
    target = next(x for x in records if (x.get('option_id') == option_id if option_id else x.get('slide_index') == slide_index))
    target['image_prompt_plan'] = plan
    write_json(root / rel, data)
    return plan


def current_plan(run_dir: str | Path, slide_index: int, *, option_id: str | None = None) -> tuple[dict, dict]:
    context = load_prompt_sources(run_dir, slide_index, option_id=option_id)
    plan = validate_image_prompt_plan(context['plan'], context['sources']['visible'])
    if plan['basis_hash'] != context['basis_hash']:
        raise ValidationError(f'第{slide_index}页画面计划来源已变化，请主控重新整理并派发')
    return plan, context['sources']


def compile_current_prompt(run_dir: str | Path, slide_index: int, *, option_id: str | None = None) -> str:
    from .prompt_compiler import render_image_prompt
    plan, sources = current_plan(run_dir, slide_index, option_id=option_id)
    return render_image_prompt(sources['visible'], plan, sources['page_number_policy'], slide_index, cover=bool(option_id) or sources['page_role'] == 'cover')


def validate_packet_prompt(run_dir: str | Path, packet: dict) -> None:
    if packet.get('prompt_format_version') != PROMPT_FORMAT_VERSION:
        raise ValidationError('旧待发送提示词需按当前规范重新准备并派发')
    option = packet.get('option_id') if packet.get('purpose') == 'cover_option' else None
    expected = compile_current_prompt(run_dir, packet['slide_index'], option_id=option)
    if packet.get('prompt') != expected or packet.get('prompt_hash') != 'sha256:' + hashlib.sha256(expected.encode()).hexdigest():
        raise ValidationError('请求提示词与当前画面计划不一致，请重新派发')
    plan, _ = current_plan(run_dir, packet['slide_index'], option_id=option)
    instructions = '\n'.join(rule for field in PLAN_FIELDS for rule in plan[field])
    if re.search(r'输入图|附图', instructions):
        api = packet.get('image_api_input', {})
        builtin = packet.get('image_gen_input', {})
        route = packet.get('image_generation_route')
        paths = builtin.get('referenced_image_paths') if route == 'codex_image_gen' else api.get('referenced_image_paths') if api.get('endpoint') == '/v1/images/edits' else None
        actual_paths = isinstance(paths, list) and bool(paths) and all(isinstance(p, str) and (Path(run_dir) / p).is_file() for p in paths)
        urls = api.get('urls') if route == 'openai_image_api' and api.get('endpoint') == '/v1/draw/completions' else None
        actual_urls = isinstance(urls, list) and bool(urls) and all(isinstance(u, str) and re.match(r'^https?://[^/\s]+', u) for u in urls)
        if not (actual_paths or actual_urls):
            raise ValidationError('提示词引用输入图，但本次请求未提供真实图片输入')
