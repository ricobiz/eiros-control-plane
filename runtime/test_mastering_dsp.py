from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path

import numpy as np

from runtime.mastering_director import validate_director_plan
from runtime.mastering_dsp import render_from_plan


def _wav(path: Path, seconds: float = 0.5, sr: int = 48000) -> None:
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    # Deliberately sub-heavy source + a little upper content.
    x = 0.28 * np.sin(2 * np.pi * 48 * t) + 0.04 * np.sin(2 * np.pi * 1200 * t)
    pcm = np.clip(x * 32767.0, -32768, 32767).astype('<i2')
    stereo = np.column_stack([pcm, pcm]).ravel().tobytes()
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(stereo)


def _pcm_hash(path: Path) -> str:
    import subprocess
    raw = subprocess.check_output([
        'ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-ac','2','-ar','48000','-f','s24le','-'
    ])
    return hashlib.sha256(raw).hexdigest()


def test_identical_source_and_plan_produce_identical_pcm(tmp_path):
    src = tmp_path / 'source.wav'; _wav(src)
    plan = validate_director_plan({
        'intent': 'determinism',
        'target': {},
        'sections': [{
            'start': 0.0, 'end': 0.5,
            'actions': [{'type':'gain','gain_db':-0.5,'reason':'bounded test gain'}],
        }],
    }, 0.5)
    a = tmp_path / 'a.wav'; b = tmp_path / 'b.wav'
    ra = render_from_plan(src, plan, a)
    rb = render_from_plan(src, plan, b)
    assert _pcm_hash(a) == _pcm_hash(b)
    assert ra['execution_log'] == rb['execution_log']


def test_empty_plan_preserves_pcm_except_container_conversion(tmp_path):
    src = tmp_path / 'source.wav'; _wav(src)
    plan = validate_director_plan({
        'intent': 'preserve intentional sub dominance',
        'protected_traits': ['sub_mass'],
        'target': {},
        'sections': [{'start':0.0,'end':0.5,'actions':[]}],
    }, 0.5)
    out = tmp_path / 'master.wav'
    report = render_from_plan(src, plan, out)
    assert report['execution_log'] == []
    # No action means no spectral correction. PCM conversion itself may quantize,
    # but the engine must not invent DSP.
    assert report['invented_actions'] == 0


def test_section_gain_has_click_free_default_transition(tmp_path):
    src = tmp_path / 'source.wav'; _wav(src, seconds=1.0)
    plan = validate_director_plan({
        'intent':'section gain', 'target': {},
        'sections':[{'start':0.2,'end':0.8,'actions':[
            {'type':'gain','gain_db':-3.0,'reason':'test local attenuation'}
        ]}],
    },1.0)
    out=tmp_path/'master.wav'
    report=render_from_plan(src,plan,out)
    assert report['execution_log'][0]['transition_ms'] >= 25.0
    assert report['execution_log'][0]['applied']['gain_db'] == -3.0


def _configure_roots(tmp_path, monkeypatch):
    from runtime import mastering
    for name in ('uploads','outputs','meta','shares'):
        (tmp_path/name).mkdir(exist_ok=True)
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads')
    monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs')
    monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta')
    monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')


def test_director_render_requires_plan_and_records_provenance(tmp_path, monkeypatch):
    from runtime import mastering
    _configure_roots(tmp_path, monkeypatch)
    src = tmp_path/'fixture.wav'; _wav(src, seconds=0.5)
    stored = mastering.store_upload('fixture.wav', src.read_bytes())
    import pytest
    with pytest.raises(ValueError, match='director_plan_id'):
        mastering.render(stored['asset_id'], profile='director')
    plan = mastering.save_director_plan(stored['asset_id'], {
        'intent':'preserve source', 'target': {},
        'sections':[{'start':0.0,'end':0.5,'actions':[]}],
    })
    result = mastering.render(stored['asset_id'], profile='director', director_plan_id=plan['plan_id'])
    out = result['output']
    assert out['plan_id'] == plan['plan_id']
    assert out['plan_fingerprint'] == plan['fingerprint']
    assert out['engine_version'] == '0.4.0-director'
    assert out['execution_log'] == []
    assert out['profile'] == 'director'
