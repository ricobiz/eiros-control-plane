from __future__ import annotations

import copy
import json
from pathlib import Path

from runtime import mastering_memory as mm


def _fp(sub=48.0, crest=12.0, corr=.85, tags=None, protected=None):
    return {
        'spectral_distribution': {'sub_20_60': sub, 'bass_60_120': 22.0, 'low_mid_120_500': 18.0},
        'crest_db': crest, 'lra_lu': 6.0, 'stereo_correlation': corr,
        'dominant_frequency_hz': 48.0,
        'section_shape': {'rising': 4, 'falling': 2, 'stable': 8},
        'intent_tags': tags or ['ritual','cinematic'],
        'protected_traits': protected or ['sub_mass'],
    }


def test_record_and_find_similar_is_advisory_only(tmp_path, monkeypatch):
    path=tmp_path/'memory.jsonl'; monkeypatch.setattr(mm,'MEMORY_PATH',path)
    plan={'protected_traits':['sub_mass'],'target':{'lufs':-10.8},'sections':[]}
    before=copy.deepcopy(plan)
    rec=mm.record_experience({
        'fingerprint':_fp(), 'artistic_intent':'preserve huge ritual sub',
        'plan_summary':plan, 'verification':'PASS','rico_feedback':'approved','approval_state':'APPROVED'
    })
    hits=mm.find_similar_experiences(_fp(),limit=3)
    assert plan==before
    assert hits[0]['record_id']==rec['record_id']
    assert hits[0]['score']>0.8
    assert 'protected sub_mass' in hits[0]['reasons']
    assert hits[0]['prior_decision']['target']['lufs']==-10.8


def test_persistence_is_append_only_jsonl(tmp_path, monkeypatch):
    path=tmp_path/'memory.jsonl'; monkeypatch.setattr(mm,'MEMORY_PATH',path)
    a=mm.record_experience({'fingerprint':_fp(tags=['a']),'plan_summary':{},'verification':'PASS'})
    b=mm.record_experience({'fingerprint':_fp(tags=['b']),'plan_summary':{},'verification':'REVIEW'})
    rows=[json.loads(x) for x in path.read_text().splitlines()]
    assert [r['record_id'] for r in rows]==[a['record_id'],b['record_id']]
    assert a['record_id']!=b['record_id']


def test_similarity_prefers_matching_audio_and_intent(tmp_path, monkeypatch):
    path=tmp_path/'memory.jsonl'; monkeypatch.setattr(mm,'MEMORY_PATH',path)
    mm.record_experience({'fingerprint':_fp(tags=['ritual','cinematic']),'plan_summary':{'name':'good'},'verification':'PASS'})
    mm.record_experience({'fingerprint':_fp(sub=5,crest=5,corr=.2,tags=['bright','pop'],protected=[]),'plan_summary':{'name':'other'},'verification':'PASS'})
    hits=mm.find_similar_experiences(_fp(),limit=2)
    assert hits[0]['prior_decision']['name']=='good'
    assert hits[0]['score']>hits[1]['score']


def test_raw_pcm_is_rejected_from_memory(tmp_path, monkeypatch):
    path=tmp_path/'memory.jsonl'; monkeypatch.setattr(mm,'MEMORY_PATH',path)
    import pytest
    with pytest.raises(ValueError,match='raw audio'):
        mm.record_experience({'fingerprint':_fp(),'raw_pcm':'AAAA'})


def test_mastering_wrapper_returns_advisory_hits_without_rendering(tmp_path, monkeypatch):
    from runtime import mastering
    for name in ('uploads','outputs','meta','shares'):
        (tmp_path/name).mkdir(exist_ok=True)
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads')
    monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs')
    monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta')
    monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')
    monkeypatch.setattr(mm,'MEMORY_PATH',tmp_path/'memory.jsonl')
    # Seed one prior experience and create an asset with compatible cached analysis.
    mm.record_experience({'fingerprint':_fp(),'plan_summary':{'target':{'lufs':-10.8}},'verification':'PASS'})
    asset='a'*32
    meta={
        'asset_id':asset,'filename':'x.wav','input_path':str(tmp_path/'uploads'/asset/'x.wav'),
        'analysis':{
            'technical':{'crest_factor_db':12.0,'stereo_correlation':.85,'spectrum':{'dominant_frequency_hz':48.0,'energy_percent':_fp()['spectral_distribution']}},
            'loudness':{'loudness_range_lu':6.0},
            'timeline':{'summary':{'rising_sections':4,'falling_sections':2,'stable_sections':8}},
        },
        'outputs':[]
    }
    (tmp_path/'meta'/f'{asset}.json').write_text(json.dumps(meta))
    hits=mastering.experience_similar(asset,['ritual','cinematic'],['sub_mass'],3)
    assert hits['matches'][0]['score']>0.8
    assert meta['outputs']==[]


def test_record_feedback_persists_contextual_experience(tmp_path, monkeypatch):
    from runtime import mastering
    import wave, io, numpy as np
    for name in ('uploads','outputs','meta','shares'):
        (tmp_path/name).mkdir(exist_ok=True)
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads')
    monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs')
    monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta')
    monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')
    monkeypatch.setattr(mm,'MEMORY_PATH',tmp_path/'memory.jsonl')
    sr=48000; t=np.arange(sr//4)/sr; x=(.2*np.sin(2*np.pi*48*t)*32767).astype('<i2')
    buf=io.BytesIO()
    with wave.open(buf,'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(np.column_stack([x,x]).ravel().tobytes())
    stored=mastering.store_upload('x.wav',buf.getvalue())
    mastering.analyze(stored['asset_id'])
    plan=mastering.save_director_plan(stored['asset_id'],{'intent':'ritual cinematic','protected_traits':['sub_mass'],'target':{},'sections':[{'start':0.0,'end':.25,'actions':[]}]})
    out=mastering.render(stored['asset_id'],profile='director',director_plan_id=plan['plan_id'])['output']
    mastering.verify_output(stored['asset_id'],out['output_id'])
    rec=mastering.record_feedback(stored['asset_id'],out['output_id'],'approved',['ritual','cinematic'])
    assert rec['experience']['rico_feedback']=='approved'
    assert rec['experience']['fingerprint']['protected_traits']==['sub_mass']
