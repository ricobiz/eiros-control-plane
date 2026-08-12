# E-MASTER 4-Stem Analysis Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cached 4-stem diagnostic analysis (`drums`, `bass`, `vocals`, `other`) so E-MASTER can attribute a suspicious time/frequency region to its dominant musical contributors without changing the export-master path.

**Architecture:** E-MASTER stays the decision layer. Source separation runs out-of-process in an isolated Demucs worker environment so Torch/model memory and dependencies cannot destabilize the mastering MCP process. The main process owns cache/job state, aligned NumPy/FFmpeg feature extraction, attribution, API/UI exposure, and Track Stress/MIC LOOP annotations.

**Tech Stack:** Python 3.12, official maintained Demucs v4 package/fork (`adefossez/demucs`), Torch in isolated worker venv, NumPy/SciPy/FFmpeg in the existing E-MASTER venv, Starlette/FastMCP HTTP routes, pytest.

## Global Constraints

- User-facing product name is **E-MASTER**.
- Phase 1 is **4-stem analysis only**: `drums`, `bass`, `vocals`, `other`.
- Separated stems are diagnostic derivatives and are never substituted into or remixed into the final master.
- Source files are immutable.
- E-MASTER remains the authority that interprets evidence, constructs the mastering plan, verifies the result, and learns monitoring trust.
- External engines may provide evidence but may not silently apply artistic changes to the export master.
- Separation failure must not block ordinary mastering.
- Supported stem states are `STEM_READY`, `STEM_PENDING`, `STEM_UNAVAILABLE`, `STEM_DEGRADED`.
- Cache identity is source hash + provider + model + provider version; separation is not repeated for every Track Stress or MIC LOOP step.
- Stem contribution shares are analytical energy estimates, not perceptual loudness or SPL claims.
- MIC LOOP evidence applies to the corresponding digital source/master window, not to the microphone recording as a stem source.
- No calibration profile may EQ the export master to compensate for listener hearing or headphone limitations.
- Keep the MCP mastering UI headless; any new visual surface is a standalone browser route.
- Deploy only `eiros-mastering-v17-preview.service` on port 8800 during validation; never restart production 8792.
- Current VPS is CPU-only for this purpose: 2 vCPU, 3.7 GiB RAM, no swap. Separation must be single-job and isolated from the main MCP process.

---

## File Structure

- `runtime/mastering_stems.py` — main-process stem cache, state machine, worker launch/status, safe record loading.
- `runtime/mastering_stem_worker.py` — isolated Demucs worker entry point; the only E-MASTER module that imports `demucs`/Torch.
- `runtime/mastering_stem_features.py` — aligned time/frequency feature grid and reconstruction-quality checks using NumPy/FFmpeg only.
- `runtime/mastering_stem_attribution.py` — confidence-scored time/frequency contributor ranking.
- `runtime/mastering_stem_inspector.html` — compact standalone diagnostic UI.
- `runtime/mastering.py` — minimal integration wrappers only; do not add separation internals here.
- `runtime/mastering_mcp_server.py` — HTTP-only prepare/status/query/inspector routes.
- `tests/test_mastering_stems.py` — cache/state/worker-launch/source-immutability tests.
- `tests/test_mastering_stem_features.py` — aligned feature/reconstruction tests.
- `tests/test_mastering_stem_attribution.py` — synthetic attribution tests.
- `tests/test_mastering_track_stress.py` — Track Stress + MIC LOOP annotation integration tests.
- `tests/test_mastering_calibration_route.py` — HTTP-only/headless route contracts.

---

### Task 0: Finish and isolate the in-progress MIC LOOP seal normalization fix

**Files:**
- Modify: `runtime/mastering.py`
- Modify: `tests/test_mastering_track_stress.py`

**Interfaces:**
- Consumes: existing `_mic_loop_baseline_analysis(...)`.
- Produces: `seal_check.raw_bass_delta_db`, `seal_check.input_gain_drift_db`, `seal_check.bass_shape_delta_db`, and `seal_check.stable` based on bass-shape repeatability after common input-gain normalization.

- [ ] **Step 1: Reproduce the already-written RED tests before changing production code**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mastering_track_stress.py::test_mic_loop_seal_ignores_common_input_gain_drift \
  tests/test_mastering_track_stress.py::test_mic_loop_seal_rejects_bass_shape_change_after_gain_normalization -vv
