from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from runtime.musetalk_jobs.api import MuseTalkJobAPI, ResultUnavailable
from runtime.musetalk_jobs.artifacts import ArtifactStore
from runtime.musetalk_jobs.store import JobStore

STATE_ROOT = Path(os.environ.get('EIROS_MUSETALK_STATE_ROOT', '/var/lib/eiros/musetalk-jobs'))

mcp = FastMCP(
    'EIROS MuseTalk Jobs',
    instructions=(
        'Durable private MuseTalk V1.5 render service. Upload one video and one audio file, '
        'then poll job status and download the MP4 when state is done.'
    ),
    stateless_http=True,
    json_response=True,
    host='127.0.0.1',
    port=8794,
)


@dataclass
class ApiContext:
    store: JobStore
    artifacts: ArtifactStore
    api: MuseTalkJobAPI


_CTX: ApiContext | None = None


def _service() -> ApiContext:
    global _CTX
    if _CTX is None:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        store = JobStore(STATE_ROOT / 'jobs.sqlite3')
        artifacts = ArtifactStore(STATE_ROOT / 'artifacts')
        _CTX = ApiContext(store, artifacts, MuseTalkJobAPI(store, artifacts))
    return _CTX


def _reset_for_tests() -> None:
    global _CTX
    _CTX = None


def _safe_suffix(filename: str, fallback: str) -> str:
    suffix = Path(str(filename or '')).suffix.lower()
    if not suffix or len(suffix) > 10 or any(c not in '.abcdefghijklmnopqrstuvwxyz0123456789' for c in suffix):
        return fallback
    return suffix


@mcp.tool(
    name='musetalk_health',
    title='Check MuseTalk job service',
    description='Read durable MuseTalk job API health and active job count.',
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def musetalk_health() -> dict[str, Any]:
    ctx = _service()
    return {'ok': True, 'service': 'eiros-musetalk-jobs', 'active_jobs': len(ctx.store.list_active()), 'time': int(time.time())}


@mcp.tool(
    name='musetalk_job_create',
    title='Create MuseTalk render job',
    description='Upload video and audio bytes and queue one durable MuseTalk V1.5 render job.',
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def musetalk_job_create(video_filename: str, video_file: bytes, audio_filename: str, audio_file: bytes) -> dict[str, Any]:
    ctx = _service()
    incoming = STATE_ROOT / 'incoming'
    incoming.mkdir(parents=True, exist_ok=True)
    video_suffix = _safe_suffix(video_filename, '.mp4')
    audio_suffix = _safe_suffix(audio_filename, '.wav')
    video_path: Path | None = None
    audio_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=incoming, suffix=video_suffix, delete=False) as f:
            f.write(video_file)
            f.flush()
            os.fsync(f.fileno())
            video_path = Path(f.name)
        with tempfile.NamedTemporaryFile(dir=incoming, suffix=audio_suffix, delete=False) as f:
            f.write(audio_file)
            f.flush()
            os.fsync(f.fileno())
            audio_path = Path(f.name)
        return ctx.api.create(video_path, audio_path)
    finally:
        if video_path is not None:
            video_path.unlink(missing_ok=True)
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)


@mcp.tool(
    name='musetalk_job_status',
    title='Read MuseTalk render status',
    description='Read durable state, retries and error details for one render job.',
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def musetalk_job_status(job_id: str) -> dict[str, Any]:
    return _service().api.status(job_id)


@mcp.tool(
    name='musetalk_job_cancel',
    title='Cancel MuseTalk render job',
    description='Mark a non-terminal job cancelled. This does not delete the RunPod or its volume.',
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def musetalk_job_cancel(job_id: str) -> dict[str, Any]:
    return _service().api.cancel(job_id)


@mcp.tool(
    name='musetalk_job_download',
    title='Download MuseTalk result',
    description='Return the rendered MP4 bytes after a job reaches done state.',
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
)
def musetalk_job_download(job_id: str) -> bytes:
    path = _service().api.result(job_id)
    return path.read_bytes()


if __name__ == '__main__':
    transport = os.environ.get('EIROS_MUSETALK_MCP_TRANSPORT', 'stdio').strip() or 'stdio'
    mcp.run(transport=transport)
