"""Controller-authored image style; reads never create or confirm project assets."""
from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .validation import ValidationError

STYLE_RELPATH = '阶段1_规划确认/图片风格.md'
LEGACY_STYLE_RELPATH = '阶段1_规划确认/风格与提示词方案.md'


def style_document_path(run_dir: str | Path) -> Path:
    root = Path(run_dir)
    return root / (STYLE_RELPATH if (root / STYLE_RELPATH).exists() else LEGACY_STYLE_RELPATH)


def ensure_image_style_doc(run_dir: str | Path) -> Path:
    """Explicit stage1 draft operation. Never call this from a read/validator."""
    root = Path(run_dir)
    path = root / STYLE_RELPATH
    if not path.exists() and (root / LEGACY_STYLE_RELPATH).exists():
        return root / LEGACY_STYLE_RELPATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        template = Path(__file__).resolve().parents[3] / 'assets/templates/阶段1图片风格模板.md'
        path.write_text(template.read_text(encoding='utf-8'), encoding='utf-8')
    return path


def load_image_style(run_dir: str | Path) -> tuple[str, str]:
    path = style_document_path(run_dir)
    if not path.exists():
        raise ValidationError('缺少图片风格.md；请主控在阶段1形成实际图片风格方案')
    text = path.read_text(encoding='utf-8').strip()
    if not text or any(x in text for x in ('待主控大模型', '用户尚未提供额外图片风格', 'TODO', 'TBD')):
        raise ValidationError('图片风格方案为空或仍为占位内容')
    current = re.split(r'(?m)^## (?:调整记录|输入与变更记录)\s*$', text)[0].strip()
    return current, 'sha256:' + hashlib.sha256(current.encode()).hexdigest()


def migrate_image_style_doc(run_dir: str | Path, merged_text: str | None = None) -> Path:
    root = Path(run_dir)
    old, new = root / LEGACY_STYLE_RELPATH, root / STYLE_RELPATH
    if not old.exists():
        if not new.exists():
            raise ValidationError('没有可迁移的图片风格文档')
        return new
    original = old.read_text(encoding='utf-8')
    if new.exists() and new.read_text(encoding='utf-8') != original and merged_text is None:
        raise ValidationError('新旧风格文档均有内容，请主控提供合并后的完整文本')
    content = merged_text if merged_text is not None else original.replace('# 风格与提示词方案', '# 图片风格', 1)
    if not content.strip() or '待主控大模型' in content:
        raise ValidationError('合并风格文档仍为空或包含占位内容')
    archive = root / '_state/阶段1/style_migration' / uuid.uuid4().hex
    archive.mkdir(parents=True)
    shutil.copy2(old, archive / old.name)
    if new.exists():
        shutil.copy2(new, archive / new.name)
    new.write_text(content, encoding='utf-8')
    old.unlink()  # The explicit migration preserved the complete original above.
    from .state import read_state, write_state
    state = read_state(root)
    for field in ('user_artifacts', 'expected_user_paths'):
        state.setdefault(field, {})['stage1_image_style'] = STYLE_RELPATH
        state[field]['stage1_style_prompt_plan'] = STYLE_RELPATH  # legacy field alias
    write_state(root, state)
    return new


PAGE_TYPES = {'封面': 'cover', '封面页': 'cover', '内容页': 'content', '章节页': 'section_intro', '模块页': 'section_intro', '流程页': 'process', '图表页': 'chart', '结束页': 'ending'}


def _sections(text: str, level: int) -> dict[str, str]:
    parts = re.split(r'(?m)^' + '#' * level + r'\s+([^\n]+)\n', text)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts), 2)}


def _clean(value: str) -> str:
    return '\n'.join(line.strip() for line in value.strip().splitlines() if line.strip())


