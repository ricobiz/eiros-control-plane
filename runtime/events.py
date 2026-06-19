from __future__ import annotations

import fcntl, json, os, tempfile, time, uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from runtime.config import RUNTIME_DIR, load_config

EVENT_FILE = RUNTIME_DIR / 'events.json'
LOCK_FILE = RUNTIME_DIR / 'events.lock'
SCHEMA_VERSION = 2

def now() -> int: return int(time.time())
def cfg() -> dict[str, Any]: return load_config()
def channel_name(value: str = '') -> str: return str(value or cfg().get('channel') or 'default').strip()[:120] or 'default'

def empty_store() -> dict[str, Any]:
    return {'schema_version': SCHEMA_VERSION, 'revision': 0, 'next_seq': 1, 'updated_at': now(), 'leaders': {}, 'events': []}

def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parent = path.parent.stat(); uid, gid, mode = parent.st_uid, parent.st_gid, 0o660
    if path.exists():
        current = path.stat(); uid = current.st_uid or uid; gid = current.st_gid or gid; mode = current.st_mode & 0o777 or mode
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        try: os.fchmod(fd, mode); os.fchown(fd, uid, gid)
        except PermissionError: pass
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = int(data.get('schema_version', 1))
    if version > SCHEMA_VERSION: raise RuntimeError(f'Unsupported event schema: {version}')
    data.setdefault('events', []); data.setdefault('next_seq', 1); data.setdefault('revision', 0); data.setdefault('updated_at', now())
    if version == 1:
        leader = data.pop('leader', None); data['leaders'] = {'default': leader} if leader else {}
    data.setdefault('leaders', {})
    for event in data['events']:
        event.setdefault('channel', 'default'); event.setdefault('delivery_attempts', 0); event.setdefault('last_delivery_error', None)
    data['schema_version'] = SCHEMA_VERSION
    return data

def load_store() -> dict[str, Any]:
    if not EVENT_FILE.exists(): return empty_store()
    data = json.loads(EVENT_FILE.read_text(encoding='utf-8'))
    if not isinstance(data, dict): raise RuntimeError('Event store is not an object')
    return migrate(data)

@contextmanager
def locked_store() -> Iterator[dict[str, Any]]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open('a+', encoding='utf-8') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX); store = load_store(); yield store
        store['revision'] = int(store.get('revision', 0)) + 1; store['updated_at'] = now()
        maximum = int(cfg().get('limits', {}).get('max_events', 5000)); store['events'] = store['events'][-maximum:]
        atomic_write(EVENT_FILE, store); fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def read_store() -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open('a+', encoding='utf-8') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH); store = load_store(); fcntl.flock(lock.fileno(), fcntl.LOCK_UN); return store

def emit(text: str, source: str = 'remote', payload: dict[str, Any] | None = None, priority: int = 0,
         idempotency_key: str = '', channel: str = '') -> dict[str, Any]:
    message = str(text or '').strip()
    if not message:
        raise ValueError('Event text is required')
    settings = cfg()
    target = channel_name(channel)
    key = str(idempotency_key or '').strip()[:240]
    message = message[:int(settings.get('limits', {}).get('max_event_text', 20000))]
    with locked_store() as store:
        if key:
            for existing in store['events']:
                if existing.get('idempotency_key') == key and existing.get('channel') == target:
                    return existing
        seq = int(store['next_seq'])
        store['next_seq'] = seq + 1
        event = {
            'id': str(uuid.uuid4()), 'seq': seq, 'channel': target,
            'source': str(source or 'remote')[:120], 'text': message, 'payload': payload or {},
            'priority': max(-1000, min(int(priority), 1000)), 'idempotency_key': key or None,
            'status': 'pending', 'created_at': now(), 'claim': None, 'delivery_attempts': 0,
            'last_delivery_error': None, 'delivered_at': None, 'acked_at': None, 'ack_result': None,
        }
        store['events'].append(event)
        return event

def leader_alive(leader: dict[str, Any] | None, timestamp: int) -> bool:
    return bool(leader and int(leader.get('lease_until', 0)) > timestamp)

