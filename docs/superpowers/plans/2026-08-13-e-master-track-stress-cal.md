# E-MASTER Track Stress Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a track-driven calibration mode that maps a real track into the listener/headphone green monitoring corridor, then raises global stress until the first repeatable audible grunt and localizes the limiting frequency band.

**Architecture:** Analyze the source in logarithmic psychoacoustic bands, using robust short-window peaks rather than one-sample maxima. A calibration-only derived preview lifts bands that fall below the listener's measured minimum-audible floor and constrains already-known ceilings without modifying the source/master. After the preview sits inside the known green corridor, one global STRESS gain is raised; on the first repeatable grunt E-MASTER records the gain and ranks the bands with the least remaining normalized headroom. A follow-up isolate/mute check can confirm the culprit, update that band's ceiling, re-normalize the calibration preview, and continue to discover the next limit.

**Tech Stack:** Python 3.12, NumPy, FFmpeg, FastMCP HTTP routes, Web Audio API, pytest.

## Global Constraints

- User-facing product name is **E-MASTER**.
- Keep the MCP mastering UI headless; calibration remains standalone browser UI.
- Deploy only `eiros-mastering-v17-preview.service` on port 8800; never restart production 8792.
- Never modify the uploaded source. All spectral floor/ceiling fitting happens only in a calibration derivative.
- A listener calibration profile affects monitoring trust and stress calibration, not automatic export compensation.
- Use robust band peaks (short-window / percentile) rather than raw FFT-bin maxima or single-sample spikes.
- The stress derivative plus browser gain may never exceed 0 dBFS by construction.
- Hardware volume condition is recorded as `max`; iOS/browser cannot verify hardware volume.
- Stop on discomfort; a first-grunt value is subjective monitoring evidence, not SPL/THD laboratory measurement.

---

### Task 1: Band peak model

**Files:**
- Modify: `runtime/mastering.py`
- Create: `tests/test_mastering_track_stress.py`

**Interfaces:**
- Produces: `_stress_band_profile(audio: np.ndarray, sample_rate: int) -> dict[str, Any]`
- Output bands contain `center_hz`, `low_hz`, `high_hz`, `robust_peak_dbfs`, `persistent_energy_db`, `activity_ratio`, `rank`.

- [ ] Write a failing synthetic-audio test with persistent 63 Hz and 125 Hz content plus a very short 1 kHz transient.
- [ ] Verify RED: persistent bass bands outrank the short transient for stress selection.
- [ ] Implement logarithmic 1/3-octave-style band analysis with 50 ms windows and a high-percentile peak statistic.
- [ ] Verify GREEN and commit `feat: analyze track stress bands`.

### Task 2: Build the calibrated stress plan

**Files:**
- Modify: `runtime/mastering.py`
- Modify: `tests/test_mastering_track_stress.py`

**Interfaces:**
- Produces: `calibration_stress_plan(asset_id: str, calibration_profile: dict[str, Any] | None = None) -> dict[str, Any]`
- Each band returns `track_peak_dbfs`, `min_audible_dbfs`, optional `max_clean_dbfs`, `floor_adjust_db`, `ceiling_adjust_db`, `normalized_peak_dbfs`, `known_headroom_db`, `status`.
- Produces global `safe_stress_max_db` constrained so the derived signal cannot exceed 0 dBFS.

- [ ] Write failing tests for per-band floor fitting and known ceiling fitting.
- [ ] Verify RED.
- [ ] Implement calibration-only spectral plan; do not mutate track/master metadata.
- [ ] Verify GREEN and commit `feat: plan calibrated track stress`.

### Task 3: Render a stress derivative

**Files:**
- Modify: `runtime/mastering.py`
- Modify: `tests/test_mastering_track_stress.py`

**Interfaces:**
- Produces: `render_calibration_stress(asset_id: str, calibration_profile: dict[str, Any] | None = None) -> dict[str, Any]`
- Produces WAV derivative under the asset output tree plus `base_peak_dbfs`, `safe_stress_max_db`, and applied broad-band EQ list.

- [ ] Write a failing render-contract test.
- [ ] Verify RED.
- [ ] Render a short representative high-load excerpt and apply bounded broad-band EQ derived from Task 2.
- [ ] Verify resulting file peak stays below/equal 0 dBFS at `safe_stress_max_db`.
- [ ] Commit `feat: render track stress preview`.