def style_rules(run_dir: str | Path) -> dict[str, Any]:
    text, _ = load_image_style(run_dir)
    sections = _sections(text, 2)
    if style_document_path(run_dir).name != '图片风格.md':
        return {'common': text, 'forbidden': '', 'types': {}, 'pages': {}}
    common = sections.get('当前生效风格', '')
    if not common:
        raise ValidationError('图片风格.md 缺少当前生效风格')
    types_text = sections.get('不同页面的应用', '')
    types = _sections(types_text, 3)
    type_rules = {PAGE_TYPES.get(k, k): _clean(v) for k, v in types.items()}
    if not types:
        type_rules['*'] = _clean(types_text)
    pages_text = sections.get('逐页图片规划', '')
    pages: dict[str, str] = {}
    for heading, body in _sections(pages_text, 3).items():
        match = re.fullmatch(r'第?\s*0*(\d+)\s*页(?:[｜| ].*)?', heading)
        if match:
            pages[str(int(match.group(1)))] = _clean(body)
    for line in pages_text.splitlines():
        cells = [x.strip() for x in line.strip().strip('|').split('|')]
        if line.strip().startswith('|') and len(cells) >= 3:
            match = re.fullmatch(r'(?:第\s*)?0*(\d+)\s*(?:页)?', cells[0])
            if match:
                pages[str(int(match.group(1)))] = '；'.join(cells[2:])
    return {'common': _clean(common), 'forbidden': _clean(sections.get('禁用项', '')), 'types': type_rules, 'pages': pages}


def image_style_snapshot(run_dir: str | Path, slide_index: int, page_type: str | None = None, *, normalize_roles: bool = False) -> dict[str, Any]:
    from .json_io import read_json
    from .materials import load_materials
    root = Path(run_dir)
    if page_type is None:
        content_path = root / '_state/阶段1/content.json'
        content = read_json(content_path) if content_path.exists() else {}
        slide = next((x for x in content.get('slides', []) if x.get('slide_index') == slide_index), {})
        page_type = slide.get('page_type', 'content')
    page_type = PAGE_TYPES.get(page_type, page_type)
    rules = style_rules(root)
    if normalize_roles:
        # New plans share one role vocabulary. The legacy default deliberately
        # preserves the original snapshot/basis calculation for old results.
        from .image_prompt_plan import normalize_role
        page_type = normalize_role(page_type)
        types = {}
        for key, value in rules['types'].items():
            canonical = normalize_role(key)
            types[canonical] = '\n'.join(filter(None, [types.get(canonical), value]))
        rules['types'] = types
    references = []
    contract_path = root / '_state/阶段1/design_contract.json'
    contract = read_json(contract_path) if contract_path.exists() else {}
    materials = {x['id']: x for x in load_materials(root)['materials']}
    for ref in contract.get('image_style_references', []):
        if not isinstance(ref, dict) or not ref.get('interpretation') or not ref.get('use'):
            raise ValidationError('参考图必须记录实际解读 interpretation 和借鉴范围 use')
        if ref.get('slide_indices') and slide_index not in ref['slide_indices']:
            continue
        material = materials.get(ref.get('material_id'))
        if not material or not material.get('stored_path'):
            raise ValidationError('图片风格参考资料缺失或尚未保存到项目')
        path = root / material['stored_path']
        if not path.is_file():
            raise ValidationError('图片风格参考文件缺失：' + material['stored_path'])
        mode = ref.get('mode', 'text_analysis')
        if mode != 'text_analysis':
            raise ValidationError('当前风格入口采用看图提炼；直接传图须通过已验证的图片编辑/参考图路线单独准备请求')
        references.append({'material_id': material['id'], 'path': material['stored_path'], 'sha256': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(), 'interpretation': ref['interpretation'], 'use': ref['use'], 'mode': mode})
    snapshot = {
        'schema_version': '1.0', 'slide_index': slide_index, 'page_type': page_type,
        'common': rules['common'], 'forbidden': rules['forbidden'],
        'type_rule': '\n'.join(filter(None, [rules['types'].get('*'), rules['types'].get(page_type)])),
        'page_rule': rules['pages'].get(str(slide_index), ''), 'references': references,
    }
    snapshot['hash'] = style_snapshot_hash(snapshot)
    return snapshot


def style_snapshot_hash(snapshot: dict[str, Any]) -> str:
    import json
    payload = {k: v for k, v in snapshot.items() if k not in ('hash', 'document_path')}
    return 'sha256:' + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def describe_image_style(snapshot: dict[str, Any]) -> str:
    parts = ['整套图片风格：' + snapshot['common']]
    for field, label in [('type_rule', '本类页面规则'), ('page_rule', '本页图片规划'), ('forbidden', '风格禁用项')]:
        if snapshot.get(field):
            parts.append(label + '：' + snapshot[field])
    for ref in snapshot.get('references', []):
        parts.append('根据参考图提炼：' + ref['interpretation'] + '；借鉴范围：' + ref['use'] + '。本次以文字描述表达参考风格。')
    return '\n'.join(parts)