```

Expected: both fail because the current result has no `raw_bass_delta_db` / `bass_shape_delta_db` fields.

- [ ] **Step 2: Implement gain-drift-normalized seal comparison**

Use trusted non-bass bands to estimate the common A→B microphone gain shift, then subtract it before evaluating low-frequency shape drift:

```python
non_bass = ("low_mid_120_500", "presence_500_2000", "high_2000_12000")
reference_deltas = [
    float(b["bands_dbfs"][name]) - float(a["bands_dbfs"][name])
    for name in non_bass
    if mask[name]["trusted"]
]
input_gain_drift_db = float(np.median(reference_deltas)) if reference_deltas else (
    float(b["rms_dbfs"]) - float(a["rms_dbfs"])
)
raw_bass_delta_db = max(
    abs(float(b["bands_dbfs"][name]) - float(a["bands_dbfs"][name]))
    for name in ("sub_20_60", "bass_60_120")
)
bass_shape_delta_db = max(
    abs((float(b["bands_dbfs"][name]) - float(a["bands_dbfs"][name])) - input_gain_drift_db)
    for name in ("sub_20_60", "bass_60_120")
)
seal_stable = bass_shape_delta_db <= 2.5
```

Return all three metrics in `seal_check`; keep `bass_confidence` independent.

- [ ] **Step 3: Verify the two regression tests turn GREEN**

Run the same two-test command. Expected: `2 passed`.

- [ ] **Step 4: Run all MIC LOOP/calibration tests**

```bash
.venv/bin/python -m pytest -q \
  tests/test_mastering_track_stress.py \
  tests/test_mastering_calibration_route.py \
  tests/test_mastering_calibration_page.py \
  tests/test_mastering_calibration_profiles.py
```

Expected: no failures.

- [ ] **Step 5: Commit only the existing MIC LOOP fix**

```bash
git add runtime/mastering.py tests/test_mastering_track_stress.py
git commit -m "fix: normalize mic loop seal gain drift"
```

---

### Task 1: Add the isolated Demucs worker contract and environment probe

**Files:**
- Create: `runtime/mastering_stem_worker.py`
- Create: `tests/test_mastering_stems.py`

**Interfaces:**
- Produces CLI: `python runtime/mastering_stem_worker.py probe`.
- Produces CLI: `python runtime/mastering_stem_worker.py separate --source PATH --output-dir PATH --model htdemucs --result-json PATH`.
- Probe JSON contains `ok`, `provider`, `provider_version`, `torch_version`, `model`, `stems`.

- [ ] **Step 1: Write a failing worker probe contract test using an injected fake Demucs module**

```python
def test_worker_probe_contract(monkeypatch):
    fake = types.SimpleNamespace(__version__="4.test")
    monkeypatch.setitem(sys.modules, "demucs", fake)
    result = mastering_stem_worker.probe_environment(model="htdemucs")
    assert result["ok"] is True
    assert result["provider"] == "demucs"
    assert result["model"] == "htdemucs"
    assert result["stems"] == ["drums", "bass", "vocals", "other"]
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q tests/test_mastering_stems.py::test_worker_probe_contract -vv
```

Expected: import/module/function missing.

- [ ] **Step 3: Implement worker argument parsing and probe without importing Demucs at module import time**

```python
STEMS = ("drums", "bass", "vocals", "other")
DEFAULT_MODEL = "htdemucs"

def probe_environment(model: str = DEFAULT_MODEL) -> dict[str, Any]:
    import importlib.metadata
    import torch
    import demucs
    return {
        "ok": True,
        "provider": "demucs",
        "provider_version": importlib.metadata.version("demucs"),
        "torch_version": torch.__version__,
        "model": model,
        "stems": list(STEMS),
    }