### Task 4: Post-render hot-peak artifact audit

**Files:**
- Modify: `runtime/mastering.py`
- Modify: `tests/test_mastering_track_stress.py`

**Interfaces:**
- Produces: `audit_calibration_stress_render(asset_id: str, stress_path: Path, source_start_seconds: float, duration_seconds: float) -> dict[str, Any]`
- Returns `digital_clean`, `sample_clip_count`, `true_peak_margin_db`, `new_hf_energy_db`, `crest_delta_db`, `hot_windows`, and `reason_codes`.

- [ ] Write a failing test where a clean gain-only derivative passes and a deliberately clipped derivative fails.
- [ ] Verify RED.
- [ ] Compare the exact source excerpt and stress derivative in short windows around their highest peaks; detect sample clipping/near-clipping, excessive new high-frequency energy, abnormal crest collapse, and non-finite samples.
- [ ] Verify GREEN. A user-reported grunt may be attributed to the playback chain only when `digital_clean == true`.
- [ ] Commit `feat: audit stress render peak artifacts`.

### Task 5: HTTP endpoints

**Files:**
- Modify: `runtime/mastering_mcp_server.py`
- Create/modify: `tests/test_mastering_calibration_route.py`

**Interfaces:**
- `POST /api/calibration/stress/prepare` -> plan + derivative metadata
- `GET /api/calibration/stress/audio?asset_id=...` -> derivative audio

- [ ] Write failing route-contract tests proving these are HTTP-only and add no MCP resource URI/output template.
- [ ] Verify RED.
- [ ] Implement routes and CORS/no-store behavior.
- [ ] Verify GREEN and commit `feat: expose track stress calibration api`.

### Task 6: Browser TRACK STRESS mode

**Files:**
- Modify: `runtime/mastering_calibration.html`
- Modify: `tests/test_mastering_calibration_page.py`

**Interfaces:**
- Adds `RANGE` and `TRACK STRESS` modes.
- TRACK STRESS lets user choose an existing asset, prepare stress preview, play/stop, move one `STRESS dB` slider from a conservative start to server-reported `safe_stress_max_db`, and press `FIRST GRUNT`.
- On grunt, UI records `stress_gain_db`, `estimated_output_peak_dbfs`, and server-ranked `suspect_bands`.

- [ ] Write failing UI-contract tests.
- [ ] Verify RED.
- [ ] Implement asset list, prepare action, audio playback, bounded gain, stress slider, and FIRST GRUNT capture.
- [ ] Verify no gain can exceed server safe max.
- [ ] Commit `feat: add track stress calibration ui`.

### Task 7: Culprit localization and profile persistence

**Files:**
- Modify: `runtime/mastering_calibration.html`
- Modify: `tests/test_mastering_calibration_page.py`
- Modify: `tests/test_mastering_calibration_profiles.py`

**Interfaces:**
- After FIRST GRUNT show top suspect bands ordered by normalized headroom.
- User can mark one as confirmed limiting band after a repeatable check.
- Save `track_stress` history in existing calibration profile while preserving older RANGE profiles.

- [ ] Write failing backward-compat/profile tests.
- [ ] Verify RED.
- [ ] Add stress-history schema and load/save migration in browser payload only; backend profile store remains generic JSON.
- [ ] Verify GREEN and commit `feat: persist track stress calibration`.

### Task 8: Preview deployment and validation

**Files:**
- No product source changes unless verification exposes a defect.

- [ ] Run all calibration/stress pytest tests.
- [ ] Run `python -m py_compile` on touched Python modules.
- [ ] Run `git diff --check` and inspect status for generated `.bak-file-replace-*` only; do not delete unrelated user files.
- [ ] Restart only `eiros-mastering-v17-preview.service`.
- [ ] Public smoke: calibration page 200, stress prepare 200 on a real asset, derivative audio 200, health 200, profile round-trip still works.
- [ ] Confirm `open_mastering_panel` remains `panel_enabled:false`.
- [ ] User validates on iPhone: stress gain changes smoothly, no layered audio, backgrounding kills playback, FIRST GRUNT stores the correct gain and suspect bands.
