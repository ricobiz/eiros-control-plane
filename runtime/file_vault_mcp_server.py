from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import Response

from runtime.file_vault import VaultConfig, VaultStore
from runtime.file_vault.http import share_response

ROOT = Path(os.environ.get('EIROS_FILE_VAULT_ROOT', '/var/lib/eiros/file-vault'))
PORT = int(os.environ.get('EIROS_FILE_VAULT_PORT', '8797'))
MAX_UPLOAD_BYTES = int(os.environ.get('EIROS_FILE_VAULT_MAX_UPLOAD_BYTES', str(2 * 1024**3)))
RESERVE_BYTES = int(os.environ.get('EIROS_FILE_VAULT_RESERVE_BYTES', str(2 * 1024**3)))
PUBLIC_ORIGIN = os.environ.get('EIROS_FILE_VAULT_PUBLIC_ORIGIN', 'https://ebridge-ui.178-105-43-79.sslip.io').rstrip('/')
PUBLIC_PREFIX = '/' + os.environ.get('EIROS_FILE_VAULT_PUBLIC_PREFIX', '/vault').strip('/')
PUBLIC_SHARE_BASE = f'{PUBLIC_ORIGIN}{PUBLIC_PREFIX}/s'

STORE = VaultStore(
    VaultConfig(
        root=ROOT,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        reserve_bytes=RESERVE_BYTES,
    )
)

mcp = FastMCP(
    'EIROS File Vault',
    instructions=(
        'Persistent private file vault for EIROS. Store arbitrary files without modification. '
        'Private files persist until explicitly deleted. Public links are temporary, unguessable, '
        'passwordless URLs and do not delete the private file when they expire.'
    ),
    stateless_http=True,
    json_response=True,
    host='127.0.0.1',
    port=PORT,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            '127.0.0.1', '127.0.0.1:*', 'localhost', 'localhost:*',
            'eiros.br-be.com', 'eiros.br-be.com:*',
        ],
        allowed_origins=[
            'http://127.0.0.1', 'http://127.0.0.1:*',
            'http://localhost', 'http://localhost:*',
            'http://eiros.br-be.com', 'https://eiros.br-be.com',
            'https://chatgpt.com', 'https://chat.openai.com', 'https://platform.openai.com',
        ],
    ),
)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
WRITE_IDEMPOTENT = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True, idempotentHint=True)
SHARE_CREATE = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False, idempotentHint=False)
SHARE_REVOKE = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True, idempotentHint=True)


def _file_dict(file_id: str) -> dict[str, Any]:
    return STORE.get(file_id).as_dict()


@mcp.tool(name='vault_health', title='Check EIROS File Vault', description='Use this when you need storage health, capacity, and file counts.', annotations=READ, structured_output=True)
def vault_health() -> dict[str, Any]:
    result = dict(STORE.health())
    result.update({
        'service': 'eiros-file-vault',
        'time': int(time.time()),
        'public_share_base': PUBLIC_SHARE_BASE,
    })
    return result


@mcp.tool(name='vault_upload', title='Store a file', description='Use this when you need to store arbitrary binary file bytes permanently in the private EIROS vault.', annotations=WRITE, structured_output=True)
def vault_upload(filename: str, file_bytes: bytes, tags: list[str] | None = None, note: str = '') -> dict[str, Any]:
    return STORE.store_bytes(filename, file_bytes, source='mcp_upload', tags=tags or (), note=note).as_dict()


@mcp.tool(name='vault_import_path', title='Import a VPS file', description='Use this when a file already exists under an allowed EIROS VPS root and should be copied into the permanent vault.', annotations=WRITE, structured_output=True)
def vault_import_path(path: str, display_name: str | None = None, tags: list[str] | None = None, note: str = '') -> dict[str, Any]:
    return STORE.import_path(path, display_name=display_name, tags=tags or (), note=note).as_dict()


@mcp.tool(name='vault_list', title='List or search vault files', description='Use this when you need to find private files by name, note, text fragment, or exact tag.', annotations=READ, structured_output=True)
def vault_list(query: str = '', tag: str = '', limit: int = 50) -> dict[str, Any]:
    return {'ok': True, 'files': [item.as_dict() for item in STORE.list(query=query, tag=tag, limit=limit)]}


@mcp.tool(name='vault_get', title='Get vault file metadata', description='Use this when you need private metadata and the internal VPS path for one stored file.', annotations=READ, structured_output=True)
def vault_get(file_id: str) -> dict[str, Any]:
    item = STORE.get(file_id)
    return {'ok': True, 'file': item.as_dict(), 'internal_path': str(STORE.object_path(file_id))}


@mcp.tool(name='vault_verify', title='Verify vault file integrity', description='Use this when you need to recompute size and SHA-256 for a stored file.', annotations=READ, structured_output=True)
def vault_verify(file_id: str) -> dict[str, Any]:
    return STORE.verify(file_id)


@mcp.tool(name='vault_download', title='Download vault file', description='Use this when you need the exact original bytes of one private vault file.', annotations=READ)
def vault_download(file_id: str) -> bytes:
    return STORE.read_bytes(file_id)


