from __future__ import annotations

from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from starlette.responses import PlainTextResponse, Response, StreamingResponse

from .store import VaultStore


def _not_found() -> Response:
    return PlainTextResponse('Share unavailable', status_code=404, headers={'Cache-Control': 'no-store'})


def _range_error(size: int) -> Response:
    return Response(
        status_code=416,
        headers={
            'Content-Range': f'bytes */{size}',
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'private, no-store',
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
        },
    )


def _parse_range(value: str | None, size: int) -> tuple[int, int, bool] | None:
    if not value:
        return 0, max(0, size - 1), False
    if not value.startswith('bytes=') or ',' in value:
        return None
    spec = value[6:].strip()
    if '-' not in spec or size <= 0:
        return None
    left, right = spec.split('-', 1)
    try:
        if left == '':
            suffix = int(right)
            if suffix <= 0:
                return None
            suffix = min(suffix, size)
            return size - suffix, size - 1, True
        start = int(left)
        if start < 0 or start >= size:
            return None
        if right == '':
            end = size - 1
        else:
            end = int(right)
            if end < start:
                return None
            end = min(end, size - 1)
        return start, end, True
    except ValueError:
        return None


def _iter_file(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open('rb') as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def share_response(store: VaultStore, token: str, range_header: str | None = None) -> Response:
    try:
        share, item = store.resolve_share_token(token)
        path = store.object_path(item.file_id)
    except Exception:
        return _not_found()

    size = item.size_bytes
    parsed = _parse_range(range_header, size)
    if parsed is None:
        return _range_error(size)
    start, end, partial = parsed
    length = max(0, end - start + 1)
    disposition = 'attachment' if share.disposition == 'attachment' else 'inline'
    safe_name = quote(item.display_name, safe='')
    headers = {
        'Accept-Ranges': 'bytes',
        'Content-Length': str(length),
        'Content-Disposition': f"{disposition}; filename*=UTF-8''{safe_name}",
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
    }
    status = 206 if partial else 200
    if partial:
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=status,
        media_type=item.media_type,
        headers=headers,
    )
