# SUM Auto-Wake Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable, visible, bounded SUM controller that acknowledges each wake, continuously detects ChatGPT host activity, and automatically issues the next wake only after the assistant returns to stable static state.

**Architecture:** Add a focused server-side controller engine with revisioned JSON state and JSONL transition logs. Expose narrow MCP tools for control, host signals, ACK, status, and logs. Extend the existing v0.5.7 Listener to run the host-state detector, render gray/red/green/yellow states, and provide fullscreen controls without changing the proven Pulse + Video PiP delivery path until regression tests pass.

**Tech Stack:** Python 3.12, FastMCP tools in `runtime/server_v2.py`, atomic JSON/JSONL persistence, vanilla HTML/CSS/JavaScript in `runtime/pulse_anchor.html`, unittest/pytest-compatible tests, systemd deployment.

## Global Constraints

- Preserve the proven v0.5.7 Listener, Pulse, SAM, and native Video PiP path as the rollback oracle.
- Gray means `IDLE/MONITORING`; red means unacknowledged `WAKE`; green means ACKed `AWAKE`; yellow means observed `WORKING`.
- SUM wakes are sent as the exact natural `role: user` message `Отлично, продолжай.` with no technical headers, identifiers, JSON, or tool instructions.
- Wake delivery is successful only after `sum_wake_ack_current(actor="chatgpt")` resolves and acknowledges the current immutable server-side wake.
- Host static detection must be transition-based and debounced; no single blur, hidden, or display-mode signal is authoritative.
- One active controller authority, one outstanding wake per cycle, revision checks on every mutation.
- Defaults: static debounce 3 seconds, ACK timeout 8 seconds, retry interval 5 seconds, max 5 attempts, max 100 cycles, max 4 hours.
- Loss of Listener/PiP heartbeat stops new wakes and records a specific diagnostic.
- All transitions and errors must be durable, bounded, and visible in fullscreen logs.
- Do not modify unrelated dirty files in the primary checkout; execute in an isolated worktree.

---

## File Map

- Create `runtime/sum_controller.py`: durable controller state machine, validation, transition logging, retry/static decisions.
- Create `runtime/test_sum_controller.py`: deterministic unit tests for state transitions, ACK idempotency, stale epochs, retry budgets, and safety limits.
- Modify `runtime/server_v2.py`: register MCP tools and bootstrap controller configuration/version into the Listener.
- Modify `runtime/pulse_anchor.html`: host signal monitor, state renderer, fullscreen switch/metrics/log panel, ACK-aware wake prompt and retry loop.
- Modify `runtime/test_ui_contract.py`: assert visual states, controls, host signals, and wake ACK contract exist in rendered Listener.
- Modify `runtime/test_pulse_mount_lifecycle.py`: preserve supported generation and one-listener authority behavior.
- Create `runtime/test_sum_listener_contract.py`: static source-level contract tests for JS state machine and tool calls.
- Modify `docs/EIROS_CURRENT_HANDOFF.md` and `.json` only after live verification.

---

### Task 1: Durable SUM Controller Engine

**Files:**
- Create: `runtime/sum_controller.py`
- Test: `runtime/test_sum_controller.py`

**Interfaces:**
- Produces: `SumControllerStore(path: Path, log_path: Path)`
- Produces: `status() -> dict[str, Any]`
- Produces: `set_enabled(enabled: bool, actor: str, listener_session_id: str = "") -> dict[str, Any]`
- Produces: `record_host_signal(signal: str, active: bool | None, listener_session_id: str, detail: dict[str, Any] | None = None) -> dict[str, Any]`
- Produces: `mark_wake_sent(listener_session_id: str, delivery_mode: str) -> dict[str, Any]`
- Produces: `ack_wake(wake_id: str, cycle_id: int, awake_epoch: int, actor: str) -> dict[str, Any]`
- Produces: `tick(listener_session_id: str, pip_active: bool, listener_healthy: bool) -> dict[str, Any]`
- Produces: `read_log(limit: int = 100) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests for initial state and enable transition**

```python
from pathlib import Path
from runtime.sum_controller import SumControllerStore


