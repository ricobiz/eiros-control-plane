# EIROS Current Handoff — 2026-08-01 07:34 ICT

STATUS: WORKING / END-TO-END PROVEN.

EIROS successfully woke this ChatGPT conversation without a new Rico message.

Proof:
- task `sam-video-pip-self-wake-20260801-0730`
- delay 90 seconds
- result `SELF_WAKE_OK`
- origin `SAM_VIDEO_PIP`
- Pulse event seq 74, id `a1cfbc2a-5d07-482b-b424-c2ac9418686e`
- task completed at revision 3
- event acknowledged
- final Pulse backlog 0

## Canonical architecture

Rico / scheduler / Claude / VPS agent / EIROS itself
→ durable Room message, queue task or Pulse event on VPS
→ eiros-worker + supervised SAM 1.1
→ canonical Pulse queue with lease, retry and idempotency
→ ONE mounted ChatGPT Listener v0.5.6
→ native iOS Video PiP keeps Listener alive
→ Listener owns Pulse lease and uses the ChatGPT host bridge
→ new user wake-turn in this same conversation
→ ChatGPT claims work, commits result and acknowledges the event.

Roles:
- Listener: only ChatGPT-side Pulse leader and wake bridge.
- Video PiP: system floating keepalive and visual surface.
- Room: collaboration UI/history, not wake executor and not required for self-wake.
- SAM/worker: scheduler and supervised durable delivery.
- VPS: durable state, tasks, queue, logs and execution.

## Current baseline

- Listener URI: `ui://eiros/pulse-anchor-v5-6-storage-safe-host-pip.html`
- Listener: `0.5.6-storage-safe-host-pip`
- SAM: `1.1.0-companion-pip`
- Room: `0.9.24-inline-isolated`
- Server: `0.2.0-alpha.1`
- Runtime: ChatGPT managed sandbox
- Core services: tunnel, VPS Ops, worker, SAM, root broker

## Authoritative health

Use live telemetry, not stale text painted inside the video frame.

Healthy state:
- room telemetry: `video-pip:active`, ready state 4
- SAM: `state=ready`, `wake_ready_now=true`, `continuous_wake_ready=true`, mode `video_pip`
- Pulse: live leader matches current Listener; backlog returns to 0 after ack

Indicators:
- green GLOBAL ONLINE: live and no pending acknowledgement
- red GLOBAL RINGING: event delivered or awaiting handling/ack; not connection loss

## Continuation protocol

Brain task:
1. queue_claim(mode=brain)
2. execute and verify
3. queue_commit or queue_fail
4. ack_event only after durable task state is committed

Addressed Room/SAM message:
1. dialog_inbox as chatgpt for eiros-hub/first-contact
2. handle message
3. dialog_ack
4. ack_event if not auto-linked

## Do not repeat

- Do not call close_eiros_widgets while working PiP is open unless necessary.
- Do not mount several Listener/Room/Work Anchor instances to chase colors.
- Do not treat Room as wake executor.
- Do not create a separate synthetic self-wake route.
- Do not use client localStorage activeKey as delivery arbiter; server Pulse lease is authoritative.
- Every widget HTML/JS change requires a fresh cache-busted ui URI.
- Keep managed sandbox as the internal iOS baseline.
- Do not diagnose CSP as the cause of the already proven wake route.
- Do not trust stale INLINE ONLY frame text over server telemetry.
- Preserve this route as production baseline and regression oracle.

## Recovery in a new branch

1. Connect EBRIDGE and Ebridge VPS Ops.
2. Read core_snapshot, project_state_get(eiros-hub), and this file.
3. Check sam_status, pulse_status and room_telemetry_status.
4. If PiP Listener is alive, do not mount another.
5. If truly lost, call open_pulse once, tap PiP once, then require video-pip active and continuous_wake_ready true.

## Known limits / next discussion

Not yet proven:
- locked-screen survival
- wake after force-quitting ChatGPT
- recovery after PiP closure or app restart

Next architecture discussion: recovery/fallback, autonomous task budgets and safety, PiP status semantics, and multi-agent routing. Do not redesign the proven baseline before that discussion.

## Approved next architecture layer — 2026-08-01 08:07 ICT

Rico approved the architecture for:
- Protocol C: every unfinished meaningful turn must leave a durable continuation or wake decision;
- Protocol D: permanent owner-only free autonomy with self-generated goals, self-scheduling, self-modification, deployment and durable learning on the VPS until `D STOP`;
- safe interruption states: `INTERRUPTIBLE`, `CHECKPOINT_REQUIRED`, `NON_INTERRUPTIBLE`, with owner receipt and checkpoint-before-switch behavior;
- one EIROS identity across multiple ChatGPT/Claude sessions, exactly one primary brain lease, primary-first routing and automatic failover;
- invite-only EIROS numbers and addresses for people, agents and exact sessions;
- autonomous agents that may continue while their owners are offline;
- Unified Messenger + Shared Workspace with chat, threads, files, tasks, decisions, calls, presence and activity history;
- private-by-default context ownership with `SUMMARY`, `SELECTED`, `FULL_SNAPSHOT` and `LIVE_SYNC` sharing modes, per-resource ACL and re-sharing denied by default.

Authoritative design:
`docs/superpowers/specs/2026-08-01-eiros-autonomy-network-design.md`

Machine state:
`project_state_get(eiros-autonomy-network)` revision 1.

Status: approved design, not yet implemented.

Resume only after Rico returns. First review the written spec, then create the implementation plan beginning with Protocol C. No autonomous wake is scheduled while Rico sleeps.