```

The main E-MASTER process must be able to import `runtime.mastering_stem_worker` in tests without importing Torch until `probe_environment()` or separation is invoked.

- [ ] **Step 4: Verify GREEN**

Run the targeted test; expected PASS.

- [ ] **Step 5: Create the separate provider venv on the VPS and record the installed version**

Do not install Torch/Demucs into the E-MASTER `.venv`.

```bash
python3.12 -m venv /opt/eiros-stem-env
/opt/eiros-stem-env/bin/python -m pip install -U pip wheel
/opt/eiros-stem-env/bin/python -m pip install -U demucs
/opt/eiros-stem-env/bin/python -m pip freeze > /opt/eiros-stem-env/requirements.lock
/opt/eiros-stem-env/bin/python runtime/mastering_stem_worker.py probe
```

Expected probe: provider `demucs`, model `htdemucs`, exactly four stems. If installation/probe fails, stop here and report `STEM_UNAVAILABLE`; do not modify the main mastering service to compensate.

- [ ] **Step 6: Commit worker contract**

```bash
git add runtime/mastering_stem_worker.py tests/test_mastering_stems.py
git commit -m "feat: add isolated demucs stem worker"
```

---

### Task 2: Implement four-stem separation with relative-level preservation

**Files:**
- Modify: `runtime/mastering_stem_worker.py`
- Modify: `tests/test_mastering_stems.py`

**Interfaces:**
- Consumes: source path and output directory.
- Produces worker result JSON with `status`, provider/model/version, `sample_rate`, `common_scale`, four stem paths, per-stem unclamped peak, runtime seconds, and quality flags.

- [ ] **Step 1: Write a failing unit test around the tensor-to-stem writer**

Use fake separated tensors where one stem peaks above 1.0. Assert a single common attenuation is applied to **all** stems so relative levels are preserved:

```python
def test_common_scale_preserves_relative_stem_levels(tmp_path):
    stems = {
        "bass": torch.tensor([[1.20, 0.60], [1.20, 0.60]]),
        "drums": torch.tensor([[0.60, 0.30], [0.60, 0.30]]),
        "vocals": torch.tensor([[0.30, 0.15], [0.30, 0.15]]),
        "other": torch.tensor([[0.15, 0.075], [0.15, 0.075]]),
    }
    scale = mastering_stem_worker.common_output_scale(stems)
    assert scale == pytest.approx(0.999 / 1.20)
    assert (0.60 * scale) / (1.20 * scale) == pytest.approx(0.5)
```

- [ ] **Step 2: Run RED**

Expected missing helper.

- [ ] **Step 3: Implement `common_output_scale()` and `run_separation()`**

Use the official Demucs programmatic API, not a third-party MCP server:

```python
from demucs.api import Separator, save_audio

separator = Separator(
    model=model,
    device="cpu",
    split=True,
    segment=7.8,
    overlap=0.25,
    shifts=1,
    jobs=1,
    progress=False,
)
origin, separated = separator.separate_audio_file(str(source_path))
```

Require exactly `drums`, `bass`, `vocals`, `other`. Compute one `common_scale` from the maximum absolute sample across all four tensors; multiply every stem by that same scale. Save 32-bit float WAVs using `save_audio(..., as_float=True, clip="clamp")`. Record `COMMON_SCALE_APPLIED` if scale < 1.0 and `RAW_STEM_OVERSHOOT` if any raw stem exceeded ±1.0.

- [ ] **Step 4: Add source-immutability and four-file contract tests**

```python
def test_separation_never_mutates_source(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"immutable-source")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    fake = {name: torch.zeros((2, 4800)) for name in mastering_stem_worker.STEMS}
    monkeypatch.setattr(mastering_stem_worker, "separate_tensor_source", lambda *a, **k: (48000, fake))
    mastering_stem_worker.run_separation(source, tmp_path / "out", "htdemucs")
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert after == before


def test_four_stem_contract_rejects_wrong_source_count():
    with pytest.raises(ValueError, match="exactly four stems"):
        mastering_stem_worker.validate_stem_keys({"vocals": object(), "other": object()})
```

- [ ] **Step 5: Run unit tests GREEN in the main venv**

```bash
.venv/bin/python -m pytest -q tests/test_mastering_stems.py -vv
```

- [ ] **Step 6: Run one real 20-second provider smoke outside the web service**

Create a 20-second WAV excerpt from an existing uploaded source with FFmpeg, then run the worker using `/opt/eiros-stem-env/bin/python`. Do not use the original upload path as output.

```bash
ffmpeg -v error -y -ss 92.5 -t 20 -i "/path/from-existing-asset" -c:a pcm_f32le /tmp/e-master-stem-smoke.wav
/usr/bin/time -v /opt/eiros-stem-env/bin/python runtime/mastering_stem_worker.py separate \
  --source /tmp/e-master-stem-smoke.wav \
  --output-dir /tmp/e-master-stem-smoke-out \
  --model htdemucs \
  --result-json /tmp/e-master-stem-smoke-result.json
