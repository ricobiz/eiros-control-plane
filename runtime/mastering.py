from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

MASTER_ROOT = Path(os.environ.get("EIROS_MASTERING_ROOT", "/var/lib/eiros/mastering"))
UPLOAD_ROOT = MASTER_ROOT / "uploads"
OUTPUT_ROOT = MASTER_ROOT / "outputs"
META_ROOT = MASTER_ROOT / "meta"
SHARE_ROOT = MASTER_ROOT / "shares"
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
ALLOWED_SUFFIXES = {".wav", ".wave", ".flac", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".ogg", ".opus"}
ID_RE = re.compile(r"^[a-f0-9]{32}$")
SHARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{24,80}$")
ANALYSIS_VERSION = 2
ADAPTIVE_ENGINE_VERSION = "0.3.0-section-aware"
CLEAN_EXPORT_VERSION = 2
PREVIEW_EXPORT_VERSION = 1
TIMELINE_HOP_SECONDS = 1.0
BAND_RANGES = {
    "sub_20_60": (20.0, 60.0),
    "bass_60_120": (60.0, 120.0),
    "low_mid_120_500": (120.0, 500.0),
    "mid_500_2000": (500.0, 2000.0),
    "presence_2000_6000": (2000.0, 6000.0),
    "high_6000_12000": (6000.0, 12000.0),
}
BAND_CENTERS = {
    "sub_20_60": 38.0,
    "bass_60_120": 85.0,
    "low_mid_120_500": 245.0,
    "mid_500_2000": 1000.0,
    "presence_2000_6000": 3500.0,
    "high_6000_12000": 8500.0,
}

for _path in (UPLOAD_ROOT, OUTPUT_ROOT, META_ROOT, SHARE_ROOT):
    _path.mkdir(parents=True, exist_ok=True)


def _run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def _safe_name(name: str) -> str:
    base = Path(str(name or "audio.wav")).name
    cleaned = re.sub(r"[^A-Za-z0-9._()\- ]+", "_", base).strip(" .")
    return (cleaned or "audio.wav")[:160]


def _validate_id(value: str, label: str = "asset_id") -> str:
    target = str(value or "").strip().lower()
    if not ID_RE.fullmatch(target):
        raise ValueError(f"Invalid {label}")
    return target


def _meta_path(asset_id: str) -> Path:
    return META_ROOT / f"{_validate_id(asset_id)}.json"


def _read_meta(asset_id: str) -> dict[str, Any]:
    path = _meta_path(asset_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown mastering asset: {asset_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Asset metadata is invalid")
    return data


def _write_meta(data: dict[str, Any]) -> None:
    asset_id = _validate_id(str(data.get("asset_id") or ""))
    path = _meta_path(asset_id)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _input_path(meta: dict[str, Any]) -> Path:
    path = Path(str(meta.get("input_path") or ""))
    expected = (UPLOAD_ROOT / _validate_id(str(meta.get("asset_id") or ""))).resolve()
    resolved = path.resolve()
    if expected not in resolved.parents or not resolved.is_file():
        raise FileNotFoundError("Stored input audio is missing")
    return resolved


def probe(path: Path) -> dict[str, Any]:
    proc = _run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,channel_layout,bits_per_sample:format=duration,size,bit_rate,format_name",
        "-of", "json", str(path),
    ], timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {(proc.stderr or proc.stdout).strip()[:1200]}")
    raw = json.loads(proc.stdout or "{}")
    stream = (raw.get("streams") or [{}])[0]
    fmt = raw.get("format") or {}
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "channel_layout": stream.get("channel_layout") or "",
        "bits_per_sample": int(stream.get("bits_per_sample") or 0),
        "duration_seconds": round(float(fmt.get("duration") or 0.0), 3),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "bit_rate": int(fmt.get("bit_rate") or 0),
        "format": fmt.get("format_name") or "",
    }


def _parse_loudnorm(stderr: str) -> dict[str, float]:
    matches = re.findall(r"\{\s*\"input_i\".*?\}", stderr or "", flags=re.S)
    if not matches:
        raise RuntimeError(f"Unable to parse FFmpeg loudness report: {(stderr or '')[-1500:]}")
    raw = json.loads(matches[-1])
    def number(key: str) -> float:
        value = str(raw.get(key, "nan"))
        try:
            return float(value)
        except ValueError:
            return float("nan")
    return {
        "integrated_lufs": number("input_i"),
        "true_peak_dbtp": number("input_tp"),
        "loudness_range_lu": number("input_lra"),
        "threshold_lufs": number("input_thresh"),
        "target_offset_lu": number("target_offset"),
    }


def loudness(path: Path, prefix_filters: str = "", target_lufs: float = -14.0, true_peak: float = -1.0, lra: float = 11.0) -> dict[str, float]:
    chain = []
    if prefix_filters.strip():
        chain.append(prefix_filters.strip().strip(","))
    chain.append(f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json")
    proc = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-map", "0:a:0", "-af", ",".join(chain), "-f", "null", "-",
    ], timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg loudness analysis failed: {(proc.stderr or proc.stdout)[-1800:]}")
    return _parse_loudnorm(proc.stderr)


def _technical_stats(path: Path, max_seconds: int = 600) -> dict[str, Any]:
    proc = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-t", str(max_seconds), "-ac", "2", "-ar", "24000", "-f", "f32le", "-",
    ], capture_output=True, timeout=600, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg decode failed: {proc.stderr.decode('utf-8', 'replace')[-1200:]}")
    audio = np.frombuffer(proc.stdout, dtype="<f4")
    if audio.size < 4:
        raise RuntimeError("Decoded audio is empty")
    audio = audio[: audio.size - (audio.size % 2)].reshape(-1, 2).astype(np.float64, copy=False)
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio))))
    crest_db = 20.0 * math.log10(max(peak, 1e-12) / max(rms, 1e-12))
    dc = [float(np.mean(audio[:, 0])), float(np.mean(audio[:, 1]))]
    left_std = float(np.std(audio[:, 0]))
    right_std = float(np.std(audio[:, 1]))
    correlation = float(np.corrcoef(audio[:, 0], audio[:, 1])[0, 1]) if left_std > 1e-9 and right_std > 1e-9 else 1.0
    mono = np.mean(audio, axis=1)
    window_size = min(len(mono), 24000 * 180)
    if window_size < 4096:
        spectrum_info: dict[str, Any] = {}
    else:
        segment = mono[:window_size]
        segment = segment - np.mean(segment)
        segment *= np.hanning(len(segment))
        power = np.abs(np.fft.rfft(segment)) ** 2
        freqs = np.fft.rfftfreq(len(segment), d=1.0 / 24000.0)
        total = float(np.sum(power)) or 1.0
        bands = {
            "sub_20_60": (20, 60),
            "bass_60_120": (60, 120),
            "low_mid_120_500": (120, 500),
            "mid_500_2000": (500, 2000),
            "presence_2000_6000": (2000, 6000),
            "high_6000_12000": (6000, 12000),
        }
        distribution = {}
        for name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs < high)
            distribution[name] = round(100.0 * float(np.sum(power[mask])) / total, 3)
        valid = freqs >= 20
        dominant = float(freqs[valid][int(np.argmax(power[valid]))]) if np.any(valid) else 0.0
        centroid = float(np.sum(freqs * power) / total)
        spectrum_info = {
            "dominant_frequency_hz": round(dominant, 1),
            "spectral_centroid_hz": round(centroid, 1),
            "energy_percent": distribution,
            "analysis_seconds": round(window_size / 24000.0, 2),
        }
    return {
        "sample_peak_dbfs": round(20.0 * math.log10(max(peak, 1e-12)), 3),
        "rms_dbfs": round(20.0 * math.log10(max(rms, 1e-12)), 3),
        "crest_factor_db": round(crest_db, 3),
        "stereo_correlation": round(correlation, 5),
        "dc_offset": [round(v, 8) for v in dc],
        "spectrum": spectrum_info,
    }



