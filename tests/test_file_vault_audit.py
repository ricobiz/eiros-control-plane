from __future__ import annotations

import json
from pathlib import Path

from runtime.file_vault import VaultConfig, VaultStore
from runtime.file_vault.audit import AuditLogger


def make_store(tmp_path: Path) -> VaultStore:
    return VaultStore(VaultConfig(root=tmp_path/'vault', reserve_bytes=0, allowed_import_roots=(tmp_path,)))


def read_events(store: VaultStore) -> list[dict]:
    path = store.audit.path
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_audit_records_mutations_without_secrets_or_contents(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    item = store.store_bytes('secret.txt', b'TOP-SECRET-CONTENT', tags=['private'])
    store.rename(item.file_id, 'renamed.txt')
    store.set_tags(item.file_id, ['x'])
    store.set_note(item.file_id, 'memo')
    share, token = store.create_share(item.file_id, expires_seconds=3600)
    store.resolve_share_token(token)
    store.revoke_share(share.share_id)
    store.delete(item.file_id)

    events = read_events(store)
    names = [event['event'] for event in events]
    assert {'file_store','file_rename','file_tags','file_note','share_create','share_access','share_revoke','file_delete'} <= set(names)
    serialized = '\n'.join(json.dumps(e, sort_keys=True) for e in events)
    assert token not in serialized
    assert 'TOP-SECRET-CONTENT' not in serialized
    assert all('ip' not in event for event in events)


def test_audit_failure_does_not_rollback_successful_store(tmp_path: Path, monkeypatch) -> None:
    store = make_store(tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError('disk log fail')

    monkeypatch.setattr(store.audit, '_append', boom)
    item = store.store_bytes('still.bin', b'works')
    assert store.read_bytes(item.file_id) == b'works'