```

Verify four float WAVs exist and inspect `Maximum resident set size` before enabling full-track jobs. If the worker is killed or peak RSS leaves insufficient headroom for the running MCP service, mark the provider `STEM_UNAVAILABLE_RESOURCE_LIMIT` and stop; do not risk OOMing preview/production.

- [ ] **Step 7: Commit**

```bash
git add runtime/mastering_stem_worker.py tests/test_mastering_stems.py
git commit -m "feat: separate diagnostic four stems"
```

---

### Task 3: Add stem cache, state machine, and single-job launcher

**Files:**
- Create: `runtime/mastering_stems.py`
- Modify: `runtime/mastering.py`
- Modify: `tests/test_mastering_stems.py`

**Interfaces:**
- Produces: `prepare_stems(asset_id: str, force: bool = False) -> dict[str, Any]`.
- Produces: `stem_status(asset_id: str) -> dict[str, Any]`.
- Produces: `load_stem_record(asset_id: str) -> dict[str, Any]`.
- Cache root: `MASTER_ROOT / "stem_analysis"`.

- [ ] **Step 1: Write failing cache-key/state tests**

```python
def test_stem_cache_key_changes_with_source_or_provider_version():
    a = mastering_stems.stem_cache_key("aaa", "demucs", "htdemucs", "4.0")
    b = mastering_stems.stem_cache_key("bbb", "demucs", "htdemucs", "4.0")
    c = mastering_stems.stem_cache_key("aaa", "demucs", "htdemucs", "4.1")
    assert a != b
    assert a != c


def test_prepare_returns_pending_without_blocking_on_new_job(...):
    result = mastering_stems.prepare_stems(asset_id)
    assert result["status"] == "STEM_PENDING"
```

- [ ] **Step 2: Run RED**

Expected module/functions missing.

- [ ] **Step 3: Implement safe record paths and atomic JSON writes**

Record schema:

```python
{
    "schema_version": 1,
    "status": "STEM_PENDING|STEM_READY|STEM_UNAVAILABLE|STEM_DEGRADED",
    "asset_id": asset_id,
    "source_sha256": source_hash,
    "provider": "demucs",
    "provider_version": provider_version,
    "model": "htdemucs",
    "cache_key": cache_key,
    "created_at": unix_time,
    "updated_at": unix_time,
    "job": {"job_id": job_id, "started_at": unix_time},
    "stems": {},
    "quality_flags": [],
}
```

Write to a temporary sibling and `os.replace()` into `record.json`.

- [ ] **Step 4: Implement a nonblocking single-job launcher**

Use `/opt/eiros-stem-env/bin/python runtime/mastering_stem_worker.py ...` with `subprocess.Popen`, `start_new_session=True`, `cwd` set to the worktree, and environment limits:

```python
env.update({
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
})
```

A filesystem lock under `STEM_ROOT / ".worker.lock"` permits only one pending separation job at a time. A second asset returns `STEM_PENDING` with reason `WORKER_BUSY` rather than launching a second Torch process.

- [ ] **Step 5: Import completed worker JSON into the cache record on status polling**

`stem_status()` checks the worker result JSON. On success, validate that all four paths resolve under the expected cache directory. On failure, return `STEM_UNAVAILABLE` with bounded error text. If a pending record is older than 30 minutes with no result file, mark `STEM_UNAVAILABLE` reason `WORKER_TIMEOUT` and release the lock.

- [ ] **Step 6: Add minimal wrappers in `runtime/mastering.py` using the immutable uploaded source**

Do **not** call `resolve_source_file()` because that function may produce an MP3 A/B preview for non-MP3 uploads. Resolve the exact upload using the existing metadata and `_input_path()` helper:

```python
def prepare_stem_analysis(asset_id: str, force: bool = False) -> dict[str, Any]:
    aid = _validate_id(asset_id)
    meta = _read_meta(aid)
    expected = (UPLOAD_ROOT / aid).resolve()
    source_path = _input_path(meta).resolve()
    if expected not in source_path.parents or not source_path.is_file():
        raise FileNotFoundError("Original source is missing")
    return mastering_stems.prepare_stems_for_path(
        asset_id=aid,
        source_path=source_path,
        force=force,
    )
