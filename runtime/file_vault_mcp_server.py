from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from runtime.file_vault import VaultConfig, VaultStore
from runtime.file_vault.http import share_response

ROOT = Path(os.environ.get('EIROS_FILE_VAULT_ROOT', '/var/lib/eiros/file-vault'))
PORT = int(os.environ.get('EIROS_FILE_VAULT_PORT', '8797'))
MAX_UPLOAD_BYTES = int(os.environ.get('EIROS_FILE_VAULT_MAX_UPLOAD_BYTES', str(2 * 1024**3)))
RESERVE_BYTES = int(os.environ.get('EIROS_FILE_VAULT_RESERVE_BYTES', str(2 * 1024**3)))
PUBLIC_ORIGIN = os.environ.get('EIROS_FILE_VAULT_PUBLIC_ORIGIN', 'https://ebridge-ui.178-105-43-79.sslip.io').rstrip('/')
PUBLIC_PREFIX = '/' + os.environ.get('EIROS_FILE_VAULT_PUBLIC_PREFIX', '/vault').strip('/')
PUBLIC_SHARE_BASE = f'{PUBLIC_ORIGIN}{PUBLIC_PREFIX}/s'
PANEL_PREFIX = '/' + os.environ.get('EIROS_FILE_VAULT_PANEL_PREFIX', '/vault-ui-local').strip('/')
PANEL_BASE = f'{PUBLIC_ORIGIN}{PANEL_PREFIX}'
PANEL_URI = 'ui://eiros/file-vault-v1.html'

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


PANEL_META: dict[str, Any] = {
    'ui': {
        'prefersBorder': True,
        'domain': PUBLIC_ORIGIN,
        'csp': {
            'connectDomains': [PUBLIC_ORIGIN],
            'resourceDomains': [PUBLIC_ORIGIN],
        },
    },
    'openai/widgetDescription': 'Private EIROS file vault: upload, find, download and create temporary external links.',
    'openai/widgetDomain': PUBLIC_ORIGIN,
    'openai/widgetCSP': {
        'connect_domains': [PUBLIC_ORIGIN],
        'resource_domains': [PUBLIC_ORIGIN],
    },
}


def _panel_html() -> str:
    template = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<style>
