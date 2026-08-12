from pathlib import Path
import hashlib
import io
import wave
import numpy as np

from runtime import mastering


def wav_bytes(seconds: float = 1.0, sr: int = 48000) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    x = (0.2 * np.sin(2 * np.pi * 55 * t)).astype(np.float32)
    pcm = np.clip(x * 32767.0, -32768, 32767).astype('<i2')
    stereo = np.column_stack([pcm, pcm]).ravel().tobytes()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(stereo)
    return buf.getvalue()


def configure_roots(tmp_path, monkeypatch):
    upload = tmp_path / 'uploads'
    output = tmp_path / 'outputs'
    meta = tmp_path / 'meta'
    shares = tmp_path / 'shares'
    for path in (upload, output, meta, shares):
        path.mkdir()
    monkeypatch.setattr(mastering, 'UPLOAD_ROOT', upload)
    monkeypatch.setattr(mastering, 'OUTPUT_ROOT', output)
    monkeypatch.setattr(mastering, 'META_ROOT', meta)
    monkeypatch.setattr(mastering, 'SHARE_ROOT', shares)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_render_never_mutates_uploaded_source(tmp_path, monkeypatch):
    configure_roots(tmp_path, monkeypatch)
    stored = mastering.store_upload('fixture.wav', wav_bytes())
    meta = mastering._read_meta(stored['asset_id'])
    source = mastering._input_path(meta)
    before = sha256(source)
    mastering.render(stored['asset_id'], profile='adaptive', target_lufs=-14.0)
    assert sha256(source) == before


def test_each_render_has_unique_output_id(tmp_path, monkeypatch):
    configure_roots(tmp_path, monkeypatch)
    stored = mastering.store_upload('fixture.wav', wav_bytes())
    a = mastering.render(stored['asset_id'], profile='adaptive', target_lufs=-14.0)
    b = mastering.render(stored['asset_id'], profile='adaptive', target_lufs=-14.0)
    assert a['output']['output_id'] != b['output']['output_id']


import pytest

@pytest.mark.xfail(reason='Director plan API arrives in Task 2', strict=True)
def test_director_protected_sub_mass_does_not_auto_cut():
    # v0.4 contract: intentional spectral dominance is evidence, not a defect.
    plan = mastering.create_director_plan(
        analysis={'bands': {'20_60': 0.49}},
        intent={'protected_traits': ['sub_mass']},
    )
    assert not any(
        a.get('type') in {'eq', 'dynamic_eq'} and a.get('band') == '20_60' and a.get('gain_db', 0) < 0
        for a in plan['actions']
    )