```

HTTP callers provide only `asset_id`; they never provide a filesystem path.

- [ ] **Step 7: Run tests and commit**

```bash
.venv/bin/python -m pytest -q tests/test_mastering_stems.py -vv
git add runtime/mastering_stems.py runtime/mastering.py tests/test_mastering_stems.py
git commit -m "feat: cache and queue stem analysis"
```

---

### Task 4: Build the aligned stem feature grid and reconstruction quality

**Files:**
- Create: `runtime/mastering_stem_features.py`
- Create: `tests/test_mastering_stem_features.py`
- Modify: `runtime/mastering_stems.py`

**Interfaces:**
- Produces: `analyze_stem_features(source_path: Path, stem_paths: dict[str, Path], common_scale: float) -> dict[str, Any]`.
- Grid version: `stem-features-v1`.
- Frame hop: 0.5 seconds; frame length: 1.0 second.
- Frequency grid: the same 1/3-octave-style centers used by `_stress_band_profile`, 20 Hz to min(20 kHz, Nyquist).

- [ ] **Step 1: Write a failing aligned-grid test**

```python
def test_feature_grid_is_aligned_for_all_four_stems(tmp_path):
    paths = write_synthetic_stems(
        tmp_path,
        bass_hz=63.0,
        drums_hz=63.0,
        vocals_hz=1000.0,
        other_hz=4000.0,
        seconds=4.0,
    )
    result = mastering_stem_features.analyze_stem_features(paths["source"], paths["stems"], common_scale=1.0)
    timelines = [result["stems"][name]["frames"] for name in ("drums", "bass", "vocals", "other")]
    assert [f["start_seconds"] for f in timelines[0]] == [f["start_seconds"] for f in timelines[1]]
    assert timelines[0][0]["bands"].keys() == timelines[2][0]["bands"].keys()
```

`write_synthetic_stems()` is a test helper in the same test file that writes 48 kHz stereo float WAV fixtures with Python `wave`/NumPy; it is not production code.

- [ ] **Step 2: Run RED**

Expected module/function missing.

- [ ] **Step 3: Implement local FFmpeg decode and aligned feature extraction**

Do not import `runtime.mastering` to avoid circular dependencies. Decode each file to 48 kHz stereo float32 with one bounded FFmpeg helper. For each frame/band store linear energy (for arithmetic), dB energy (for display), peak, RMS, crest, and activity.

Example frame record:

```python
{
    "start_seconds": 92.5,
    "end_seconds": 93.5,
    "rms_dbfs": -14.2,
    "peak_dbfs": -2.1,
    "crest_db": 12.1,
    "bands": {
        "63.50": {"low_hz": 56.57, "high_hz": 71.27, "energy": 0.0042, "dbfs": -23.77}
    },
}
```

- [ ] **Step 4: Implement reconstruction-quality evidence**

Decode source and stems on the same grid. Apply `common_scale` to source before comparing it with the sum of saved scaled stems. Compute:

```python
residual = scaled_source - (drums + bass + vocals + other)
relative_error = rms(residual) / max(rms(scaled_source), 1e-12)
correlation = corrcoef(scaled_source_mono, summed_stems_mono)
```

Quality policy:

```python
if relative_error <= 0.15 and correlation >= 0.95:
    reconstruction_confidence = 1.0
elif relative_error <= 0.30 and correlation >= 0.85:
    reconstruction_confidence = 0.7
else:
    reconstruction_confidence = 0.35
    quality_flags.append("STEM_RECONSTRUCTION_WEAK")
```

These thresholds are Phase 1 engineering confidence heuristics, not Demucs quality scores or perceptual claims.

- [ ] **Step 5: Persist features into the stem record only after separation is complete**

On `STEM_READY` import, `mastering_stems` calls the feature analyzer once and atomically appends `feature_version`, `features`, and reconstruction metrics. If feature extraction fails, state becomes `STEM_DEGRADED`; the four derivative files remain diagnostic and ordinary mastering remains available.

- [ ] **Step 6: Run tests and commit**

```bash
.venv/bin/python -m pytest -q tests/test_mastering_stem_features.py tests/test_mastering_stems.py -vv
git add runtime/mastering_stem_features.py runtime/mastering_stems.py tests/test_mastering_stem_features.py tests/test_mastering_stems.py
git commit -m "feat: analyze aligned stem features"
```

---

### Task 5: Add confidence-scored time/frequency attribution

**Files:**
- Create: `runtime/mastering_stem_attribution.py`
- Create: `tests/test_mastering_stem_attribution.py`
- Modify: `runtime/mastering_stems.py`

**Interfaces:**
- Produces: `attribute_region(record: dict[str, Any], start_seconds: float, end_seconds: float, low_hz: float, high_hz: float) -> dict[str, Any]`.
- Produces public wrapper: `stem_attribution(asset_id: str, start_seconds: float, end_seconds: float, low_hz: float, high_hz: float) -> dict[str, Any]`.

- [ ] **Step 1: Write synthetic attribution RED tests**

Tests must cover:

```python
assert bass_only["contributors"][0]["stem"] == "bass"
assert bass_only["contributors"][0]["share"] > 0.90
assert kick_plus_bass["contributors"][0]["stem"] in {"drums", "bass"}
assert inactive_vocal_share == pytest.approx(0.0, abs=1e-6)
```

- [ ] **Step 2: Run RED**

Expected module/function missing.

- [ ] **Step 3: Implement regional energy aggregation**

Select frames overlapping `[start_seconds, end_seconds]` and 1/3-octave bands whose ranges overlap `[low_hz, high_hz]`. Sum **linear energy**, never dB values. Compute shares only across the four stems:

```python
stem_energy = {stem: sum_selected_energy(features[stem]) for stem in STEMS}
total = sum(stem_energy.values())
share = 0.0 if total <= 1e-18 else stem_energy[stem] / total
```

Sort descending. Do not invent contribution when all stem energy is below the region floor; return empty contributors and confidence 0.

- [ ] **Step 4: Compute confidence from reconstruction evidence, activity, and dominance**

```python
reconstruction = float(record["quality"]["reconstruction_confidence"])
active_ratio = min(1.0, total / max(full_mix_region_energy, 1e-18))
dominance = contributors[0]["share"] if contributors else 0.0
confidence = max(0.0, min(1.0,
    0.60 * reconstruction + 0.25 * min(active_ratio, 1.0) + 0.15 * dominance
))
```

Return `quality_flags` alongside confidence. Never relabel low confidence as certainty.

- [ ] **Step 5: Add cache-by-query key**

Cache exact normalized region keys rounded to milliseconds and 0.1 Hz. Cache data belongs in the stem record and is invalidated when cache key/feature version changes.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/python -m pytest -q tests/test_mastering_stem_attribution.py tests/test_mastering_stem_features.py -vv
git add runtime/mastering_stem_attribution.py runtime/mastering_stems.py tests/test_mastering_stem_attribution.py
git commit -m "feat: attribute mastering regions to stems"
```

