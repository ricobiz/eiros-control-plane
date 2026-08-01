# SUM Auto-Wake Controller — Design Specification

**Date:** 2026-08-02

**Status:** Approved design, pending user review

**Target:** EIROS Wake Listener / fullscreen Control Room

**Baseline to preserve:** working v0.5.7 Listener + active Video PiP + Pulse wake path

## 1. Purpose

SUM must continue a multi-turn EIROS work cycle without relying on ChatGPT to remember to schedule another timer before each turn ends.

The Listener remains alive beside the ChatGPT conversation through Video PiP, observes the host activity state continuously, delivers wake messages, waits for an explicit acknowledgement from ChatGPT, then detects when ChatGPT returns to a stable static state and starts the next cycle.

The system must make every stage visible, auditable, bounded, and diagnosable.

## 2. Scope

This feature adds:

1. A persistent auto-wake state machine inside the live Listener.
2. Explicit wake acknowledgement from ChatGPT.
3. Continuous host-activity monitoring while the Listener is alive.
4. A fullscreen `Auto Wake Cycle` switch and controls.
5. Clear color/status feedback in compact and fullscreen views.
6. Durable cycle statistics and transition logs.
7. Retry, timeout, stale-state, and safety-limit diagnostics.

This feature does **not** replace the durable task queue, Pulse, SAM, or PiP. It coordinates them.

## 3. User-visible state model

The compact Listener and fullscreen Control Room use exactly these primary colors:

| Color | State | Meaning |
|---|---|---|
| Gray | `IDLE` / `MONITORING` | Listener is alive. Auto-wake is off, or the controller is waiting without an active cycle. |
| Red | `WAKE` | SUM is initiating or retrying a wake and has not yet received ChatGPT acknowledgement. |
| Green | `AWAKE` | ChatGPT explicitly acknowledged the current `wake_id`; retries stop immediately. |
| Yellow | `WORKING` | ChatGPT host activity indicates the current assistant turn is still active: generating, using tools, or otherwise not static. |

Green is reserved for a confirmed wake. It must not also mean merely “Listener healthy.” Listener/PiP health is displayed separately.

### Compact labels

Examples:

- `IDLE · monitoring`
- `WAKE · attempt 2`
- `AWAKE · cycle 17`
- `WORKING · 01:24`
- `ERROR · ACK_TIMEOUT`

## 4. State machine

```text
DISABLED
  └─ user enables Auto Wake Cycle → ARMED

ARMED
  └─ stable static detected → WAKE_PENDING

WAKE_PENDING (red)
  ├─ send wake(wake_id, cycle_id, epoch)
  ├─ no ACK before retry deadline → WAKE_RETRY
  ├─ retry budget exceeded → ERROR
  └─ ACK received → AWAKE

AWAKE (green)
  ├─ host activity begins → WORKING
  ├─ no visible activity but ACK accepted → wait for activity/static evidence
  └─ protocol timeout → ERROR or guarded recovery

WORKING (yellow)
  ├─ activity continues → remain WORKING
  └─ static candidate observed → STATIC_DEBOUNCE

STATIC_DEBOUNCE
  ├─ activity resumes → WORKING
  └─ static remains stable for debounce interval → CYCLE_COMPLETE

CYCLE_COMPLETE
  ├─ cycle still enabled and limits remain → increment cycle, return to WAKE_PENDING
  └─ objective/controller stopped → IDLE

ERROR
  ├─ recoverable and retry allowed → controlled retry
  └─ user stops/resets → IDLE
```

## 5. Wake acknowledgement contract

Delivery is not considered successful merely because `ui/message` accepted the request.

Each wake has immutable identifiers:

```text
controller_id
cycle_id
wake_id
awake_epoch
attempt
sent_at
```

The first EIROS action after ChatGPT receives a SUM wake is an explicit acknowledgement:

```text
sum_wake_ack(
  controller_id,
  cycle_id,
  wake_id,
  awake_epoch,
  assistant_actor
)
```

On valid ACK:

1. The wake changes to `ACKED`.
2. All retry timers for that `wake_id` are cancelled.
3. The visible state changes from red `WAKE` to green `AWAKE`.
4. SUM begins waiting for host activity and the later return to static.