def poll(widget_id: str, cursor: int = 0, channel: str = '', instance_id: str = '',
         leader_lease_seconds: int = 25, claim_seconds: int = 45) -> dict[str, Any]:
    identity = str(widget_id or '').strip()[:200]
    if not identity:
        raise ValueError('widget_id is required')
    settings = cfg()
    actual_instance = str(settings.get('instance_id') or '')
    if instance_id and str(instance_id) != actual_instance:
        raise RuntimeError('Pulse instance mismatch')
    target = channel_name(channel)
    timestamp = now()
    with locked_store() as store:
        leaders = store.setdefault('leaders', {})
        leader = leaders.get(target)
        if not leader_alive(leader, timestamp) or leader.get('widget_id') == identity:
            leaders[target] = {
                'widget_id': identity,
                'lease_until': timestamp + max(10, min(int(leader_lease_seconds), 120)),
                'last_seen': timestamp,
            }
        leader = leaders[target]
        is_leader = leader.get('widget_id') == identity
        selected = None
        if is_leader:
            candidates = []
            for event in store['events']:
                if event.get('channel') != target:
                    continue
                if int(event.get('seq', 0)) <= int(cursor) or event.get('status') == 'acked':
                    continue
                claim = event.get('claim') or {}
                claim_alive = int(claim.get('until', 0)) > timestamp
                if claim_alive and claim.get('widget_id') != identity:
                    continue
                candidates.append(event)
            candidates.sort(key=lambda entry: (-int(entry.get('priority', 0)), int(entry.get('seq', 0))))
            if candidates:
                selected = candidates[0]
                selected['status'] = 'claimed'
                selected['delivery_attempts'] = int(selected.get('delivery_attempts', 0)) + 1
                selected['claim'] = {
                    'widget_id': identity, 'channel': target,
                    'until': timestamp + max(15, min(int(claim_seconds), 180)),
                    'claimed_at': timestamp,
                }
        channel_events = [entry for entry in store['events'] if entry.get('channel') == target]
        return {
            'instance_id': actual_instance, 'channel': target, 'leader': is_leader,
            'leader_widget_id': leader.get('widget_id'), 'leader_lease_until': leader.get('lease_until'),
            'event': selected,
            'latest_seq': max([int(entry.get('seq', 0)) for entry in channel_events] or [0]),
            'pending_count': sum(1 for entry in channel_events if entry.get('status') != 'acked'),
            'server_time': timestamp,
        }

def mark_delivered(event_id: str, widget_id: str, channel: str = '') -> dict[str, Any]:
    target = channel_name(channel)
    with locked_store() as store:
        for event in store['events']:
            if event.get('id') != event_id:
                continue
            if event.get('channel') != target:
                raise RuntimeError('Event belongs to another channel')
            claim = event.get('claim') or {}
            if claim.get('widget_id') != widget_id:
                raise RuntimeError('Delivery claim belongs to another widget')
            event['status'] = 'delivered'
            event['delivered_at'] = now()
            event['claim']['until'] = now() + 120
            return event
    raise RuntimeError(f'Event not found: {event_id}')

def acknowledge(event_id: str, result: str = '', actor: str = 'eiros') -> dict[str, Any]:
    with locked_store() as store:
        for event in store['events']:
            if event.get('id') != event_id:
                continue
            event['status'] = 'acked'
            event['acked_at'] = now()
            event['ack_result'] = str(result or '')[:20000]
            event['ack_actor'] = str(actor or 'eiros')[:120]
            event['claim'] = None
            return event
    raise RuntimeError(f'Event not found: {event_id}')

def status(limit: int = 100, channel: str = '') -> dict[str, Any]:
    store = read_store()
    target = channel_name(channel)
    selected = [entry for entry in store['events'] if entry.get('channel') == target]
    return {
        'schema_version': store['schema_version'],
        'revision': store['revision'],
        'updated_at': store['updated_at'],
        'instance_id': cfg().get('instance_id'),
        'channel': target,
        'leader': store.get('leaders', {}).get(target),
        'latest_seq': max([int(entry.get('seq', 0)) for entry in selected] or [0]),
        'pending_count': sum(1 for entry in selected if entry.get('status') != 'acked'),
        'events': selected[-max(1, min(int(limit), 500)):],
    }
