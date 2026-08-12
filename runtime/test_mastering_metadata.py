from __future__ import annotations

import subprocess
from pathlib import Path

from runtime.mastering_metadata import clean_export, inspect_metadata


def _run(cmd):
    p=subprocess.run(cmd,capture_output=True,text=True,check=False)
    assert p.returncode==0, p.stderr


def _tagged_wav(path: Path):
    _run([
        'ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=220:duration=0.4',
        '-metadata','title=Secret Title','-metadata','comment=left-side-tag',
        '-metadata','artist=Test Artist','-metadata','encoder=BadEncoder 9.9',
        '-ar','48000','-ac','2','-c:a','pcm_s16le',str(path)
    ])


def test_inspect_metadata_lists_optional_tags_and_structural_fields(tmp_path):
    src=tmp_path/'tagged.wav'; _tagged_wav(src)
    audit=inspect_metadata(src)
    assert audit['structural']['sample_rate']==48000
    assert audit['structural']['channels']==2
    keys={x['key'].lower() for x in audit['optional_textual_tags']}
    assert 'title' in keys
    assert 'comment' in keys
    assert 'artist' in keys
    assert audit['encoder_identifying_fields']


def test_clean_export_removes_optional_metadata_without_mutating_source(tmp_path):
    src=tmp_path/'tagged.wav'; dst=tmp_path/'clean.wav'; _tagged_wav(src)
    before=src.read_bytes()
    report=clean_export(src,dst,'wav')
    assert src.read_bytes()==before
    assert dst.exists()
    after=inspect_metadata(dst)
    assert after['optional_textual_tags']==[]
    assert after['embedded_art']==[]
    assert after['chapters']==[]
    assert after['structural']['sample_rate']==48000
    assert after['structural']['channels']==2
    assert report['removed_fields']
    assert 'proprietary acoustic watermarks' in report['disclaimer']


def test_clean_export_mp3_has_no_optional_tags(tmp_path):
    src=tmp_path/'tagged.wav'; dst=tmp_path/'clean.mp3'; _tagged_wav(src)
    report=clean_export(src,dst,'mp3')
    after=inspect_metadata(dst)
    assert after['optional_textual_tags']==[]
    assert after['embedded_art']==[]
    assert dst.stat().st_size>0
    assert report['format']=='mp3'


def _configure_roots(tmp_path, monkeypatch):
    from runtime import mastering
    for name in ('uploads','outputs','meta','shares'):
        (tmp_path/name).mkdir(exist_ok=True)
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads')
    monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs')
    monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta')
    monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')


def test_asset_metadata_audit_is_persisted(tmp_path, monkeypatch):
    from runtime import mastering
    _configure_roots(tmp_path, monkeypatch)
    src=tmp_path/'tagged.wav'; _tagged_wav(src)
    stored=mastering.store_upload('tagged.wav',src.read_bytes())
    result=mastering.audit_asset_metadata(stored['asset_id'])
    assert result['audit']['optional_textual_tags']
    meta=mastering._read_meta(stored['asset_id'])
    assert meta['metadata_audit']['optional_textual_tags']