def generation_basis(run_dir: str | Path, slide_index: int, *, kind: str = 'full_slide', option_id: str | None = None, version: str = '1') -> dict[str, Any]:
    """Hash effective page inputs, not unrelated file metadata or execution purpose."""
    import json
    from .json_io import read_json
    if version == '2':
        from .image_prompt_plan import load_prompt_sources, digest
        context = load_prompt_sources(run_dir, slide_index, option_id=option_id if kind == 'cover_option' else None)
        return {'version': '2', 'kind': kind, 'slide_index': slide_index, 'option_id': option_id,
                'hash': digest({'sources': context['sources'], 'plan': context['plan']})}
    if version != '1':
        raise ValidationError('未知生成依据版本')
    root = Path(run_dir)
    def asset(path):
        file = root / path
        return read_json(file) if file.exists() else {}
    def page(data):
        return next((x for x in data.get('slides', []) if x.get('slide_index') == slide_index), {})
    content = page(asset('_state/阶段1/content.json'))
    brief = page(asset('_state/阶段1/slide_prompt_briefs.json'))
    page_type = 'cover' if kind == 'cover_option' else content.get('page_type', 'content')
    style = image_style_snapshot(root, slide_index, page_type)
    inputs = {'style_hash': style['hash'], 'content': {k: content.get(k) for k in ('title', 'purpose', 'final_visible_text', 'page_type')},
              'brief': {k: brief.get(k) for k in ('final_visible_text', 'visual_composition', 'main_visual_elements', 'density_budget', 'negative_constraints')}}
    if kind == 'cover_option':
        contract = asset('_state/阶段1/design_contract.json')
        option = next((x for x in contract.get('stage2_cover_option_strategy', {}).get('option_briefs', []) if x.get('option_id') == option_id), {})
        inputs['cover_composition'] = option.get('composition')
    else:
        deck = asset('_state/阶段2/deck_style.json')
        layout = asset('_state/阶段2/layout_intent.json')
        section = page_type in {'section_intro', 'section', 'chapter', 'module', 'chapter_intro'}
        keys = ['page_number_policy', 'forbidden_visuals'] + (['section_intro_template', 'section_policy'] if section else ['header_lock', 'header_policy'])
        inputs['deck'] = {k: deck.get(k) for k in keys}
        inputs['layout'] = {'page_type_rules': layout.get('page_type_rules', {}).get(page_type) if isinstance(layout.get('page_type_rules', {}), dict) else None,
                            'shared': layout.get('section_intro_template' if section else 'header_lock')}
        inputs['safety'] = page(asset('_state/阶段1/layout_safety_contract.json'))
    return {'kind': kind, 'slide_index': slide_index, 'option_id': option_id,
            'hash': 'sha256:' + hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}


def packet_matches_current(run_dir: str | Path, packet: dict[str, Any]) -> bool:
    try:
        if packet.get('generation_basis'):
            basis = packet['generation_basis']
            return generation_basis(run_dir, basis['slide_index'], kind=basis['kind'], option_id=basis.get('option_id'), version=basis.get('version', '1'))['hash'] == basis['hash']
        if packet.get('image_style_hash'):
            return image_style_snapshot(run_dir, packet['slide_index'], packet.get('image_style_snapshot', {}).get('page_type'))['hash'] == packet['image_style_hash']
        return True  # legacy requests still have their original evidence; not automatic reuse
    except (OSError, ValueError, KeyError, ValidationError):
        return False


def _result_key(result: dict[str, Any]) -> str:
    return '|'.join(str(result.get(k) or '') for k in ('generation_request_id', 'generation_id', 'image_sha256'))


def result_is_current(run_dir: str | Path, result: dict[str, Any], *, allow_legacy: bool = False) -> bool:
    from .state import read_state
    root = Path(run_dir)
    image = root / result.get('image_path', '__missing__')
    if not image.is_file() or 'sha256:' + hashlib.sha256(image.read_bytes()).hexdigest() != result.get('image_sha256'):
        return False
    acceptance = read_state(root).get('image_style_acceptances', {}).get(_result_key(result))
    if acceptance:
        try:
            basis = acceptance['basis']
            if generation_basis(root, result['slide_index'], kind=basis['kind'], option_id=basis.get('option_id'), version=basis.get('version', '1'))['hash'] == basis['hash']:
                return True
        except (OSError, ValueError, KeyError, ValidationError):
            return False
    if result.get('stale_for_current_style'):
        return False
    if not result.get('image_style_hash') and not result.get('generation_basis'):
        return allow_legacy
    return packet_matches_current(root, result)


