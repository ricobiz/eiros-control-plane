from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from runtime.file_vault import VaultConfig, VaultStore
from runtime.file_vault.http import share_response


def make_client(tmp_path: Path):
    store = VaultStore(VaultConfig(root=tmp_path/'vault', reserve_bytes=0, allowed_import_roots=(tmp_path,)))
    data = bytes(range(256)) * 16
    item = store.store_bytes('clip.mp4', data)
    share, token = store.create_share(item.file_id, expires_seconds=3600, disposition='inline')

    async def handle(request: Request):
        return share_response(store, request.path_params['token'], request.headers.get('range'))

    app = Starlette(routes=[Route('/s/{token}', handle, methods=['GET'])])
    return TestClient(app), store, token, share.share_id, data


def test_full_and_partial_range_delivery(tmp_path: Path) -> None:
    client, _store, token, _share_id, data = make_client(tmp_path)
    full = client.get(f'/s/{token}')
    assert full.status_code == 200
    assert full.content == data
    assert full.headers['content-type'].startswith('video/mp4')
    assert full.headers['accept-ranges'] == 'bytes'
    assert 'inline' in full.headers['content-disposition']

    part = client.get(f'/s/{token}', headers={'Range':'bytes=0-1023'})
    assert part.status_code == 206
    assert part.content == data[:1024]
    assert part.headers['content-range'] == 'bytes 0-1023/4096'
    assert part.headers['content-length'] == '1024'

    suffix = client.get(f'/s/{token}', headers={'Range':'bytes=-100'})
    assert suffix.status_code == 206
    assert suffix.content == data[-100:]
    assert suffix.headers['content-range'] == 'bytes 3996-4095/4096'


def test_invalid_range_is_416(tmp_path: Path) -> None:
    client, _store, token, _share_id, _data = make_client(tmp_path)
    for header in ('bytes=9000-9100', 'bytes=1-2,4-5', 'items=0-1'):
        response = client.get(f'/s/{token}', headers={'Range': header})
        assert response.status_code == 416
        assert response.headers['content-range'] == 'bytes */4096'


def test_revoked_share_returns_404_without_file_metadata(tmp_path: Path) -> None:
    client, store, token, share_id, _data = make_client(tmp_path)
    store.revoke_share(share_id)
    response = client.get(f'/s/{token}')
    assert response.status_code == 404
    body = response.text.lower()
    assert 'clip.mp4' not in body
    assert 'file_id' not in body