ChatGPT may then write a visible reply, call tools, or perform a technical step without a user-visible message. The ACK is the authoritative delivery proof.

Duplicate ACKs are idempotent. An ACK for an old `wake_id`, wrong `cycle_id`, or superseded epoch is logged and ignored.

## 6. Continuous host-state monitoring

The Listener remains active through the proven Video PiP keepalive path and continuously records host signals such as:

- `ui/notifications/host-context-changed`
- `openai:set_globals`
- `focus` / `blur`
- `visibilitychange`
- `pageshow` / `pagehide`
- `freeze` / `resume`
- display-mode changes
- bridge request/response activity
- Listener heartbeat and PiP state

The detector classifies a transition, not a single event. No individual `blur`, `hidden`, or display-mode change is enough to declare the assistant static.

### Static confirmation rule

A new cycle may start only when all are true:

1. The current wake was ACKed.
2. The controller observed activity for the current epoch, or the guarded no-activity path completed.
3. No activity signal has occurred for the configured debounce period.
4. Listener heartbeat and PiP remain healthy.
5. No wake is already outstanding for the current cycle.
6. Auto Wake Cycle remains enabled.

Initial defaults:

- static debounce: 3 seconds;
- wake ACK timeout: 8 seconds;
- retry interval: 5 seconds;
- maximum attempts per wake: 5.

These values are configuration, not hard-coded semantics.

## 7. Fullscreen Control Room

The compact Listener is primarily a monitor. The user opens the existing fullscreen EIROS console from the widget to control the cycle.

The fullscreen panel contains:

### Main switch

```text
AUTO WAKE CYCLE     OFF / ON
```

Enabling it creates or resumes one controller session. Disabling it stops future wakes but does not kill the Listener, PiP, Pulse, or durable history.

### Controls

- `Start / Enable`
- `Pause`
- `Stop`
- `Reset statistics`
- `Open log`
- `Copy diagnostic snapshot`

`Stop` invalidates the active controller epoch so delayed or duplicate events cannot restart it.

### Live metrics

- Current state
- Controller ID
- Cycle number
- Current `wake_id`
- Start time
- Total runtime
- Current cycle duration
- Time in current state
- Wake attempts
- Confirmed wakes
- Retries
- Failed wakes
- Last ACK time
- Last transition
- Listener heartbeat age
- PiP state
- Host-state confidence

The primary controller lives in the fullscreen Listener Control Room. It must not depend on a separately mounted Collab Room, because the Listener/PiP is the proven always-on surface. A Collab Room may mirror the state later but is not required for operation.

## 8. Durable controller state

A server-side controller record is the authority. Local storage may cache UI state but must not be the sole source of truth.

Suggested record:

```json
{
  "controller_id": "sum-...",
  "enabled": true,
  "state": "WORKING",
  "revision": 12,
  "cycle_id": 17,
  "awake_epoch": 17,
  "wake_id": "wake-...",
  "wake_attempt": 1,
  "started_at": 0,
  "state_entered_at": 0,
  "last_activity_at": 0,
  "last_static_candidate_at": 0,
  "last_ack_at": 0,
  "listener_session_id": "...",
  "max_cycles": 100,
  "max_runtime_seconds": 14400,
  "stop_reason": null,
  "counters": {
    "cycles_started": 17,
    "wakes_sent": 21,
    "wakes_acked": 17,
    "retries": 4,
    "errors": 0
  }
}
```

Every mutation uses revision checks to prevent two Listener instances from advancing the same controller.

## 9. Logging and diagnostics

Every state transition is written to a bounded durable JSONL log and surfaced in the fullscreen UI.

Required fields:

```text
timestamp
controller_id
revision
cycle_id
awake_epoch
wake_id
previous_state
new_state
reason
attempt
listener_session_id
host_signal
confidence
elapsed_ms
error_code
```

Example:

```text
05:54:12 CYCLE_ARMED
05:54:15 STATIC_CONFIRMED
05:54:15 WAKE_SENT wake_id=78 attempt=1
05:54:20 WAKE_RETRY wake_id=78 attempt=2
05:54:22 WAKE_ACK wake_id=78
05:54:22 AWAKE
05:54:23 WORKING
05:55:04 STATIC_CANDIDATE
05:55:07 STATIC_CONFIRMED
05:55:07 CYCLE_COMPLETE
```

