from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from runtime.file_vault import VaultConfig, VaultStore


def load_server(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('EIROS_FILE_VAULT_ROOT', str(tmp_path/'module-root'))
    monkeypatch.setenv('EIROS_FILE_VAULT_PUBLIC_ORIGIN', 'https://files.example.test')
    monkeypatch.setenv('EIROS_FILE_VAULT_PUBLIC_PREFIX', '/vault')
    monkeypatch.setenv('EIROS_FILE_VAULT_PANEL_PREFIX', '/vault-ui-secret-test')
    import runtime.file_vault_mcp_server as server
    server = importlib.reload(server)
    server.STORE = VaultStore(VaultConfig(root=tmp_path/'store', reserve_bytes=0, allowed_import_roots=(tmp_path,)))
    return server


def panel_client(server):
    app = Starlette(routes=[
        Route('/ui/', server.api_panel, methods=['GET']),
        Route('/ui/api/upload', server.api_upload, methods=['POST','OPTIONS']),
        Route('/ui/api/list', server.api_list, methods=['GET','OPTIONS']),
        Route('/ui/api/share', server.api_share_create, methods=['POST','OPTIONS']),
        Route('/ui/api/share/revoke', server.api_share_revoke, methods=['POST','OPTIONS']),
        Route('/ui/api/download/{file_id}', server.api_download, methods=['GET','OPTIONS']),
        Route('/ui/api/delete', server.api_delete, methods=['POST','OPTIONS']),
    ])
    return TestClient(app)


def test_browser_upload_streams_in_bounded_chunks(tmp_path: Path, monkeypatch) -> None:
    server = load_server(tmp_path, monkeypatch)
    seen: list[int] = []
    real_begin = server.STORE.begin_stream_upload

    def begin(*args, **kwargs):
        session = real_begin(*args, **kwargs)
        real_write = session.write
        def write(data: bytes):
            seen.append(len(data))
            return real_write(data)
        session.write = write
        return session

    monkeypatch.setattr(server.STORE, 'begin_stream_upload', begin)
    data = (b'0123456789abcdef' * 327680)  # 5 MiB
    response = panel_client(server).post(
        '/ui/api/upload',
        files={'file': ('big.bin', data, 'application/octet-stream')},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['size_bytes'] == len(data)
    assert payload['sha256'] == hashlib.sha256(data).hexdigest()
    assert len(seen) > 1
    assert max(seen) <= 1024 * 1024


def test_panel_api_list_share_download_revoke_delete(tmp_path: Path, monkeypatch) -> None:
    server = load_server(tmp_path, monkeypatch)
    client = panel_client(server)
    uploaded = client.post('/ui/api/upload', files={'file': ('photo.jpg', b'photo-data', 'image/jpeg')}).json()
    file_id = uploaded['file_id']

    listed = client.get('/ui/api/list').json()
    assert listed['files'][0]['file_id'] == file_id

    share = client.post('/ui/api/share', json={'file_id': file_id, 'expires_hours': 24}).json()
    assert share['public_url'].startswith('https://files.example.test/vault/s/')

    downloaded = client.get(f'/ui/api/download/{file_id}')
    assert downloaded.status_code == 200
    assert downloaded.content == b'photo-data'

    revoked = client.post('/ui/api/share/revoke', json={'share_id': share['share']['share_id']})
    assert revoked.status_code == 200

    deleted = client.post('/ui/api/delete', json={'file_id': file_id})
    assert deleted.status_code == 200
    assert client.get('/ui/api/list').json()['files'] == []


def test_open_panel_contract_uses_secret_panel_prefix(tmp_path: Path, monkeypatch) -> None:
    server = load_server(tmp_path, monkeypatch)
    result = server.open_file_vault()
    assert result['resource_uri'] == server.PANEL_URI
    assert result['panel_base'] == 'https://files.example.test/vault-ui-secret-test'
    assert result['panel_url'] == 'https://files.example.test/vault-ui-secret-test/'
    direct = panel_client(server).get('/ui/')
    assert direct.status_code == 200
    assert 'EIROS File Vault' in direct.text
    html = server.file_vault_panel_resource()
    assert 'https://files.example.test/vault-ui-secret-test' in html
    assert '<input' in html and 'type="file"' in html
    assert 'cdn.' not in html.lower()