def make_store(tmp_path: Path) -> SumControllerStore:
    return SumControllerStore(tmp_path / "sum-controller.json", tmp_path / "sum-controller.jsonl")


def test_initial_state_is_disabled_gray(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    state = store.status()
    assert state["enabled"] is False
    assert state["state"] == "IDLE"
    assert state["color"] == "gray"


def test_enable_arms_controller_without_sending_wake(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    state = store.set_enabled(True, actor="rico", listener_session_id="listener-1")
    assert state["enabled"] is True
    assert state["state"] == "ARMED"
    assert state["cycle_id"] == 0
    assert state["wake_id"] == ""
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `python -m pytest runtime/test_sum_controller.py -q`
Expected: FAIL because `runtime.sum_controller` does not exist.

- [ ] **Step 3: Implement atomic state storage and transition helper**

Implement defaults with schema version, revision, timestamps, counters, limits, and a `_transition(previous, new, reason, **fields)` helper that increments revision, writes state atomically, and appends one bounded JSONL record.

- [ ] **Step 4: Run tests and verify initial transitions pass**

Run: `python -m pytest runtime/test_sum_controller.py -q`
Expected: PASS for initial/enable tests.

- [ ] **Step 5: Add failing tests for wake, ACK, working, and stable static**

```python
def test_wake_ack_working_static_cycle(tmp_path: Path, monkeypatch) -> None:
    clock = iter([100, 100, 104, 105, 106, 110, 114])
    monkeypatch.setattr("runtime.sum_controller.now", lambda: next(clock))
    store = make_store(tmp_path)
    store.set_enabled(True, actor="rico", listener_session_id="listener-1")
    wake = store.tick("listener-1", pip_active=True, listener_healthy=True)
    assert wake["state"] == "WAKE"
    assert wake["color"] == "red"
    acked = store.ack_wake(wake["wake_id"], wake["cycle_id"], wake["awake_epoch"], "chatgpt")
    assert acked["state"] == "AWAKE"
    assert acked["color"] == "green"
    working = store.record_host_signal("host-context", True, "listener-1")
    assert working["state"] == "WORKING"
    assert working["color"] == "yellow"
    store.record_host_signal("host-context", False, "listener-1")
    completed = store.tick("listener-1", pip_active=True, listener_healthy=True)
    assert completed["state"] in {"STATIC_DEBOUNCE", "WAKE"}
```

- [ ] **Step 6: Implement transition rules and configurable timing**

Implement `ARMED -> WAKE`, immutable wake identifiers, `WAKE -> AWAKE` on exact ACK, `AWAKE/WORKING -> STATIC_DEBOUNCE`, debounce completion, next-cycle increment, and color mapping.

- [ ] **Step 7: Add and pass tests for idempotency and stale data**

Cover duplicate ACK, wrong wake ID, old cycle/epoch, duplicate wake suppression, revision conflicts, and listener authority mismatch.

- [ ] **Step 8: Add and pass tests for retry and safety limits**

Cover ACK timeout/retry with same wake ID, max attempts to `ERROR/ACK_TIMEOUT`, cycle limit, runtime limit, PiP loss, Listener loss, pause, stop, and reset statistics.

- [ ] **Step 9: Commit controller engine**

```bash
git add runtime/sum_controller.py runtime/test_sum_controller.py
git commit -m "feat: add durable SUM controller engine"
```

---

### Task 2: MCP Control and ACK Tools

**Files:**
- Modify: `runtime/server_v2.py`
- Test: `runtime/test_sum_controller.py`
- Create: `runtime/test_sum_server_tools.py`

**Interfaces:**
- Consumes: `SumControllerStore`
- Produces MCP tools:
  - `sum_controller_status()`
  - `sum_controller_set(enabled: bool, action: str = "set", actor: str = "rico", listener_session_id: str = "")`
  - `sum_host_signal(signal: str, listener_session_id: str, active: bool | None = None, detail: dict | None = None)`
  - `sum_controller_tick(listener_session_id: str, pip_active: bool = False, listener_healthy: bool = True)`
  - `sum_wake_sent(listener_session_id: str, delivery_mode: str = "bridge-confirmed")`
  - `sum_wake_ack_current(actor: str = "chatgpt", listener_session_id: str = "")`
  - `sum_wake_ack(wake_id: str, cycle_id: int, awake_epoch: int, actor: str = "chatgpt")` for diagnostics
  - `sum_controller_log(limit: int = 100)`

- [ ] **Step 1: Write failing server-tool registration tests**

Assert all seven tools exist in `server_v2.mcp._tool_manager._tools`, app-only tools have `visibility: ["app"]`, and `sum_wake_ack` is visible to the model and app.

- [ ] **Step 2: Run targeted tests and verify failure**

Run: `python -m pytest runtime/test_sum_server_tools.py -q`
Expected: FAIL because tools are not registered.

- [ ] **Step 3: Instantiate one controller store in `server_v2.py`**

Use runtime paths such as `RUNTIME_DIR / "sum-controller.json"` and `RUNTIME_DIR / "sum-controller.jsonl"`. Keep the engine outside `server_v2.py`.

- [ ] **Step 4: Register narrow MCP wrappers**

Validate bounded string lengths and log only structured controller data. Do not expose arbitrary file paths or arbitrary event emission through these tools.

- [ ] **Step 5: Add bootstrap configuration**

Add to `_render_pulse_anchor_html`:

```python
"sumController": {
    "enabled": True,
    "staticDebounceMs": 3000,
    "ackTimeoutMs": 8000,
    "retryIntervalMs": 5000,
    "maxWakeAttempts": 5,
}
```

The live status still comes from `sum_controller_status`; bootstrap values are defaults only.

- [ ] **Step 6: Run controller and server tool tests**

Run: `python -m pytest runtime/test_sum_controller.py runtime/test_sum_server_tools.py -q`
Expected: PASS.

- [ ] **Step 7: Commit MCP tool layer**

```bash
git add runtime/server_v2.py runtime/test_sum_server_tools.py
git commit -m "feat: expose SUM controller MCP tools"
```

---

### Task 3: Listener Visual State and Fullscreen Controls

**Files:**
- Modify: `runtime/pulse_anchor.html`
- Modify: `runtime/test_ui_contract.py`
- Create: `runtime/test_sum_listener_contract.py`

**Interfaces:**
- Consumes app tools: `sum_controller_status`, `sum_controller_set`, `sum_controller_log`
- Produces JS functions: `renderSumState(state)`, `refreshSumState()`, `setSumEnabled(enabled)`, `renderSumLog(entries)`

- [ ] **Step 1: Write failing UI contract tests**

Assert the template contains:

```text
AUTO WAKE CYCLE
sumState
sumToggle
sumCycle
sumWakeAttempts
sumConfirmedWakes
sumCurrentDuration
sumLog
renderSumState
sum_controller_status
sum_controller_set
```

Assert CSS classes exist for gray `idle`, red `wake`, green `awake`, and yellow `working`.

- [ ] **Step 2: Run targeted UI tests and verify failure**

Run: `python -m pytest runtime/test_ui_contract.py runtime/test_sum_listener_contract.py -q`
Expected: FAIL on missing controls/state renderer.

- [ ] **Step 3: Add compact state rendering**

Make the compact dot and label controller-aware while preserving independent PiP/Listener health details. Render exact labels such as `WAKE · attempt 2`, `AWAKE · cycle 17`, and `WORKING · 01:24`.

- [ ] **Step 4: Add fullscreen control cards**

Add ON/OFF switch, Pause, Stop, Reset statistics, Open log, and Copy diagnostic snapshot. Show current state, IDs, counters, total runtime, state duration, heartbeat age, PiP state, confidence, last transition, and last error.

- [ ] **Step 5: Implement polling and mutations**

Poll `sum_controller_status` every 1–2 seconds in fullscreen and at a lighter interval in compact/PiP. Call `sum_controller_set` only from explicit user controls.

- [ ] **Step 6: Implement durable log viewer**

Fetch bounded entries through `sum_controller_log(limit=100)`, render newest first, and display timestamp/state/reason/wake ID/attempt/error.

- [ ] **Step 7: Run UI contract tests**

Run: `python -m pytest runtime/test_ui_contract.py runtime/test_sum_listener_contract.py -q`
Expected: PASS.

- [ ] **Step 8: Commit visual controller UI**

```bash
git add runtime/pulse_anchor.html runtime/test_ui_contract.py runtime/test_sum_listener_contract.py
git commit -m "feat: add SUM state UI and controls"
```

---

### Task 4: Continuous Host Activity Detector

**Files:**
- Modify: `runtime/pulse_anchor.html`
- Modify: `runtime/test_sum_listener_contract.py`

**Interfaces:**
- Consumes app tool: `sum_host_signal`
- Produces JS functions: `recordHostSignal(kind, active, detail)`, `classifyHostActivity()`, `scheduleStaticCandidate()`

- [ ] **Step 1: Write failing source-contract tests for all host signals**

Require listeners for `ui/notifications/host-context-changed`, `openai:set_globals`, `focus`, `blur`, `visibilitychange`, `pageshow`, `pagehide`, `freeze`, and `resume`, plus bridge request start/end activity.

- [ ] **Step 2: Add a telemetry-only detector first**

Record timestamped signals and a confidence score. Do not trigger wakes yet. Coalesce high-frequency signals and call `sum_host_signal` only on meaningful changes or heartbeat intervals.

- [ ] **Step 3: Classify activity conservatively**

Treat correlated bridge/tool activity and host generation signatures as active. Treat static only after prior activity or guarded ACK state, no recent active signals, visible healthy Listener, and stable debounce.

- [ ] **Step 4: Add diagnostic snapshot fields**

Include recent host signals, current classification, confidence, debounce deadline, PiP state, visibility, focus, display mode, and last bridge activity.

- [ ] **Step 5: Run source and server transition tests**

Run: `python -m pytest runtime/test_sum_listener_contract.py runtime/test_sum_controller.py -q`
Expected: PASS.

- [ ] **Step 6: Commit detector**

```bash
git add runtime/pulse_anchor.html runtime/test_sum_listener_contract.py
git commit -m "feat: monitor ChatGPT host activity for SUM"
```

---

### Task 5: ACK-Aware Wake Delivery and Retry Loop

**Files:**
- Modify: `runtime/pulse_anchor.html`
- Modify: `runtime/server_v2.py`
- Modify: `runtime/test_sum_listener_contract.py`
- Modify: `runtime/test_sum_server_tools.py`

**Interfaces:**
- Consumes: `sum_controller_tick`, `sum_wake_sent`, `sum_wake_ack_current`, existing `bridgeRequest('ui/message', ...)`
- Produces the exact natural user-role wake content: `Отлично, продолжай.`
- Keeps `controller_id`, `cycle_id`, `wake_id`, and `awake_epoch` only in server state and logs, never in visible message text

- [ ] **Step 1: Write failing tests for natural user-role wake content and retry identity**

Assert `buildSumWakeMessage()` returns exactly `Отлично, продолжай.` and the `ui/message` payload uses `role: user`. Assert the visible content contains no identifiers, JSON, brackets, tool names, or protocol instructions. Assert retries reuse the same server-side `wake_id` and only increment attempt.

- [ ] **Step 2: Integrate controller tick into Listener poll loop**

When controller state requests wake and no Pulse event is being handled, send the controller wake through the same proven correlated `ui/message` bridge.

- [ ] **Step 3: Mark delivery attempt**

After bridge-confirmed delivery call `sum_wake_sent(listener_session_id, delivery_mode)`. Do not mark ACKed and do not advance cycle.

- [ ] **Step 4: Add natural user-message and hidden ACK contract**

`buildSumWakeMessage()` must return exactly:

```text
Отлично, продолжай.
```

Send it with `role: user`. Do not embed identifiers, protocol headers, tool instructions, JSON, or metadata-like text in visible content. Register `sum_wake_ack_current(actor="chatgpt")` so the model acknowledges the authoritative outstanding wake without receiving technical identifiers in the message. Visible assistant text remains optional.

- [ ] **Step 5: Implement retry rendering and suppression**

Remain red before ACK. Retry only after controller timeout, same IDs, bounded attempts. Suppress duplicate simultaneous sends and log `DUPLICATE_WAKE_SUPPRESSED`.

- [ ] **Step 6: Run tests**

Run: `python -m pytest runtime/test_sum_controller.py runtime/test_sum_server_tools.py runtime/test_sum_listener_contract.py runtime/test_ui_contract.py -q`
Expected: PASS.

- [ ] **Step 7: Commit wake integration**

```bash
git add runtime/pulse_anchor.html runtime/server_v2.py runtime/test_sum_listener_contract.py runtime/test_sum_server_tools.py
git commit -m "feat: add ACK-aware SUM wake loop"
```

---

### Task 6: Regression, Deployment, and Live Calibration

**Files:**
- Modify only if failures require it: `runtime/test_pulse_mount_lifecycle.py`, `runtime/server_v2.py`, `runtime/pulse_anchor.html`
- Update after proof: `docs/EIROS_CURRENT_HANDOFF.md`, `docs/EIROS_CURRENT_HANDOFF.json`

**Interfaces:**
- Produces a new cache-busted Listener version and URI while retaining v0.5.7 resource alias.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
python -m pytest \
  runtime/test_sum_controller.py \
  runtime/test_sum_server_tools.py \
  runtime/test_sum_listener_contract.py \
  runtime/test_ui_contract.py \
  runtime/test_pulse_mount_lifecycle.py \
  runtime/test_widget_boot_diagnosis.py \
  runtime/test_widget_boot_diagnostics.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full runtime tests**

Run: `python -m pytest runtime/test_*.py -q`
Expected: PASS or document only pre-existing unrelated failures with evidence.

- [ ] **Step 3: Compile and restart safely**

Run `python -m py_compile runtime/server_v2.py runtime/sum_controller.py`, restart `eiros-mcp.service`/actual allowlisted bridge service only after confirming the deployed unit name, and verify `/readyz` plus service journal.

- [ ] **Step 4: Mount the new Listener once**

Use a new cache-busted version/URI. Preserve v0.5.7 as rollback. Call `widget_boot_status(wait_seconds=5)` and require `JS_STARTED`, `BRIDGE_READY`, `HEARTBEAT_OK`, `PULSE_POLL_OK`, `VIDEO_READY`, and `PIP_ACTIVE`.

- [ ] **Step 5: Calibrate visual host detection with one manual turn**

With Auto Wake off, observe gray idle. Send one normal Rico message, verify yellow during assistant work and gray after stable static. Inspect durable signal log for false transitions.

- [ ] **Step 6: Verify one bounded cycle**

Enable Auto Wake. Require red wake, explicit assistant ACK, immediate green, yellow working, stable static, and exactly one next red wake. Stop after one cycle.

- [ ] **Step 7: Verify two consecutive cycles**

Run two cycles without a new Rico message. Confirm cycle/wake/ACK/retry counters and durations match JSONL logs.

- [ ] **Step 8: Verify failure paths**

Test no-ACK retry, Stop, PiP loss, stale ACK, and duplicate wake suppression. Ensure no uncontrolled loop remains.

- [ ] **Step 9: Update handoff and commit proof**

```bash
git add docs/EIROS_CURRENT_HANDOFF.md docs/EIROS_CURRENT_HANDOFF.json
git commit -m "docs: record SUM auto-wake proof"
```

- [ ] **Step 10: Final verification snapshot**

Capture controller status, bounded log tail, Listener boot status, Pulse backlog, service status, and exact commit hashes before declaring completion.

---

## Plan Self-Review

- Spec coverage: state colors, explicit ACK, continuous monitoring, switch, metrics, logs, retries, safety limits, PiP health, stale-event protection, rollback, and live two-cycle proof are each mapped to tasks.
- Placeholder scan: no TBD/TODO or unspecified “handle errors” steps remain.
- Type consistency: controller methods and MCP tool names are defined once and reused consistently across tasks.
- Scope: one subsystem with server engine, MCP boundary, Listener UI/detector, and deployment verification; no unrelated Room redesign is included.