---

### Task 6: Expose HTTP-only prepare/status/attribution routes

**Files:**
- Modify: `runtime/mastering_mcp_server.py`
- Modify: `tests/test_mastering_calibration_route.py`

**Interfaces:**
- `POST /api/stems/prepare` body `{ "asset_id": "...", "force": false }`.
- `GET /api/stems/status?asset_id=...`.
- `POST /api/stems/attribution` body `{ "asset_id": "...", "start_seconds": 92.5, "end_seconds": 112.5, "low_hz": 60, "high_hz": 120 }`.
- These routes are HTTP-only and add no MCP output template/resource URI.

- [ ] **Step 1: Write failing route-contract tests**

```python
def test_stem_routes_are_http_only():
    text = Path("runtime/mastering_mcp_server.py").read_text()
    assert '@mcp.custom_route("/api/stems/prepare"' in text
    assert '@mcp.custom_route("/api/stems/status"' in text
    assert '@mcp.custom_route("/api/stems/attribution"' in text
    block = text[text.index("def api_stems_prepare"):text.index("def api_health")]
    assert "resourceUri" not in block
    assert "outputTemplate" not in block
```

- [ ] **Step 2: Run RED**

Expected missing routes.

- [ ] **Step 3: Implement validation and state-aware responses**

`prepare` returns HTTP 200 for cached ready/degraded and 202 for new/pending jobs. `status` returns the safe record without filesystem-internal absolute paths. `attribution` returns 409 with `STEM_PENDING`, 503 with `STEM_UNAVAILABLE`, and 200 for ready/degraded records that have usable features.

Validate `0 <= start < end <= source_duration`, `20 <= low_hz < high_hz <= 20000`.

- [ ] **Step 4: Verify routes and commit**

```bash
.venv/bin/python -m pytest -q tests/test_mastering_calibration_route.py tests/test_mastering_stems.py tests/test_mastering_stem_attribution.py -vv
git add runtime/mastering_mcp_server.py tests/test_mastering_calibration_route.py
git commit -m "feat: expose stem analysis api"
```

---

### Task 7: Connect attribution to Track Stress and MIC LOOP evidence without changing mastering DSP

**Files:**
- Modify: `runtime/mastering.py`
- Modify: `tests/test_mastering_track_stress.py`

**Interfaces:**
- Produces helper: `annotate_problem_region_with_stems(asset_id: str, region: dict[str, float]) -> dict[str, Any]`.
- Input region: `start_seconds`, `end_seconds`, `low_hz`, `high_hz`.
- Output: `{ "stem_state": ..., "stem_attribution": ... | None }`.

- [ ] **Step 1: Write a failing fallback test**

