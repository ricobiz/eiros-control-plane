# E-MASTER Calibration Live Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tiny standalone iPhone-safe E-MASTER calibration page that plays one bass test point at a time, accepts `OK`/`NO`, brackets the first critical boundary, then converges on it and performs a repeatability check.

**Architecture:** Keep the mastering MCP headless. Serve one static calibration HTML document from the existing v17 preview process at `/api/calibration`, which is already reachable through the current nginx `/mastering-v17-preview-7f4d91c2/api/` proxy. Generate audio entirely client-side with Web Audio API; keep the adaptive search state entirely in the page for this prototype.

**Tech Stack:** Python 3.12, FastMCP custom routes, Starlette `HTMLResponse`, vanilla HTML/CSS/JavaScript, Web Audio API, pytest, curl.

## Global Constraints

- Do not register this page as an MCP Apps resource or attach `_meta.ui.resourceUri` / `openai/outputTemplate`.
- Do not change the existing headless state of `open_mastering_panel`.
- Do not overwrite or modify any audio asset/mastering output.
- Audio must start only after an explicit user tap.
- Test gain must use short ramps and a conservative ceiling; the page must never alter hardware volume.
- `visibilitychange`, `pagehide`, Stop, and reset must immediately silence and dispose active audio nodes/timers.
- Only one test dimension changes during a boundary search.
- Preserve raw `OK`/`NO` decisions in page state for later pattern analysis.
- No polling, SSE, WebSocket, waveform decode, server-side audio streaming, or large payloads.

---

### Task 1: Calibration page and adaptive frequency boundary search

**Files:**
- Create: `runtime/mastering_calibration.html`
- Test: `tests/test_mastering_calibration_page.py`

**Interfaces:**
- Consumes: browser `AudioContext`, `OscillatorNode`, `GainNode`.
- Produces: a self-contained HTML page with `window.EMasterCalibration` exposing `start()`, `stop()`, `answer(ok)`, `reset()`, and `snapshot()` for smoke/debug inspection.

- [ ] **Step 1: Write the failing static contract test**

```python
from pathlib import Path

PAGE = Path("runtime/mastering_calibration.html")


def test_calibration_page_contract():
    text = PAGE.read_text(encoding="utf-8")
    for token in [
        "E-MASTER CAL",
        'id="start"',
        'id="ok"',
        'id="no"',
        "AudioContext",
        "visibilitychange",
        "pagehide",
        "EMasterCalibration",
        "Math.sqrt",
    ]:
        assert token in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_mastering_calibration_page.py::test_calibration_page_contract -v`

Expected: FAIL because `runtime/mastering_calibration.html` does not exist.

- [ ] **Step 3: Implement the minimal page**

Create `runtime/mastering_calibration.html` with:

```js
const cfg = {
  mode: "frequency",
  fixedLevelDb: -30,
  initialHz: 80,
  minHz: 20,
  coarseRatio: 0.75,
  toleranceHz: 0.75,
  maxGainDb: -18,
  toneMs: 900,
  gapMs: 180
};

const state = {
  running: false,
  phase: "coarse",
  currentHz: cfg.initialHz,
  lastGoodHz: null,
  firstBadHz: null,
  candidateHz: null,
  verification: [],
  decisions: []
};
```

Frequency search behavior:

```js
function nextFrequencyAfterAnswer(ok) {
  const f = state.currentHz;
  state.decisions.push({
    mode: "frequency",
    hz: f,
    levelDb: cfg.fixedLevelDb,
    ok,
    at: Date.now()
  });

  if (ok) state.lastGoodHz = f;
  else state.firstBadHz = f;

  if (state.lastGoodHz != null && state.firstBadHz != null) {
    state.phase = "refine";
    const hi = Math.max(state.lastGoodHz, state.firstBadHz);
    const lo = Math.min(state.lastGoodHz, state.firstBadHz);
    if (hi - lo <= cfg.toleranceHz) {
      state.candidateHz = Math.sqrt(hi * lo);
      state.phase = "verify";
      return state.candidateHz;
    }
    return Math.sqrt(hi * lo);
  }

  if (ok) return Math.max(cfg.minHz, f * cfg.coarseRatio);
  return Math.min(cfg.initialHz, f / cfg.coarseRatio);
}
```