Required error codes:

- `ACK_TIMEOUT`
- `WAKE_DELIVERY_FAILED`
- `HOST_STATE_UNKNOWN`
- `STATIC_DETECTOR_UNCERTAIN`
- `PIP_HEARTBEAT_LOST`
- `LISTENER_HEARTBEAT_LOST`
- `DUPLICATE_WAKE_SUPPRESSED`
- `STALE_ACK_IGNORED`
- `REVISION_CONFLICT`
- `CYCLE_LIMIT_REACHED`
- `RUNTIME_LIMIT_REACHED`
- `USER_STOPPED`

The UI must show the exact failed stage and last successful stage, not merely a generic red error.

## 10. Safety and loop limits

The auto-wake loop is bounded even when enabled.

Defaults:

- maximum 100 cycles per controller session;
- maximum 4 hours continuous runtime;
- maximum 5 delivery attempts per wake;
- only one active controller per Listener authority lease;
- only one outstanding wake per cycle;
- user message or Stop command may pause/stop the loop;
- loss of PiP/Listener heartbeat pauses new wakes;
- stale events from an old epoch cannot revive a stopped session.

Limits are visible in the UI and recorded when reached.

## 11. Failure recovery

### Wake sent, no ACK

Remain red, retry the same `wake_id`, increment only `attempt`, and never start another cycle.

### ACK received, host state unclear

Remain green with warning detail, collect host signals, and do not issue another wake until static is safely confirmed or a timeout enters `HOST_STATE_UNKNOWN`.

### Listener/PiP interrupted

Persist controller state, mark paused/error, stop new wakes, and resume only after the same or a newer valid Listener session reacquires authority.

### Duplicate Listener

The current leader/lease mechanism selects one authority. Non-leaders display mirrored state but cannot send wakes or advance counters.

### User sends a new message

The controller records the interruption. Default behavior is to pause automatic continuation until the current user-directed turn is acknowledged, preventing SUM from competing with Rico.

## 12. Compatibility and rollout

Implementation must preserve the proven v0.5.7 self-wake route until the new version passes regression tests.

Rollout sequence:

1. Add server-side controller state and log APIs.
2. Add Listener telemetry-only host detector and observe one manual conversation turn.
3. Calibrate active/static signatures for the current iOS app.
4. Add visual gray/red/green/yellow states without automatic wake.
5. Add fullscreen switch and bounded one-cycle mode.
6. Verify ACK retry behavior.
7. Verify two consecutive cycles.
8. Enable continuous bounded mode.
9. Keep v0.5.7 available as rollback oracle until all tests pass.

## 13. Acceptance tests

The feature is accepted only when all of the following are observed in live ChatGPT iOS testing:

1. With Auto Wake off, the widget remains gray and no automatic wake occurs.
2. Enabling Auto Wake in fullscreen persists across compact/fullscreen transitions.
3. On static confirmation, the widget turns red and sends exactly one wake attempt at a time.
4. Without ACK, it remains red and retries the same `wake_id`.
5. On explicit ACK, it turns green immediately and stops retries.
6. When host activity begins, it turns yellow and displays `WORKING`.
7. It does not interpret a short blur/tool pause as static.
8. After stable static, it starts the next cycle and turns red.
9. Two complete consecutive cycles run without Rico sending another message.
10. Cycle count, attempt count, durations, ACKs, retries, and transitions match the durable log.
11. Killing PiP or Listener prevents new wakes and produces a specific diagnostic.
12. Stop prevents delayed events or stale ACKs from restarting the controller.
13. Existing one-shot SAM/Pulse wake behavior remains functional.

## 14. Chosen design decisions

- Gray means idle/monitoring only.
- Green means a specific wake was explicitly ACKed.
- Yellow means observed ChatGPT work activity.
- Red means wake initiation/retry before ACK.
- Control lives in the fullscreen Listener Control Room; compact PiP is primarily monitoring.
- ACK is explicit and authoritative; visible assistant text is optional.
- The Listener continuously monitors host state while PiP is alive.
- Static detection is transition-based and debounced.
- All cycles are durable, revisioned, bounded, and fully logged.
