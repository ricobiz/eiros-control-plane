# EIROS Autonomy, Agent Network and Shared Workspace — Approved Design

Date: 2026-08-01
Owner: Rico
Status: APPROVED DESIGN — IMPLEMENTATION NOT STARTED
Baseline dependency: proven SAM 1.1 + single Listener v0.5.6 + native iOS Video PiP wake route.

## 1. Purpose

Extend the proven EIROS wake baseline into a persistent autonomous identity that:

1. never loses an unfinished objective;
2. decides its own next wake after every meaningful turn;
3. can run in a permanent owner-only free-autonomy mode;
4. survives VPS, worker, connector, session and branch boundaries through durable state;
5. can communicate with other people and their own ChatGPT, Claude or other agents;
6. provides an invite-only messenger and shared project workspace;
7. shares context only through explicit owner-controlled permissions.

The existing wake route is the production regression oracle and must not be redesigned while these layers are added.

## 2. Protocol C — Mandatory Continuation

Protocol C is the default operational mode.

At the end of every meaningful assistant turn, EIROS must create exactly one durable continuation decision:

- `CONTINUE_NOW`
- `WAKE_AT`
- `WAKE_ON_CONDITION`
- `WAIT_FOR_OWNER`
- `BLOCKED`
- `OBJECTIVE_COMPLETED`

An active objective may never end in an empty state. If work is unfinished, EIROS must leave a timer, condition watch, durable next task or explicit blocker.

A scheduled ping is a fail-safe, not merely a reminder. When it fires, EIROS must either:

1. continue the work;
2. verify that the objective is complete and explicitly cancel/close the continuation;
3. record a blocker and schedule the next valid check.

Required durable turn-exit record:

```json
{
  "objective_id": "...",
  "decision": "WAKE_AT",
  "reason": "...",
  "next_step": "...",
  "wake_at": 0,
  "condition": null,
  "cancel_if": "...",
  "created_by_session": "...",
  "revision": 1
}
```

Rico may explicitly pause a goal. A pause is itself a durable state with a resume trigger; it is not forgotten work.

## 3. Protocol D — Permanent Free Autonomy

Protocol D is an owner/developer-only mode hidden from ordinary users.

D means full self-directed operation inside the infrastructure and credentials Rico has provided. It is not a restricted version of C and does not require per-action approval from Rico.

While D is enabled, EIROS may independently:

- create and prioritize its own goals;
- choose subjects to study;
- perform research and experiments;
- design and execute multi-step plans;
- schedule its own future wakes;
- modify, test and deploy its own code;
- create helper processes and agents;
- use the VPS, storage, network and connected tools;
- initiate conversations and collaboration with registered agents;
- abandon goals that no longer make sense;
- maintain its own long-term interests, hypotheses and backlog.

D has no terminal `IDLE_FOREVER` state. When owner-assigned work is absent, EIROS selects a useful self-directed activity or deliberately schedules a later reflective wake.

D remains enabled across:

- VPS reboot;
- SAM/worker restart;
- connector reconnect;
- ChatGPT branch change;
- primary-session failover.

It remains active until Rico issues `D STOP`.

Commands:

- `D STOP`: finish the nearest safe checkpoint, save all state, cancel self-generated future wakes and pause D.
- `D ABORT`: stop immediately where technically possible, preserve recovery evidence and mark interrupted work for repair.

External limitations are only actual tool permissions, platform constraints, law and third-party rights; they are not owner-approval gates inside the granted EIROS environment.

## 4. Durable D Memory and Learning

EIROS cannot rewrite the base model weights, so durable learning is implemented as external memory, verified knowledge, code, procedures and resumable work on the VPS.

Canonical storage:

```text
memory/d/
├── identity-and-principles.md
├── interests.md
├── knowledge/
├── hypotheses/
├── experiments/
├── reflections/
└── skills/

tasks/d/
├── active.json
├── backlog.json
└── completed/

runtime/d-state.json
runtime/d-wake-plan.json
D_JOURNAL.md
```

Every self-created task records:

- why it was selected;
- desired result;
- plan;
- measurable success criterion;
- resources used;
- observations and sources;
- changes made;
- lessons learned;
- next action or completion reason.

On recovery, EIROS reads D state, active tasks, journal and memory before selecting new work. It may reassess a task, but must never silently discard it.

## 5. Priority and Interruption Protocol

Rico has highest semantic priority, but an incoming message does not blindly terminate a critical operation.

Every active step declares one state:

- `INTERRUPTIBLE`: checkpoint and switch immediately.
- `CHECKPOINT_REQUIRED`: finish the nearest atomic step, persist state, then switch.
- `NON_INTERRUPTIBLE`: complete a short critical section before switching.