Playback behavior:
- create/resume `AudioContext` only inside Start/Retest tap;
- create exactly one oscillator + gain per test point;
- convert dB to linear with `10 ** (db / 20)`;
- ramp gain from `0` to target over ~40 ms and back to `0` before stop;
- never allow a digital level greater than `cfg.maxGainDb`;
- after an answer, stop the current node before scheduling the next point;
- `visibilitychange` when hidden and `pagehide` call `stop(true)`.

UI behavior:
- dark compact card, no scrolling requirement;
- current frequency displayed prominently, digital level smaller;
- two primary response controls: green `OK`, red `NO`;
- Start/Stop, Retest, Reset remain compact;
- while a point is playing, show a minimal ring/progress pulse rather than technical metrics;
- once a candidate is bracketed, display `GOOD … Hz / BAD … Hz` and `± interval` only.

Expose:

```js
window.EMasterCalibration = {
  start,
  stop,
  answer,
  reset,
  snapshot: () => JSON.parse(JSON.stringify(state))
};
```

- [ ] **Step 4: Run the static contract test**

Run: `.venv/bin/pytest tests/test_mastering_calibration_page.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the page**

```bash
git add runtime/mastering_calibration.html tests/test_mastering_calibration_page.py
git commit -m "feat: add e-master calibration boundary prototype"
```

---

### Task 2: Expose the page through the existing v17 preview without enabling MCP UI

**Files:**
- Modify: `runtime/mastering_mcp_server.py` near the custom route block beginning around line 1524
- Test: `tests/test_mastering_calibration_route.py`

**Interfaces:**
- Consumes: `runtime/mastering_calibration.html`.
- Produces: HTTP `GET /api/calibration` returning `text/html` with `Cache-Control: no-store`.

- [ ] **Step 1: Write the failing route-source contract test**

```python
from pathlib import Path