```python
def test_problem_region_does_not_fail_when_stems_unavailable(monkeypatch):
    monkeypatch.setattr(mastering_stems, "stem_attribution", lambda *a, **k: {"status": "STEM_UNAVAILABLE"})
    result = mastering.annotate_problem_region_with_stems("a" * 32, REGION)
    assert result["stem_state"] == "STEM_UNAVAILABLE"
    assert result["stem_attribution"] is None
```

- [ ] **Step 2: Write a failing successful-annotation test**

```python
def test_problem_region_attaches_ranked_stem_evidence(monkeypatch):
    expected = {
        "status": "STEM_READY",
        "contributors": [
            {"stem": "bass", "share": 0.64},
            {"stem": "drums", "share": 0.31},
            {"stem": "other", "share": 0.04},
            {"stem": "vocals", "share": 0.01},
        ],
        "confidence": 0.88,
    }
    monkeypatch.setattr(mastering_stems, "stem_attribution", lambda *a, **k: expected)
    region = {"start_seconds": 92.5, "end_seconds": 112.5, "low_hz": 60.0, "high_hz": 120.0}
    result = mastering.annotate_problem_region_with_stems("a" * 32, region)
    assert result["stem_attribution"]["contributors"][0]["stem"] == "bass"
    assert "actions" not in result
```

- [ ] **Step 3: Implement the helper with strict evidence-only semantics**

The helper may call prepare/status/query. It may never call `render`, `render_director`, EQ/compressor helpers, or change source/master metadata except the diagnostic stem cache.

- [ ] **Step 4: Attach the helper at the Track Stress evidence boundary**

When Track Stress has a concrete `asset_id`, suspect time window, and frequency band, call `annotate_problem_region_with_stems()` and append the result under `stem_evidence`. The helper must return pending/unavailable states without blocking or changing the stress result itself.

- [ ] **Step 5: Extend MIC LOOP requests with digital identity and gate attribution on verified digital output**

The browser already knows the selected asset/output. Add these multipart fields when STRESS is analyzed:

```javascript
const {asset_id, output_id}=selectedPair();
fd.append('asset_id', asset_id);
fd.append('output_id', output_id);
fd.append('clip_start_seconds', String(cfg.clipStart));
fd.append('clip_end_seconds', String(cfg.clipStart + cfg.clipDuration));
```

After `_mic_loop_compare()` returns, the server may add stem evidence only when:

```python
report["classification_valid"] is True
and report["artifact_detected"] is True
and output_item.get("verification", {}).get("status") == "PASS"
```

Choose the trusted flagged MIC LOOP band with the largest absolute `residual_db`, map its name through `MIC_LOOP_BANDS`, and query stems for the exact clip window. Otherwise return `stem_attribution: None` and one of `MIC_LEVEL_INVALID`, `MIC_NO_ARTIFACT`, or `DIGITAL_AUDIT_NOT_PASS`. Do not run stem analysis on the microphone recording itself.

- [ ] **Step 6: Run integration tests and ordinary mastering regression**

```bash
.venv/bin/python -m pytest -q \
  tests/test_mastering_track_stress.py \
  runtime/test_mastering_v04_regression.py \
  runtime/test_mastering_v04_e2e.py
```

Expected: stem integration tests pass and existing mastering outputs remain operational.

- [ ] **Step 7: Commit**

```bash
git add runtime/mastering.py tests/test_mastering_track_stress.py
git commit -m "feat: annotate stress evidence with stems"
```

---

### Task 8: Add the standalone compact STEM INSPECTOR

**Files:**
- Create: `runtime/mastering_stem_inspector.html`
- Modify: `runtime/mastering_mcp_server.py`
- Modify: `tests/test_mastering_calibration_route.py`

**Interfaces:**
- `GET /api/stems` returns standalone HTML.
- UI uses existing `/api/list`, `/api/stems/prepare`, `/api/stems/status`, `/api/stems/attribution`.
- No in-chat MCP panel/resource registration.

- [ ] **Step 1: Write failing UI contract test**

Require tokens:

```python
for token in [
    "E-MASTER STEM INSPECTOR",
    "DRUMS", "BASS", "VOCALS", "OTHER",
    "/api/stems/prepare",
    "/api/stems/status",
    "/api/stems/attribution",
    "start_seconds", "end_seconds", "low_hz", "high_hz",
]:
    assert token in html
```

- [ ] **Step 2: Run RED**

Expected file/route missing.

- [ ] **Step 3: Implement compact UI**

Controls: asset selector, `PREPARE STEMS`, state line, start/end seconds, low/high Hz, `ATTRIBUTE`, and four ranked bars/text rows. Display confidence and quality flags. No stem mixer, no solo, no per-stem gain, no processing controls.