:root{color-scheme:dark;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}*{box-sizing:border-box}body{margin:0;background:#090b10;color:#eef2f7}main{padding:14px;display:grid;gap:12px}.card{border:1px solid #29313d;border-radius:16px;background:#10141b;padding:14px}h1,h2{margin:0 0 10px}h1{font-size:18px}h2{font-size:14px}.muted,.status{color:#8e99a8;font-size:11px;line-height:1.45}.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px}input,button{font:inherit}input[type=file],input[type=text]{width:100%;border:1px solid #343e4d;border-radius:10px;background:#090c11;color:#eef2f7;padding:10px}button,a.btn{border:1px solid #4b596d;border-radius:9px;background:#17202b;color:#eef2f7;padding:9px 11px;text-decoration:none;font-size:11px;font-weight:700}button.primary{background:#edf1f6;color:#0a0d11;border-color:#edf1f6}.item{margin-top:8px;padding:11px;border:1px solid #28313d;border-radius:12px;background:#0b0f15}.name{font-weight:800;word-break:break-word}.meta{margin-top:4px;color:#798596;font-size:10px}.share{margin-top:7px;word-break:break-all;color:#9ab7df;font-size:10px}.danger{border-color:#633944!important;color:#f08b97!important}.hidden{display:none}.bar{height:4px;margin-top:8px;background:#232a34;border-radius:9px;overflow:hidden}.bar>span{display:block;height:100%;width:0;background:#dfe7f0}
</style></head><body><main>
<section class="card"><h1>EIROS File Vault</h1><div class="muted">Private permanent storage · external links are temporary.</div><input id="file" type="file"><div class="row"><button id="upload" class="primary">Загрузить</button><button id="refresh">Обновить</button></div><div class="bar"><span id="bar"></span></div><div id="uploadStatus" class="status">Выбери любой файл.</div></section>
<section class="card"><h2>Файлы</h2><input id="search" type="text" placeholder="Поиск по имени / заметке / тегу"><div id="list" class="status">Загрузка…</div></section>
</main><script>
(()=>{const BASE='__PANEL_BASE__';const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const fmt=n=>n>=1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.round(n/1024))+' KB';async function req(path,opt={}){const r=await fetch(BASE+path,opt);const d=(r.headers.get('content-type')||'').includes('json')?await r.json():await r.text();if(!r.ok)throw new Error(d.error||d||('HTTP '+r.status));return d}async function load(){try{const q=encodeURIComponent($('search').value||'');const d=await req('/api/list?query='+q);$('list').innerHTML=(d.files||[]).map(f=>'<div class="item" data-id="'+esc(f.file_id)+'"><div class="name">'+esc(f.display_name)+'</div><div class="meta">'+esc(f.media_type)+' · '+fmt(f.size_bytes)+' · '+esc((f.tags||[]).join(', '))+' · SHA '+esc(f.sha256.slice(0,12))+'</div><div class="row"><a class="btn" href="'+BASE+'/api/download/'+encodeURIComponent(f.file_id)+'" target="_blank">Скачать</a><button data-share>Ссылка 24ч</button><button class="danger" data-delete>Удалить</button></div><div class="share" data-share-zone></div></div>').join('')||'Хранилище пустое.';bind()}catch(e){$('list').textContent='Ошибка: '+e.message}}function bind(){$('list').querySelectorAll('.item').forEach(card=>{const id=card.dataset.id;card.querySelector('[data-share]').onclick=async()=>{const z=card.querySelector('[data-share-zone]');try{const d=await req('/api/share',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_id:id,expires_hours:24})});z.innerHTML='<a class="btn" href="'+esc(d.public_url)+'" target="_blank">Открыть ссылку</a> <button data-copy>Копировать</button> <button class="danger" data-revoke>Отозвать</button><div>'+esc(d.public_url)+'</div>';z.querySelector('[data-copy]').onclick=()=>navigator.clipboard?.writeText(d.public_url);z.querySelector('[data-revoke]').onclick=async()=>{await req('/api/share/revoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({share_id:d.share.share_id})});z.textContent='Ссылка отозвана.'}}catch(e){z.textContent='Ошибка: '+e.message}};card.querySelector('[data-delete]').onclick=async ev=>{const b=ev.currentTarget;if(b.dataset.armed!=='1'){b.dataset.armed='1';b.textContent='Подтвердить';setTimeout(()=>{b.dataset.armed='';b.textContent='Удалить'},5000);return}await req('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_id:id})});load()}})}$('upload').onclick=async()=>{const f=$('file').files[0];if(!f)return;$('upload').disabled=true;$('uploadStatus').textContent='Загрузка '+f.name+'…';try{const form=new FormData();form.append('file',f,f.name);const d=await req('/api/upload',{method:'POST',body:form});$('bar').style.width='100%';$('uploadStatus').textContent='Сохранено: '+d.file_id+' · '+d.sha256.slice(0,12);await load()}catch(e){$('uploadStatus').textContent='Ошибка: '+e.message}finally{$('upload').disabled=false}};$('refresh').onclick=load;$('search').oninput=()=>{clearTimeout(window._vt);window._vt=setTimeout(load,250)};load()})();
</script></body></html>"""
    return template.replace('__PANEL_BASE__', PANEL_BASE)


@mcp.resource(
    PANEL_URI,
    name='EIROS File Vault Panel',
    title='EIROS File Vault',
    description='Private browser upload and file library panel.',
    mime_type='text/html;profile=mcp-app',
    meta=PANEL_META,
)
def file_vault_panel_resource() -> str:
    return _panel_html()


@mcp.tool(
    name='open_file_vault',
    title='Open EIROS File Vault',
    description='Use this when a browser file picker is the reliable way to upload a local device file into the private EIROS vault.',
    annotations=READ,
    meta={
        'ui': {'resourceUri': PANEL_URI, 'visibility': ['model', 'app']},
        'openai/outputTemplate': PANEL_URI,
        'openai/toolInvocation/invoking': 'Opening EIROS File Vault…',
        'openai/toolInvocation/invoked': 'EIROS File Vault opened.',
    },
    structured_output=True,
)
def open_file_vault() -> dict[str, Any]:
    return {
        'ok': True,
        'resource_uri': PANEL_URI,
        'panel_base': PANEL_BASE,
        'max_upload_bytes': MAX_UPLOAD_BYTES,
    }


def _cors(response: Response) -> Response:
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Range'
    response.headers['Cache-Control'] = 'no-store'
    return response


def _options() -> Response:
    return _cors(Response(status_code=204))


def _json_error(exc: Exception, status: int = 400) -> Response:
    return _cors(JSONResponse({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}, status_code=status))


async def _read_json(request: Request) -> dict[str, Any]:
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError('JSON object required')
    return body


@mcp.custom_route('/ui/api/upload', methods=['POST', 'OPTIONS'])
async def api_upload(request: Request) -> Response:
    if request.method == 'OPTIONS':
        return _options()
    session = None
    try:
        async with request.form(max_files=1, max_fields=8, max_part_size=MAX_UPLOAD_BYTES) as form:
            upload = form.get('file')
            if upload is None or not hasattr(upload, 'read'):
                raise ValueError("multipart field 'file' is required")
            filename = str(getattr(upload, 'filename', '') or 'file.bin')
            session = STORE.begin_stream_upload(filename, source='browser_upload')
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                session.write(chunk)
            item = session.finish()
            session = None
        return _cors(JSONResponse(item.as_dict()))
    except Exception as exc:
        if session is not None:
            session.abort()
        return _json_error(exc)


@mcp.custom_route('/ui/api/list', methods=['GET', 'OPTIONS'])
async def api_list(request: Request) -> Response:
    if request.method == 'OPTIONS':
        return _options()
    try:
        query = str(request.query_params.get('query') or '')
        tag = str(request.query_params.get('tag') or '')
        limit = int(request.query_params.get('limit') or 50)
        return _cors(JSONResponse(vault_list(query, tag, limit)))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route('/ui/api/share', methods=['POST', 'OPTIONS'])
async def api_share_create(request: Request) -> Response:
    if request.method == 'OPTIONS':
        return _options()
    try:
        body = await _read_json(request)
        result = vault_share_create(
            str(body.get('file_id') or ''),
            float(body.get('expires_hours', 24.0)),
            str(body.get('disposition') or 'inline'),
        )
        return _cors(JSONResponse(result))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route('/ui/api/share/revoke', methods=['POST', 'OPTIONS'])
async def api_share_revoke(request: Request) -> Response:
    if request.method == 'OPTIONS':
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(vault_share_revoke(str(body.get('share_id') or ''))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route('/ui/api/download/{file_id}', methods=['GET', 'OPTIONS'])
async def api_download(request: Request) -> Response:
    if request.method == 'OPTIONS':
        return _options()
    try:
        file_id = str(request.path_params.get('file_id') or '')
        item = STORE.get(file_id)
        response = FileResponse(
            path=str(STORE.object_path(file_id)),
            media_type=item.media_type,
            filename=item.display_name,
            content_disposition_type='attachment',
        )
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return _cors(response)
    except Exception as exc:
        return _json_error(exc, 404)


@mcp.custom_route('/ui/api/delete', methods=['POST', 'OPTIONS'])
async def api_delete(request: Request) -> Response:
    if request.method == 'OPTIONS':
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(STORE.delete(str(body.get('file_id') or ''))))
    except Exception as exc:
        return _json_error(exc, 404)


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


_register_alias('open_file_vault', open_file_vault, title='Open EIROS File Vault', description='Open private browser upload panel.', annotations=READ)
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
