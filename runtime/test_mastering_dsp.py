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


def _read_f32(path: Path, sr: int=48000):
    import subprocess
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-ac','2','-ar',str(sr),'-f','f32le','-'])
    return np.frombuffer(raw,dtype='<f4').reshape(-1,2)

def _tone_level(x, sr, hz):
    mono=x.mean(axis=1); n=len(mono); w=np.hanning(n); spec=np.abs(np.fft.rfft(mono*w)); f=np.fft.rfftfreq(n,1/sr)
    i=np.argmin(np.abs(f-hz)); return 20*np.log10(max(spec[i],1e-12))

def test_eq_action_is_frequency_selective(tmp_path):
    sr=48000; t=np.arange(sr,dtype=np.float64)/sr
    x=.12*np.sin(2*np.pi*55*t)+.12*np.sin(2*np.pi*1000*t)
    pcm=np.clip(x*32767,-32768,32767).astype('<i2'); src=tmp_path/'eq.wav'
    with wave.open(str(src),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(np.column_stack([pcm,pcm]).ravel().tobytes())
    plan=validate_director_plan({'intent':'eq','target':{},'sections':[{'start':0,'end':1,'actions':[{'type':'eq','reason':'remove 1k resonance','frequency_hz':1000,'gain_db':-6,'q':1.2}]}]},1)
    out=tmp_path/'eq-out.wav'; render_from_plan(src,plan,out); y=_read_f32(out)
    assert (_tone_level(y,sr,1000)-_tone_level(y,sr,55)) < -4.0

def test_stereo_width_zero_collapses_to_mono(tmp_path):
    sr=48000;t=np.arange(sr,dtype=np.float64)/sr;l=.15*np.sin(2*np.pi*220*t);r=.15*np.sin(2*np.pi*330*t)
    pcm=np.clip(np.column_stack([l,r])*32767,-32768,32767).astype('<i2');src=tmp_path/'st.wav'
    with wave.open(str(src),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(pcm.ravel().tobytes())
    plan=validate_director_plan({'intent':'mono','target':{},'sections':[{'start':0,'end':1,'actions':[{'type':'stereo_width','reason':'mono compatibility','width':0.0}]}]},1)
    out=tmp_path/'st-out.wav';render_from_plan(src,plan,out);y=_read_f32(out)
    # Ignore the intentional 25 ms dry/wet boundary ramps; the body of the section must be mono.
    edge=int(sr*.04)
    assert np.max(np.abs(y[edge:-edge,0]-y[edge:-edge,1])) < 2e-4

def test_compressor_reduces_crest(tmp_path):
    sr=48000;x=np.full(sr,.04);x[::2400]=.8;pcm=np.clip(x*32767,-32768,32767).astype('<i2');src=tmp_path/'c.wav'
    with wave.open(str(src),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(np.column_stack([pcm,pcm]).ravel().tobytes())
    plan=validate_director_plan({'intent':'compress','target':{},'sections':[{'start':0,'end':1,'actions':[{'type':'compressor','reason':'control peaks','threshold_dbfs':-18,'ratio':4,'attack_ms':2,'release_ms':80,'makeup_db':0,'bounds':{'max_gain_reduction_db':12}}]}]},1)
    out=tmp_path/'c-out.wav';render_from_plan(src,plan,out);y=_read_f32(out)[:,0]
    def crest(a):return 20*np.log10(np.max(np.abs(a))/np.sqrt(np.mean(a*a)))
    edge=int(sr*.1)
    assert crest(y[edge:-edge]) < crest(x[edge:-edge])-2

def test_limiter_respects_ceiling(tmp_path):
    src=tmp_path/'lim.wav';_wav(src,seconds=1)
    plan=validate_director_plan({'intent':'limit','target':{},'sections':[{'start':0,'end':1,'actions':[{'type':'limiter','reason':'safety ceiling','ceiling_dbtp':-6,'release_ms':80,'bounds':{'max_gain_reduction_db':12}}]}]},1)
    out=tmp_path/'lim-out.wav';render_from_plan(src,plan,out);y=_read_f32(out)
    peak=20*np.log10(np.max(np.abs(y)))
    assert peak <= -5.8

def test_dynamic_eq_reduces_hot_band_but_preserves_sub(tmp_path):
    sr=48000;t=np.arange(sr,dtype=np.float64)/sr;x=.15*np.sin(2*np.pi*55*t)+.25*np.sin(2*np.pi*900*t);pcm=np.clip(x*32767,-32768,32767).astype('<i2');src=tmp_path/'deq.wav'
    with wave.open(str(src),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(np.column_stack([pcm,pcm]).ravel().tobytes())
    plan=validate_director_plan({'intent':'deq','target':{},'sections':[{'start':0,'end':1,'actions':[{'type':'dynamic_eq','reason':'control hot 900','frequency_hz':900,'q':1.5,'threshold_dbfs':-24,'ratio':3,'max_reduction_db':6}]}]},1)
    out=tmp_path/'deq-out.wav';render_from_plan(src,plan,out);y=_read_f32(out)
    assert (_tone_level(y,sr,900)-_tone_level(y,sr,55)) < (_tone_level(_read_f32(src),sr,900)-_tone_level(_read_f32(src),sr,55))-1.5


def test_transient_action_changes_crest_in_requested_direction(tmp_path):
    sr=48000;x=np.full(sr,.04);x[::2400]=.7;pcm=np.clip(x*32767,-32768,32767).astype('<i2');src=tmp_path/'tr.wav'
    with wave.open(str(src),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(np.column_stack([pcm,pcm]).ravel().tobytes())
    plan=validate_director_plan({'intent':'soften transients','target':{},'sections':[{'start':0,'end':1,'actions':[{'type':'transient','reason':'soften clicks','amount_db':-4}]}]},1)
    out=tmp_path/'tr-out.wav';render_from_plan(src,plan,out);y=_read_f32(out)[:,0];edge=int(sr*.1)
    def crest(a):return 20*np.log10(np.max(np.abs(a))/np.sqrt(np.mean(a*a)))
    assert crest(y[edge:-edge]) < crest(x[edge:-edge])

def test_declipping_repairs_full_scale_plateau(tmp_path):
    sr=48000;t=np.arange(sr)/sr;x=.2*np.sin(2*np.pi*220*t);x[20000:20020]=1.0;pcm=np.clip(x*32767,-32768,32767).astype('<i2');src=tmp_path/'dc.wav'
    with wave.open(str(src),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(np.column_stack([pcm,pcm]).ravel().tobytes())
    plan=validate_director_plan({'intent':'repair','target':{},'sections':[{'start':0,'end':1,'actions':[{'type':'declipping','reason':'repair known clipped plateau','threshold':.995}]}]},1)
    out=tmp_path/'dc-out.wav';rep=render_from_plan(src,plan,out);y=_read_f32(out)
    assert rep['execution_log'][0]['applied']['repaired_samples'] >= 20
    assert np.max(np.abs(y[20000:20020])) < .95

def test_director_target_loudness_is_actually_rendered(tmp_path, monkeypatch):
    from runtime import mastering
    _configure_roots(tmp_path, monkeypatch)
    src=tmp_path/'target.wav';_wav(src,seconds=2.0)
    stored=mastering.store_upload('target.wav',src.read_bytes())
    plan=mastering.save_director_plan(stored['asset_id'],{'intent':'target','target':{'lufs':-16.0,'true_peak_dbtp':-2.0},'sections':[{'start':0,'end':2,'actions':[]}]})
    out=mastering.render(stored['asset_id'],profile='director',director_plan_id=plan['plan_id'])['output']
    assert abs(out['report']['loudness']['integrated_lufs']-(-16.0)) <= .5
    assert out['report']['loudness']['true_peak_dbtp'] <= -1.8
    assert any(a['type']=='target_loudness' for a in out['execution_log'])
