from __future__ import annotations

import hashlib
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

DIRECTOR_DSP_VERSION = '0.4.0-director'
DEFAULT_TRANSITION_MS = 25.0
EXECUTABLE_ACTIONS = {'gain'}


def _run(command: list[str], *, input_bytes: bytes | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(command, input=input_bytes, capture_output=True, timeout=timeout, check=False)


def _decode(path: Path, sample_rate: int = 48000) -> np.ndarray:
    proc = _run([
        'ffmpeg','-v','error','-i',str(path),'-map','0:a:0',
        '-ac','2','-ar',str(sample_rate),'-f','f32le','-'
    ])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode('utf-8','replace')[-1600:])
    raw = np.frombuffer(proc.stdout, dtype='<f4')
    if raw.size < 4:
        raise RuntimeError('decoded audio is empty')
    raw = raw[:raw.size-(raw.size % 2)]
    return raw.reshape(-1,2).astype(np.float64, copy=True)


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
    env = np.zeros(n, dtype=np.float64)
    start = max(0, min(n, int(start)))
    end = max(start, min(n, int(end)))
    if end <= start:
        return env
    env[start:end] = 1.0
    ramp = max(1, min(int(transition_samples), max(1, (end-start)//2)))
    if ramp > 1:
        phase = np.linspace(0.0, math.pi, ramp, endpoint=True)
        fade_in = 0.5 - 0.5*np.cos(phase)
        fade_out = fade_in[::-1]
        env[start:start+ramp] = fade_in
        env[end-ramp:end] = np.minimum(env[end-ramp:end], fade_out)
    return env


def _apply_gain(audio: np.ndarray, env: np.ndarray, gain_db: float) -> np.ndarray:
    linear = 10.0 ** (float(gain_db) / 20.0)
    factor = 1.0 + env[:,None] * (linear - 1.0)
    return audio * factor


def _pcm_sha256(path: Path) -> str:
    proc = _run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-ac','2','-ar','48000','-f','s24le','-'])
    if proc.returncode != 0:
        raise RuntimeError('unable to hash rendered PCM')
    return hashlib.sha256(proc.stdout).hexdigest()


def render_from_plan(input_path: Path, plan: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Execute only explicit Director actions. This function makes no artistic decisions."""
    sr = 48000
    audio = _decode(Path(input_path), sr)
    execution_log: list[dict[str, Any]] = []

    for section in plan.get('sections') or []:
        for action in section.get('actions') or []:
            kind = str(action.get('type') or '')
            if kind not in EXECUTABLE_ACTIONS:
                raise ValueError(f'DSP action is validated but not executable in v0.4 core: {kind}')
            start_s = float(action.get('start', section['start']))
            end_s = float(action.get('end', section['end']))
            transition_ms = max(DEFAULT_TRANSITION_MS, float(action.get('transition_ms', DEFAULT_TRANSITION_MS)))
            start_i = round(start_s * sr)
            end_i = round(end_s * sr)
            env = _envelope(len(audio), start_i, end_i, round(transition_ms * sr / 1000.0))

            if kind == 'gain':
                gain_db = float(action.get('gain_db', (action.get('parameters') or {}).get('gain_db', 0.0)))
                audio = _apply_gain(audio, env, gain_db)
                applied = {'gain_db': gain_db}
            else:  # pragma: no cover - guarded above
                raise ValueError(f'unsupported DSP action: {kind}')

            execution_log.append({
                'action_id': action['action_id'],
                'type': kind,
                'requested': {k:v for k,v in action.items() if k not in {'reason'}},
                'applied': applied,
                'start_seconds': start_s,
                'end_seconds': end_s,
                'start_sample': start_i,
                'end_sample': min(end_i, len(audio)),
                'transition_ms': transition_ms,
                'reason': action['reason'],
            })

    if not np.all(np.isfinite(audio)):
        raise RuntimeError('DSP produced non-finite samples')
    # No implicit clipping/normalization: any such operation must be explicit in a plan.
    _write_pcm24(audio, Path(destination), sr)
    return {
        'engine_version': DIRECTOR_DSP_VERSION,
        'execution_log': execution_log,
        'invented_actions': 0,
        'pcm_sha256': _pcm_sha256(Path(destination)),
    }
