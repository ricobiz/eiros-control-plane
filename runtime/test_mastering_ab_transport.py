from pathlib import Path
import io
import wave
import numpy as np

from runtime import mastering


def wav_bytes(freq=55.0, amp=.2, seconds=.7, sr=48000):
    t=np.arange(int(seconds*sr))/sr
    x=(amp*np.sin(2*np.pi*freq*t)).astype(np.float32)
    pcm=np.clip(x*32767,-32768,32767).astype('<i2')
    stereo=np.column_stack([pcm,pcm]).ravel().tobytes()
    b=io.BytesIO()
    with wave.open(b,'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(stereo)
    return b.getvalue()


def roots(tmp_path, monkeypatch):
    for n in ('uploads','outputs','meta','shares'):(tmp_path/n).mkdir()
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads')
    monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs')
    monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta')
    monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')


def test_ab_metadata_has_matched_timebase_and_loudness_gains(tmp_path, monkeypatch):
    roots(tmp_path,monkeypatch)
    stored=mastering.store_upload('a.wav',wav_bytes())
    out=mastering.render(stored['asset_id'],profile='none',target_lufs=-12.0)['output']
    ab=mastering.ab_comparison(stored['asset_id'],out['output_id'])
    p=ab['preview']
    assert p['timebase_match'] is True
    assert abs(p['source_duration_seconds']-p['master_duration_seconds']) < .02
    assert -12.0 <= p['source_gain_db'] <= 0.0
    assert -12.0 <= p['master_gain_db'] <= 0.0
    assert p['level_match_method']=='attenuate_to_quieter_integrated_lufs'


def test_delta_preview_is_real_difference_signal(tmp_path, monkeypatch):
    roots(tmp_path,monkeypatch)
    stored=mastering.store_upload('a.wav',wav_bytes())
    out=mastering.render(stored['asset_id'],profile='none',target_lufs=-12.0)['output']
    info=mastering.ensure_delta_preview(stored['asset_id'],out['output_id'])
    assert Path(info['path']).is_file()
    assert info['difference_signal'] is True
    assert info['sample_rate']==48000
    assert abs(info['duration_seconds']-.7) < .03
    assert info['metadata_stripped'] is True
