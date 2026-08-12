# EIROS Mastering v0.4 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace opaque adaptive mastering decisions with a Director-guided, traceable mastering pipeline that renders deterministic DSP instructions, verifies the result against the source, cleans optional metadata, and records contextual mastering experience.

**Architecture:** `runtime/mastering.py` remains the deterministic audio engine but stops treating statistical spectral dominance as an error by itself. New focused modules own Director plans, verification/delta analysis, metadata inspection, and experience memory. `runtime/mastering_mcp_server.py` exposes these capabilities through explicit MCP/API contracts; every render becomes an immutable revision and cannot become `APPROVED` until verification passes.

**Tech Stack:** Python 3, NumPy, FFmpeg/ffprobe, FastMCP, Starlette, JSON metadata persisted under `/var/lib/eiros/mastering`, pytest/unittest-style existing runtime tests.

## Global Constraints

- Source audio is immutable.
- No DSP operation may execute without a traceable Director-plan reason and bounded scope.
- Statistical dominance of a frequency band is evidence, never an automatic defect classification.
- Every render creates a new revision; outputs are never overwritten in place.
- `APPROVED` is impossible before post-master verification passes.
- Clean export removes optional container/tag metadata but must not claim removal of proprietary acoustic watermarks.
- Experience Memory is advisory to the Director and may never execute DSP by itself.
- Existing mastering assets and old adaptive outputs must remain readable.
- 48 kHz / 24-bit WAV remains the canonical rendered master format.

---

### Task 1: Freeze v0.3 behavior with regression tests

**Files:**
- Create: `runtime/test_mastering_v04_regression.py`
- Read: `runtime/mastering.py`

**Interfaces:**
- Consumes: current `analyze()`, `render()`, `_adaptive_curves()` behavior.
- Produces: regression fixtures/assertions protecting source immutability, output revision semantics, and the Ayibobo bass-dominance case.

- [ ] **Step 1: Write regression tests for source immutability and render revision creation**

```python
from pathlib import Path
import hashlib
import io
import wave
import numpy as np

from runtime import mastering


def wav_bytes(seconds: float = 1.0, sr: int = 48000) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    x = (0.2 * np.sin(2 * np.pi * 55 * t)).astype(np.float32)
    pcm = np.clip(x * 32767.0, -32768, 32767).astype('<i2')
    stereo = np.column_stack([pcm, pcm]).ravel().tobytes()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(stereo)
    return buf.getvalue()


def configure_roots(tmp_path, monkeypatch):
    upload = tmp_path / 'uploads'
    output = tmp_path / 'outputs'
    meta = tmp_path / 'meta'
    shares = tmp_path / 'shares'
    for path in (upload, output, meta, shares):
        path.mkdir()
    monkeypatch.setattr(mastering, 'UPLOAD_ROOT', upload)
    monkeypatch.setattr(mastering, 'OUTPUT_ROOT', output)
    monkeypatch.setattr(mastering, 'META_ROOT', meta)
    monkeypatch.setattr(mastering, 'SHARE_ROOT', shares)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_render_never_mutates_uploaded_source(tmp_path, monkeypatch):
    configure_roots(tmp_path, monkeypatch)
    stored = mastering.store_upload('fixture.wav', wav_bytes())
    meta = mastering._read_meta(stored['asset_id'])
    source = mastering._input_path(meta)
    before = sha256(source)
    mastering.render(stored['asset_id'], profile='adaptive', target_lufs=-14.0)
    assert sha256(source) == before


def test_each_render_has_unique_output_id(tmp_path, monkeypatch):
    configure_roots(tmp_path, monkeypatch)
    stored = mastering.store_upload('fixture.wav', wav_bytes())
    first = mastering.render(stored['asset_id'], profile='adaptive', target_lufs=-14.0)
    second = mastering.render(stored['asset_id'], profile='adaptive', target_lufs=-14.0)
    assert first['output_id'] != second['output_id']
```

- [ ] **Step 2: Write the Ayibobo-class regression test**

Generate a synthetic signal where 20–60 Hz intentionally carries >45% of spectral energy, add a clean transient layer, and assert that a future Director plan with `protected_traits=["sub_mass"]` does not create any automatic sub cut merely because the sub band dominates.

- [ ] **Step 3: Run the regression file and record the expected pre-v0.4 failure**

Run: `python3 -m pytest runtime/test_mastering_v04_regression.py -v`