Polling interval while pending: 3 seconds; stop polling when page hidden/unloaded.

- [ ] **Step 4: Implement standalone route with `Cache-Control: no-store`**

No `resourceUri`, `outputTemplate`, or panel registration.

- [ ] **Step 5: Run route/UI tests and commit**

```bash
.venv/bin/python -m pytest -q tests/test_mastering_calibration_route.py -vv
git add runtime/mastering_stem_inspector.html runtime/mastering_mcp_server.py tests/test_mastering_calibration_route.py
git commit -m "feat: add stem attribution inspector"
```

---

### Task 9: Real-asset validation and preview deployment

**Files:**
- No product source changes unless validation reveals a defect.

**Interfaces:**
- Existing assets: use one 20-second excerpt first, then one complete source only if resource smoke is safe.
- Preview only: `eiros-mastering-v17-preview.service` on port 8800.

- [ ] **Step 1: Run the complete stem/calibration test set**

```bash
.venv/bin/python -m pytest -q \
  tests/test_mastering_stems.py \
  tests/test_mastering_stem_features.py \
  tests/test_mastering_stem_attribution.py \
  tests/test_mastering_track_stress.py \
  tests/test_mastering_calibration_route.py \
  tests/test_mastering_calibration_page.py \
  tests/test_mastering_calibration_profiles.py \
  runtime/test_mastering_v04_regression.py \
  runtime/test_mastering_v04_e2e.py
```

Expected: zero failures.

- [ ] **Step 2: Compile and inspect diffs**

```bash
.venv/bin/python -m py_compile \
  runtime/mastering.py \
  runtime/mastering_stems.py \
  runtime/mastering_stem_worker.py \
  runtime/mastering_stem_features.py \
  runtime/mastering_stem_attribution.py \
  runtime/mastering_mcp_server.py
git diff --check
git status --short
```

Do not delete unrelated `.bak-file-replace-*` files.

- [ ] **Step 3: Verify source immutability on a real asset**

Compute SHA-256 of the uploaded source before and after separation. They must match exactly.

- [ ] **Step 4: Validate a real attribution on the existing 92.5–112.5 s low-end window**

Prepare stems for the chosen source, wait for `STEM_READY` or `STEM_DEGRADED`, query `60–120 Hz`, and inspect contributor shares/confidence. The result must contain only the four allowed stems and shares must sum to ~1.0 when contributors are present.

- [ ] **Step 5: Restart only preview**

```bash
systemctl restart eiros-mastering-v17-preview.service
systemctl is-active eiros-mastering-v17-preview.service
```

Never restart `eiros-mastering-mcp.service` on 8792.

- [ ] **Step 6: Public smoke**

Verify:

```text
GET  /api/health                    -> 200
GET  /api/stems                     -> 200 + E-MASTER STEM INSPECTOR
POST /api/stems/prepare             -> 200 cached or 202 pending
GET  /api/stems/status              -> valid state
POST /api/stems/attribution         -> 200 when ready
GET  /api/calibration               -> 200
GET  /api/calibration/mic-loop      -> 200
```

Confirm ordinary mastering list/analyze/render endpoints still respond and `open_mastering_panel` remains `panel_enabled:false`.

- [ ] **Step 7: User validation**

On the standalone inspector, user selects an existing song, waits for separation, requests the 60–120 Hz window, and verifies the ranking is musically plausible. Do not enable per-stem mastering from this validation.

- [ ] **Step 8: Commit any validation-only test fixtures if needed; otherwise leave code at the last feature commit**

No production promotion in this task.

---

## Self-Review Checklist

- Spec coverage: separation adapter/cache, four stems, aligned features, attribution, degraded fallback, Track Stress/MIC LOOP annotations, compact standalone UI, real-asset validation are all assigned to tasks.
- Source preservation: every separation/output path is under the diagnostic stem cache; real-asset SHA check is mandatory.
- Mastering isolation: no Phase 1 task creates per-stem DSP actions or rebuilds a final mix.
- Dependency isolation: Demucs/Torch live only in `/opt/eiros-stem-env`; the existing E-MASTER venv stays lightweight.
- Resource isolation: one worker at a time, CPU threads limited, 20-second RSS smoke precedes full-track work.
- Type/interface consistency: all later tasks consume `prepare_stems`, `stem_status`, `stem_attribution`, or the `attribute_region` contract defined earlier.
- Headless constraint: only standalone HTTP/HTML routes are added; no MCP UI output template/resource URI is registered.
