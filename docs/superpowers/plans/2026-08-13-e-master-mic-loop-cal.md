# E-MASTER MIC LOOP Calibration Draft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-cost draft acoustic feedback calibration that plays a fixed 20-second mastered excerpt through an earbud, records it with the phone microphone, subtracts background confidence, checks bass seal repeatability, and detects playback-chain nonlinear changes across stress levels.

**Architecture:** The browser records five bounded states: background, baseline A, baseline B, stress, with all music recordings using the exact same excerpt. The server never treats the phone microphone as an absolute SPL/FR instrument; it compares the physical chain against itself. Background establishes per-band trust, two baselines establish measurement repeatability and low-frequency seal stability, and stress is gain-normalized before spectral residuals are compared against the baseline variance. A result is invalid/low-confidence if the microphone clips, bass seal is unstable, or the useful band is too close to background noise.

**Tech Stack:** Python 3.12, NumPy, FFmpeg, FastMCP HTTP routes, Web Audio API, MediaRecorder/getUserMedia, pytest.

## Global Constraints

- User-facing name is **E-MASTER**.
- Keep MCP mastering panel headless; MIC LOOP is a standalone draft browser route.
- Never restart production mastering service on port 8792; preview only on port 8800.
- No claim of laboratory THD, absolute SPL, or calibrated frequency response.
- Do not literally subtract the background waveform from the recording. Use background as a per-band confidence/noise mask.
- Bass measurements require a repeatable earbud-to-mic seal. Two same-level baselines must agree before bass data is trusted.
- Same 20-second excerpt and same playback gain for BASELINE A/B.
- Stress comparison normalizes overall level before looking for new spectral shape/residuals.
- If microphone input approaches clipping, the run is invalid for physical-distortion attribution.
- Playback and recording must stop on page hide/page exit.

---

### Task 1: Background, repeatability, and seal analysis

**Files:**
- Modify: `runtime/mastering.py`
- Modify: `tests/test_mastering_track_stress.py`

**Interfaces:**
- `_mic_measurement_levels(audio, sample_rate) -> dict`
- `_mic_loop_baseline_analysis(background, baseline_a, baseline_b, sample_rate) -> dict`
- `_mic_loop_compare(background, baseline_a, baseline_b, stress, sample_rate) -> dict`

- [ ] Write RED tests: a background-dominated band is untrusted; equal bass baselines are `SEAL STABLE`; a bass amplitude collapse is `SEAL UNSTABLE`.
- [ ] Implement per-band background SNR and baseline repeatability.
- [ ] Write RED test: pure gain is clean after normalization, an injected new high-frequency component is flagged.
- [ ] Implement gain-normalized stress residuals and microphone clipping risk.
- [ ] Run focused tests and commit.

### Task 2: Decode microphone recordings and expose HTTP analysis

**Files:**
- Modify: `runtime/mastering.py`
- Modify: `runtime/mastering_mcp_server.py`
- Modify: `tests/test_mastering_calibration_route.py`

**Interfaces:**
- `POST /api/calibration/mic-loop/analyze` multipart: `background`, `baseline_a`, `baseline_b`, optional `stress`.

- [ ] Write RED route-contract test proving HTTP-only/no MCP resource UI metadata.
- [ ] Decode each uploaded recording through FFmpeg to 48 kHz float audio and clean temporary files.
- [ ] Return baseline-only seal/noise report or full stress comparison.
- [ ] Run tests and commit.

### Task 3: Standalone iPhone draft page

**Files:**
- Create: `runtime/mastering_mic_loop.html`
- Modify: `runtime/mastering_mcp_server.py`
- Modify: `tests/test_mastering_calibration_route.py`

**Interfaces:**
- `GET /api/calibration/mic-loop`
- Browser steps: MIC PERMISSION -> BACKGROUND 5s -> BASELINE A 20s -> BASELINE B 20s -> STRESS 20s -> ANALYZE.

- [ ] Write RED route/page token test.
- [ ] Add microphone device selection and request `echoCancellation:false`, `noiseSuppression:false`, `autoGainControl:false` where the browser honors them.
- [ ] Use Web Audio GainNode for controlled digital playback gain.
- [ ] Use one exact 20-second excerpt for all music captures.
- [ ] Stop media/audio tracks on visibility/pagehide.
- [ ] Run tests and commit.

### Task 4: Real preview smoke

**Files:** none unless smoke reveals a defect.

- [ ] Use existing `Ayibobo` asset and its verified Director master; default excerpt 92.5-112.5 s.
- [ ] Run all calibration tests, py_compile, and diff check.
- [ ] Restart only `eiros-mastering-v17-preview.service`.
- [ ] Public page returns 200 and asks for mic permission.
- [ ] User runs physical AirPod-to-phone-mic test and reports whether iOS keeps built-in mic input while playback routes to AirPods.