def test_calibration_route_is_standalone_and_headless():
    text = Path("runtime/mastering_mcp_server.py").read_text(encoding="utf-8")
    assert '@mcp.custom_route("/api/calibration", methods=["GET"])' in text
    assert 'Path(__file__).with_name("mastering_calibration.html")' in text
    route_block = text[text.index('def api_calibration'):text.index('def api_health')]
    assert "HTMLResponse" in route_block
    assert "resourceUri" not in route_block
    assert "outputTemplate" not in route_block
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_mastering_calibration_route.py -v`

Expected: FAIL because the route does not exist.

- [ ] **Step 3: Add the standalone route before `/api/health`**

```python
@mcp.custom_route("/api/calibration", methods=["GET"])
async def api_calibration(request: Request) -> Response:
    html_text = Path(__file__).with_name("mastering_calibration.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html_text,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
```

Do not change `open_mastering_panel()` and do not add any MCP resource decorator.

- [ ] **Step 4: Run route and page tests**

Run: `.venv/bin/pytest tests/test_mastering_calibration_page.py tests/test_mastering_calibration_route.py -v`

Expected: all PASS.

- [ ] **Step 5: Compile the server**

Run: `.venv/bin/python -m py_compile runtime/mastering_mcp_server.py`

Expected: exit 0.

- [ ] **Step 6: Commit the route**

```bash
git add runtime/mastering_mcp_server.py tests/test_mastering_calibration_route.py
git commit -m "feat: expose standalone calibration test"
```

---

### Task 3: Add digital-level boundary mode using the same bracketing state machine

**Files:**
- Modify: `runtime/mastering_calibration.html`
- Modify: `tests/test_mastering_calibration_page.py`

**Interfaces:**
- Consumes: the same `answer(ok)` flow from Task 1.
- Produces: a compact `FREQ / LEVEL` mode selector; level mode keeps frequency fixed and changes only digital level.

- [ ] **Step 1: Extend the failing page contract test**

Add assertions for:

```python
for token in [
    'data-mode="frequency"',
    'data-mode="level"',
    "fixedHz",
    "lastGoodDb",
    "firstBadDb",
    "toleranceDb",
]:
    assert token in text
```

- [ ] **Step 2: Run the test and verify failure**

Run: `.venv/bin/pytest tests/test_mastering_calibration_page.py -v`

Expected: FAIL on the new level-mode tokens.

- [ ] **Step 3: Implement level mode**

Use conservative bounds:

```js
const levelCfg = {
  fixedHz: 60,
  initialDb: -36,
  maxDb: -18,
  coarseStepDb: 4,
  toleranceDb: 0.75
};
```

Rules:
- `OK` at a level test means advance upward by `coarseStepDb` until a bad point exists;
- `NO` sets/tightens `firstBadDb`;
- when both good/bad dB values exist, use arithmetic midpoint `(good + bad) / 2`;
- never exceed `maxDb`;
- frequency stays exactly `fixedHz` throughout level search;
- verification repeats the final bracket near the candidate level;
- switching modes calls `stop(true)` and resets only the active search state.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_mastering_calibration_page.py tests/test_mastering_calibration_route.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit level mode**

```bash
git add runtime/mastering_calibration.html tests/test_mastering_calibration_page.py
git commit -m "feat: add calibration level boundary search"
```

---

### Task 4: Deploy only the preview process and perform live smoke checks

**Files:**
- Runtime service: `eiros-mastering-v17-preview.service`
- No production mastering service changes.

**Interfaces:**
- Public test URL: `https://178-105-43-79.sslip.io/mastering-v17-preview-7f4d91c2/api/calibration`
- Existing MCP URL remains: `https://178-105-43-79.sslip.io/mastering-v17-preview-7f4d91c2/mcp`

- [ ] **Step 1: Run the complete calibration test set and compile check**

```bash
.venv/bin/pytest tests/test_mastering_calibration_page.py tests/test_mastering_calibration_route.py -v
.venv/bin/python -m py_compile runtime/mastering_mcp_server.py
```

Expected: PASS / exit 0.

- [ ] **Step 2: Restart only the v17 preview service**

Run: `systemctl restart eiros-mastering-v17-preview.service`

Expected: service returns `active (running)` on port 8800.

- [ ] **Step 3: Verify the public calibration page**

Run:

```bash
curl -fsS -D /tmp/e-master-cal.headers \
  https://178-105-43-79.sslip.io/mastering-v17-preview-7f4d91c2/api/calibration \
  -o /tmp/e-master-cal.html

grep -q "E-MASTER CAL" /tmp/e-master-cal.html
grep -qi "cache-control: no-store" /tmp/e-master-cal.headers
```

Expected: HTTP 200, HTML marker present, `Cache-Control: no-store` present.

- [ ] **Step 4: Recheck the MCP is still headless and healthy**

Run a local/public health check against `/api/health` and confirm the returned server still reports the existing Director/analysis versions. Do not invoke an in-chat widget.

- [ ] **Step 5: User iPhone validation**

Open the public calibration URL on iPhone and verify:
- Start tap produces exactly one tone;
- `OK` descends through bass points;
- first `NO` causes tests to move between the last good and first bad points;
- interval narrows after repeated `OK`/`NO` answers;
- Stop/backgrounding the page kills audio immediately;
- repeated start/stop does not layer tones;
- level mode changes level while keeping 60 Hz fixed.

Record the raw decision sequence from `EMasterCalibration.snapshot()` only if debugging is needed; no server persistence in this prototype.

- [ ] **Step 6: Commit any deployment-only config change only if one was actually necessary**

No nginx change is expected because `/api/calibration` is already covered by the existing preview `/api/` proxy.