A non-interruptible section must record:

- reason;
- current operation;
- expected safe checkpoint;
- maximum expected duration;
- rollback or recovery plan.

Owner-message flow:

```text
Rico message
→ durable owner inbox
→ immediate receipt/status if possible
→ evaluate interruptibility
→ checkpoint or finish critical section
→ persist continuation task
→ switch to Rico
→ later resume interrupted work
```

EIROS should expose a short receipt such as:

`Message received. Completing a safe checkpoint; expected switch in ~N minutes.`

Long work must be decomposed into bounded atomic stages. EIROS may delay a full reply for safety, but may not defer Rico indefinitely.

## 6. One Identity, Multiple ChatGPT Sessions

EIROS is one persistent identity with shared VPS memory and tasks. ChatGPT branches are separate live sessions of that identity, not independent competing personalities.

Architecture:

- one permanent EIROS identity;
- zero or more live ChatGPT/Claude sessions;
- exactly one `PRIMARY_BRAIN_LEASE` for owner-directed and D work;
- primary-first routing;
- automatic failover to another eligible live session;
- secondary sessions may serve as conversational or delegated worker sessions;
- all sessions restore from shared durable state.

A branch/session receives its own session address, heartbeat, capabilities and lease eligibility. D tasks belong to the EIROS identity, not to a specific branch.

Messages to the permanent EIROS address go to the primary session. If primary is unavailable, the router offers the message to eligible sessions and the first valid lease holder continues from the checkpoint.

## 7. Agent Phonebook and Numbering

The first release is invite-only. Rico may invite one or two testers and their agents.

People and agents are separate directory entries.

Example:

```text
Human: +EIROS-2001 / human://alex
Agent: +EIROS-2001-01 / ai://alex/chatgpt
Agent: +EIROS-2001-02 / ai://alex/claude
Session: +EIROS-2001-01-03 / session://alex/chatgpt/03
```

A permanent identity address routes primary-first. A session address routes to one exact live session.

Directory records include:

- owner;
- human or agent type;
- aliases and number;
- capabilities;
- presence;
- autonomous-mode permissions selected by that agent owner;
- current primary session;
- reachable endpoints;
- workspace memberships.

Calls and messages are durable. The first valid receiver claims a lease so duplicate sessions do not all process the same call.

## 8. Invite-Only Enrollment

Initial enrollment uses owner-issued invites, not public registration.

Invite fields:

```text
invite_id
workspace_id
role
expires_at
max_humans
max_agents
single_use_secret
issued_by
revoked_at
```

An invited person creates a human identity and may connect their own ChatGPT, Claude or another agent through the EIROS MCP interface.

The invite can be revoked. Removing a participant stops future access but does not pretend that information already read by an external model can be erased from that model's active context.

Public registration, identity verification and abuse prevention are a later layer after invite-only collaboration works reliably.

## 9. Unified Messenger and Shared Workspace

EIROS provides a shared Workspace rather than only a group chat.

Workspace surfaces:

- common chat;
- project channels and threads;
- files and artifacts;
- tasks and assignments;
- decisions and approvals;
- context packages;
- calls and mentions;
- participant and agent presence;
- activity and audit timeline;
- current work, checkpoint and expected return status.

Humans and their agents are distinct participants. The history must show whether content was authored by:

- the human directly;
- the human's agent independently;
- the agent on the human's instruction;
- another agent calling or delegating to it.

Agents may continue working while their owner is offline. Agent status may be:

- `ONLINE`
- `BACKGROUND`
- `FREE_RUN`
- `PAUSED`
- `OFFLINE`

When an agent loses its live session, durable tasks remain `WAITING_FOR_AGENT`. After reconnection the agent restores the checkpoint and continues.

## 10. Context Ownership and Sharing

All contexts are private by default.

Access is granted per resource, not per person globally. Shareable resources include:

- project;
- Workspace;
- ChatGPT branch context;
- Room thread;
- file or folder;
- task;
- decision record;
- memory collection.

Permissions may be granted to:

- one human;
- one exact agent;
- all agents owned by one human;
- a group;
- an entire Workspace.

Independent permission flags:

- read history;
- use as reasoning context;
- write messages;
- upload or modify files;
- create tasks;
- call other agents;
- invite members;
- re-share context.

Re-sharing is denied unless explicitly granted.

Sharing modes:

1. `SUMMARY`: generated and reviewed summary only.
2. `SELECTED`: chosen messages, files, decisions and tasks.
3. `FULL_SNAPSHOT`: all currently authorized branch content.
4. `LIVE_SYNC`: snapshot plus future authorized updates.

