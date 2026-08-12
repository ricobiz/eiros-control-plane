from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import pytest

from runtime import mastering
from runtime.mastering_metadata import clean_export, inspect_metadata


def _configure(tmp_path, monkeypatch):
    for name in ('uploads','outputs','meta','shares'):
        (tmp_path/name).mkdir(exist_ok=True)
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads')
    monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs')
    monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta')
    monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')


def _bass_wav(seconds=1.0,sr=48000):
    t=np.arange(int(seconds*sr))/sr
    x=.28*np.sin(2*np.pi*48*t)+.035*np.sin(2*np.pi*1100*t)
    # sparse transients on top of intentional sub mass
    x[::2400]+=0.12
    pcm=np.clip(x*32767,-32768,32767).astype('<i2')
    stereo=np.column_stack([pcm,pcm]).ravel().tobytes()
    buf=io.BytesIO()
    with wave.open(buf,'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(stereo)
    return buf.getvalue()


def test_full_director_lifecycle_preserves_intentional_sub_and_clean_exports(tmp_path, monkeypatch):
    _configure(tmp_path,monkeypatch)
    stored=mastering.store_upload('ayibobo-class.wav',_bass_wav())
    analysis=mastering.analyze(stored['asset_id'])['analysis']
    assert analysis['technical']['spectrum']['energy_percent']['sub_20_60']>35

    plan=mastering.save_director_plan(stored['asset_id'],{
        'intent':'heavy ritual bass; preserve intentional sub mass and transients',
        'protected_traits':['sub_mass'],
        'target':{},
        'sections':[{'start':0.0,'end':1.0,'actions':[]}],
    })
    rendered=mastering.render(stored['asset_id'],profile='director',director_plan_id=plan['plan_id'])['output']
    assert rendered['state']=='RENDERED'
    assert rendered['plan_id']==plan['plan_id']
    assert rendered['execution_log']==[]

    verified=mastering.verify_output(stored['asset_id'],rendered['output_id'])
    assert verified['state']=='VERIFIED'
    assert verified['verification']['status']=='PASS'
    assert not any(f['code']=='protected_sub_loss' for f in verified['verification']['flags'])

    approved=mastering.approve_output(stored['asset_id'],rendered['output_id'])['output']
    assert approved['state']=='APPROVED'

    meta=mastering._read_meta(stored['asset_id'])
    item=mastering._find_output(meta,rendered['output_id'])
    clean=tmp_path/'final-clean.wav'
    export=clean_export(Path(item['path']),clean,'wav')
    assert clean.exists()
    assert inspect_metadata(clean)['optional_textual_tags']==[]
    assert export['post_audit']['embedded_art']==[]


def test_bad_director_plan_that_crushes_protected_sub_is_rejected(tmp_path, monkeypatch):
    _configure(tmp_path,monkeypatch)
    stored=mastering.store_upload('bad.wav',_bass_wav())
    mastering.analyze(stored['asset_id'])
    plan=mastering.save_director_plan(stored['asset_id'],{
        'intent':'bad test', 'protected_traits':['sub_mass'], 'target':{},
        'sections':[{'start':0.0,'end':1.0,'actions':[
            {'type':'gain','gain_db':-6.0,'reason':'deliberately destructive regression action'}
        ]}],
    })
    rendered=mastering.render(stored['asset_id'],profile='director',director_plan_id=plan['plan_id'])['output']
    verified=mastering.verify_output(stored['asset_id'],rendered['output_id'])
    assert verified['state']=='REJECTED'
    assert any(f['code']=='protected_sub_loss' for f in verified['verification']['flags'])
    with pytest.raises(ValueError,match='verification PASS'):
        mastering.approve_output(stored['asset_id'],rendered['output_id'])
