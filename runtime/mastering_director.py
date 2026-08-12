from __future__ import annotations

import copy
import hashlib
import json
import uuid

SUPPORTED_ACTIONS = {
    'gain', 'eq', 'dynamic_eq', 'compressor', 'transient',
    'stereo_width', 'limiter', 'declipping',
}
BOUNDED_ACTIONS = {'compressor', 'limiter'}


def _num(value, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be numeric') from exc


def validate_director_plan(plan: dict, duration_seconds: float) -> dict:
    duration = _num(duration_seconds, 'duration')
    if duration <= 0:
        raise ValueError('duration must be positive')
    if not isinstance(plan, dict):
        raise ValueError('plan must be an object')
    out = copy.deepcopy(plan)
    out['schema_version'] = '0.4'
    out['plan_id'] = str(out.get('plan_id') or uuid.uuid4().hex)
    out['intent'] = str(out.get('intent') or '').strip()
    out['protected_traits'] = sorted({str(x).strip() for x in out.get('protected_traits', []) if str(x).strip()})
    target = dict(out.get('target') or {})
    if 'lufs' in target:
        target['lufs'] = _num(target['lufs'], 'target.lufs')
    if 'true_peak_dbtp' in target:
        target['true_peak_dbtp'] = _num(target['true_peak_dbtp'], 'target.true_peak_dbtp')
    out['target'] = target

    sections = []
    for raw_section in out.get('sections', []):
        section = dict(raw_section)
        start = _num(section.get('start'), 'section.start')
        end = _num(section.get('end'), 'section.end')
        if start < 0 or end <= start or end > duration:
            raise ValueError('section range is outside duration')
        actions = []
        for raw_action in section.get('actions', []):
            action = dict(raw_action)
            kind = str(action.get('type') or '').strip()
            if kind not in SUPPORTED_ACTIONS:
                raise ValueError(f'unsupported action type: {kind}')
            if not str(action.get('reason') or '').strip():
                raise ValueError('every action requires reason')
            action['type'] = kind
            action['reason'] = str(action['reason']).strip()
            action['action_id'] = str(action.get('action_id') or uuid.uuid4().hex)
            action['start'] = _num(action.get('start', start), 'action.start')
            action['end'] = _num(action.get('end', end), 'action.end')
            if action['start'] < start or action['end'] > end or action['end'] <= action['start'] or action['end'] > duration:
                raise ValueError('action range is outside section or duration')
            if kind in BOUNDED_ACTIONS and not isinstance(action.get('bounds'), dict):
                raise ValueError(f'{kind} action requires bounds')
            if 'bounds' in action and not isinstance(action['bounds'], dict):
                raise ValueError('bounds must be an object')
            actions.append(action)
        section['start'], section['end'], section['actions'] = start, end, actions
        sections.append(section)
    sections.sort(key=lambda s: (s['start'], s['end']))
    for prev, cur in zip(sections, sections[1:]):
        if cur['start'] < prev['end']:
            raise ValueError('sections overlap')
    out['sections'] = sections
    return out


def plan_fingerprint(plan: dict) -> str:
    stable = copy.deepcopy(plan)
    stable.pop('plan_id', None)
    for section in stable.get('sections', []):
        for action in section.get('actions', []):
            action.pop('action_id', None)
    payload = json.dumps(stable, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