Expected: new Director-specific test fails because the plan interface does not exist yet; source immutability tests pass.

- [ ] **Step 4: Commit the regression harness**

```bash
git add runtime/test_mastering_v04_regression.py
git commit -m "test: freeze mastering v03 behavior"
```

---

### Task 2: Introduce Director Plan schema and validation

**Files:**
- Create: `runtime/mastering_director.py`
- Create: `runtime/test_mastering_director.py`
- Modify: `runtime/mastering.py`

**Interfaces:**
- Produces: `validate_director_plan(plan: dict, duration_seconds: float) -> dict`
- Produces: `plan_fingerprint(plan: dict) -> str`
- Produces schema fields: `intent`, `protected_traits`, `target`, `sections[]`, `actions[]`, `reason`, `scope`, `bounds`.
- Consumed later by deterministic render and UI.

- [ ] **Step 1: Write failing schema tests**

```python
from runtime.mastering_director import validate_director_plan


def test_rejects_action_without_reason():
    plan = {
        "intent": "preserve ritual sub mass",
        "protected_traits": ["sub_mass"],
        "target": {"lufs": -10.8, "true_peak_dbtp": -1.1},
        "sections": [{
            "start": 0.0,
            "end": 20.0,
            "actions": [{"type": "eq", "frequency_hz": 62, "gain_db": -0.5}],
        }],
    }
    try:
        validate_director_plan(plan, 20.0)
    except ValueError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("plan should have been rejected")
```

Add tests for overlapping invalid ranges, action outside duration, unbounded compression/limiting, and valid protected-trait plans.

- [ ] **Step 2: Implement immutable normalized Director plan validation**

`validate_director_plan` must return a deep-normalized dict containing a `schema_version`, generated `plan_id`, sorted sections, normalized numeric values, and hard action bounds. Supported v0.4 action types:

```python
SUPPORTED_ACTIONS = {
    "gain",
    "eq",
    "dynamic_eq",
    "compressor",
    "transient",
    "stereo_width",
    "limiter",
    "declipping",
}
```

Every action requires `reason`; every non-safety action requires explicit start/end scope either inherited from its section or provided locally.

- [ ] **Step 3: Add persistence helpers in `mastering.py`**

Store validated plans under asset metadata as append-only `director_plans`; never silently rewrite historical plans.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest runtime/test_mastering_director.py runtime/test_mastering_v04_regression.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/mastering_director.py runtime/mastering.py runtime/test_mastering_director.py runtime/test_mastering_v04_regression.py
git commit -m "feat: add mastering director plan schema"
```

---

### Task 3: Replace opaque adaptive decisions with deterministic plan execution

**Files:**
- Create: `runtime/mastering_dsp.py`
- Create: `runtime/test_mastering_dsp.py`
- Modify: `runtime/mastering.py:447-763`

**Interfaces:**
- Consumes: validated Director plan from Task 2.
- Produces: `render_from_plan(input_path: Path, plan: dict, destination: Path) -> dict`
- Produces per-action execution log: `action_id`, requested values, applied values, affected sample/time range, reason.

- [ ] **Step 1: Write failing deterministic-render tests**

Test that identical source + identical plan yields numerically identical PCM hash, and that a plan containing no sub action cannot alter sub-band gain beyond a narrow tolerance caused by final loudness normalization.

- [ ] **Step 2: Extract DSP execution from `mastering.py` into `mastering_dsp.py`**

Keep low-level audio math deterministic. The module must not inspect genre, spectral dominance, or decide corrective values. It receives decisions only.

- [ ] **Step 3: Implement section-scoped action envelopes**

Use click-free ramps at action boundaries. Minimum default fade is 25 ms unless the plan explicitly requests a longer transition.

- [ ] **Step 4: Make `render()` accept `director_plan_id`**

New signature concept:

```python
def render(
    asset_id: str,
    profile: str = "director",
    target_lufs: float | None = None,
    true_peak_dbtp: float | None = None,
    label: str = "master",
    director_plan_id: str | None = None,
) -> dict:
    if profile == "director" and not director_plan_id:
        raise ValueError("director_plan_id is required for director profile")
    # Existing legacy adaptive branch remains below this guard.
    # Director branch resolves the persisted plan and calls render_from_plan().
