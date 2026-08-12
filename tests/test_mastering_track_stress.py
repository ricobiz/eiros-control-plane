import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path.cwd()))
from runtime import mastering


def _stereo_tone(freq, amp, seconds, sr=48000):
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    mono = amp * np.sin(2 * np.pi * freq * t)
    return np.column_stack([mono, mono]).astype(np.float32)


def test_stress_band_profile_prefers_persistent_peaks_over_short_transient():
    sr = 48000
    audio = _stereo_tone(63.0, 0.18, 4.0, sr) + _stereo_tone(125.0, 0.11, 4.0, sr)
    transient = _stereo_tone(1000.0, 0.7, 0.035, sr)
    audio[: len(transient)] += transient

    result = mastering._stress_band_profile(audio, sr)

    assert result["bands"]
    top = result["bands"][:6]
    peak_hz = [row["peak_hz"] for row in top]
    assert any(abs(hz - 63.0) < 4.0 for hz in peak_hz)
    assert any(abs(hz - 125.0) < 8.0 for hz in peak_hz)
    one_k = min(result["bands"], key=lambda row: abs(row["peak_hz"] - 1000.0))
    bass_63 = min(result["bands"], key=lambda row: abs(row["peak_hz"] - 63.0))
    assert bass_63["activity_ratio"] > one_k["activity_ratio"]
    assert bass_63["rank"] < one_k["rank"]
    assert result["suspect_bands"][0]["rank"] == 1


def test_mic_loop_noise_profile_masks_background_and_detects_unstable_seal():
    sr = 48000
    seconds = 2.0
    baseline_a = _stereo_tone(63.0, 0.08, seconds, sr) + _stereo_tone(1000.0, 0.02, seconds, sr)
    baseline_b = _stereo_tone(63.0, 0.079, seconds, sr) + _stereo_tone(1000.0, 0.0205, seconds, sr)
    background = _stereo_tone(1000.0, 0.018, seconds, sr)

    stable = mastering._mic_loop_baseline_analysis(background, baseline_a, baseline_b, sr)

    assert stable["background_mask"]["presence_500_2000"]["trusted"] is False
    assert stable["seal_check"]["stable"] is True
    assert stable["seal_check"]["bass_delta_db"] < 1.0

    leaking = _stereo_tone(63.0, 0.035, seconds, sr) + _stereo_tone(1000.0, 0.0205, seconds, sr)
    unstable = mastering._mic_loop_baseline_analysis(background, baseline_a, leaking, sr)
    assert unstable["seal_check"]["stable"] is False
    assert unstable["seal_check"]["bass_delta_db"] > 3.0


def test_mic_loop_stress_comparison_ignores_pure_gain_but_flags_new_spectrum():
    sr = 48000
    seconds = 2.0
    background = _stereo_tone(1000.0, 0.001, seconds, sr)
    baseline_a = _stereo_tone(63.0, 0.05, seconds, sr) + _stereo_tone(500.0, 0.025, seconds, sr)
    baseline_b = _stereo_tone(63.0, 0.0505, seconds, sr) + _stereo_tone(500.0, 0.0245, seconds, sr)
    pure_gain = baseline_a * 1.8

    clean = mastering._mic_loop_compare(background, baseline_a, baseline_b, pure_gain, sr)
    assert clean["artifact_detected"] is False

    nonlinear = pure_gain + _stereo_tone(3000.0, 0.035, seconds, sr)
    flagged = mastering._mic_loop_compare(background, baseline_a, baseline_b, nonlinear, sr)
    assert flagged["artifact_detected"] is True
    assert "high_2000_12000" in flagged["flagged_bands"]


def _wav_bytes(audio, sr=48000):
    import io
    import wave
    mono = np.mean(audio, axis=1)
    pcm = np.clip(mono, -0.999, 0.999)
    pcm = (pcm * 32767.0).astype('<i2').tobytes()
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm)
    return out.getvalue()


def test_analyze_mic_loop_recordings_decodes_uploaded_audio():
    sr = 48000
    seconds = 1.0
    background = _stereo_tone(1000.0, 0.001, seconds, sr)
    a = _stereo_tone(63.0, 0.05, seconds, sr) + _stereo_tone(500.0, 0.02, seconds, sr)
    b = _stereo_tone(63.0, 0.0505, seconds, sr) + _stereo_tone(500.0, 0.0198, seconds, sr)
    stress = a * 1.5
    result = mastering.analyze_mic_loop_recordings({
        'background': ('background.wav', _wav_bytes(background, sr)),
        'baseline_a': ('a.wav', _wav_bytes(a, sr)),
        'baseline_b': ('b.wav', _wav_bytes(b, sr)),
        'stress': ('stress.wav', _wav_bytes(stress, sr)),
    }, sr)
    assert result['ok'] is True
    assert result['mode'] == 'stress'
    assert result['report']['seal_check']['stable'] is True
    assert result['report']['artifact_detected'] is False


def test_mic_loop_seal_repeatability_is_separate_from_bass_snr_confidence():
    sr = 48000
    seconds = 2.0
    # Deliberately poor bass SNR: the room/background already contains almost
    # as much 63 Hz energy as the playback. A/B placement is nevertheless
    # highly repeatable, so SEAL must be stable while bass confidence is low.
    background = _stereo_tone(63.0, 0.045, seconds, sr)
    baseline_a = _stereo_tone(63.0, 0.050, seconds, sr)
    baseline_b = _stereo_tone(63.0, 0.0495, seconds, sr)

    result = mastering._mic_loop_baseline_analysis(background, baseline_a, baseline_b, sr)

    assert result["seal_check"]["bass_delta_db"] < 2.5
    assert result["seal_check"]["stable"] is True
    assert result["seal_check"]["bass_confidence"] == "LOW"
    assert result["seal_check"]["trusted_bass_bands"] == 0