def accept_image_result(run_dir: str | Path, result_file: str | Path, reason: str) -> dict[str, Any]:
    from .json_io import read_json
    from .state import read_state, write_state
    from .time_utils import now_iso
    root = Path(run_dir)
    path = Path(result_file)
    if not path.is_absolute():
        path = root / path
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValidationError('只能接纳当前项目内的图片结果记录')
    result = read_json(path)
    if not reason.strip():
        raise ValidationError('接纳旧图需要主控实际核对后的理由')
    image = root / result['image_path']
    if not image.is_file() or 'sha256:' + hashlib.sha256(image.read_bytes()).hexdigest() != result['image_sha256']:
        raise ValidationError('实际图片与原始记录不符，不能接纳')
    kind = 'cover_option' if result.get('promoted_from_cover_option') or result.get('purpose') == 'cover_option' else 'full_slide'
    basis = generation_basis(root, result['slide_index'], kind=kind, option_id=result.get('selected_cover_option') or result.get('option_id'), version=result.get('generation_basis', {}).get('version', '1'))
    state = read_state(root)
    acceptance = {'basis': basis, 'reason': reason, 'checked_at': now_iso(), 'result_file': str(path.relative_to(root))}
    state.setdefault('image_style_acceptances', {})[_result_key(result)] = acceptance
    write_state(root, state)
    return acceptance


def reconcile_image_style(run_dir: str | Path, *, reason: str, affected_slides: list[int] | None = None, reusable_slides: list[int] | None = None) -> dict[str, Any]:
    from .json_io import read_json
    from .state import read_state, write_state
    from .time_utils import now_iso
    root = Path(run_dir)
    state = read_state(root)
    if state['current_stage'] not in {'stage1', 'stage2'} or not reason.strip():
        raise ValidationError('风格变更须在阶段1/2执行并记录理由')
    affected = set(affected_slides or [])
    reusable = set(reusable_slides or [])
    if affected & reusable:
        raise ValidationError('同一页不能同时标为需返工和继续复用')
    if any(not isinstance(index, int) or index < 1 for index in affected | reusable):
        raise ValidationError('受影响页和复用页必须是正整数页码')
    records = (
        list((root / '_state/阶段2/cover_options/results').glob('cover_option_*.json'))
        + list((root / '_state/阶段2/results').glob('slide_*.json'))
        + list((root / '_state/阶段2/trial_first5/results').glob('slide_*.json'))
    )
    reusable_found: set[int] = set()
    to_accept: list[Path] = []
    for path in records:
        try:
            result = read_json(path)
            slide_index = result['slide_index']
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if slide_index in reusable:
            reusable_found.add(slide_index)
            to_accept.append(path)
        elif not result_is_current(root, result):
            affected.add(slide_index)
    missing_reusable = reusable - reusable_found
    if missing_reusable:
        raise ValidationError('指定复用的页面缺少可核对的图片记录：' + '、'.join(map(str, sorted(missing_reusable))))
    for path in to_accept:
        accept_image_result(root, path, reason)
    state = read_state(root)
    content_path = root / '_state/阶段1/content.json'
    content = read_json(content_path) if content_path.exists() else {}
    cover = next((x['slide_index'] for x in content.get('slides', []) if x.get('page_type') == 'cover'), 1)
    trial_path = root / '_state/阶段2/trial_first5/selection.json'
    trial = set(read_json(trial_path).get('selected_slide_indices', [])) if trial_path.exists() else set()
    if affected:
        if cover in affected:
            state['confirmed']['stage2_cover_style'] = False
        if cover in affected or affected & trial:
            state['confirmed']['stage2_trial_first5'] = False
        state['confirmed']['stage2_image_deck'] = False
        state['quality']['stage2'] = 'needs_revision'
        state['status'] = 'ready_for_stage2_cover_options' if cover in affected else ('trial_first5_revision_requested' if affected & trial else 'ready_for_stage2_remaining_images')
        state['required_actor'] = 'main_controller'
        state['next_required_action'] = '按当前图片风格重新准备受影响页面：' + '、'.join(map(str, sorted(affected)))
    change = {'reason': reason, 'affected_slides': sorted(affected), 'reusable_slides': sorted(reusable), 'recorded_at': now_iso()}
    state.setdefault('image_style_changes', []).append(change)
    write_state(root, state)
    return change