```

Keep legacy `profile="adaptive"` available but mark it legacy in returned metadata. New UI must default to `director`.

- [ ] **Step 5: Record exact execution provenance**

Every output metadata entry gets `plan_id`, `plan_fingerprint`, `engine_version`, and full bounded execution log.

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest runtime/test_mastering_dsp.py runtime/test_mastering_director.py runtime/test_mastering_v04_regression.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/mastering_dsp.py runtime/mastering.py runtime/test_mastering_dsp.py
git commit -m "feat: execute deterministic director mastering plans"
```

---

### Task 4: Build source/master delta analysis and verification gate

**Files:**
- Create: `runtime/mastering_verify.py`
- Create: `runtime/test_mastering_verify.py`
- Modify: `runtime/mastering.py`

**Interfaces:**
- Produces: `build_delta_report(source: Path, master: Path, plan: dict) -> dict`
- Produces: `verify_master(source: Path, master: Path, plan: dict) -> dict`
- Verification status enum: `PASS`, `REVIEW`, `REJECTED`.

- [ ] **Step 1: Write failing QA tests**

Cover at minimum: true-peak violation, unexpected crest collapse, stereo-correlation collapse, unplanned >1 dB protected-sub change, new clipping, and a clean passing render.

- [ ] **Step 2: Implement aligned source/master analysis**

Reuse existing timeline segmentation where possible, but calculate source and master metrics on identical time windows. Report:

```python
{
    "global": {"lufs_delta": 2.8, "true_peak_delta": 1.1, "crest_delta": -0.6},
    "sections": [
        {
            "start": 57.5,
            "end": 74.5,
            "source": {"crest_db": 10.0, "sub_percent": 52.4, "stereo_correlation": 0.92},
            "master": {"crest_db": 9.6, "sub_percent": 51.9, "stereo_correlation": 0.91},
            "delta": {"crest_db": -0.4, "sub_percent": -0.5, "stereo_correlation": -0.01},
            "flags": [],
        }
    ],
}
```

- [ ] **Step 3: Implement plan-aware verification**

Protected traits modify tolerances. Example: `sub_mass` means a large unintended negative sub delta is a failure, not an improvement. Verification evaluates against plan intent and hard bounds, not generic tonal targets.

- [ ] **Step 4: Gate approval state in output metadata**

Output lifecycle:

```text
RENDERED -> VERIFYING -> VERIFIED -> APPROVED
                     \-> REVIEW
                     \-> REJECTED
```

No function may mark `APPROVED` unless latest verification is `PASS`.

- [ ] **Step 5: Add explicit `approve_output(asset_id, output_id)`**

It fails with a clear error when verification is not `PASS`.

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest runtime/test_mastering_verify.py runtime/test_mastering_dsp.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/mastering_verify.py runtime/mastering.py runtime/test_mastering_verify.py
git commit -m "feat: add post-master verification gate"
```

---

### Task 5: Add metadata forensics and deterministic clean export

**Files:**
- Create: `runtime/mastering_metadata.py`
- Create: `runtime/test_mastering_metadata.py`
- Modify: `runtime/mastering.py`

**Interfaces:**
- Produces: `inspect_metadata(path: Path) -> dict`
- Produces: `clean_export(source_master: Path, destination: Path, format: str) -> dict`

- [ ] **Step 1: Write metadata fixture tests**

Generate temporary MP3/WAV files with title, comment, cover-art/attached-picture where supported, encoder string, and WAV INFO/BWF metadata. Assert inspection enumerates detected fields.

- [ ] **Step 2: Implement ffprobe-based container/tag audit**

Return categories: structural, optional textual tags, embedded art, chapters, encoder-identifying fields, unknown fields.

- [ ] **Step 3: Implement clean export**

Use explicit stream mapping, `-map_metadata -1`, chapter removal, attached-picture exclusion where applicable, deterministic mux settings, and canonical output encoding. Never rewrite uploaded source.

- [ ] **Step 4: Verify clean output**

Re-run `inspect_metadata` after export and persist `removed_fields`, `retained_structural_fields`, and disclaimer:

```text
No claim is made that proprietary acoustic watermarks were detected or removed.
```

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest runtime/test_mastering_metadata.py -v`

```bash
git add runtime/mastering_metadata.py runtime/mastering.py runtime/test_mastering_metadata.py
git commit -m "feat: add mastering metadata forensics and clean export"
```

---

### Task 6: Implement contextual Experience Memory

**Files:**
- Create: `runtime/mastering_memory.py`
- Create: `runtime/test_mastering_memory.py`
- Modify: `runtime/mastering.py`

