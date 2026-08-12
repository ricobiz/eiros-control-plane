import io, wave
import numpy as np
from runtime import mastering


def wav_bytes(seconds=.8,sr=48000):
    t=np.arange(int(seconds*sr))/sr
    x=(.18*np.sin(2*np.pi*48*t)+.03*np.sin(2*np.pi*800*t)).astype(np.float32)
    pcm=np.clip(x*32767,-32768,32767).astype('<i2')
    b=io.BytesIO()
    with wave.open(b,'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(np.column_stack([pcm,pcm]).ravel().tobytes())
    return b.getvalue()


def roots(tmp_path,monkeypatch):
    for n in ('uploads','outputs','meta','shares'):(tmp_path/n).mkdir()
    monkeypatch.setattr(mastering,'UPLOAD_ROOT',tmp_path/'uploads');monkeypatch.setattr(mastering,'OUTPUT_ROOT',tmp_path/'outputs');monkeypatch.setattr(mastering,'META_ROOT',tmp_path/'meta');monkeypatch.setattr(mastering,'SHARE_ROOT',tmp_path/'shares')


def test_timeline_payload_contains_real_waveform_sections_actions_and_flags(tmp_path,monkeypatch):
    roots(tmp_path,monkeypatch)
    stored=mastering.store_upload('x.wav',wav_bytes())
    mastering.analyze(stored['asset_id'])
    plan=mastering.save_director_plan(stored['asset_id'],{
        'intent':'test','protected_traits':['sub_mass'],'target':{},
        'sections':[{'start':0.0,'end':.8,'actions':[{'type':'gain','reason':'test bounded action','gain_db':-.2,'start':.2,'end':.4}]}],
    })
    out=mastering.render(stored['asset_id'],profile='director',director_plan_id=plan['plan_id'])['output']
    # inject verification flag only to exercise payload aggregation
    meta=mastering._read_meta(stored['asset_id']); item=mastering._find_output(meta,out['output_id'])
    item['verification']={'status':'REVIEW','flags':[{'code':'crest_delta','severity':'review','start_seconds':.3,'end_seconds':.5}]}; mastering._write_meta(meta)
    payload=mastering.timeline_payload(stored['asset_id'],out['output_id'],points=64)
    assert .78 < payload['duration'] < .82
    assert 8 <= len(payload['waveform']) <= 64
    assert all(len(p)==3 for p in payload['waveform']) # t, min, max normalized envelope
    assert payload['sections']
    assert payload['actions'][0]['type']=='gain'
    assert payload['actions'][0]['reason']=='test bounded action'
    assert payload['flags'][0]['code']=='crest_delta'
    assert payload['timebase']=='seconds'
