from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from runtime.file_vault import VaultConfig, VaultStore


def make_store(tmp_path: Path) -> VaultStore:
    return VaultStore(VaultConfig(root=tmp_path / 'vault', reserve_bytes=0, allowed_import_roots=(tmp_path,)))


def test_metadata_mutation_does_not_touch_object(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    item = store.store_bytes('orig.bin', b'payload', tags=['one'], note='old')
    path = store.object_path(item.file_id)
    before = path.stat().st_mtime_ns

    renamed = store.rename(item.file_id, ' renamed.bin ')
    tagged = store.set_tags(item.file_id, [' Two ', 'two', 'ONE'])
    noted = store.set_note(item.file_id, 'x' * 5000)

    assert renamed.display_name == 'renamed.bin'
    assert tagged.tags == ('one', 'two')
    assert len(noted.note) == 4000
    assert store.read_bytes(item.file_id) == b'payload'
    assert store.get(item.file_id).sha256 == item.sha256
    assert path.stat().st_mtime_ns == before


def test_share_token_is_hashed_reusable_and_private_file_survives_expiry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1_800_000_000
    monkeypatch.setattr('runtime.file_vault.store.time.time', lambda: now)
    store = make_store(tmp_path)
    item = store.store_bytes('video.mp4', b'abcdef')

    share, token = store.create_share(item.file_id, expires_seconds=86400, disposition='inline')
    assert len(token) >= 40
    assert share.expires_at == now + 86400
    assert share.access_count == 0

    with sqlite3.connect(store.db_path) as db:
        row = db.execute('SELECT token_hash FROM shares WHERE share_id=?', (share.share_id,)).fetchone()
    assert row[0] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row[0]

    resolved1, file1 = store.resolve_share_token(token)
    resolved2, file2 = store.resolve_share_token(token)
    assert file1.file_id == file2.file_id == item.file_id
    assert resolved2.access_count == 2

    monkeypatch.setattr('runtime.file_vault.store.time.time', lambda: now + 86401)
    with pytest.raises(FileNotFoundError):
        store.resolve_share_token(token)
    assert store.read_bytes(item.file_id) == b'abcdef'


def test_share_revoke_and_validation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    item = store.store_bytes('x.bin', b'x')

    with pytest.raises(ValueError, match='expiry'):
        store.create_share(item.file_id, expires_seconds=299)
    with pytest.raises(ValueError, match='expiry'):
        store.create_share(item.file_id, expires_seconds=2_592_001)
    with pytest.raises(ValueError, match='disposition'):
        store.create_share(item.file_id, disposition='evil')

    share, token = store.create_share(item.file_id, expires_seconds=3600, disposition='attachment')
    listed = store.list_shares(item.file_id)
    assert [x.share_id for x in listed] == [share.share_id]
    assert listed[0].token_hash == ''

    revoked = store.revoke_share(share.share_id)
    assert revoked.revoked_at is not None
    with pytest.raises(FileNotFoundError):
        store.resolve_share_token(token)
    assert store.read_bytes(item.file_id) == b'x'


def test_unknown_share_is_not_distinguishable(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(FileNotFoundError, match='Share unavailable'):
        store.resolve_share_token('not-a-real-token')