def _decode_float_audio(path: Path, sample_rate: int = 48000) -> np.ndarray:
    proc = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-ac", "2", "-ar", str(sample_rate), "-f", "f32le", "-",
    ], capture_output=True, timeout=900, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg decode failed: {proc.stderr.decode('utf-8', 'replace')[-1600:]}")
    raw = np.frombuffer(proc.stdout, dtype="<f4")
    if raw.size < 4:
        raise RuntimeError("Decoded audio is empty")
    raw = raw[: raw.size - (raw.size % 2)]
    return raw.reshape(-1, 2).copy()


def _smooth_series(values: np.ndarray, radius: int = 2) -> np.ndarray:
    data = np.asarray(values, dtype=np.float64)
    if data.size < 2 or radius <= 0:
        return data.copy()
    radius = min(int(radius), max(1, (data.size - 1) // 2))
    ramp = np.arange(1, radius + 2, dtype=np.float64)
    kernel = np.concatenate([ramp, ramp[-2::-1]])
    kernel /= np.sum(kernel)
    padded = np.pad(data, (radius, radius), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _rolling_median(values: np.ndarray, radius: int = 5) -> np.ndarray:
    data = np.asarray(values, dtype=np.float64)
    result = np.empty_like(data)
    for index in range(data.size):
        left = max(0, index - radius)
        right = min(data.size, index + radius + 1)
        result[index] = float(np.median(data[left:right]))
    return result


def _robust_features(columns: list[np.ndarray]) -> np.ndarray:
    matrix = np.column_stack(columns).astype(np.float64, copy=False)
    normalized = np.zeros_like(matrix)
    for column in range(matrix.shape[1]):
        values = matrix[:, column]
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        scale = max(1.4826 * mad, float(np.std(values)) * 0.35, 1e-6)
        normalized[:, column] = (values - median) / scale
        normalized[:, column] = _smooth_series(normalized[:, column], 1)
    return normalized


def _detect_sections(times: np.ndarray, features: np.ndarray, duration: float) -> tuple[list[float], np.ndarray]:
    count = len(times)
    if count < 4:
        return [0.0, float(duration)], np.zeros(count, dtype=np.float64)
    novelty = np.zeros(count, dtype=np.float64)
    novelty[1:] = np.sqrt(np.mean(np.square(features[1:] - features[:-1]), axis=1))
    novelty = _smooth_series(novelty, 1)
    threshold = max(float(np.percentile(novelty[1:], 78.0)), 0.65)
    candidates = [index for index in range(2, count - 2) if novelty[index] >= threshold]
    candidates.sort(key=lambda index: float(novelty[index]), reverse=True)
    selected = [0.0, float(duration)]
    max_internal = max(2, min(18, int(duration // 9.0)))
    for index in candidates:
        boundary = float(times[index])
        if boundary < 4.0 or duration - boundary < 4.0:
            continue
        if min(abs(boundary - value) for value in selected) < 7.0:
            continue
        selected.append(boundary)
        if len(selected) - 2 >= max_internal:
            break
    selected.sort()
    while True:
        gaps = [(selected[i + 1] - selected[i], i) for i in range(len(selected) - 1)]
        gap, position = max(gaps)
        if gap <= 32.0:
            break
        left = selected[position] + 7.0
        right = selected[position + 1] - 7.0
        valid = np.where((times >= left) & (times <= right))[0]
        if valid.size:
            chosen = int(valid[np.argmax(novelty[valid])])
            boundary = float(times[chosen])
        else:
            boundary = float((selected[position] + selected[position + 1]) / 2.0)
        selected.append(boundary)
        selected.sort()
    return selected, novelty


def _timeline_from_audio(audio: np.ndarray, sample_rate: int = 48000) -> dict[str, Any]:
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError("Timeline analysis expects stereo audio")
    duration = float(len(audio) / sample_rate)
    times = np.arange(0.5, max(0.51, duration), TIMELINE_HOP_SECONDS, dtype=np.float64)
    if times.size == 0:
        times = np.array([duration / 2.0], dtype=np.float64)
    rms_values: list[float] = []
    peak_values: list[float] = []
    crest_values: list[float] = []
    correlation_values: list[float] = []
    band_values: dict[str, list[float]] = {name: [] for name in BAND_RANGES}
    spectrum_size = 65536
    spectrum_freqs = np.fft.rfftfreq(spectrum_size, d=1.0 / sample_rate)
    spectrum_masks = {
        name: (spectrum_freqs >= low) & (spectrum_freqs < high)
        for name, (low, high) in BAND_RANGES.items()
    }
    audible_mask = (spectrum_freqs >= 20.0) & (spectrum_freqs < min(20000.0, sample_rate / 2.0))
    one_second = max(2048, int(sample_rate))
    three_seconds = max(one_second, int(sample_rate * 3.0))
    for point in times:
        center = int(round(point * sample_rate))
        loud_left = max(0, center - three_seconds // 2)
        loud_right = min(len(audio), loud_left + three_seconds)
        loud_left = max(0, loud_right - three_seconds)
        loud_frame = audio[loud_left:loud_right].astype(np.float64, copy=False)
        rms = float(np.sqrt(np.mean(np.square(loud_frame)))) if loud_frame.size else 0.0
        peak = float(np.max(np.abs(loud_frame))) if loud_frame.size else 0.0
        rms_db = 20.0 * math.log10(max(rms, 1e-12))
        peak_db = 20.0 * math.log10(max(peak, 1e-12))
        rms_values.append(rms_db)
        peak_values.append(peak_db)
        crest_values.append(peak_db - rms_db)
        if len(loud_frame) > 16:
            left_std = float(np.std(loud_frame[:, 0]))
            right_std = float(np.std(loud_frame[:, 1]))
            corr = float(np.corrcoef(loud_frame[:, 0], loud_frame[:, 1])[0, 1]) if left_std > 1e-9 and right_std > 1e-9 else 1.0
        else:
            corr = 1.0
        correlation_values.append(corr if math.isfinite(corr) else 1.0)
        spec_left = max(0, center - one_second // 2)
        spec_right = min(len(audio), spec_left + one_second)
        spec_left = max(0, spec_right - one_second)
        mono = np.mean(audio[spec_left:spec_right].astype(np.float64, copy=False), axis=1)
        if mono.size < 2048:
            power = np.zeros_like(spectrum_freqs)
        else:
            mono = mono - float(np.mean(mono))
            mono *= np.hanning(mono.size)
            power = np.abs(np.fft.rfft(mono, n=spectrum_size)) ** 2
        total = max(float(np.sum(power[audible_mask])), 1e-18)
        for name, mask in spectrum_masks.items():
            band_values[name].append(100.0 * float(np.sum(power[mask])) / total)
    rms_array = np.asarray(rms_values, dtype=np.float64)
    peak_array = np.asarray(peak_values, dtype=np.float64)
    crest_array = np.asarray(crest_values, dtype=np.float64)
    corr_array = np.asarray(correlation_values, dtype=np.float64)
    band_arrays = {name: np.asarray(values, dtype=np.float64) for name, values in band_values.items()}
    feature_columns = [rms_array, crest_array, corr_array]
    feature_columns.extend(10.0 * np.log10(np.maximum(band_arrays[name], 1e-8)) for name in BAND_RANGES)
    features = _robust_features(feature_columns)
    boundaries, novelty = _detect_sections(times, features, duration)
    sections: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:]), start=1):
        mask = (times >= start) & (times < end)
        if not np.any(mask):
            nearest = int(np.argmin(np.abs(times - ((start + end) / 2.0))))
            mask[nearest] = True
        section_times = times[mask]
        section_rms = rms_array[mask]
        slope = 0.0
        fit_r2 = 0.0
        if section_times.size >= 3:
            x = section_times - float(section_times[0])
            slope, intercept = np.polyfit(x, section_rms, 1)
            prediction = slope * x + intercept
            residual = float(np.sum(np.square(section_rms - prediction)))
            total = float(np.sum(np.square(section_rms - float(np.mean(section_rms)))))
            fit_r2 = max(0.0, 1.0 - residual / max(total, 1e-9))
        if slope >= 0.075 and fit_r2 >= 0.18:
            trajectory = "rising"
        elif slope <= -0.075 and fit_r2 >= 0.18:
            trajectory = "falling"
        else:
            trajectory = "stable"
        sections.append({
            "index": index,
            "start_seconds": round(float(start), 2),
            "end_seconds": round(float(end), 2),
            "duration_seconds": round(float(end - start), 2),
            "trajectory": trajectory,
            "loudness_slope_db_per_s": round(float(slope), 4),
            "trajectory_fit_r2": round(float(fit_r2), 3),
            "short_rms_dbfs": round(float(np.median(section_rms)), 3),
            "peak_dbfs": round(float(np.max(peak_array[mask])), 3),
            "crest_db": round(float(np.median(crest_array[mask])), 3),
            "stereo_correlation": round(float(np.median(corr_array[mask])), 5),
            "bands_percent": {
                name: round(float(np.median(values[mask])), 3)
                for name, values in band_arrays.items()
            },
        })
    points = []
    for index, point in enumerate(times):
        points.append({
            "t": round(float(point), 2),
            "short_rms_dbfs": round(float(rms_array[index]), 3),
            "peak_dbfs": round(float(peak_array[index]), 3),
            "crest_db": round(float(crest_array[index]), 3),
            "stereo_correlation": round(float(corr_array[index]), 5),
            "novelty": round(float(novelty[index]), 4),
            "bands_percent": {
                name: round(float(values[index]), 3)
                for name, values in band_arrays.items()
            },
        })
    valid_rms = rms_array[rms_array > -60.0]
    spread = float(np.percentile(valid_rms, 95.0) - np.percentile(valid_rms, 5.0)) if valid_rms.size else 0.0
    return {
        "version": ANALYSIS_VERSION,
        "hop_seconds": TIMELINE_HOP_SECONDS,
        "duration_seconds": round(duration, 3),
        "summary": {
            "section_count": len(sections),
            "short_term_spread_db": round(spread, 3),
            "rising_sections": sum(1 for section in sections if section["trajectory"] == "rising"),
            "falling_sections": sum(1 for section in sections if section["trajectory"] == "falling"),
            "stable_sections": sum(1 for section in sections if section["trajectory"] == "stable"),
        },
        "sections": sections,
        "points": points,
    }


def _timeline_stats(path: Path) -> dict[str, Any]:
    return _timeline_from_audio(_decode_float_audio(path, 48000), 48000)


def _adaptive_curves(timeline: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    points = list(timeline.get("points") or [])
    if not points:
        raise ValueError("Timeline analysis is empty")
    times = np.asarray([float(point["t"]) for point in points], dtype=np.float64)
    rms = np.asarray([float(point["short_rms_dbfs"]) for point in points], dtype=np.float64)
    macro = _rolling_median(rms, 5)
    sections = list(timeline.get("sections") or [])
    trajectory_by_point = np.full(times.size, "stable", dtype=object)
    for section in sections:
        start = float(section["start_seconds"])
        end = float(section["end_seconds"])
        mask = (times >= start) & (times < end)
        trajectory = str(section.get("trajectory") or "stable")
        trajectory_by_point[mask] = trajectory
        if np.sum(mask) >= 3 and trajectory in {"rising", "falling"}:
            x = times[mask] - float(times[mask][0])
            slope, intercept = np.polyfit(x, rms[mask], 1)
            fitted = slope * x + intercept
            macro[mask] = 0.70 * macro[mask] + 0.30 * fitted
    residual = rms - macro
    gain_db = np.zeros_like(rms)
    high = residual > 1.35
    gain_db[high] = -0.42 * (residual[high] - 1.35)
    low = residual < -2.8
    gain_db[low] = 0.16 * (-residual[low] - 2.8)
    intentional_motion = trajectory_by_point != "stable"
    gain_db[intentional_motion & (gain_db > 0.0)] = 0.0
    gain_db[(rms < -42.0) & (gain_db > 0.0)] = 0.0
    gain_db = np.clip(gain_db, -1.5, 0.4)
    gain_db = _smooth_series(gain_db, 2)
    if gain_db.size:
        gain_db[: min(4, gain_db.size)] = np.minimum(gain_db[: min(4, gain_db.size)], 0.0)
        gain_db[max(0, gain_db.size - 4):] = np.minimum(gain_db[max(0, gain_db.size - 4):], 0.0)
    for section in sections:
        boundary = float(section["start_seconds"])
        near = np.abs(times - boundary) <= 1.0
        gain_db[near] *= 0.45
    band_limits = {
        "sub_20_60": (1.45, 1.30),
        "bass_60_120": (1.55, 1.10),
        "low_mid_120_500": (1.70, 1.00),
        "mid_500_2000": (2.00, 0.75),
        "presence_2000_6000": (1.75, 1.05),
        "high_6000_12000": (2.15, 0.80),
    }
    eq_curves: dict[str, np.ndarray] = {}
    for name in BAND_RANGES:
        values = np.asarray([
            max(float((point.get("bands_percent") or {}).get(name, 0.0)), 1e-6)
            for point in points
        ], dtype=np.float64)
        baseline = _rolling_median(values, 5)
        deviation_db = 10.0 * np.log10(np.maximum(values, 1e-9) / np.maximum(baseline, 1e-9))
        threshold, max_cut = band_limits[name]
        correction = -0.33 * np.maximum(deviation_db - threshold, 0.0)
        correction = np.clip(correction, -max_cut, 0.0)
        correction[rms < -42.0] = 0.0
        eq_curves[name] = _smooth_series(correction, 2)
    return times, gain_db, eq_curves


def _apply_adaptive_processing(audio: np.ndarray, sample_rate: int, timeline: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    times, gain_db, eq_curves = _adaptive_curves(timeline)
    frame_size = 4096
    hop = frame_size // 2
    pad = frame_size // 2
    window = np.sqrt(np.hanning(frame_size).astype(np.float64))
    padded = np.pad(audio.astype(np.float32, copy=False), ((pad, pad), (0, 0)))
    accumulator = np.zeros_like(padded, dtype=np.float32)
    normalization = np.zeros(len(padded), dtype=np.float32)
    frequencies = np.fft.rfftfreq(frame_size, d=1.0 / sample_rate)
    positive = frequencies > 0.0
    log_frequencies = np.zeros_like(frequencies)
    log_frequencies[positive] = np.log2(frequencies[positive])
    band_names = list(BAND_RANGES)
    centers = np.asarray([20.0] + [BAND_CENTERS[name] for name in band_names] + [min(20000.0, sample_rate / 2.0)], dtype=np.float64)
    log_centers = np.log2(np.maximum(centers, 1.0))
    duration = len(audio) / float(sample_rate)
    for start in range(0, max(1, len(padded) - frame_size + 1), hop):
        frame = padded[start:start + frame_size].astype(np.float64, copy=False)
        if len(frame) < frame_size:
            break
        center_time = float(np.clip((start + frame_size / 2.0 - pad) / sample_rate, 0.0, duration))
        band_gain_values = [
            float(np.interp(center_time, times, eq_curves[name], left=eq_curves[name][0], right=eq_curves[name][-1]))
            for name in band_names
        ]
        control_gains = np.asarray([0.0] + band_gain_values + [0.0], dtype=np.float64)
        response_db = np.interp(log_frequencies, log_centers, control_gains)
        response_db[~positive] = 0.0
        response = np.power(10.0, response_db / 20.0)
        spectrum = np.fft.rfft(frame * window[:, None], axis=0)
        processed = np.fft.irfft(spectrum * response[:, None], n=frame_size, axis=0)
        processed *= window[:, None]
        accumulator[start:start + frame_size] += processed.astype(np.float32)
        normalization[start:start + frame_size] += np.square(window).astype(np.float32)
    normal = np.maximum(normalization[pad:pad + len(audio)], 1e-8)
    result = accumulator[pad:pad + len(audio)] / normal[:, None]
    anchors_t = np.concatenate(([0.0], times, [duration]))
    anchors_g = np.concatenate(([gain_db[0]], gain_db, [gain_db[-1]]))
    chunk = 1_000_000
    for start in range(0, len(result), chunk):
        end = min(len(result), start + chunk)
        sample_times = np.arange(start, end, dtype=np.float64) / sample_rate
        envelope_db = np.interp(sample_times, anchors_t, anchors_g)
        result[start:end] *= np.power(10.0, envelope_db / 20.0)[:, None].astype(np.float32)
    if not np.all(np.isfinite(result)):
        raise RuntimeError("Adaptive processing produced non-finite audio")
    peak = float(np.max(np.abs(result))) if result.size else 0.0
    safety_trim_db = 0.0
    if peak > 0.98:
        safety_trim_db = 20.0 * math.log10(0.98 / peak)
        result *= float(10.0 ** (safety_trim_db / 20.0))
    eq_report = {
        name: {
            "max_cut_db": round(float(np.min(curve)), 3),
            "mean_cut_db": round(float(np.mean(curve)), 3),
        }
        for name, curve in eq_curves.items()
    }
    report = {
        "engine_version": ADAPTIVE_ENGINE_VERSION,
        "principle": "Preserve section-level macro dynamics; correct only local residuals around each section trajectory.",
        "section_count": int((timeline.get("summary") or {}).get("section_count", 0)),
        "intentional_trajectories": {
            "rising": int((timeline.get("summary") or {}).get("rising_sections", 0)),
            "falling": int((timeline.get("summary") or {}).get("falling_sections", 0)),
        },
        "gain_ride": {
            "max_boost_db": round(float(np.max(gain_db)), 3),
            "max_cut_db": round(float(np.min(gain_db)), 3),
            "mean_absolute_db": round(float(np.mean(np.abs(gain_db))), 3),
        },
        "dynamic_eq": eq_report,
        "safety_trim_db": round(float(safety_trim_db), 3),
        "sections": timeline.get("sections") or [],
    }
    return result.astype(np.float32, copy=False), report


def _write_float_wav(audio: np.ndarray, sample_rate: int, destination: Path) -> None:
    raw_path = destination.with_suffix(".f32")
    raw_path.write_bytes(audio.astype("<f4", copy=False).tobytes())
    try:
        proc = _run([
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-f", "f32le", "-ar", str(sample_rate), "-ac", "2", "-i", str(raw_path),
            "-c:a", "pcm_f32le", str(destination),
        ], timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"Adaptive intermediate encode failed: {(proc.stderr or proc.stdout)[-1800:]}")
    finally:
        raw_path.unlink(missing_ok=True)


def _adaptive_prepare(input_path: Path, destination: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    audio = _decode_float_audio(input_path, 48000)
    timeline = _timeline_from_audio(audio, 48000)
    processed, report = _apply_adaptive_processing(audio, 48000, timeline)
    _write_float_wav(processed, 48000, destination)
    return timeline, report


def store_upload(filename: str, audio_file: bytes) -> dict[str, Any]:
    if not isinstance(audio_file, (bytes, bytearray)):
        raise TypeError("audio_file must be binary audio data")
    size = len(audio_file)
    if size <= 0:
        raise ValueError("Uploaded audio is empty")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"Audio exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
    safe = _safe_name(filename)
    suffix = Path(safe).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported audio extension: {suffix or 'none'}")
    asset_id = uuid.uuid4().hex
    folder = UPLOAD_ROOT / asset_id
    folder.mkdir(parents=True, mode=0o750)
    path = folder / safe
    path.write_bytes(bytes(audio_file))
    info = probe(path)
    meta = {
        "asset_id": asset_id,
        "filename": safe,
        "input_path": str(path),
        "created_at": int(time.time()),
        "probe": info,
        "analysis": None,
        "outputs": [],
    }
    _write_meta(meta)
    return {"ok": True, "asset_id": asset_id, "filename": safe, "probe": info}


def analyze(asset_id: str, force: bool = False) -> dict[str, Any]:
    meta = _read_meta(asset_id)
    cached = meta.get("analysis")
    if cached and int(cached.get("analysis_version") or 0) >= ANALYSIS_VERSION and not force:
        return {"ok": True, "asset_id": meta["asset_id"], "cached": True, "analysis": cached}
    path = _input_path(meta)
    report = {
        "analysis_version": ANALYSIS_VERSION,
        "engine_version": ADAPTIVE_ENGINE_VERSION,
        "probe": probe(path),
        "loudness": loudness(path),
        "technical": _technical_stats(path),
        "timeline": _timeline_stats(path),
        "analyzed_at": int(time.time()),
    }
    meta["analysis"] = report
    _write_meta(meta)
    return {"ok": True, "asset_id": meta["asset_id"], "cached": False, "analysis": report}


def _profile_filters(profile: str) -> tuple[str, str]:
    key = str(profile or "transparent").strip().lower()
    profiles = {
        "adaptive": ("highpass=f=20", "Adaptive: section-aware gain riding and time-varying spectral control while preserving intentional macro dynamics."),
        "transparent": ("highpass=f=20", "Transparent: subsonic cleanup only before loudness control."),
        "dynamic": ("highpass=f=20,acompressor=threshold=-18dB:ratio=1.18:attack=30:release=220:knee=3dB:makeup=1", "Dynamic: extremely gentle glue compression."),
        "dark_ambient": ("highpass=f=22,equalizer=f=230:t=q:w=0.9:g=-0.6,acompressor=threshold=-20dB:ratio=1.15:attack=40:release=280:knee=3dB:makeup=1", "Dark ambient: restrained low-mid cleanup with slow glue."),
        "none": ("", "No tonal or dynamic preprocessing; loudness stage only."),
    }
    if key not in profiles:
        raise ValueError(f"Unknown profile '{profile}'. Available: {', '.join(profiles)}")
    filters, description = profiles[key]
    return filters, description


def render(asset_id: str, profile: str = "adaptive", target_lufs: float = -14.0, true_peak_dbtp: float = -1.0, label: str = "spotify") -> dict[str, Any]:
    target_lufs = float(target_lufs)
    true_peak_dbtp = float(true_peak_dbtp)
    profile_key = str(profile or "adaptive").strip().lower()
    if not (-18.0 <= target_lufs <= -7.0):
        raise ValueError("target_lufs must be between -18 and -7")
    if not (-3.0 <= true_peak_dbtp <= -0.1):
        raise ValueError("true_peak_dbtp must be between -3.0 and -0.1")
    meta = _read_meta(asset_id)
    input_path = _input_path(meta)
    filters, description = _profile_filters(profile_key)
    output_id = uuid.uuid4().hex
    out_dir = OUTPUT_ROOT / _validate_id(meta["asset_id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9_-]+", "-", str(label or "master")).strip("-")[:40] or "master"
    output_name = f"{Path(meta['filename']).stem}-{safe_label}-{output_id[:8]}.wav"
    output_path = out_dir / output_name
    adaptive_path = out_dir / f".{output_id}.adaptive.wav"
    render_input = input_path
    source_timeline: dict[str, Any] | None = None
    adaptive_report: dict[str, Any] | None = None
    try:
        if profile_key == "adaptive":
            source_timeline, adaptive_report = _adaptive_prepare(input_path, adaptive_path)
            render_input = adaptive_path
        measured = loudness(render_input, filters, target_lufs, true_peak_dbtp, 11.0)
        chain = []
        if filters:
            chain.append(filters)
        chain.append(
            "loudnorm="
            f"I={target_lufs}:TP={true_peak_dbtp}:LRA=11:"
            f"measured_I={measured['integrated_lufs']}:"
            f"measured_TP={measured['true_peak_dbtp']}:"
            f"measured_LRA={measured['loudness_range_lu']}:"
            f"measured_thresh={measured['threshold_lufs']}:"
            f"offset={measured['target_offset_lu']}:linear=true:print_format=summary"
        )
        proc = _run([
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(render_input),
            "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
            "-fflags", "+bitexact", "-flags:a", "+bitexact",
            "-af", ",".join(chain),
            "-ar", "48000", "-c:a", "pcm_s24le", str(output_path),
        ], timeout=1200)
        if proc.returncode != 0:
            output_path.unlink(missing_ok=True)
            raise RuntimeError(f"Master render failed: {(proc.stderr or proc.stdout)[-2400:]}")
    finally:
        adaptive_path.unlink(missing_ok=True)
        adaptive_path.with_suffix(".f32").unlink(missing_ok=True)
    output_report = {
        "analysis_version": ANALYSIS_VERSION,
        "engine_version": ADAPTIVE_ENGINE_VERSION if profile_key == "adaptive" else "legacy-static",
        "probe": probe(output_path),
        "loudness": loudness(output_path),
        "technical": _technical_stats(output_path),
        "timeline": _timeline_stats(output_path),
    }
    item = {
        "output_id": output_id,
        "filename": output_name,
        "path": str(output_path),
        "profile": profile_key,
        "profile_description": description,
        "target_lufs": target_lufs,
        "true_peak_target_dbtp": true_peak_dbtp,
        "created_at": int(time.time()),
        "clean_export": {
            "version": CLEAN_EXPORT_VERSION,
            "container_metadata": "stripped",
            "chapters": "stripped",
            "deterministic_muxing": True,
            "proprietary_audio_watermark": "not claimed removed",
        },
        "source_timeline": source_timeline,
        "adaptive": adaptive_report,
        "report": output_report,
    }
    outputs = list(meta.get("outputs") or [])
    outputs.append(item)
    meta["outputs"] = outputs[-50:]
    _write_meta(meta)
    return {"ok": True, "asset_id": meta["asset_id"], "output": _safe_output_item(item)}



def _validate_share_token(value: str) -> str:
    token = str(value or "").strip()
    if not SHARE_TOKEN_RE.fullmatch(token):
        raise ValueError("Invalid share token")
    return token


def _share_path(token: str) -> Path:
    return SHARE_ROOT / f"{_validate_share_token(token)}.json"


def _find_output(meta: dict[str, Any], output_id: str) -> dict[str, Any]:
    target = _validate_id(output_id, "output_id")
    for item in meta.get("outputs") or []:
        if str(item.get("output_id") or "") == target:
            return item
    raise FileNotFoundError(f"Unknown output: {output_id}")


def _safe_share(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": entry.get("token"),
        "created_at": entry.get("created_at"),
        "expires_at": entry.get("expires_at"),
    }


def _safe_output_item(item: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(item))
    result.pop("path", None)
    result.pop("source_timeline", None)
    adaptive = result.get("adaptive")
    if isinstance(adaptive, dict):
        adaptive.pop("sections", None)
    report = result.get("report")
    if isinstance(report, dict):
        timeline = report.get("timeline")
        if isinstance(timeline, dict):
            report["timeline"] = {
                "version": timeline.get("version"),
                "duration_seconds": timeline.get("duration_seconds"),
                "summary": timeline.get("summary") or {},
                "sections": timeline.get("sections") or [],
            }
    derivatives = result.get("derivatives")
    if isinstance(derivatives, dict):
        for key, derivative in list(derivatives.items()):
            if isinstance(derivative, dict) and derivative.get("private_preview"):
                derivatives.pop(key, None)
            elif isinstance(derivative, dict):
                derivative.pop("path", None)
    result["shares"] = [
        _safe_share(entry) for entry in (result.get("shares") or [])
        if isinstance(entry, dict)
    ]
    return result


def _write_share(entry: dict[str, Any]) -> None:
    path = _share_path(str(entry.get("token") or ""))
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_share(token: str) -> dict[str, Any]:
    path = _share_path(token)
    if not path.exists():
        raise FileNotFoundError("Share link is unavailable")
    entry = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entry, dict):
        raise ValueError("Share record is invalid")
    if int(entry.get("expires_at") or 0) <= int(time.time()):
        path.unlink(missing_ok=True)
        raise FileNotFoundError("Share link has expired")
    return entry


def _remove_shares_for(asset_id: str, output_id: str | None = None) -> int:
    removed = 0
    for path in SHARE_ROOT.glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if str(entry.get("asset_id") or "") != asset_id:
                continue
            if output_id is not None and str(entry.get("output_id") or "") != output_id:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except Exception:
            continue
    return removed


def ensure_mp3(asset_id: str, output_id: str) -> dict[str, Any]:
    meta = _read_meta(asset_id)
    item = _find_output(meta, output_id)
    derivatives = item.setdefault("derivatives", {})
    existing = derivatives.get("mp3_320")
    if isinstance(existing, dict):
        existing_path = Path(str(existing.get("path") or "")).resolve()
        expected = (OUTPUT_ROOT / _validate_id(meta["asset_id"])).resolve()
        clean_version = int(existing.get("clean_export_version") or 0)
        if (
            expected in existing_path.parents
            and existing_path.is_file()
            and clean_version >= CLEAN_EXPORT_VERSION
        ):
            return existing
    wav_path = Path(str(item.get("path") or "")).resolve()
    expected = (OUTPUT_ROOT / _validate_id(meta["asset_id"])).resolve()
    if expected not in wav_path.parents or not wav_path.is_file():
        raise FileNotFoundError("Master WAV is missing")
    filename = f"{wav_path.stem}-320.mp3"
    mp3_path = wav_path.with_name(filename)
    proc = _run([
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(wav_path),
        "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
        "-fflags", "+bitexact", "-flags:a", "+bitexact",
        "-c:a", "libmp3lame", "-b:a", "320k",
        "-ar", "48000", "-write_xing", "0",
        "-id3v2_version", "0", "-write_id3v1", "0", str(mp3_path),
    ], timeout=900)
    if proc.returncode != 0:
        mp3_path.unlink(missing_ok=True)
        raise RuntimeError(f"MP3 export failed: {(proc.stderr or proc.stdout)[-1800:]}")
    info = {
        "format": "mp3",
        "quality": "320k",
        "filename": filename,
        "path": str(mp3_path),
        "size_bytes": mp3_path.stat().st_size,
        "created_at": int(time.time()),
        "clean_export_version": CLEAN_EXPORT_VERSION,
        "metadata_policy": "all optional metadata and encoder-identifying headers stripped",
        "probe": probe(mp3_path),
    }
    derivatives["mp3_320"] = info
    _write_meta(meta)
    return info


def ensure_preview_mp3(asset_id: str, output_id: str) -> dict[str, Any]:
    """Create a private Safari-compatible preview; never use it for downloads."""
    meta = _read_meta(asset_id)
    item = _find_output(meta, output_id)
    derivatives = item.setdefault("derivatives", {})
    existing = derivatives.get("mp3_preview")
    expected = (OUTPUT_ROOT / _validate_id(meta["asset_id"])).resolve()
    if isinstance(existing, dict):
        existing_path = Path(str(existing.get("path") or "")).resolve()
        preview_version = int(existing.get("preview_export_version") or 0)
        if (
            expected in existing_path.parents
            and existing_path.is_file()
            and preview_version >= PREVIEW_EXPORT_VERSION
        ):
            return existing
    wav_path = Path(str(item.get("path") or "")).resolve()
    if expected not in wav_path.parents or not wav_path.is_file():
        raise FileNotFoundError("Master WAV is missing")
    filename = f".{wav_path.stem}.preview.mp3"
    preview_path = wav_path.with_name(filename)
    proc = _run([
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(wav_path),
        "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
        "-fflags", "+bitexact", "-flags:a", "+bitexact",
        "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "48000",
        "-write_xing", "1", "-id3v2_version", "0", "-write_id3v1", "0",
        str(preview_path),
    ], timeout=900)
    if proc.returncode != 0:
        preview_path.unlink(missing_ok=True)
        raise RuntimeError(f"Preview MP3 export failed: {(proc.stderr or proc.stdout)[-1800:]}")
    info = {
        "format": "mp3",
        "quality": "320k",
        "filename": filename,
        "path": str(preview_path),
        "size_bytes": preview_path.stat().st_size,
        "created_at": int(time.time()),
        "preview_export_version": PREVIEW_EXPORT_VERSION,
        "private_preview": True,
        "compatibility_header": "Xing/LAME",
        "distribution_policy": "internal playback only",
        "probe": probe(preview_path),
    }
    derivatives["mp3_preview"] = info
    _write_meta(meta)
    return info


def _decoded_pcm_sha256(path: Path) -> str:
    proc = _run([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-c:a", "pcm_s24le", "-f", "hash", "-hash", "sha256", "-",
    ], timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"PCM verification failed: {(proc.stderr or proc.stdout)[-1600:]}")
    value = (proc.stdout or "").strip()
    if not value.startswith("SHA256="):
        raise RuntimeError("PCM verification returned an invalid hash")
    return value.removeprefix("SHA256=").lower()


def clean_existing_outputs(asset_id: str) -> dict[str, Any]:
    """Losslessly rewrap stored WAV masters without container metadata."""
    meta = _read_meta(asset_id)
    expected = (OUTPUT_ROOT / _validate_id(meta["asset_id"])).resolve()
    cleaned: list[dict[str, Any]] = []
    for item in meta.get("outputs") or []:
        wav_path = Path(str(item.get("path") or "")).resolve()
        if expected not in wav_path.parents or not wav_path.is_file() or wav_path.suffix.lower() != ".wav":
            continue
        before_hash = _decoded_pcm_sha256(wav_path)
        temp_path = wav_path.with_name(f".{wav_path.name}.{uuid.uuid4().hex}.clean.wav")
        original_stat = wav_path.stat()
        try:
            proc = _run([
                "ffmpeg", "-y", "-v", "error", "-i", str(wav_path),
                "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
                "-fflags", "+bitexact", "-flags:a", "+bitexact",
                "-c:a", "copy", str(temp_path),
            ], timeout=900)
            if proc.returncode != 0:
                raise RuntimeError(f"Clean WAV rewrap failed: {(proc.stderr or proc.stdout)[-1600:]}")
            after_hash = _decoded_pcm_sha256(temp_path)
            if after_hash != before_hash:
                raise RuntimeError(f"PCM mismatch while cleaning {wav_path.name}")
            os.chmod(temp_path, original_stat.st_mode & 0o7777)
            try:
                os.chown(temp_path, original_stat.st_uid, original_stat.st_gid)
            except PermissionError:
                pass
            os.replace(temp_path, wav_path)
        finally:
            temp_path.unlink(missing_ok=True)
        item["clean_export"] = {
            "version": CLEAN_EXPORT_VERSION,
            "container_metadata": "stripped",
            "chapters": "stripped",
            "deterministic_muxing": True,
            "pcm_sha256": before_hash,
            "pcm_verified_unchanged": True,
            "proprietary_audio_watermark": "not claimed removed",
        }
        report = item.get("report")
        if isinstance(report, dict):
            report["probe"] = probe(wav_path)
        cleaned.append({
            "output_id": item.get("output_id"),
            "filename": wav_path.name,
            "pcm_sha256": before_hash,
            "size_bytes": wav_path.stat().st_size,
        })
    _write_meta(meta)
    return {"ok": True, "asset_id": meta["asset_id"], "cleaned": cleaned}


def ab_comparison(asset_id: str, output_id: str) -> dict[str, Any]:
    """Return measured source/master data and the actual adaptive processing map."""
    meta = _read_meta(asset_id)
    item = _find_output(meta, output_id)
    analysis = meta.get("analysis")
    if not isinstance(analysis, dict):
        analysis = analyze(asset_id).get("analysis") or {}

    source_loudness = analysis.get("loudness") or {}
    source_technical = analysis.get("technical") or {}
    source_timeline = analysis.get("timeline") or item.get("source_timeline") or {}
    master_report = item.get("report") or {}
    master_loudness = master_report.get("loudness") or {}
    master_technical = master_report.get("technical") or {}
    master_timeline = master_report.get("timeline") or {}
    source_energy = ((source_technical.get("spectrum") or {}).get("energy_percent") or {})
    master_energy = ((master_technical.get("spectrum") or {}).get("energy_percent") or {})

    labels = {
        "sub_20_60": "SUB",
        "bass_60_120": "BASS",
        "low_mid_120_500": "LOW MID",
        "mid_500_2000": "MID",
        "presence_2000_6000": "PRESENCE",
        "high_6000_12000": "AIR",
    }
    bands = []
    for key, (low_hz, high_hz) in BAND_RANGES.items():
        source_value = max(float(source_energy.get(key) or 0.0), 1e-9)
        master_value = max(float(master_energy.get(key) or 0.0), 1e-9)
        bands.append({
            "key": key,
            "label": labels.get(key, key),
            "low_hz": low_hz,
            "high_hz": high_hz,
            "center_hz": BAND_CENTERS.get(key),
            "source_percent": round(source_value, 4),
            "master_percent": round(master_value, 4),
            "tonal_delta_db": round(10.0 * math.log10(master_value / source_value), 3),
        })

    source_points = list(source_timeline.get("points") or [])
    master_points = list(master_timeline.get("points") or [])
    dynamics = []
    point_count = min(len(source_points), len(master_points))
    if point_count:
        selected = np.unique(
            np.linspace(0, point_count - 1, min(point_count, 96), dtype=int)
        )
        for index in selected:
            source_point = source_points[int(index)]
            master_point = master_points[int(index)]
            source_rms = float(source_point.get("short_rms_dbfs") or -120.0)
            master_rms = float(master_point.get("short_rms_dbfs") or -120.0)
            dynamics.append({
                "t": round(float(source_point.get("t") or master_point.get("t") or 0.0), 3),
                "source_rms_dbfs": round(source_rms, 3),
                "master_rms_dbfs": round(master_rms, 3),
                "delta_db": round(master_rms - source_rms, 3),
            })

    adaptive = item.get("adaptive") or {}
    processing_map: dict[str, Any] = {
        "mode": "global",
        "duration_seconds": float(source_timeline.get("duration_seconds") or 0.0),
        "points": [],
        "dynamic_eq_summary": adaptive.get("dynamic_eq") or {},
        "gain_ride_summary": adaptive.get("gain_ride") or {},
    }
    if str(item.get("profile") or "") == "adaptive" and source_timeline.get("points"):
        times, gain_db, eq_curves = _adaptive_curves(source_timeline)
        selected = np.unique(
            np.linspace(0, len(times) - 1, min(len(times), 96), dtype=int)
        )
        map_points = []
        for index in selected:
            i = int(index)
            map_points.append({
                "t": round(float(times[i]), 3),
                "gain_db": round(float(gain_db[i]), 3),
                "bands": {
                    key: round(float(eq_curves[key][i]), 3)
                    for key in BAND_RANGES
                },
            })
        processing_map = {
            "mode": "adaptive",
            "duration_seconds": float(source_timeline.get("duration_seconds") or 0.0),
            "points": map_points,
            "dynamic_eq_summary": adaptive.get("dynamic_eq") or {},
            "gain_ride_summary": adaptive.get("gain_ride") or {},
        }

    return {
        "asset_id": meta["asset_id"],
        "output_id": item["output_id"],
        "profile": item.get("profile") or "master",
        "section_count": adaptive.get("section_count"),
        "source": {
            "label": "A · ORIGINAL",
            "loudness": source_loudness,
            "spectral_centroid_hz": (source_technical.get("spectrum") or {}).get("spectral_centroid_hz"),
        },
        "master": {
            "label": "B · MASTER",
            "loudness": master_loudness,
            "spectral_centroid_hz": (master_technical.get("spectrum") or {}).get("spectral_centroid_hz"),
        },
        "bands": bands,
        "dynamics": dynamics,
        "processing_map": processing_map,
        "spectrum_note": "Whole-track relative spectral energy; processing map shows actual adaptive EQ decisions over time.",
    }


def ensure_source_preview(asset_id: str) -> dict[str, Any]:
    """Create a private Safari-compatible MP3 preview of the untouched source."""
    meta = _read_meta(asset_id)
    source_path = _input_path(meta)
    derivatives = meta.setdefault("source_derivatives", {})
    cached = derivatives.get("mp3_preview")
    if isinstance(cached, dict):
        cached_path = Path(str(cached.get("path") or "")).resolve()
        expected = (UPLOAD_ROOT / _validate_id(meta["asset_id"])).resolve()
        if (
            expected in cached_path.parents
            and cached_path.is_file()
            and int(cached.get("preview_export_version") or 0) >= PREVIEW_EXPORT_VERSION
        ):
            return cached

    preview_name = f".{source_path.stem}.source-preview-v{PREVIEW_EXPORT_VERSION}.mp3"
    preview_path = source_path.parent / preview_name
    proc = _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source_path),
        "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
        "-vn", "-sn", "-dn",
        "-fflags", "+bitexact", "-flags:a", "+bitexact",
        "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "48000",
        "-write_xing", "1", "-id3v2_version", "0", "-write_id3v1", "0",
        str(preview_path),
    ], timeout=900)
    if proc.returncode != 0:
        preview_path.unlink(missing_ok=True)
        raise RuntimeError(f"Source preview export failed: {(proc.stderr or proc.stdout)[-1800:]}")

    info = {
        "format": "mp3",
        "quality": "320k",
        "filename": preview_name,
        "path": str(preview_path),
        "size_bytes": preview_path.stat().st_size,
        "created_at": int(time.time()),
        "preview_export_version": PREVIEW_EXPORT_VERSION,
        "private_preview": True,
        "source_untouched": True,
        "compatibility_header": "Xing/LAME",
        "distribution_policy": "internal A/B playback only",
        "probe": probe(preview_path),
    }
    derivatives["mp3_preview"] = info
    _write_meta(meta)
    return info


def resolve_source_file(asset_id: str, file_format: str = "preview") -> dict[str, Any]:
    fmt = str(file_format or "preview").strip().lower()
    if fmt not in {"preview", "mp3_preview"}:
        raise ValueError("source format must be preview")
    meta = _read_meta(asset_id)
    expected = (UPLOAD_ROOT / _validate_id(meta["asset_id"])).resolve()
    source_path = _input_path(meta).resolve()

    # For an uploaded MP3, A/B must play the exact uploaded bytes. Besides being
    # the most honest comparison, this avoids an unnecessary lossy generation.
    if source_path.suffix.lower() == ".mp3":
        if expected not in source_path.parents or not source_path.is_file():
            raise FileNotFoundError("Original source is missing")
        return {
            "path": str(source_path),
            "filename": Path(str(meta.get("filename") or source_path.name)).name,
            "media_type": "audio/mpeg",
            "size_bytes": source_path.stat().st_size,
            "format": "original",
            "asset_id": meta["asset_id"],
            "source_exact_upload": True,
        }

    derivative = ensure_source_preview(asset_id)
    path = Path(str(derivative.get("path") or "")).resolve()
    if expected not in path.parents or not path.is_file():
        raise FileNotFoundError("Source preview is missing")
    return {
        "path": str(path),
        "filename": f"{Path(str(meta.get('filename') or 'source')).stem}-original-preview.mp3",
        "media_type": "audio/mpeg",
        "size_bytes": path.stat().st_size,
        "format": "preview",
        "asset_id": meta["asset_id"],
        "source_exact_upload": False,
    }


def resolve_output_file(asset_id: str, output_id: str, file_format: str = "wav") -> dict[str, Any]:
    fmt = str(file_format or "wav").strip().lower()
    meta = _read_meta(asset_id)
    item = _find_output(meta, output_id)
    if fmt == "mp3":
        derivative = ensure_mp3(asset_id, output_id)
        path = Path(str(derivative.get("path") or "")).resolve()
        filename = str(derivative.get("filename") or "master.mp3")
        media_type = "audio/mpeg"
    elif fmt in {"preview", "mp3_preview"}:
        derivative = ensure_preview_mp3(asset_id, output_id)
        path = Path(str(derivative.get("path") or "")).resolve()
        filename = str(derivative.get("filename") or "preview.mp3")
        media_type = "audio/mpeg"
        fmt = "preview"
    elif fmt == "wav":
        path = Path(str(item.get("path") or "")).resolve()
        filename = str(item.get("filename") or "master.wav")
        media_type = "audio/wav"
    else:
        raise ValueError("format must be wav, mp3 or preview")
    expected = (OUTPUT_ROOT / _validate_id(meta["asset_id"])).resolve()
    if expected not in path.parents or not path.is_file():
        raise FileNotFoundError("Master output is missing")
    return {
        "path": str(path),
        "filename": Path(filename).name,
        "media_type": media_type,
        "size_bytes": path.stat().st_size,
        "format": fmt,
        "asset_id": meta["asset_id"],
        "output_id": item["output_id"],
    }


def delete_output(asset_id: str, output_id: str) -> dict[str, Any]:
    meta = _read_meta(asset_id)
    item = _find_output(meta, output_id)
    aid = _validate_id(meta["asset_id"])
    oid = _validate_id(str(item.get("output_id") or ""), "output_id")
    expected = (OUTPUT_ROOT / aid).resolve()
    removed_files: list[str] = []
    candidates = [item.get("path")]
    for derivative in (item.get("derivatives") or {}).values():
        if isinstance(derivative, dict):
            candidates.append(derivative.get("path"))
    for raw in candidates:
        if not raw:
            continue
        path = Path(str(raw)).resolve()
        if expected in path.parents and path.is_file():
            removed_files.append(path.name)
            path.unlink(missing_ok=True)
    shares_removed = _remove_shares_for(aid, oid)
    meta["outputs"] = [
        row for row in (meta.get("outputs") or [])
        if str(row.get("output_id") or "") != oid
    ]
    _write_meta(meta)
    return {
        "ok": True,
        "asset_id": aid,
        "output_id": oid,
        "deleted": True,
        "removed_files": removed_files,
        "shares_removed": shares_removed,
    }


def create_share(asset_id: str, output_id: str, expires_days: int = 30) -> dict[str, Any]:
    days = max(1, min(int(expires_days), 90))
    meta = _read_meta(asset_id)
    item = _find_output(meta, output_id)
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    entry = {
        "token": token,
        "asset_id": _validate_id(meta["asset_id"]),
        "output_id": _validate_id(str(item.get("output_id") or ""), "output_id"),
        "created_at": now,
        "expires_at": now + days * 86400,
    }
    _write_share(entry)
    shares = [
        row for row in (item.get("shares") or [])
        if isinstance(row, dict) and int(row.get("expires_at") or 0) > now
    ]
    shares.append(_safe_share(entry))
    item["shares"] = shares[-10:]
    _write_meta(meta)
    return {"ok": True, **_safe_share(entry)}


def resolve_share(token: str) -> dict[str, Any]:
    entry = _read_share(token)
    meta = _read_meta(str(entry.get("asset_id") or ""))
    item = _find_output(meta, str(entry.get("output_id") or ""))
    return {
        "share": entry,
        "asset": {
            "asset_id": meta.get("asset_id"),
            "filename": meta.get("filename"),
        },
        "output": _safe_output_item(item),
    }


def revoke_share(token: str) -> dict[str, Any]:
    entry = _read_share(token)
    path = _share_path(token)
    path.unlink(missing_ok=True)
    try:
        meta = _read_meta(str(entry.get("asset_id") or ""))
        item = _find_output(meta, str(entry.get("output_id") or ""))
        item["shares"] = [
            row for row in (item.get("shares") or [])
            if str((row or {}).get("token") or "") != token
        ]
        _write_meta(meta)
    except Exception:
        pass
    return {"ok": True, "token": token, "revoked": True}


def list_assets(limit: int = 30) -> dict[str, Any]:
    rows = []
    for path in sorted(META_ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, min(int(limit), 100))]:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            rows.append({
                "asset_id": meta.get("asset_id"),
                "filename": meta.get("filename"),
                "created_at": meta.get("created_at"),
                "probe": meta.get("probe"),
                "analyzed": bool(meta.get("analysis")),
                "analysis_summary": ((meta.get("analysis") or {}).get("timeline") or {}).get("summary") or {},
                "outputs": [_safe_output_item(item) for item in (meta.get("outputs") or [])],
            })
        except Exception:
            continue
    return {"ok": True, "count": len(rows), "assets": rows}


def output_bytes(asset_id: str, output_id: str, file_format: str = "wav") -> bytes:
    resolved = resolve_output_file(asset_id, output_id, file_format)
    return Path(str(resolved["path"])).read_bytes()


def delete_asset(asset_id: str) -> dict[str, Any]:
    meta = _read_meta(asset_id)
    aid = _validate_id(meta["asset_id"])
    shares_removed = _remove_shares_for(aid)
    shutil.rmtree(UPLOAD_ROOT / aid, ignore_errors=True)
    shutil.rmtree(OUTPUT_ROOT / aid, ignore_errors=True)
    _meta_path(aid).unlink(missing_ok=True)
    return {"ok": True, "asset_id": aid, "deleted": True, "shares_removed": shares_removed}
