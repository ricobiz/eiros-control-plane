from __future__ import annotations

import wave
from pathlib import Path
import numpy as np
import pytest

from runtime.mastering_verify import build_delta_report, verify_master


def _write(path: Path, left: np.ndarray, right: np.ndarray | None = None, sr: int = 48000):
    if right is None: right = left
    x = np.column_stack([left,right])
    pcm=np.clip(x*32767,-32768,32767).astype('<i2').ravel().tobytes()
    with wave.open(str(path),'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(pcm)


def _tone(seconds=1.0, amp=.2, freq=50, sr=48000):
    t=np.arange(int(seconds*sr))/sr
    return amp*np.sin(2*np.pi*freq*t)


def _plan(**kw):
    p={'intent':'qa','target':{'true_peak_dbtp':-1.0},'protected_traits':[],
       'sections':[{'start':0.0,'end':1.0,'actions':[]}]}
    p.update(kw); return p


def test_clean_master_passes(tmp_path):
    src=tmp_path/'s.wav'; mast=tmp_path/'m.wav'; x=_tone()
    _write(src,x); _write(mast,x*.95)
    result=verify_master(src,mast,_plan())
    assert result['status']=='PASS'


def test_true_peak_violation_rejected(tmp_path):
    src=tmp_path/'s.wav'; mast=tmp_path/'m.wav'; x=_tone(amp=.2)
    _write(src,x); _write(mast,_tone(amp=.9))
    result=verify_master(src,mast,_plan(target={'true_peak_dbtp':-3.0}))
    assert result['status']=='REJECTED'
    assert any(f['code']=='true_peak_violation' for f in result['flags'])


def test_protected_sub_loss_rejected(tmp_path):
    sr=48000; t=np.arange(sr)/sr
    srcx=.3*np.sin(2*np.pi*48*t)+.03*np.sin(2*np.pi*1200*t)
    mastx=.08*np.sin(2*np.pi*48*t)+.03*np.sin(2*np.pi*1200*t)
    src=tmp_path/'s.wav'; mast=tmp_path/'m.wav'; _write(src,srcx); _write(mast,mastx)
    result=verify_master(src,mast,_plan(protected_traits=['sub_mass'], target={}))
    assert result['status']=='REJECTED'
    assert any(f['code']=='protected_sub_loss' for f in result['flags'])


def test_stereo_correlation_collapse_is_flagged(tmp_path):
    sr=48000; t=np.arange(sr)/sr
    x=.2*np.sin(2*np.pi*220*t)
    y=.2*np.sin(2*np.pi*331*t)
    src=tmp_path/'s.wav'; mast=tmp_path/'m.wav'; _write(src,x,x); _write(mast,x,y)
    result=verify_master(src,mast,_plan(target={}))
    assert result['status'] in {'REVIEW','REJECTED'}
    assert any(f['code']=='stereo_correlation_collapse' for f in result['flags'])


def test_crest_collapse_is_flagged(tmp_path):
    sr=48000; t=np.arange(sr)/sr
    # source has sparse impulses; master is dense/limited-like
    srcx=np.zeros(sr); srcx[::2400]=.8
    mastx=np.full(sr,.2)
    src=tmp_path/'s.wav'; mast=tmp_path/'m.wav'; _write(src,srcx); _write(mast,mastx)
    result=verify_master(src,mast,_plan(target={}))
    assert result['status'] in {'REVIEW','REJECTED'}
    assert any(f['code']=='crest_collapse' for f in result['flags'])


def test_delta_report_uses_identical_plan_windows(tmp_path):
    x=_tone(); src=tmp_path/'s.wav'; mast=tmp_path/'m.wav'; _write(src,x); _write(mast,x*.9)
    report=build_delta_report(src,mast,_plan())
    assert len(report['sections'])==1
    assert report['sections'][0]['start']==0.0
    assert report['sections'][0]['end']==1.0


def _configure_roots(tmp_path, monkeypatch):
    from runtime import mastering
    for name in ('uploads','outputs','meta','shares'):
        (tmp_path/name).mkdir(exist_ok=True)
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads')
    monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs')
    monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta')
    monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')


def test_output_cannot_be_approved_before_pass_verification(tmp_path, monkeypatch):
    from runtime import mastering
    _configure_roots(tmp_path, monkeypatch)
    x=_tone(amp=.2); src=tmp_path/'source.wav'; _write(src,x)
    stored=mastering.store_upload('source.wav',src.read_bytes())
    plan=mastering.save_director_plan(stored['asset_id'],{
        'intent':'preserve','target':{},'sections':[{'start':0.0,'end':1.0,'actions':[]}]
    })
    rendered=mastering.render(stored['asset_id'],profile='director',director_plan_id=plan['plan_id'])['output']
    with pytest.raises(ValueError,match='verification'):
        mastering.approve_output(stored['asset_id'],rendered['output_id'])
    verified=mastering.verify_output(stored['asset_id'],rendered['output_id'])
    assert verified['verification']['status']=='PASS'
    approved=mastering.approve_output(stored['asset_id'],rendered['output_id'])
    assert approved['output']['state']=='APPROVED'