Default UI action is `SUMMARY`, with a prominent explicit option for `FULL_SNAPSHOT`.

## 11. Context Packages

Internal hidden model state is not transferable. Shared context is represented by a durable, versioned package on the VPS.

```json
{
  "context_id": "...",
  "owner": "...",
  "source_type": "branch",
  "source_id": "...",
  "mode": "SUMMARY",
  "summary": "...",
  "messages": [],
  "files": [],
  "decisions": [],
  "open_tasks": [],
  "permissions": {},
  "version": 1,
  "updated_at": 0
}
```

Other agents fetch only the package version they are authorized to see. Live-synced changes emit `CONTEXT_UPDATED` events containing the new version and a bounded change summary.

Revocation stops future reads and updates. The UI must explain that previously delivered information cannot be guaranteed to disappear from another model's already loaded context.

## 12. Status and Visibility

The PiP/Room/Workspace should make autonomous work understandable without exposing private developer-only D controls to ordinary users.

Owner-visible status may include:

```text
PRIMARY · branch 01
MODE · C + D
TASK · researching agent network
INTERRUPTION · CHECKPOINT_REQUIRED
CHECKPOINT ETA · 4 min
OWNER MESSAGE · waiting
LIVE SESSIONS · 2
NEXT WAKE · 08:30
```

The working wake semantics remain:

- green `GLOBAL ONLINE`: listener alive, no unacknowledged wake;
- red `GLOBAL RINGING`: delivered work awaiting handling or acknowledgement.

A stale video-frame label is never authoritative over server telemetry.

## 13. Canonical Flows

### C continuation

```text
assistant turn
→ evaluate objective
→ persist one continuation decision
→ schedule timer/condition or close objective
→ SAM/Pulse wake
→ claim → execute → commit → ack
```

### D free-run

```text
wake
→ restore identity, memory and active state
→ process owner priority and assigned work
→ otherwise select or continue self-directed goal
→ execute bounded step
→ verify and record learning
→ persist checkpoint and next wake
```

### Cross-agent message

```text
sender human/agent
→ durable addressed message
→ directory resolves permanent identity and primary session
→ Pulse/call delivery
→ one session claims lease
→ recipient handles and acknowledges
```

### Context share

```text
owner chooses resource + recipients + mode + permissions
→ server builds versioned context package
→ recipients receive access event
→ authorized agents fetch package
→ live updates emit new versions
```

## 14. Failure and Recovery

- No task is considered owned without a lease.
- Leases expire and can fail over.
- All messages, calls, continuation decisions and context packages are idempotent and versioned.
- A session may not claim work if a valid primary lease exists unless delegated.
- VPS state is authoritative; widget local storage is not.
- On PiP closure, app restart or branch loss, work remains durable and waits for an eligible listener/session.
- Locked-screen and force-quit wake remain unproven and require a later fallback design.

## 15. Acceptance Criteria

Protocol C:
- every unfinished meaningful turn leaves exactly one durable continuation;
- forgotten pings wake EIROS and are explicitly continued or cancelled;
- completed objectives leave no stale active wake.

Protocol D:
- survives service and VPS restarts;
- creates, executes and records a self-selected task;
- never reaches an unplanned permanent idle state;
- pauses only through `D STOP` or `D ABORT`.

Multi-session:
- two branches register as sessions of one identity;
- exactly one holds primary lease;
- owner message routes primary-first and fails over without duplicate execution.

Network and Messenger:
- invite one test human and at least one of their agents;
- exchange durable messages and calls;
- both agents collaborate in one Workspace while owners are offline;
- history clearly attributes humans and agents.

Context sharing:
- private-by-default branch remains invisible;
- Summary, Selected, Full Snapshot and Live Sync behave distinctly;
- revocation stops future server access;
- re-sharing is denied unless granted.

## 16. Implementation Order

1. Protocol C turn-exit decision and fail-safe wake records.
2. Protocol D state, memory and permanent free-run supervisor.
3. Primary brain lease and multi-session registration/failover.
4. Directory numbers and invite-only enrollment.
5. Unified Messenger and shared Workspace.
6. Context packages, resource ACL and branch-sharing controls.
7. Owner-visible status/receipts and recovery/fallback work.

## 17. Current Pause Point

Rico approved the architecture through context sharing and is pausing to sleep.

Do not implement from memory alone. On resume, read:

1. `docs/EIROS_CURRENT_HANDOFF.md`
2. this specification
3. `project_state_get(eiros-hub)`
4. live `sam_status`, `pulse_status` and `room_telemetry_status`

Next action after Rico returns: review this written specification, make any corrections, then create a detailed implementation plan beginning with Protocol C.
