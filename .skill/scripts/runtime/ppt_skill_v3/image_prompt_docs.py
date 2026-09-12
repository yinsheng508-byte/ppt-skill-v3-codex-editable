"""Exact prompt ledger and rebuildable human-facing document for both image routes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .image_style import STYLE_RELPATH, ensure_image_style_doc, load_image_style
from .json_io import read_json
from .ppt_consistency import CONSISTENCY_RELPATH
from .time_utils import now_iso
from .validation import ValidationError

PROMPTS_RELPATH = '阶段2_图片版PPT/图片生成提示词.md'
HISTORY_RELPATH = '_state/阶段2/prompt_history/history.json'  # legacy read only
LEDGER_RELPATH = '_state/阶段2/prompt_history/requests'
_LOCK = threading.RLock()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(text, encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


@contextmanager
def _ledger_lock(root: Path, lock_name: str = '.lock'):
    with _LOCK:
        lock = root / '_state/阶段2/prompt_history' / lock_name
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def apply_image_style(run_dir: str | Path, packet: dict[str, Any]) -> None:
    from .image_style import image_style_snapshot, generation_basis
    from .image_prompt_plan import load_prompt_sources
    option_id = packet.get('option_id') if packet.get('purpose') == 'cover_option' else None
    role = load_prompt_sources(run_dir, packet['slide_index'], option_id=option_id)['sources']['page_role']
    snapshot = image_style_snapshot(run_dir, packet['slide_index'], role, normalize_roles=True)
    packet['image_style_path'] = STYLE_RELPATH
    packet['image_style_snapshot'] = snapshot
    packet['image_style_hash'] = snapshot['hash']
    packet['generation_basis'] = generation_basis(run_dir, packet['slide_index'], version='2', kind='cover_option' if packet.get('purpose') == 'cover_option' else 'full_slide', option_id=packet.get('option_id'))
    from .image_prompt_plan import PROMPT_FORMAT_VERSION
    packet['prompt_format_version'] = PROMPT_FORMAT_VERSION
    packet['prompt_hash'] = 'sha256:' + hashlib.sha256(packet['prompt'].encode()).hexdigest()


def require_current_image_style(run_dir: str | Path, packet: dict[str, Any]) -> None:
    from .image_style import packet_matches_current
    if not packet_matches_current(run_dir, packet):
        raise ValidationError('PPT一致性、图片风格或本页规划已变化，请重新派发后再生图')


def _entry_id(packet: dict[str, Any]) -> str:
    if packet.get('generation_request_id'):
        return str(packet['generation_request_id'])
    fields = [packet.get(k) for k in ('packet_id', 'prompt', 'created_at', 'image_generation_route')]
    return 'legacy-' + hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()[:32]


def prepare_image_request(run_dir: str | Path, packet_path: str | Path, packet: dict[str, Any], *, submitted: bool = True) -> tuple[Path, dict[str, Any]]:
    """One immutable packet per actual attempt. A planned entry may be used once."""
    with _ledger_lock(Path(run_dir), '.prepare.lock'):
        return _prepare_image_request(run_dir, packet_path, packet, submitted=submitted)


def _prepare_image_request(run_dir: str | Path, packet_path: str | Path, packet: dict[str, Any], *, submitted: bool) -> tuple[Path, dict[str, Any]]:
    root = Path(run_dir)
    from .image_prompt_plan import validate_packet_prompt
    validate_packet_prompt(root, packet)
    snapshot = deepcopy(packet)
    entry_path = root / LEDGER_RELPATH / (_entry_id(packet) + '.json')
    planned = read_json(entry_path) if entry_path.exists() else {}
    if not snapshot.get('generation_request_id') or (submitted and planned.get('status') != '待生成'):
        snapshot['generation_request_id'] = uuid.uuid4().hex
    reference_snapshots = []
    for ref in snapshot.get('image_style_snapshot', {}).get('references', []):
        source_ref = root / ref['path']
        digest = 'sha256:' + hashlib.sha256(source_ref.read_bytes()).hexdigest()
        if digest != ref['sha256']:
            raise ValidationError('请求准备期间参考图发生变化，请重新派发')
        target_ref = root / '_state/阶段2/prompt_history/reference_images' / (digest.removeprefix('sha256:') + source_ref.suffix)
        target_ref.parent.mkdir(parents=True, exist_ok=True)
        if not target_ref.exists():
            shutil.copy2(source_ref, target_ref)
        reference_snapshots.append({**ref, 'archived_path': target_ref.relative_to(root).as_posix()})
    if reference_snapshots:
        snapshot['reference_snapshots'] = reference_snapshots
    # Freeze the actual local edit inputs, not just style reference provenance.
    # The endpoint and the built-in prepare output both use these archived paths.
    input_key = 'image_gen_input' if snapshot.get('image_generation_route') == 'codex_image_gen' else 'image_api_input'
    request_input = snapshot.get(input_key, {})
    if input_key == 'image_gen_input' or request_input.get('endpoint') == '/v1/images/edits':
        inputs = request_input.get('referenced_image_paths', [])
        archived_inputs = []
        previous = {x['archived_path']: x for x in snapshot.get('input_image_snapshots', [])}
        for value in inputs:
            source_image = root / value
            data = source_image.read_bytes()
            digest = 'sha256:' + hashlib.sha256(data).hexdigest()
            old = previous.get(value)
            if old and digest != old['sha256']:
                raise ValidationError('已冻结的图片输入发生变化，不能提交')
            target_image = root / '_state/阶段2/prompt_history/input_images' / (digest.removeprefix('sha256:') + source_image.suffix)
            target_image.parent.mkdir(parents=True, exist_ok=True)
            if not target_image.exists():
                target_image.write_bytes(data)
            elif hashlib.sha256(target_image.read_bytes()).hexdigest() != digest.removeprefix('sha256:'):
                raise ValidationError('图片输入存档损坏，不能提交')
            archived_inputs.append({'original_path': old['original_path'] if old else value,
                                    'archived_path': target_image.relative_to(root).as_posix(), 'sha256': digest})
        if archived_inputs:
            snapshot['input_image_snapshots'] = archived_inputs
            request_input['referenced_image_paths'] = [x['archived_path'] for x in archived_inputs]
    source = Path(packet_path)
    snapshot.setdefault('original_packet_path', str(source.relative_to(root)) if source.is_absolute() and source.is_relative_to(root) else str(source))
    path = root / '_state/阶段2/prompt_history/packets' / (snapshot['generation_request_id'] + '.json')
    if not path.exists():
        atomic_json(path, snapshot)
    elif read_json(path) != snapshot:
        raise ValidationError('请求快照不可覆盖，请准备新的生成请求')
    record_prompt_document(root, snapshot, status='生成中' if submitted else '待生成')
    return path, snapshot


def record_prompt_document(run_dir: str | Path, packet: dict[str, Any], *, result: dict[str, Any] | None = None, status: str | None = None) -> Path:
    root = Path(run_dir)
    if packet.get('stage') != 'stage2':
        return root / PROMPTS_RELPATH
    with _ledger_lock(root):
        entry_id = _entry_id(packet)
        path = root / LEDGER_RELPATH / (entry_id + '.json')
        entry = read_json(path) if path.exists() else {
            'id': entry_id, 'packet_id': packet.get('packet_id'), 'prompt': packet['prompt'],
            'prompt_hash': packet.get('prompt_hash'), 'purpose': packet.get('purpose', 'full_slide'),
            'slide_index': packet.get('slide_index'), 'option_id': packet.get('option_id'),
            'title': packet.get('title', ''), 'created_at': now_iso(), 'status': '待生成',
            'image_style_snapshot': packet.get('image_style_snapshot'), 'reference_snapshots': packet.get('reference_snapshots', []), 'results': [],
        }
        if entry['prompt'] != packet['prompt']:
            raise ValidationError('请求记录与实际提示词不一致，不能覆盖旧请求')
        if status:
            entry['status'] = status
        if result:
            identity = '|'.join(str(result.get(k) or '') for k in ('tool_call_id', 'api_call_id', 'generation_id', 'image_sha256'))
            result_key = hashlib.sha256(identity.encode()).hexdigest()[:32]
            if not any(x.get('key') == result_key for x in entry['results']):
                image = root / result.get('source_image_snapshot', result['image_path'])
                archive = root / '_state/阶段2/prompt_history/images' / (result_key + image.suffix)
                archive.parent.mkdir(parents=True, exist_ok=True)
                if not archive.exists():
                    shutil.copy2(image, archive)
                entry['results'].append({'key': result_key, 'image_path': result['image_path'], 'image_sha256': result['image_sha256'], 'archived_image': archive.relative_to(root).as_posix(), 'fixture': bool(result.get('fixture')), 'result_path': result.get('result_path'), 'recorded_at': now_iso()})
            entry['status'] = '测试图片，非正式生图' if result.get('fixture') else ('旧风格请求已返回，仅保留历史记录' if result.get('stale_for_current_style') else '生成成功，确认状态以项目说明为准')
        atomic_json(path, entry)
        _render_document(root, _read_entries(root))
    return root / PROMPTS_RELPATH


def _read_entries(root: Path) -> list[dict[str, Any]]:
    entries = [read_json(p) for p in sorted((root / LEDGER_RELPATH).glob('*.json'))]
    legacy = root / HISTORY_RELPATH
    if legacy.exists():
        for i, old in enumerate(read_json(legacy).get('entries', [])):
            identity = old.get('identity', [])
            if any(x['prompt'] == old.get('prompt') and x.get('packet_id') == (identity[0] if identity else None) for x in entries):
                continue
            entries.append({**old, 'id': f'old-{i}', 'packet_id': identity[0] if identity else None})
    return sorted(entries, key=lambda x: (x.get('created_at', ''), x.get('id', '')))


def _image_link(root: Path, item: dict[str, Any]) -> str:
    current = root / item['image_path']
    actual = 'sha256:' + hashlib.sha256(current.read_bytes()).hexdigest() if current.is_file() else None
    if actual == item.get('image_sha256') and current.is_relative_to(root / '阶段2_图片版PPT'):
        return current.relative_to(root / '阶段2_图片版PPT').as_posix()
    old = root / item['archived_image']
    if not old.is_file():
        raise ValidationError('历史图片缺失，无法恢复提示词对应关系')
    attachment = root / '阶段2_图片版PPT/提示词附件' / old.name
    attachment.parent.mkdir(parents=True, exist_ok=True)
    if not attachment.exists():
        shutil.copy2(old, attachment)
    return attachment.relative_to(root / '阶段2_图片版PPT').as_posix()


def _render_document(root: Path, entries: list[dict[str, Any]]) -> None:
    visible_entries = [entry for entry in entries if entry.get('results')]
    lines = ['# 图片生成提示词', '', '这里保留已成功生成图片时实际使用的完整提示词与对应图片，按生成过程持续更新。图片成功不代表用户已确认。', '']
    if (root / CONSISTENCY_RELPATH).exists():
        lines.extend(['[查看PPT一致性](<../阶段1_规划确认/PPT一致性.md>)', ''])
    if (root / STYLE_RELPATH).exists():
        lines.extend(['[查看图片风格](<../阶段1_规划确认/图片风格.md>)', ''])
    formal = {}
    for p in sorted((root / '_state/阶段2/results').glob('slide_*.json')):
        value = read_json(p)
        formal[value['slide_index']] = value
    selected_cover = next((r.get('selected_cover_option') for r in formal.values() if r.get('promoted_from_cover_option')), None)
    if formal:
        lines.extend(['## 当前全套页面索引', '', '| 页面 | 当前图片 | 对应生成记录 |', '| --- | --- | --- |'])
        for index, result in sorted(formal.items()):
            match = next((e for e in reversed(visible_entries) if e.get('id') == result.get('generation_request_id')), None)
            if match is None and not result.get('generation_request_id'):
                candidates = [e for e in visible_entries if e.get('slide_index') == index and any(r.get('image_sha256') == result.get('image_sha256') for r in e['results'])]
                match = candidates[0] if len(candidates) == 1 else None
            image_link = _stage2_visible_link(root, result.get('image_path', ''))
            image_cell = f"[查看图片](<{image_link}>)" if image_link else "图片待核对"
            prompt_cell = f"[查看提示词](#记录-{match['id']})" if match else '历史来源待核对'
            lines.append(f"| 第{index:02d}页 | {image_cell} | {prompt_cell} |")
        lines.append('')
    for entry in visible_entries:
        page = '封面候选' + str(entry['option_id']) if entry.get('option_id') else f"第{entry['slide_index']:02d}页"
        lines.extend([f"<a id=\"记录-{entry['id']}\"></a>", f"## {page}｜{entry.get('title', '')}", '', '状态：' + entry.get('status', '待生成'), ''])
        if selected_cover and entry.get('option_id') == selected_cover:
            lines.extend(['此候选已选为当前封面。', ''])
        for ref in entry.get('reference_snapshots', []):
            archived = root / ref['archived_path']
            attachment = root / '阶段2_图片版PPT/提示词附件/reference_images' / archived.name
            attachment.parent.mkdir(parents=True, exist_ok=True)
            if archived.is_file() and not attachment.exists():
                shutil.copy2(archived, attachment)
            path = os.path.relpath(attachment, root / '阶段2_图片版PPT')
            note = str(ref['use']).strip().rstrip('。；; ')
            lines.extend([f"参考图：[查看图片](<{Path(path).as_posix()}>)；{note}。", ''])
        for item in entry.get('results', []):
            lines.extend([f"![{page}](<{_image_link(root, item)}>)", ''])
        runs = re.findall(r'`+', entry['prompt'])
        fence = '`' * max(3, max((len(x) + 1 for x in runs), default=3))
        lines.extend(['### 使用的提示词', '', fence + 'text', entry['prompt'], fence, ''])
    atomic_text(root / PROMPTS_RELPATH, '\n'.join(lines))


def _stage2_visible_link(root: Path, relpath: str) -> str:
    if not isinstance(relpath, str) or not relpath:
        return ''
    path = root / relpath
    try:
        return path.resolve().relative_to((root / '阶段2_图片版PPT').resolve()).as_posix()
    except ValueError:
        return ''


def rebuild_prompt_document(run_dir: str | Path) -> Path:
    root = Path(run_dir)
    for receipt in sorted((root / '_state/阶段2/prompt_history/result_receipts').glob('*.json')):
        result = read_json(receipt)
        path = root / result['packet_path']
        if path.is_file():
            record_prompt_document(root, read_json(path), result=result)
    with _ledger_lock(root):
        _render_document(root, _read_entries(root))
    return root / PROMPTS_RELPATH


def export_prompt_document(run_dir: str | Path, output_dir: str | Path) -> Path:
    root, dest = Path(run_dir).resolve(), Path(output_dir)
    source = rebuild_prompt_document(root)
    text = source.read_text(encoding='utf-8')
    dest.mkdir(parents=True, exist_ok=True)
    def copy_link(match):
        link = match.group(1)
        if link.startswith('#') or '://' in link:
            return match.group(0)
        path = (source.parent / link).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValidationError('提示词交付附件缺失或不在项目内：' + link)
        relative = path.relative_to(source.parent) if path.is_relative_to(source.parent) else Path('参考附件') / path.name
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() != path:
            shutil.copy2(path, target)
        return '](<' + relative.as_posix() + '>)'
    text = re.sub(r'\]\(<([^>]+)>\)', copy_link, text)
    target = dest / '图片生成提示词.md'
    atomic_text(target, text)
    return target


def refresh_prompt_delivery(run_dir: str | Path) -> Path:
    from .state import read_state, write_state
    root = Path(run_dir)
    path = rebuild_prompt_document(root)
    state = read_state(root)
    state.setdefault('user_artifacts', {})['stage2_image_prompts'] = PROMPTS_RELPATH
    write_state(root, state)
    return path
