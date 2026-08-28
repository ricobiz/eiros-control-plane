from __future__ import annotations

import importlib
from pathlib import Path

from runtime.file_vault import VaultConfig, VaultStore


def load_server(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('EIROS_FILE_VAULT_ROOT', str(tmp_path / 'module-root'))
    monkeypatch.setenv('EIROS_FILE_VAULT_PUBLIC_ORIGIN', 'https://files.example.test')
    monkeypatch.setenv('EIROS_FILE_VAULT_PUBLIC_PREFIX', '/vault')
    import runtime.file_vault_mcp_server as server
    server = importlib.reload(server)
    server.STORE = VaultStore(VaultConfig(root=tmp_path / 'store', reserve_bytes=0, allowed_import_roots=(tmp_path,)))
    return server


def test_direct_mcp_tool_roundtrip(tmp_path: Path, monkeypatch) -> None:
    server = load_server(tmp_path, monkeypatch)
    saved = server.vault_upload('portrait.jpg', b'\xff\xd8vault-test\xff\xd9', ['avatar', 'REF'], 'face')
    file_id = saved['file_id']

    rows = server.vault_list(query='portrait', tag='avatar', limit=20)
    assert rows['files'][0]['file_id'] == file_id

    details = server.vault_get(file_id)
    assert details['file']['file_id'] == file_id
    assert details['internal_path'].endswith(file_id)
    assert server.vault_download(file_id) == b'\xff\xd8vault-test\xff\xd9'

    share = server.vault_share_create(file_id, expires_hours=24, disposition='inline')
    assert share['public_url'].startswith('https://files.example.test/vault/s/')
    assert share['token'] in share['public_url']
    assert server.vault_share_list(file_id)['shares'][0]['share_id'] == share['share']['share_id']

    revoked = server.vault_share_revoke(share['share']['share_id'])
    assert revoked['share']['revoked_at'] is not None


def test_import_verify_mutations_and_delete(tmp_path: Path, monkeypatch) -> None:
    server = load_server(tmp_path, monkeypatch)
    source = tmp_path / 'artifact.bin'
    source.write_bytes(b'artifact')
    item = server.vault_import_path(str(source), display_name='LAM result.bin', tags=['lam'])
    file_id = item['file_id']

    assert server.vault_verify(file_id)['ok'] is True
    assert server.vault_rename(file_id, 'renamed.bin')['display_name'] == 'renamed.bin'
    assert server.vault_set_tags(file_id, ['x', 'X', 'y'])['tags'] == ['x', 'y']
    assert server.vault_set_note(file_id, 'note')['note'] == 'note'
    assert server.vault_delete(file_id)['deleted'] is True


def test_health_does_not_expose_share_tokens(tmp_path: Path, monkeypatch) -> None:
    server = load_server(tmp_path, monkeypatch)
    health = server.vault_health()
    assert health['ok'] is True
    assert health['service'] == 'eiros-file-vault'
    assert health['public_share_base'] == 'https://files.example.test/vault/s'
