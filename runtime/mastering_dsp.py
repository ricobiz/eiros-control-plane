from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal, ndimage

DIRECTOR_DSP_VERSION = '0.4.0-director'
PROCESSOR_SET_VERSION = 2
DEFAULT_TRANSITION_MS = 25.0
EXECUTABLE_ACTIONS = {'gain','eq','dynamic_eq','compressor','transient','stereo_width','limiter','declipping'}


def _run(command: list[str], *, input_bytes: bytes | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(command, input=input_bytes, capture_output=True, timeout=timeout, check=False)


def _decode(path: Path, sample_rate: int = 48000) -> np.ndarray:
    proc = _run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-ac','2','-ar',str(sample_rate),'-f','f32le','-'])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode('utf-8','replace')[-1600:])
    raw = np.frombuffer(proc.stdout, dtype='<f4')
    if raw.size < 4:
        raise RuntimeError('decoded audio is empty')
    raw = raw[:raw.size-(raw.size % 2)]
    return raw.reshape(-1,2).astype(np.float32, copy=True)


def _write_pcm24(audio: np.ndarray, destination: Path, sample_rate: int = 48000) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = np.asarray(audio, dtype='<f4').tobytes(order='C')
    proc = _run([
        'ffmpeg','-y','-v','error','-f','f32le','-ar',str(sample_rate),'-ac','2','-i','-',
        '-map_metadata','-1','-map_chapters','-1','-fflags','+bitexact','-flags:a','+bitexact',
        '-ar',str(sample_rate),'-c:a','pcm_s24le',str(destination)
    ], input_bytes=payload)
    if proc.returncode != 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(proc.stderr.decode('utf-8','replace')[-1600:])


def _envelope(n: int, start: int, end: int, transition_samples: int) -> np.ndarray:
    env = np.zeros(n, dtype=np.float32)
    start = max(0, min(n, int(start))); end = max(start, min(n, int(end)))
    if end <= start: return env
    env[start:end] = 1.0
    ramp = max(1, min(int(transition_samples), max(1, (end-start)//2)))
    if ramp > 1:
        phase = np.linspace(0.0, math.pi, ramp, endpoint=True, dtype=np.float32)
        fade_in = 0.5 - 0.5*np.cos(phase); fade_out = fade_in[::-1]
        env[start:start+ramp] = fade_in
        env[end-ramp:end] = np.minimum(env[end-ramp:end], fade_out)
    return env


def _blend(dry: np.ndarray, wet: np.ndarray, env: np.ndarray) -> np.ndarray:
    return (dry + (wet-dry)*env[:,None]).astype(np.float32,copy=False)


def _params(action: dict[str,Any]) -> dict[str,Any]:
    p=dict(action.get('parameters') or {})
    for k,v in action.items():
        if k not in {'parameters','reason','bounds','action_id','type','start','end'}: p.setdefault(k,v)
    return p


def _rbj_peaking(sr: int, frequency_hz: float, q: float, gain_db: float) -> tuple[np.ndarray,np.ndarray]:
    f=min(max(float(frequency_hz),10.0),sr*0.49); q=max(.1,float(q)); A=10**(float(gain_db)/40)
    w=2*math.pi*f/sr; alpha=math.sin(w)/(2*q); c=math.cos(w)
    b=np.array([1+alpha*A,-2*c,1-alpha*A],dtype=np.float64)
    a=np.array([1+alpha/A,-2*c,1-alpha/A],dtype=np.float64)
    return b/a[0],a/a[0]


def _eq(audio: np.ndarray,sr:int,p:dict[str,Any]) -> np.ndarray:
    b,a=_rbj_peaking(sr,p.get('frequency_hz',1000),p.get('q',1.0),p.get('gain_db',0.0))
    return signal.lfilter(b,a,audio,axis=0).astype(np.float32)


def _dynamic_eq(audio:np.ndarray,sr:int,p:dict[str,Any]) -> tuple[np.ndarray,dict[str,Any]]:
    f=float(p.get('frequency_hz',1000)); q=float(p.get('q',1.2)); max_red=abs(float(p.get('max_reduction_db',p.get('gain_db',3.0))))
    threshold=float(p.get('threshold_dbfs',-24)); ratio=max(1.0,float(p.get('ratio',2.0)))
    # Band detector uses a stable 2nd-order bandpass; processing uses a peaking cut.
    lo=max(20.0,f/max(q,0.2)); hi=min(sr*.49,f*max(q,0.2))
    if hi <= lo*1.05: lo=max(20,f*.7); hi=min(sr*.49,f*1.3)
    sos=signal.butter(2,[lo,hi],btype='bandpass',fs=sr,output='sos')
    band=signal.sosfilt(sos,audio,axis=0).astype(np.float32)
    power=np.mean(band*band,axis=1)
    window=max(32,int(sr*float(p.get('detector_ms',40))/1000))
    rms=np.sqrt(np.maximum(ndimage.uniform_filter1d(power,size=window,mode='nearest'),1e-12))
    level=20*np.log10(rms+1e-12)
    over=np.maximum(0.0,level-threshold)
    reduction=np.minimum(max_red,over*(1-1/ratio)).astype(np.float32)
    wet=_eq(audio,sr,{'frequency_hz':f,'q':q,'gain_db':-max_red})
    mix=(reduction/max(max_red,1e-6))[:,None]
    out=audio+(wet-audio)*mix
    return out.astype(np.float32),{'max_reduction_db':round(float(np.max(reduction)),3),'mean_reduction_db':round(float(np.mean(reduction)),3),'frequency_hz':f,'q':q}


def _compressor(audio:np.ndarray,sr:int,p:dict[str,Any],bounds:dict[str,Any]) -> tuple[np.ndarray,dict[str,Any]]:
    threshold=float(p.get('threshold_dbfs',-18)); ratio=max(1,float(p.get('ratio',2))); makeup=float(p.get('makeup_db',0))
    attack=max(.2,float(p.get('attack_ms',10))); release=max(5,float(p.get('release_ms',120)))
    # Peak-aware detector: mastering compression must see sparse transients, not average them away.
    peak=np.max(np.abs(audio),axis=1)
    attack_n=max(3,int(sr*attack/1000)); release_n=max(attack_n,int(sr*release/1000))
    fast=ndimage.maximum_filter1d(peak,size=attack_n if attack_n%2 else attack_n+1,mode='nearest')
    power=np.mean(audio*audio,axis=1)
    slow=np.sqrt(np.maximum(ndimage.uniform_filter1d(power,size=release_n,mode='nearest'),1e-12))
    detector=np.maximum(fast,slow); level=20*np.log10(detector+1e-12)
    red=np.maximum(0.0,(level-threshold)*(1-1/ratio))
    max_bound=abs(float(bounds.get('max_gain_reduction_db',24))); red=np.minimum(red,max_bound)
    gain=10**((makeup-red)/20)
    out=audio*gain[:,None]
    return out.astype(np.float32),{'max_gain_reduction_db':round(float(np.max(red)),3),'mean_gain_reduction_db':round(float(np.mean(red)),3),'makeup_db':makeup}


def _transient(audio:np.ndarray,sr:int,p:dict[str,Any]) -> tuple[np.ndarray,dict[str,Any]]:
    amount=float(p.get('amount_db',0)); fast_ms=max(.2,float(p.get('fast_ms',5))); slow_ms=max(10,float(p.get('slow_ms',60)))
    power=np.mean(audio*audio,axis=1)
    fast=np.sqrt(np.maximum(ndimage.uniform_filter1d(power,size=max(8,int(sr*fast_ms/1000)),mode='nearest'),1e-12))
    slow=np.sqrt(np.maximum(ndimage.uniform_filter1d(power,size=max(16,int(sr*slow_ms/1000)),mode='nearest'),1e-12))
    transient=np.clip((fast/(slow+1e-9)-1.0),0,2)
    gain_db=np.clip(amount*transient,-abs(amount)*2,abs(amount)*2)
    out=audio*(10**(gain_db/20))[:,None]
    return out.astype(np.float32),{'amount_db':amount,'max_applied_db':round(float(np.max(np.abs(gain_db))),3)}


def _stereo_width(audio:np.ndarray,p:dict[str,Any]) -> tuple[np.ndarray,dict[str,Any]]:
    width=float(p.get('width',float(p.get('width_percent',100))/100)); width=max(0,min(2,width))
    mid=(audio[:,0]+audio[:,1])*.5; side=(audio[:,0]-audio[:,1])*.5*width
    out=np.column_stack([mid+side,mid-side]).astype(np.float32)
    return out,{'width':width}


def _limiter(audio:np.ndarray,sr:int,p:dict[str,Any],bounds:dict[str,Any]) -> tuple[np.ndarray,dict[str,Any]]:
    ceiling=float(p.get('ceiling_dbtp',p.get('ceiling_dbfs',-1.0))); ceiling_lin=10**(ceiling/20)
    lookahead=max(.5,float(p.get('lookahead_ms',3))); release=max(5,float(p.get('release_ms',80)))
    peak=np.max(np.abs(audio),axis=1)
    window=max(3,int(sr*(lookahead+release*.20)/1000)); if_even=window%2==0; window+=1 if if_even else 0
    env=ndimage.maximum_filter1d(peak,size=window,mode='nearest')
    desired=np.minimum(1.0,ceiling_lin/np.maximum(env,1e-12))
    max_bound=abs(float(bounds.get('max_gain_reduction_db',24))); min_gain=10**(-max_bound/20); gain=np.maximum(desired,min_gain)
    out=audio*gain[:,None]
    red=-20*np.log10(np.maximum(gain,1e-12))
    return out.astype(np.float32),{'ceiling_dbtp':ceiling,'max_gain_reduction_db':round(float(np.max(red)),3),'mean_gain_reduction_db':round(float(np.mean(red)),3)}


def _declipping(audio:np.ndarray,p:dict[str,Any]) -> tuple[np.ndarray,dict[str,Any]]:
    threshold=float(p.get('threshold',0.995)); out=audio.copy(); repaired=0
    for ch in range(2):
        x=out[:,ch]; bad=np.abs(x)>=threshold; repaired+=int(np.sum(bad))
        good=np.flatnonzero(~bad); bad_i=np.flatnonzero(bad)
        if bad_i.size and good.size>=2: x[bad_i]=np.interp(bad_i,good,x[good]).astype(np.float32)
    return out,{'repaired_samples':repaired,'threshold':threshold}


def _pcm_sha256(path: Path) -> str:
    proc=_run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-ac','2','-ar','48000','-f','s24le','-'])
    if proc.returncode != 0: raise RuntimeError('unable to hash rendered PCM')
    return hashlib.sha256(proc.stdout).hexdigest()


def render_from_plan(input_path: Path, plan: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Execute only explicit Director actions. This function makes no artistic decisions."""
    sr=48000; audio=_decode(Path(input_path),sr); execution_log=[]
    for section in plan.get('sections') or []:
        for action in section.get('actions') or []:
            kind=str(action.get('type') or '')
            if kind not in EXECUTABLE_ACTIONS: raise ValueError(f'DSP action is validated but not executable: {kind}')
            start_s=float(action.get('start',section['start'])); end_s=float(action.get('end',section['end']))
            transition_ms=max(DEFAULT_TRANSITION_MS,float(action.get('transition_ms',DEFAULT_TRANSITION_MS)))
            start_i=round(start_s*sr); end_i=round(end_s*sr); env=_envelope(len(audio),start_i,end_i,round(transition_ms*sr/1000))
            p=_params(action); bounds=dict(action.get('bounds') or {})
            if kind=='gain':
                gain_db=float(p.get('gain_db',0)); wet=audio*(10**(gain_db/20)); applied={'gain_db':gain_db}
            elif kind=='eq': wet=_eq(audio,sr,p); applied={'frequency_hz':float(p.get('frequency_hz',1000)),'gain_db':float(p.get('gain_db',0)),'q':float(p.get('q',1))}
            elif kind=='dynamic_eq': wet,applied=_dynamic_eq(audio,sr,p)
            elif kind=='compressor': wet,applied=_compressor(audio,sr,p,bounds)
            elif kind=='transient': wet,applied=_transient(audio,sr,p)
            elif kind=='stereo_width': wet,applied=_stereo_width(audio,p)
            elif kind=='limiter': wet,applied=_limiter(audio,sr,p,bounds)
            elif kind=='declipping': wet,applied=_declipping(audio,p)
            audio=_blend(audio,wet,env)
            execution_log.append({'action_id':action['action_id'],'type':kind,'requested':{k:v for k,v in action.items() if k!='reason'},'applied':applied,'start_seconds':start_s,'end_seconds':end_s,'start_sample':start_i,'end_sample':min(end_i,len(audio)),'transition_ms':transition_ms,'reason':action['reason']})
    if not np.all(np.isfinite(audio)): raise RuntimeError('DSP produced non-finite samples')
    _write_pcm24(audio,Path(destination),sr)
    return {'engine_version':DIRECTOR_DSP_VERSION,'processor_set_version':PROCESSOR_SET_VERSION,'execution_log':execution_log,'invented_actions':0,'pcm_sha256':_pcm_sha256(Path(destination))}
