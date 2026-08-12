from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

DISCLAIMER = 'No claim is made that proprietary acoustic watermarks were detected or removed.'
_TEXT_KEYS = {'title','artist','album','comment','description','genre','date','track','copyright','composer','lyrics','language','publisher'}
_ENCODER_KEYS = {'encoder','encoded_by','encoding_tool','software','application','isft','tool'}


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd,text=True,capture_output=True,timeout=timeout,check=False)


def _entries(tags: dict[str, Any] | None, scope: str) -> tuple[list[dict],list[dict],list[dict]]:
    text=[]; encoder=[]; unknown=[]
    for key,value in (tags or {}).items():
        lk=str(key).lower()
        entry={'scope':scope,'key':str(key),'value':str(value)}
        if lk in _ENCODER_KEYS or 'encoder' in lk or 'software' in lk:
            encoder.append(entry)
        elif lk in _TEXT_KEYS:
            text.append(entry)
        else:
            unknown.append(entry)
    return text,encoder,unknown


def inspect_metadata(path: Path) -> dict[str, Any]:
    path=Path(path)
    proc=_run([
        'ffprobe','-v','error','-show_streams','-show_format','-show_chapters','-of','json',str(path)
    ],60)
    if proc.returncode!=0:
        raise RuntimeError((proc.stderr or proc.stdout)[-1800:])
    raw=json.loads(proc.stdout or '{}')
    streams=raw.get('streams') or []
    audio=next((s for s in streams if s.get('codec_type')=='audio'),{})
    structural={
        'format':(raw.get('format') or {}).get('format_name') or '',
        'codec':audio.get('codec_name') or '',
        'sample_rate':int(audio.get('sample_rate') or 0),
        'channels':int(audio.get('channels') or 0),
        'channel_layout':audio.get('channel_layout') or '',
        'bits_per_sample':int(audio.get('bits_per_sample') or audio.get('bits_per_raw_sample') or 0),
        'duration_seconds':float((raw.get('format') or {}).get('duration') or 0.0),
    }
    textual=[]; encoders=[]; unknown=[]
    t,e,u=_entries((raw.get('format') or {}).get('tags'),'format'); textual+=t; encoders+=e; unknown+=u
    for idx,stream in enumerate(streams):
        t,e,u=_entries(stream.get('tags'),f'stream:{idx}'); textual+=t; encoders+=e; unknown+=u
    art=[]
    for idx,stream in enumerate(streams):
        disposition=stream.get('disposition') or {}
        if stream.get('codec_type')=='video' and int(disposition.get('attached_pic') or 0)==1:
            art.append({'stream_index':idx,'codec':stream.get('codec_name'),'tags':stream.get('tags') or {}})
    chapters=[]
    for ch in raw.get('chapters') or []:
        chapters.append({'id':ch.get('id'),'start_time':ch.get('start_time'),'end_time':ch.get('end_time'),'tags':ch.get('tags') or {}})
    return {
        'structural':structural,
        'optional_textual_tags':textual,
        'embedded_art':art,
        'chapters':chapters,
        'encoder_identifying_fields':encoders,
        'unknown_fields':unknown,
    }


def clean_export(source_master: Path, destination: Path, format: str='wav') -> dict[str, Any]:
    source_master=Path(source_master); destination=Path(destination)
    fmt=str(format or '').lower().strip()
    if fmt not in {'wav','mp3'}:
        raise ValueError('clean export format must be wav or mp3')
    before=inspect_metadata(source_master)
    destination.parent.mkdir(parents=True,exist_ok=True)
    cmd=[
        'ffmpeg','-y','-v','error','-i',str(source_master),'-map','0:a:0','-vn','-sn','-dn',
        '-map_metadata','-1','-map_chapters','-1','-fflags','+bitexact','-flags:a','+bitexact',
        '-ar','48000','-ac','2',
    ]
    if fmt=='wav':
        cmd += ['-write_bext','0','-c:a','pcm_s24le',str(destination)]
    else:
        cmd += ['-c:a','libmp3lame','-b:a','320k','-id3v2_version','0','-write_id3v1','0',str(destination)]
    proc=_run(cmd,900)
    if proc.returncode!=0:
        destination.unlink(missing_ok=True)
        raise RuntimeError((proc.stderr or proc.stdout)[-1800:])
    after=inspect_metadata(destination)
    removed=[]
    for cat in ('optional_textual_tags','embedded_art','chapters','encoder_identifying_fields','unknown_fields'):
        if before.get(cat): removed.extend([{'category':cat,'value':x} for x in before[cat]])
    return {
        'format':fmt,
        'destination':str(destination),
        'removed_fields':removed,
        'retained_structural_fields':after['structural'],
        'post_audit':after,
        'disclaimer':DISCLAIMER,
    }
