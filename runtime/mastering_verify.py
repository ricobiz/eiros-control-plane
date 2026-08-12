from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

VERIFY_SCHEMA_VERSION = 1


def _slice_metrics(audio: np.ndarray, sr: int, start: float, end: float) -> dict[str, float]:
    i0=max(0,round(start*sr)); i1=min(len(audio),round(end*sr)); seg=audio[i0:i1]
    if len(seg)<8:
        return {'crest_db':0.0,'sub_percent':0.0,'sub_level_db':-120.0,'stereo_correlation':1.0,'sample_peak_dbfs':-120.0}
    peak=float(np.max(np.abs(seg)))
    rms=float(np.sqrt(np.mean(seg**2)))
    crest=20*math.log10(max(peak,1e-12)/max(rms,1e-12))
    l=seg[:,0]; r=seg[:,1]
    corr=float(np.corrcoef(l,r)[0,1]) if np.std(l)>1e-9 and np.std(r)>1e-9 else 1.0
    mono=np.mean(seg,axis=1)
    mono=mono-np.mean(mono)
    win=np.hanning(len(mono)); spec=np.abs(np.fft.rfft(mono*win))**2; freqs=np.fft.rfftfreq(len(mono),1/sr)
    total=float(np.sum(spec[(freqs>=20)&(freqs<12000)])) or 1e-20
    sub=float(np.sum(spec[(freqs>=20)&(freqs<60)]))
    sub_percent=100.0*sub/total
    # absolute sub energy proxy, stable for aligned source/master comparisons
    sub_level_db=10*math.log10(max(sub,1e-20)/max(len(mono)**2,1))
    return {
        'crest_db':round(crest,3), 'sub_percent':round(sub_percent,3),
        'sub_level_db':round(sub_level_db,3), 'stereo_correlation':round(corr,5),
        'sample_peak_dbfs':round(20*math.log10(max(peak,1e-12)),3),
    }


def build_delta_report(source: Path, master: Path, plan: dict[str, Any]) -> dict[str, Any]:
    from runtime import mastering
    src=mastering._decode_float_audio(Path(source),48000)
    dst=mastering._decode_float_audio(Path(master),48000)
    n=min(len(src),len(dst)); src=src[:n]; dst=dst[:n]
    src_l=mastering.loudness(Path(source)); dst_l=mastering.loudness(Path(master))
    src_t=mastering._technical_stats(Path(source)); dst_t=mastering._technical_stats(Path(master))
    sections=[]
    raw_sections=plan.get('sections') or [{'start':0.0,'end':n/48000.0,'actions':[]}]
    for sec in raw_sections:
        start=float(sec['start']); end=min(float(sec['end']),n/48000.0)
        sm=_slice_metrics(src,48000,start,end); mm=_slice_metrics(dst,48000,start,end)
        delta={k:round(mm[k]-sm[k],4) for k in sm}
        sections.append({'start':start,'end':end,'source':sm,'master':mm,'delta':delta,'flags':[]})
    return {
        'schema_version':VERIFY_SCHEMA_VERSION,
        'global':{
            'lufs_delta':round(dst_l['integrated_lufs']-src_l['integrated_lufs'],3),
            'true_peak_delta':round(dst_l['true_peak_dbtp']-src_l['true_peak_dbtp'],3),
            'crest_delta':round(dst_t['crest_factor_db']-src_t['crest_factor_db'],3),
            'stereo_correlation_delta':round(dst_t['stereo_correlation']-src_t['stereo_correlation'],5),
            'source_true_peak_dbtp':src_l['true_peak_dbtp'],
            'master_true_peak_dbtp':dst_l['true_peak_dbtp'],
            'source_sample_peak_dbfs':src_t['sample_peak_dbfs'],
            'master_sample_peak_dbfs':dst_t['sample_peak_dbfs'],
        },
        'sections':sections,
    }


def _has_action(plan: dict[str,Any], kinds: set[str]) -> bool:
    return any(a.get('type') in kinds for s in plan.get('sections',[]) for a in s.get('actions',[]))


def verify_master(source: Path, master: Path, plan: dict[str, Any]) -> dict[str, Any]:
    report=build_delta_report(source,master,plan)
    flags=[]; hard=False
    g=report['global']; target=dict(plan.get('target') or {})
    tp=target.get('true_peak_dbtp')
    if tp is not None and g['master_true_peak_dbtp'] > float(tp)+0.08:
        flags.append({'code':'true_peak_violation','severity':'REJECT','value':g['master_true_peak_dbtp'],'limit':float(tp)})
        hard=True
    if g['master_sample_peak_dbfs'] >= -0.01 and g['source_sample_peak_dbfs'] < -0.05:
        flags.append({'code':'new_clipping','severity':'REJECT','value':g['master_sample_peak_dbfs']})
        hard=True
    if g['crest_delta'] < -3.0 and not _has_action(plan,{'compressor','limiter','transient'}):
        flags.append({'code':'crest_collapse','severity':'REVIEW','value':g['crest_delta']})
    if g['stereo_correlation_delta'] < -0.25 and not _has_action(plan,{'stereo_width'}):
        flags.append({'code':'stereo_correlation_collapse','severity':'REVIEW','value':g['stereo_correlation_delta']})
    if 'sub_mass' in set(plan.get('protected_traits') or []):
        worst=min((s['delta']['sub_level_db'] for s in report['sections']),default=0.0)
        if worst < -1.0 and not any(a.get('type') in {'eq','dynamic_eq'} and (a.get('band')=='20_60' or float((a.get('parameters') or {}).get('frequency_hz',999))<60) for s in plan.get('sections',[]) for a in s.get('actions',[])):
            flags.append({'code':'protected_sub_loss','severity':'REJECT','value':round(worst,3),'limit':-1.0})
            hard=True
    status='REJECTED' if hard else ('REVIEW' if flags else 'PASS')
    return {'schema_version':VERIFY_SCHEMA_VERSION,'status':status,'flags':flags,'delta_report':report}