**Interfaces:**
- Produces: `record_experience(record: dict) -> dict`
- Produces: `find_similar_experiences(fingerprint: dict, limit: int = 5) -> list[dict]`
- Records contain source features, artistic intent, plan summary, verification outcome, Rico feedback, and approval state.

- [ ] **Step 1: Write tests proving memory is advisory only**

A similarity hit must never mutate a Director plan or trigger render automatically.

- [ ] **Step 2: Define compact audio/context fingerprint**

Include measured spectral distribution, crest/LRA, stereo correlation, section-shape summary, dominant frequency, textual intent tags, and protected traits. Do not store raw PCM in the memory index.

- [ ] **Step 3: Implement local JSONL persistence**

Store under mastering root as versioned append-only records. Add stable record IDs and timestamps.

- [ ] **Step 4: Implement similarity scoring with explanation**

Return both score and reasons, for example:

```python
{
    "score": 0.87,
    "reasons": ["sub-dominant", "cinematic crescendo", "protected sub_mass"],
    "prior_decision": {"protected_traits": ["sub_mass"], "target_lufs": -10.8},
    "verification": "PASS",
    "rico_feedback": "approved",
}
```

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest runtime/test_mastering_memory.py -v`

```bash
git add runtime/mastering_memory.py runtime/mastering.py runtime/test_mastering_memory.py
git commit -m "feat: add contextual mastering experience memory"
```

---

### Task 7: Expose Director/verify/metadata/memory capabilities through MCP and HTTP APIs

**Files:**
- Modify: `runtime/mastering_mcp_server.py`
- Create: `runtime/test_mastering_mcp_v04.py`

**Interfaces:**
- New MCP/API operations:
  - `mastering_plan_create`
  - `mastering_plan_get`
  - `mastering_render_directed`
  - `mastering_verify`
  - `mastering_approve`
  - `mastering_metadata_audit`
  - `mastering_experience_similar`
  - `mastering_feedback_record`

- [ ] **Step 1: Write contract tests for all new tool functions**

Assert schemas include IDs/statuses and errors are explicit rather than HTTP 500s.

- [ ] **Step 2: Add MCP tools with narrow contracts**

Tool descriptions must state that Director plans are authoritative and that verification is mandatory before approval.

- [ ] **Step 3: Add matching HTTP endpoints for panel use**

Use existing CORS/error helpers and maintain backward-compatible existing endpoints.

- [ ] **Step 4: Bump engine/API versions**

Set `ADAPTIVE_ENGINE_VERSION` legacy marker and introduce `DIRECTOR_ENGINE_VERSION = "0.4.0-director"` plus verification schema version.

- [ ] **Step 5: Run contract tests**

Run: `python3 -m pytest runtime/test_mastering_mcp_v04.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/mastering_mcp_server.py runtime/test_mastering_mcp_v04.py
git commit -m "feat: expose director mastering workflow"
```

---

### Task 8: End-to-end verification and Ayibobo regression

**Files:**
- Modify: `runtime/test_mastering_v04_regression.py`
- Create: `runtime/test_mastering_v04_e2e.py`

**Interfaces:**
- Consumes full v0.4 API.
- Produces release-level proof that intentional bass is preserved and verification catches unplanned degradation.

- [ ] **Step 1: Add synthetic end-to-end test**

Upload generated bass-dominant track -> analyze -> create protected-sub plan -> render -> verify -> approve -> clean export. Assert every lifecycle state and provenance link.

- [ ] **Step 2: Add negative end-to-end test**

Render a deliberately bad plan that overcuts protected sub; verification must return `REJECTED` and approval must fail.

- [ ] **Step 3: Run complete mastering test suite**

Run:

```bash
python3 -m pytest runtime/test_mastering_*.py -v
```

Expected: all PASS.

- [ ] **Step 4: Compile and smoke-test service**

Run:

```bash
python3 -m py_compile runtime/mastering.py runtime/mastering_director.py runtime/mastering_dsp.py runtime/mastering_verify.py runtime/mastering_metadata.py runtime/mastering_memory.py runtime/mastering_mcp_server.py
```

Restart only the mastering service after confirming its actual systemd unit name with `systemctl list-units '*master*'`.

- [ ] **Step 5: Verify service health and existing asset readability**

Check MCP health and list existing assets, including the current Ayibobo asset and The Void asset. Old outputs must still deserialize.

- [ ] **Step 6: Commit release core**

```bash
git add runtime
git commit -m "test: verify mastering v04 director core"
```

