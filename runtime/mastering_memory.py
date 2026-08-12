from __future__ import annotations

import copy
import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

MEMORY_VERSION = 1
MASTER_ROOT = Path(os.environ.get('EIROS_MASTERING_ROOT','/var/lib/eiros/mastering'))
MEMORY_PATH = MASTER_ROOT / 'experience_v1.jsonl'


def _reject_raw_audio(record: dict[str, Any]) -> None:
    forbidden={'raw_pcm','pcm','audio_bytes','source_audio','waveform_bytes'}
    if any(k in record for k in forbidden):
        raise ValueError('raw audio must not be stored in Experience Memory')


def record_experience(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record,dict):
        raise ValueError('experience record must be an object')
    _reject_raw_audio(record)
    out=copy.deepcopy(record)
    out['memory_version']=MEMORY_VERSION
    out['record_id']=str(out.get('record_id') or uuid.uuid4().hex)
    out['created_at']=int(out.get('created_at') or time.time())
    out.setdefault('fingerprint',{})
    out.setdefault('plan_summary',{})
    MEMORY_PATH.parent.mkdir(parents=True,exist_ok=True)
    with MEMORY_PATH.open('a',encoding='utf-8') as f:
        f.write(json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n')
        f.flush(); os.fsync(f.fileno())
    return out


def _rows() -> list[dict[str,Any]]:
    if not MEMORY_PATH.exists(): return []
    rows=[]
    for line in MEMORY_PATH.read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        try:
            value=json.loads(line)
            if isinstance(value,dict): rows.append(value)
        except json.JSONDecodeError:
            continue
    return rows


def _jaccard(a:list[str],b:list[str]) -> float:
    sa={str(x) for x in a}; sb={str(x) for x in b}
    if not sa and not sb: return 1.0
    if not sa or not sb: return 0.0
    return len(sa&sb)/len(sa|sb)


def _closeness(a:float,b:float,scale:float) -> float:
    return max(0.0,1.0-abs(float(a)-float(b))/max(scale,1e-9))


def _score(query:dict[str,Any], candidate:dict[str,Any]) -> tuple[float,list[str]]:
    qspec=query.get('spectral_distribution') or {}; cspec=candidate.get('spectral_distribution') or {}
    bands=set(qspec)&set(cspec)
    spectral=sum(_closeness(qspec[k],cspec[k],50.0) for k in bands)/len(bands) if bands else 0.5
    crest=_closeness(query.get('crest_db',10),candidate.get('crest_db',10),12.0)
    lra=_closeness(query.get('lra_lu',6),candidate.get('lra_lu',6),12.0)
    corr=_closeness(query.get('stereo_correlation',.8),candidate.get('stereo_correlation',.8),1.0)
    dom=_closeness(query.get('dominant_frequency_hz',100),candidate.get('dominant_frequency_hz',100),300.0)
    tags=_jaccard(query.get('intent_tags',[]),candidate.get('intent_tags',[]))
    protected=_jaccard(query.get('protected_traits',[]),candidate.get('protected_traits',[]))
    qshape=query.get('section_shape') or {}; cshape=candidate.get('section_shape') or {}
    shape_keys=set(qshape)&set(cshape)
    shape=sum(_closeness(qshape[k],cshape[k],8.0) for k in shape_keys)/len(shape_keys) if shape_keys else .5
    score=.24*spectral+.12*crest+.08*lra+.10*corr+.06*dom+.18*tags+.16*protected+.06*shape
    reasons=[]
    if float(query.get('spectral_distribution',{}).get('sub_20_60',0))>=35 and float(candidate.get('spectral_distribution',{}).get('sub_20_60',0))>=35:
        reasons.append('sub-dominant')
    shared_tags=sorted(set(query.get('intent_tags',[]))&set(candidate.get('intent_tags',[])))
    reasons.extend(shared_tags[:3])
    for trait in sorted(set(query.get('protected_traits',[]))&set(candidate.get('protected_traits',[]))):
        reasons.append(f'protected {trait}')
    return round(max(0.0,min(1.0,score)),4),reasons


def find_similar_experiences(fingerprint: dict[str,Any], limit:int=5) -> list[dict[str,Any]]:
    results=[]
    for row in _rows():
        score,reasons=_score(fingerprint,row.get('fingerprint') or {})
        results.append({
            'record_id':row.get('record_id'),'score':score,'reasons':reasons,
            'prior_decision':copy.deepcopy(row.get('plan_summary') or {}),
            'verification':row.get('verification'),'rico_feedback':row.get('rico_feedback'),
            'approval_state':row.get('approval_state'),'created_at':row.get('created_at'),
        })
    results.sort(key=lambda x:(x['score'],x.get('created_at') or 0),reverse=True)
    return results[:max(0,int(limit))]


def build_experience_fingerprint(analysis:dict[str,Any], intent_tags:list[str]|None=None, protected_traits:list[str]|None=None) -> dict[str,Any]:
    tech=analysis.get('technical') or {}; loud=analysis.get('loudness') or {}; timeline=(analysis.get('timeline') or {}).get('summary') or {}
    spectrum=tech.get('spectrum') or {}
    return {
        'spectral_distribution':copy.deepcopy(spectrum.get('energy_percent') or {}),
        'crest_db':tech.get('crest_factor_db'), 'lra_lu':loud.get('loudness_range_lu'),
        'stereo_correlation':tech.get('stereo_correlation'),
        'dominant_frequency_hz':spectrum.get('dominant_frequency_hz'),
        'section_shape':{
            'rising':timeline.get('rising_sections',0),'falling':timeline.get('falling_sections',0),'stable':timeline.get('stable_sections',0),
        },
        'intent_tags':sorted(set(intent_tags or [])), 'protected_traits':sorted(set(protected_traits or [])),
    }
