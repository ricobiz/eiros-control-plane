import io, wave
import numpy as np
from runtime import mastering

def wav_bytes(seconds=1.2,sr=48000):
    t=np.arange(int(seconds*sr))/sr
    l=.16*np.sin(2*np.pi*55*t)+.025*np.sin(2*np.pi*880*t)
    r=.15*np.sin(2*np.pi*55*t+.08)+.02*np.sin(2*np.pi*880*t)
    pcm=np.clip(np.column_stack([l,r])*32767,-32768,32767).astype('<i2').ravel().tobytes()
    b=io.BytesIO()
    with wave.open(b,'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(pcm)
    return b.getvalue()

def roots(tmp_path,monkeypatch):
    for name in ('UPLOAD_ROOT','OUTPUT_ROOT','META_ROOT','SHARE_ROOT'):
        p=tmp_path/name.lower();p.mkdir();monkeypatch.setattr(mastering,name,p)

def test_analysis_payload_contains_only_measured_source_master_and_delta(tmp_path,monkeypatch):
    roots(tmp_path,monkeypatch)
    a=mastering.store_upload('measure.wav',wav_bytes())
    mastering.analyze(a['asset_id'])
    out=mastering.render(a['asset_id'],profile='none',target_lufs=-12.0)['output']
    p=mastering.analysis_payload(a['asset_id'],out['output_id'])
    assert p['measurement_basis']=='decoded_audio_measurements'
    for side in ('source','master'):
        m=p[side]['metrics']
        assert {'lufs_i','true_peak_dbtp','lra_lu','rms_dbfs','crest_db','stereo_correlation','dc_offset','bands_percent'} <= set(m)
        assert p[side]['series'] and {'t','rms_dbfs','crest_db','stereo_correlation','bands_percent'} <= set(p[side]['series'][0])
    assert p['delta']['metrics']['crest_db'] == round(p['master']['metrics']['crest_db']-p['source']['metrics']['crest_db'],3)
    assert set(p['delta']['bands_db']) >= {'sub_20_60','bass_60_120','low_mid_120_500','mid_500_2000','presence_2000_6000','high_6000_12000'}
    assert p['delta']['series'] and {'t','rms_db','crest_db','stereo_correlation'} <= set(p['delta']['series'][0])