@mcp.tool(name='vault_rename', title='Rename vault file', description='Use this when you want to change only the display name without changing stored bytes.', annotations=WRITE_IDEMPOTENT, structured_output=True)
def vault_rename(file_id: str, display_name: str) -> dict[str, Any]:
    return STORE.rename(file_id, display_name).as_dict()


@mcp.tool(name='vault_set_tags', title='Set vault file tags', description='Use this when you want to replace the normalized tags on one private file.', annotations=WRITE_IDEMPOTENT, structured_output=True)
def vault_set_tags(file_id: str, tags: list[str]) -> dict[str, Any]:
    return STORE.set_tags(file_id, tags).as_dict()


@mcp.tool(name='vault_set_note', title='Set vault file note', description='Use this when you want to replace the private note attached to one vault file.', annotations=WRITE_IDEMPOTENT, structured_output=True)
def vault_set_note(file_id: str, note: str) -> dict[str, Any]:
    return STORE.set_note(file_id, note).as_dict()


@mcp.tool(name='vault_share_create', title='Create temporary public file link', description='Use this when a private vault file should be viewable or downloadable externally by anyone who has the secret URL until it expires.', annotations=SHARE_CREATE, structured_output=True)
def vault_share_create(file_id: str, expires_hours: float = 24.0, disposition: str = 'inline') -> dict[str, Any]:
    seconds = int(float(expires_hours) * 3600)
    share, token = STORE.create_share(file_id, expires_seconds=seconds, disposition=disposition)
    return {
        'ok': True,
        'share': share.as_dict(),
        'token': token,
        'public_url': f'{PUBLIC_SHARE_BASE}/{token}',
    }


@mcp.tool(name='vault_share_list', title='List file share records', description='Use this when you need expiry, revoke, and access state for links created for one file. Raw secret tokens are not stored.', annotations=READ, structured_output=True)
def vault_share_list(file_id: str) -> dict[str, Any]:
    return {'ok': True, 'file_id': STORE.get(file_id).file_id, 'shares': [s.as_dict() for s in STORE.list_shares(file_id)]}


@mcp.tool(name='vault_share_revoke', title='Revoke public file link', description='Use this when one existing public share link must stop working immediately.', annotations=SHARE_REVOKE, structured_output=True)
def vault_share_revoke(share_id: str) -> dict[str, Any]:
    return {'ok': True, 'share': STORE.revoke_share(share_id).as_dict()}


@mcp.tool(name='vault_delete', title='Delete private vault file', description='Use this only when the stored file and all its share records should be permanently deleted.', annotations=DESTRUCTIVE, structured_output=True)
def vault_delete(file_id: str) -> dict[str, Any]:
    return STORE.delete(file_id)


@mcp.custom_route('/s/{token}', methods=['GET'])
async def public_share(request: Request) -> Response:
    return share_response(STORE, str(request.path_params.get('token') or ''), request.headers.get('range'))


# The ChatGPT connector broker may qualify tool names with the connector namespace.
def _register_alias(name: str, fn, *, title: str, description: str, annotations: ToolAnnotations, structured_output: bool = True) -> None:
    mcp.tool(
        name=f'filevault.{name}',
        title=title,
        description=f'Compatibility alias. {description}',
        annotations=annotations,
        structured_output=structured_output,
    )(fn)


_register_alias('vault_health', vault_health, title='Check EIROS File Vault', description='Read storage health.', annotations=READ)
_register_alias('vault_upload', vault_upload, title='Store a file', description='Store arbitrary binary bytes.', annotations=WRITE)
_register_alias('vault_import_path', vault_import_path, title='Import a VPS file', description='Copy an allowed VPS file into the vault.', annotations=WRITE)
_register_alias('vault_list', vault_list, title='List vault files', description='Search private vault metadata.', annotations=READ)
_register_alias('vault_get', vault_get, title='Get vault file', description='Read private file metadata.', annotations=READ)
_register_alias('vault_verify', vault_verify, title='Verify vault file', description='Recompute integrity metadata.', annotations=READ)
_register_alias('vault_download', vault_download, title='Download vault file', description='Return exact stored bytes.', annotations=READ, structured_output=False)
_register_alias('vault_rename', vault_rename, title='Rename vault file', description='Change display name.', annotations=WRITE_IDEMPOTENT)
_register_alias('vault_set_tags', vault_set_tags, title='Set vault tags', description='Replace normalized tags.', annotations=WRITE_IDEMPOTENT)
_register_alias('vault_set_note', vault_set_note, title='Set vault note', description='Replace private note.', annotations=WRITE_IDEMPOTENT)
_register_alias('vault_share_create', vault_share_create, title='Create public link', description='Create an expiring passwordless share.', annotations=SHARE_CREATE)
_register_alias('vault_share_list', vault_share_list, title='List public links', description='Read share metadata.', annotations=READ)
_register_alias('vault_share_revoke', vault_share_revoke, title='Revoke public link', description='Disable a share immediately.', annotations=SHARE_REVOKE)
_register_alias('vault_delete', vault_delete, title='Delete vault file', description='Permanently delete one private file.', annotations=DESTRUCTIVE)


if __name__ == '__main__':
    mcp.run(transport='streamable-http')
